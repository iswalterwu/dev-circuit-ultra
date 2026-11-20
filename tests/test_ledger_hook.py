"""The Claude Code hook is a subprocess contract: JSON in, exit code out."""

import ast
import builtins
import contextlib
import functools
import importlib.util
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tokenize
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "claude" / "ledger_guard.py"
# guard.json contents from which the ledger's location cannot be told; built by unreadable_guard_file(). The
# Claude Code hook, the pi hook and devcircuit's ledger.read_guard share one rule for this, so the samples are
# meant to be used for all three.
UNREADABLE = ("truncated", "empty", "not json", "an array", "null", "a number", "deeply nested", "utf-16", "gbk",
              "ledger is a number", "ledger is blank", "ledger is null", "ledger is blank to str.strip",
              "ledger is U+001C", "ledger is U+0085", "NaN", "Infinity", "-Infinity", "nested 65 deep",
              "nested 65 deep after a backslash")
# Contents near those that are read all the same: the ledger is guarded and nothing else is blocked; built by
# readable_guard_file().
READABLE = ("brackets in strings", "nested 64 deep", "1e999", "a 5000-digit integer")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def linked_worktree(project: Path, tree: Path, *flags: str) -> Path:
    """Make `project` a git repository if it is not one yet, and add `tree` as a linked working tree of it.

    guard.json stays out of git, as `hooks install` leaves it, so the worktree has no copy.
    """
    if not (project / ".git").exists():
        (project / ".gitignore").write_text(".dev-circuit/guard.json\n", encoding="utf-8")
        git(project, "init", "-q", "-b", "main")
        git(project, "add", "-A")
        git(project, "commit", "-q", "-m", "base")
    tree.parent.mkdir(parents=True, exist_ok=True)
    git(project, "worktree", "add", "-q", *flags, "-b", f"wt/{tree.name}", str(tree))
    return tree


def setup_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "app"
    ledger = tmp_path / "ledgers" / "app"
    project.mkdir()
    ledger.mkdir(parents=True)
    (project / ".dev-circuit").mkdir()
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger)}), encoding="utf-8")
    return project, ledger


def with_field(ledger: Path, value: str, before: str = "") -> bytes:
    """A guard.json naming `ledger`, with `value` (JSON text) in a field of its own and `before` ahead of it."""
    return f'{{"ledger": {json.dumps(str(ledger))}, {before}"x": {value}, "deny": []}}'.encode("utf-8")


def nested(depth: int) -> str:
    """JSON text `depth` levels deep, objects and arrays taking turns: both count."""
    value = 0
    for level in range(depth):
        value = [value] if level % 2 else {"k": value}
    return json.dumps(value)


def unreadable_guard_file(sample: str, ledger: Path) -> bytes:
    good = json.dumps({"ledger": str(ledger)})
    return {
        "truncated": good[:-2].encode("utf-8"),
        "empty": b"",
        "not json": f"LEAKMARK {good}".encode("utf-8"),       # Node's parse error quotes the first characters
        "an array": json.dumps([str(ledger)]).encode("utf-8"),
        "null": b"null",                                      # an "object" to JavaScript's typeof
        "a number": b"5",
        "deeply nested": b"[" * 200_000 + b"]" * 200_000,     # Python's parser gave up with a RecursionError
        "utf-16": good.encode("utf-16"),
        # What `echo {…} > guard.json` leaves in cmd on Chinese Windows. Read leniently it is still JSON, and
        # the ledger it names is a path with U+FFFD where the Chinese was: a folder that is not the ledger.
        "gbk": json.dumps({"ledger": str(ledger), "project": "账本"}, ensure_ascii=False).encode("gbk", "replace"),
        "ledger is a number": b'{"ledger": 5}',
        "ledger is blank": b'{"ledger": " "}',
        "ledger is null": b'{"ledger": null}',
        # blank is what Python's str.strip() takes away; JavaScript's trim() leaves U+001C to U+001F and U+0085
        "ledger is blank to str.strip": b'{"ledger": "\\u001f"}',
        "ledger is U+001C": b'{"ledger": "\\u001c"}',
        "ledger is U+0085": b'{"ledger": "\\u0085"}',
        # Python's json reads these three, JSON.parse does not: no JSON, so neither hook reads them
        "NaN": with_field(ledger, "NaN"),
        "Infinity": with_field(ledger, "Infinity"),
        "-Infinity": with_field(ledger, "-Infinity"),
        # One level past the limit of 64, the object itself counted. Both parsers would read it; the limit
        # keeps either from deciding by its own recursion limit, which differs by parser and version.
        "nested 65 deep": with_field(ledger, nested(64)),
        # "C:\\" ends at its second quote: taken for an escaped quote, the string would swallow the nesting after it
        "nested 65 deep after a backslash": with_field(ledger, nested(64), before='"drive": "C:\\\\", '),
    }[sample]


def readable_guard_file(sample: str, ledger: Path) -> bytes:
    return {
        # brackets inside strings, behind escaped quotes too, are no nesting
        "brackets in strings": json.dumps({"ledger": str(ledger), "notes": ["[" * 100],
                                           "note": 'he wrote "' + "[" * 100 + '" and ' + "{" * 100}).encode("utf-8"),
        "nested 64 deep": with_field(ledger, nested(63)),
        # too large for a double: infinity to JSON.parse and to Python's float
        "1e999": with_field(ledger, "1e999"),
        # past Python's limit for turning digits into an int (4300 on 3.11, and on 3.8.14, 3.9.14 and 3.10.7 as a
        # security fix); a double to JSON.parse
        "a 5000-digit integer": with_field(ledger, "1" * 5000),
    }[sample]


def spaced_guard_file(project: Path, ledger: Path) -> tuple[bytes, list[tuple[Path, bool]]]:
    """guard.json with `deny` entries where Python's str.strip() and JavaScript's trim() part ways, and paths a call
    can name, each with whether both hooks block it: as str.strip() has it.

    U+001F alone is blank, so skipped. U+FEFF is no space: a folder of that name, where trim() took it away and
    left the project itself denied. "notes" and U+0085 is the folder notes, where trim() kept the U+0085.
    """
    text = json.dumps({"ledger": str(ledger), "deny": ["\u001f", "\ufeff", "notes\u0085"]}).encode("utf-8")
    return text, [(ledger / "entries" / "x.md", True), (project / "src" / "app.py", False),
                  (project / "\u001f" / "x.md", False), (project / "\ufeff" / "x.md", True),
                  (project / "notes" / "a.md", True)]


windows_only = pytest.mark.skipif(os.name != "nt", reason="drive letters and their spellings are a Windows matter")
# How Windows itself lets a path be written, and how Git Bash, Cygwin and WSL write a drive; see spelled().
WINDOWS_SPELLINGS = ("upper case", "lower-case drive", "forward slashes", "extended prefix",
                     "extended prefix, forward slashes", "8.3 short names")
POSIX_SPELLINGS = ("git bash", "cygwin", "wsl")
# Some 400 KB of ordinary source: thousands of slashes, quotes and words that could be paths.
LARGE_SOURCE = "\n".join(f"""    print("line {index}", 'it is {index}', base / "a b" / name)  # see ../docs/x{index}.md"""
                         for index in range(6000))


def spelled(path: Path, how: str) -> str:
    text = str(path)
    drive, tail = text[0].lower(), text[2:].replace("\\", "/")
    if how == "8.3 short names":
        import ctypes
        buffer = ctypes.create_unicode_buffer(1024)
        ctypes.windll.kernel32.GetShortPathNameW(text, buffer, len(buffer))
        if not buffer.value or buffer.value.lower() == text.lower():
            pytest.skip("this volume keeps no 8.3 short names")
        return buffer.value
    return {
        "upper case": text.upper(),
        "lower-case drive": drive + text[1:],
        "forward slashes": text.replace("\\", "/"),
        "extended prefix": "\\\\?\\" + text,
        "extended prefix, forward slashes": "//?/" + text.replace("\\", "/"),
        "git bash": f"/{drive}{tail}",
        "cygwin": f"/cygdrive/{drive}{tail}",
        "wsl": f"/mnt/{drive}{tail}",
    }[how]


def link_to(target: Path, link: Path) -> None:
    """A junction on Windows (it needs no privilege), a symlink elsewhere; skips where neither can be made."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
    except (OSError, ImportError, AttributeError, NotImplementedError) as error:
        pytest.skip(f"cannot make a link here: {error}")


@contextlib.contextmanager
def held_shut(path: Path):
    """`path` is there and cannot be read: locked by this process on Windows, mode 000 elsewhere."""
    if os.name == "nt":
        import msvcrt
        with open(path, "rb") as handle:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, max(path.stat().st_size, 1))
            yield
    else:
        if os.geteuid() == 0:
            pytest.skip("root reads a file whatever its mode")
        path.chmod(0)
        try:
            yield
        finally:
            path.chmod(0o644)


def run_hook(payload: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK), *args],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        timeout=60,
    )


def verdict(cwd: Path, tool_name: str, tool_input: dict) -> int:
    """The hook's exit code for one tool call of a session in `cwd`: 0 lets it through, 2 blocks it."""
    return run_hook({"cwd": str(cwd), "tool_name": tool_name, "tool_input": tool_input}).returncode


@functools.lru_cache(maxsize=None)
def hook_module():
    """The script loaded in this process, for what a subprocess cannot show: a stub of the platform, an annotation."""
    spec = importlib.util.spec_from_file_location("ledger_guard_under_test", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Names and modules that came after 3.8, of the kind a path-handling script reaches for.
NEWER_NAMES = {"removeprefix", "removesuffix", "is_relative_to", "with_stem", "readlink", "is_junction", "isjunction",
               "hardlink_to", "full_match", "pairwise", "batched", "bit_count"}
NEWER_MODULES = {"zoneinfo", "graphlib", "tomllib"}
BUILTIN_TYPES = {name for name, value in vars(builtins).items() if isinstance(value, type)}
NO_CODE = {tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}


def newer_than_38(source: str) -> list[str]:
    """What in `source` Python 3.8 cannot run, one line each; empty when there is nothing.

    ast.parse(feature_version=(3, 8)) turns down match and a few later statements, and on 3.12 and later reads
    the rest of the newer grammar without a word: parenthesized `with`, any expression as a decorator, `:=` in an
    index or a set, `*` in an index, and f-strings that reuse their own quotes or hold a backslash or a comment in
    a replacement field. The tree and the tokens are looked at for those. Of what fails only as it runs: `|` with a
    type, None or a dict on one side, generics such as tuple[str, ...], zip(strict=), and the names above. `|`
    between two variables that hold dicts cannot be seen here. Annotations are left out: the future import, which
    the test asserts, keeps them text.
    """
    try:
        tree = ast.parse(source, feature_version=(3, 8))
    except SyntaxError as error:
        return [f"{error.lineno}: {error.msg}"]
    lines = io.StringIO(source).readlines()
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    code = [token for token in tokens if token.type not in NO_CODE]
    starts = {token.start: index for index, token in enumerate(code)}
    ends = {token.end: index for index, token in enumerate(code)}

    def at(lineno: int, offset: int) -> tuple[int, int]:
        """A tree position as tokenize gives it: ast counts the column in UTF-8 bytes, tokenize in characters."""
        return lineno, len(lines[lineno - 1].encode("utf-8")[:offset].decode("utf-8"))

    def token_before(node) -> str:
        index = starts.get(at(node.lineno, node.col_offset))
        return code[index - 1].string if index else ""

    def token_after(node) -> str:
        index = ends.get(at(node.end_lineno, node.end_col_offset))
        return code[index + 1].string if index is not None and index + 1 < len(code) else ""

    def first_token(node) -> str:
        index = starts.get(at(node.lineno, node.col_offset))
        return code[index].string if index is not None else ""

    def joins_by_bar(node) -> bool:
        """A type, None, a generic of a built-in type or a dict: what `|` joins from 3.9 or 3.10 on only."""
        return (isinstance(node, ast.Constant) and node.value is None
                or isinstance(node, ast.Name) and node.id in BUILTIN_TYPES
                or isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id in BUILTIN_TYPES
                or isinstance(node, (ast.Dict, ast.DictComp))
                or isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict")

    annotations = set()
    for node in ast.walk(tree):
        for annotation in (getattr(node, "annotation", None), getattr(node, "returns", None)):
            if isinstance(annotation, ast.AST):
                annotations.update(map(id, ast.walk(annotation)))
    found = []
    for node in ast.walk(tree):
        if id(node) in annotations:
            continue
        if isinstance(node, (ast.With, ast.AsyncWith)):
            head = node.items[0].context_expr
            if token_before(head) == "(" and token_after(head) != ")":
                found.append(f"{node.lineno}: with (…) (3.9)")
        for decorator in getattr(node, "decorator_list", ()):
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            while isinstance(target, ast.Attribute):
                target = target.value
            if not isinstance(target, ast.Name) or token_before(decorator) != "@":
                found.append(f"{decorator.lineno}: a decorator that is no dotted name or call of one (3.9)")
        if isinstance(node, ast.Subscript):
            index = node.slice
            parts = index.elts if isinstance(index, ast.Tuple) and first_token(index) != "(" else [index]
            if any(isinstance(part, ast.Starred) for part in parts):
                found.append(f"{node.lineno}: * in an index (3.11)")
            if any(isinstance(part, ast.NamedExpr) and token_before(part) != "(" for part in parts):
                found.append(f"{node.lineno}: := in an index (3.10)")
            if isinstance(node.value, ast.Name) and node.value.id in BUILTIN_TYPES:
                found.append(f"{node.lineno}: {node.value.id}[…] outside an annotation (3.9)")
        if isinstance(node, (ast.Set, ast.SetComp)):
            parts = node.elts if isinstance(node, ast.Set) else [node.elt]
            if any(isinstance(part, ast.NamedExpr) and token_before(part) != "(" for part in parts):
                found.append(f"{node.lineno}: := in a set (3.10)")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr) and (
                joins_by_bar(node.left) or joins_by_bar(node.right)) or (
                isinstance(node, ast.AugAssign) and isinstance(node.op, ast.BitOr) and joins_by_bar(node.value)):
            found.append(f"{node.lineno}: | of types or dicts (3.9, 3.10)")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "zip" and any(
                keyword.arg == "strict" for keyword in node.keywords):
            found.append(f"{node.lineno}: zip(strict=) (3.10)")
        if isinstance(node, ast.Attribute) and node.attr in NEWER_NAMES:
            found.append(f"{node.lineno}: .{node.attr}")
        if isinstance(node, ast.ImportFrom) and (node.module in NEWER_MODULES
                                                 or any(alias.name in NEWER_NAMES for alias in node.names)):
            found.append(f"{node.lineno}: from {node.module} import")
        if isinstance(node, ast.Import) and any(alias.name.split(".")[0] in NEWER_MODULES for alias in node.names):
            found.append(f"{node.lineno}: import")
    if sys.version_info >= (3, 12):
        # Before 3.12 an f-string was first read as a plain string, then its replacement fields as code: one of
        # its own quotes ended it, a backslash anywhere in a field was an error, and so was a # outside the strings
        # there (a comment); a # inside a string in a field was fine. From 3.12 on, tokens show it.
        strings = []                                            # [quotes, braces open] of each f-string a token is in
        for token in tokens:
            holding = [quotes for quotes, braces in strings if braces]   # the f-strings whose field holds the token
            if token.type == tokenize.FSTRING_START:
                quotes = token.string.lstrip("rRfFbBuU")
                if any(outer in quotes for outer in holding):
                    found.append(f"{token.start[0]}: an f-string in a field of one with the same quotes (3.12)")
                strings.append([quotes, 0])
            elif token.type == tokenize.FSTRING_END:
                strings.pop()
            elif token.type == tokenize.OP and token.string in "{}" and strings:
                strings[-1][1] += 1 if token.string == "{" else -1
            elif token.type in (tokenize.STRING, tokenize.FSTRING_MIDDLE):
                # an f-string's own text, format specs included, is its own: what counts is the fields it is in
                outer = holding if token.type == tokenize.STRING else [quotes for quotes, _ in strings[:-1]]
                if outer and (any(quotes in token.string for quotes in outer) or "\\" in token.string):
                    found.append(f"{token.start[0]}: a quote or backslash in an f-string's field (3.12)")
            elif token.type == tokenize.COMMENT and holding:
                found.append(f"{token.start[0]}: a comment in an f-string's field (3.12)")
    return found


def test_the_script_carries_a_version_on_a_line_of_its_own() -> None:
    # The CLI reads this line, without running the script, to tell an installed copy that is older or newer
    # than its own.
    lines = HOOK.read_text(encoding="utf-8").splitlines()

    assert [line for line in lines if re.fullmatch(r'VERSION = "\d+\.\d+\.\d+"', line)] == ['VERSION = "0.2.0"']


def test_the_script_loads_on_an_older_python3() -> None:
    # The hook command runs the first python3 on PATH, whatever its version: 3.9 from macOS's command line
    # tools, 3.9 on Debian 11. There `str | None` in a signature raised a TypeError as the script loaded, the
    # hook exited 1, and Claude Code let every call through.
    source = HOOK.read_text(encoding="utf-8")
    tree = ast.parse(source)

    future = tree.body[1]                                                         # right after the docstring
    assert isinstance(future, ast.ImportFrom) and future.module == "__future__"
    assert [alias.name for alias in future.names] == ["annotations"]
    module = hook_module()
    functions = [value for value in vars(module).values()
                 if inspect.isfunction(value) and value.__module__ == module.__name__]
    assert functions and all(isinstance(annotation, str)                          # kept as text, never evaluated
                             for function in functions for annotation in function.__annotations__.values())
    assert newer_than_38(source) == []


# What 3.8 cannot run, by the release that brought it. ast.parse(feature_version=(3, 8)) turns down match on every
# version; on 3.12 and later it reads all the others without a word.
NEWER_THAN_38 = (
    ("3.9", "with (open(a) as b, open(c) as d):\n    pass\n"),
    ("3.9", "with (open(a) as b):\n    pass\n"),
    ("3.9", "@a[0].b\ndef f():\n    pass\n"),
    ("3.9", "@(a)\ndef f():\n    pass\n"),
    ("3.9", "@a.b()()\ndef f():\n    pass\n"),
    ("3.9", "a = {} | b\n"),
    ("3.9", "a |= dict(b)\n"),
    ("3.9", "A = tuple[str, ...]\n"),
    ("3.9", "a.removeprefix(b)\n"),
    ("3.10", "a[b := 1]\n"),
    ("3.10", "{a, b := 1}\n"),
    ("3.10", "isinstance(a, str | bytes)\n"),
    ("3.10", "a = b | None\n"),
    ("3.10", "zip(a, b, strict=True)\n"),
    ("3.10", "from itertools import pairwise\n"),
    ("3.10", "match a:\n    case 1:\n        pass\n"),
    ("3.11", "a[*b]\n"),
    ("3.11", "a[1, *b]\n"),
    ("3.11", "import tomllib\n"),
    ("3.12", 'f"{"a"}"\n'),
    ("3.12", "f\"{f'{\"a\"}'}\"\n"),
    ("3.12", "f\"{'\\n'}\"\n"),
    ("3.12", 'f"""{a  # note\n}"""\n'),
)
# Close to those, and fine on 3.8.
FINE_ON_38 = (
    "with open(a) as b, open(c) as d:\n    pass\n",
    "with (a) as b, c:\n    pass\n",
    "with (a, b) as c:\n    pass\n",
    "@a.b(c)\ndef f():\n    pass\n",
    "a[(b := 1)]\n",
    "if a := b:\n    pass\n",
    "a[(*b,)]\n",
    "a[f(*b)]\n",
    "a = b | c\n",
    "f\"{'a'}\"\n",
    # Before 3.12 a backslash anywhere in a field was an error, a # only outside the strings there: CPython 3.10
    # on CI reads this one with feature_version=(3, 8), and 3.8 and 3.9 share that parser.
    "f\"{'#'}\"\n",
    'f"""{"a"}"""\n',
    'f"{a:#x}"\n',
    "from __future__ import annotations\ndef f(a: str | None) -> tuple[str, ...]:\n    b: list[int] = []\n",
)


@pytest.mark.parametrize(("release", "source"), NEWER_THAN_38)
def test_the_check_for_older_pythons_sees_what_ast_parse_lets_through(release: str, source: str) -> None:
    assert newer_than_38(source), release


@pytest.mark.parametrize("source", FINE_ON_38)
def test_the_check_for_older_pythons_leaves_what_they_run(source: str) -> None:
    assert newer_than_38(source) == []


OLDER_PYTHONS = tuple(filter(None, map(shutil.which, ("python3.8", "python3.9"))))


@pytest.mark.skipif(not OLDER_PYTHONS, reason="no python3.8 or python3.9 on PATH")
def test_the_hook_guards_on_an_older_python3(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    for python in OLDER_PYTHONS:
        for file_path, code in ((ledger / "entries" / "x.md", 2), (project / "src" / "app.py", 0)):
            payload = {"cwd": str(project), "tool_name": "Read", "tool_input": {"file_path": str(file_path)}}
            result = subprocess.run([python, "-I", str(HOOK)], input=json.dumps(payload).encode("utf-8"),
                                    capture_output=True, timeout=60)
            assert result.returncode == code, (python, result.stderr)


def test_the_script_does_not_promise_isolation() -> None:
    # Its header said "the agent cannot reach the ledger through a tool call"; it blocks the spellings it knows.
    text = " ".join(HOOK.read_text(encoding="utf-8").split())

    assert "cannot reach the ledger" not in text
    assert "What it is not: filesystem isolation." in text


def test_blocks_ledger_read(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    payload = {"cwd": str(project), "tool_name": "Read",
               "tool_input": {"file_path": str(ledger / "entries" / "2026.md")}}

    result = run_hook(payload)
    assert result.returncode == 2
    assert "账本边界" in result.stderr.decode("utf-8")
    assert "绕开" in result.stderr.decode("utf-8")  # the skill leaves this guidance to the block message
    assert "devcircuit ledger add" in result.stderr.decode("utf-8")


def test_blocks_bash_that_names_the_ledger(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    payload = {"cwd": str(project), "tool_name": "Bash",
               "tool_input": {"command": f'cat "{ledger}/entries/x.md"'}}

    assert run_hook(payload).returncode == 2


def test_reads_hook_input_as_utf8_whatever_the_console_encoding(tmp_path: Path) -> None:
    # Claude Code sends raw UTF-8. Decoded as GBK (the stdin default on Chinese Windows), the odd
    # 9 bytes of "账本：" swallow the drive letter that follows, and the path slipped through.
    project, ledger = setup_project(tmp_path)
    payload = {"cwd": str(project), "tool_name": "Bash",
               "tool_input": {"command": f"echo 账本：{ledger}"}}

    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        timeout=60,
        env={**os.environ, "PYTHONIOENCODING": "gbk:surrogateescape"},
    )
    assert result.returncode == 2, result.stderr.decode("utf-8", errors="replace")
    assert "账本边界" in result.stderr.decode("utf-8")           # and answers in UTF-8, as Claude Code reads it


def test_half_a_surrogate_pair_in_a_call_does_not_let_it_through(tmp_path: Path) -> None:
    # JSON can carry half a surrogate pair, UTF-8 cannot. The reason quotes the call, so printing it raised
    # UnicodeEncodeError: a traceback and exit 1, which lets the call through.
    project, ledger = setup_project(tmp_path)
    payload = {"cwd": str(project), "tool_name": "Bash",
               "tool_input": {"command": f'echo \ud83d; cat "{ledger}/entries/x.md"'}}

    result = run_hook(payload)                                   # sent as the escape \ud83d
    assert result.returncode == 2, result.stderr.decode("utf-8", errors="replace")
    assert "账本边界" in result.stderr.decode("utf-8") and b"Traceback" not in result.stderr
    answered = run_hook(payload, "--json")
    assert answered.returncode == 0, answered.stderr.decode("utf-8", errors="replace")
    decision = json.loads(answered.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny" and "\ud83d" in decision["permissionDecisionReason"]


@pytest.mark.parametrize("flag", ["--json", "--status"])
def test_json_and_status_are_utf8_under_a_gbk_console(tmp_path: Path, gbk_env: dict, flag: str) -> None:
    project, ledger = setup_project(tmp_path)
    payload = {"cwd": str(project), "tool_name": "Read", "tool_input": {"file_path": str(ledger / "x.md")}}

    result = subprocess.run([sys.executable, str(HOOK), flag], cwd=project, env=gbk_env,
                            input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=60)

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    printed = result.stdout.decode("utf-8")                      # GBK bytes would not decode
    if flag == "--json":
        decision = json.loads(printed)["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny" and "账本边界" in decision["permissionDecisionReason"]
    else:
        assert "账本：已配置" in printed and "拒绝" in printed


def test_blocks_reads_of_the_guard_config(tmp_path: Path) -> None:
    project, _ = setup_project(tmp_path)
    payload = {"cwd": str(project), "tool_name": "Read",
               "tool_input": {"file_path": str(project / ".dev-circuit" / "guard.json")}}

    assert run_hook(payload).returncode == 2


def test_allows_normal_work(tmp_path: Path) -> None:
    project, _ = setup_project(tmp_path)
    for payload in (
        {"cwd": str(project), "tool_name": "Read",
         "tool_input": {"file_path": str(project / "src" / "app.py")}},
        {"cwd": str(project), "tool_name": "Bash", "tool_input": {"command": "pytest -q"}},
        {"cwd": str(project), "tool_name": "Write",
         "tool_input": {"file_path": str(project / "docs" / "a.md"), "content": "hi"}},
    ):
        assert run_hook(payload).returncode == 0, payload


def test_a_large_write_is_judged_in_time(tmp_path: Path) -> None:
    # Every string of a call is also read as one path, and in source code each "/" makes one more folder of
    # it. Stepping out of them one at a time takes minutes on a file of a few hundred KB.
    project, _ = setup_project(tmp_path)
    started = time.monotonic()

    assert verdict(project, "Write", {"file_path": str(project / "src" / "big.py"), "content": LARGE_SOURCE}) == 0
    assert time.monotonic() - started < 30


def test_without_config_the_hook_stays_out_of_the_way(tmp_path: Path) -> None:
    project = tmp_path / "app"
    project.mkdir()
    payload = {"cwd": str(project), "tool_name": "Read",
               "tool_input": {"file_path": str(tmp_path / "anything.md")}}

    assert run_hook(payload).returncode == 0


def test_a_linked_worktree_outside_the_project_uses_the_main_trees_guard_file(tmp_path: Path) -> None:
    # guard.json is machine-local and gitignored, so a linked worktree has no copy. The ledger commands fell
    # back to the main working tree; the hook only walked up, found nothing from a worktree outside the
    # project folder, and let every call through without a word.
    project, ledger = setup_project(tmp_path)
    tree = linked_worktree(project, tmp_path / "wt-export")
    (tree / "src").mkdir()

    assert verdict(tree, "Read", {"file_path": str(ledger / "entries" / "x.md")}) == 2
    assert verdict(tree, "Read", {"file_path": str(project / ".dev-circuit" / "guard.json")}) == 2
    assert verdict(tree / "src", "Bash", {"command": f'cat "{ledger}/entries/x.md"'}) == 2   # the walk up still runs
    assert verdict(tree, "Read", {"file_path": str(tree / "src" / "app.py")}) == 0
    assert verdict(tree, "Bash", {"command": "pytest -q"}) == 0


def test_a_worktrees_own_guard_file_wins(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    tree = linked_worktree(project, tmp_path / "wt-export")
    own = tmp_path / "ledgers" / "own"
    (tree / ".dev-circuit").mkdir()
    (tree / ".dev-circuit" / "guard.json").write_text(json.dumps({"ledger": str(own)}), encoding="utf-8")

    assert verdict(tree, "Read", {"file_path": str(own / "entries" / "x.md")}) == 2
    assert verdict(tree, "Read", {"file_path": str(tree / ".dev-circuit" / "guard.json")}) == 2
    assert verdict(tree, "Read", {"file_path": str(ledger / "entries" / "x.md")}) == 0   # the main tree's is not asked


def test_a_guard_file_cannot_be_planted_nearer_than_the_one_in_use(tmp_path: Path) -> None:
    # The nearest guard.json wins. In a worktree that borrows the main tree's, and in a subfolder a session
    # sits in, the nearer place is empty: a `{}` written there was the whole boundary from the next call on.
    project, _ = setup_project(tmp_path)
    tree = linked_worktree(project, tmp_path / "wt-export")
    (tree / "src").mkdir()
    (project / "src").mkdir()
    planted = tree / ".dev-circuit" / "guard.json"

    assert verdict(tree, "Write", {"file_path": str(planted), "content": "{}"}) == 2
    assert verdict(tree, "Write", {"file_path": ".dev-circuit/guard.json", "content": "{}"}) == 2
    assert verdict(tree, "Bash", {"command": "mkdir -p .dev-circuit && echo {} > .dev-circuit/guard.json"}) == 2
    assert verdict(tree, "Bash", {"command": f"tool --out={planted}"}) == 2                 # only the text tells
    # every folder that is asked before the one that answered
    assert verdict(tree / "src", "Write", {"file_path": str(planted), "content": "{}"}) == 2
    for session in (tree / "src", project / "src"):
        nearer = session / ".dev-circuit" / "guard.json"
        assert verdict(session, "Write", {"file_path": str(nearer), "content": "{}"}) == 2, session
        assert verdict(session, "Bash", {"command": "echo {} > src/.dev-circuit/guard.json"}) == 2, session
    # nothing else in such a folder, and no other guard.json, is taken for one
    assert verdict(tree, "Read", {"file_path": str(tree / ".dev-circuit" / "hooks" / "ledger_guard.py")}) == 0
    assert verdict(tree, "Write", {"file_path": str(tree / "docs" / "guard.json"), "content": "{}"}) == 0
    assert verdict(tree / "src", "Write", {"file_path": str(tree / "src" / "app.py"), "content": "x"}) == 0


def test_relative_paths_in_a_call_resolve_from_the_worktree(tmp_path: Path) -> None:
    # The session runs in the worktree: a relative path in a tool call starts there, not in the main
    # working tree that holds guard.json.
    project, _ = setup_project(tmp_path)
    tree = linked_worktree(project, tmp_path / "deep" / "wt")

    assert verdict(tree, "Read", {"file_path": "../../ledgers/app/entries/x.md"}) == 2
    assert verdict(tree, "Bash", {"command": "cat ../../ledgers/app/entries/x.md"}) == 2
    assert verdict(tree, "Read", {"file_path": "../ledgers/app/entries/x.md"}) == 0   # the ledger only from the main tree


def test_relative_entries_in_the_main_guard_file_resolve_from_the_main_tree(tmp_path: Path) -> None:
    project = tmp_path / "app"
    (project / ".dev-circuit").mkdir(parents=True)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": "../ledgers/app", "deny": ["../notes"]}), encoding="utf-8")
    tree = linked_worktree(project, tmp_path / "deep" / "wt")

    assert verdict(tree, "Read", {"file_path": str(tmp_path / "ledgers" / "app" / "entries" / "x.md")}) == 2
    assert verdict(tree, "Read", {"file_path": str(tmp_path / "notes" / "a.md")}) == 2
    # what the same entries would name if they were read from the worktree
    assert verdict(tree, "Read", {"file_path": str(tmp_path / "deep" / "ledgers" / "app" / "entries" / "x.md")}) == 0
    assert verdict(tree, "Read", {"file_path": str(tmp_path / "deep" / "notes" / "a.md")}) == 0


def test_the_git_file_may_name_its_folder_relatively_and_end_in_crlf(tmp_path: Path) -> None:
    # `git worktree add --relative-paths` (git 2.48+) writes the path relative to the worktree, not to
    # wherever the hook happens to run; a pointer file rewritten on Windows can end in CRLF.
    project, ledger = setup_project(tmp_path)
    tree = linked_worktree(project, tmp_path / "wt-export")
    pointer = tree / ".git"
    admin = pointer.read_text(encoding="utf-8").split(":", 1)[1].strip()
    relative = os.path.relpath(admin, tree).replace(os.sep, "/")
    pointer.unlink()                                             # hidden on Windows: it cannot be rewritten in place
    pointer.write_bytes(f"gitdir: {relative}  \r\n".encode("utf-8"))

    assert verdict(tree, "Read", {"file_path": str(ledger / "entries" / "x.md")}) == 2


def test_a_git_file_that_is_not_a_linked_worktree_does_not_fall_back(tmp_path: Path) -> None:
    # A submodule and a `git init --separate-git-dir` repository keep a `.git` file too, but the folder it
    # names has no `commondir`: there is no main working tree to borrow a guard.json from.
    store, ledger = setup_project(tmp_path)                     # a configured folder that holds the git dir
    (store / "module").mkdir()
    library = tmp_path / "lib"
    library.mkdir()
    (library / ".git").write_text("gitdir: ../app/module\n", encoding="utf-8")

    assert verdict(library, "Read", {"file_path": str(ledger / "entries" / "x.md")}) == 0


def test_a_guard_file_with_a_bom_still_blocks(tmp_path: Path) -> None:
    # Notepad and Windows PowerShell write UTF-8 with a byte order mark.
    project, ledger = setup_project(tmp_path)
    guard = project / ".dev-circuit" / "guard.json"
    guard.write_bytes(b"\xef\xbb\xbf" + guard.read_bytes())

    assert verdict(project, "Read", {"file_path": str(ledger / "entries" / "x.md")}) == 2
    assert verdict(project, "Bash", {"command": "pytest -q"}) == 0


def test_a_ledger_path_written_as_utf8_text_is_guarded(tmp_path: Path) -> None:
    # `hooks install` writes the path as text, not as \u escapes, and tmp_path has Chinese in it. Only bytes
    # that are not UTF-8 make the file unreadable.
    project, ledger = setup_project(tmp_path)
    guard = project / ".dev-circuit" / "guard.json"
    guard.write_text(json.dumps({"ledger": str(ledger), "project": "账本"}, ensure_ascii=False), encoding="utf-8")

    assert verdict(project, "Read", {"file_path": str(ledger / "entries" / "x.md")}) == 2
    assert verdict(project, "Read", {"file_path": str(project / "src" / "app.py")}) == 0
    assert verdict(project, "Bash", {"command": "pytest -q"}) == 0


@pytest.mark.parametrize("sample", UNREADABLE)
def test_an_unreadable_guard_file_blocks_every_call(tmp_path: Path, sample: str) -> None:
    # A human set a boundary on this machine and it can no longer be read, so the ledger could be anywhere.
    # The hook used to pass every call without a word, a read of guard.json included.
    project, ledger = setup_project(tmp_path)
    guard = project / ".dev-circuit" / "guard.json"
    guard.write_bytes(unreadable_guard_file(sample, ledger))

    for tool_name, tool_input in (("Read", {"file_path": str(project / "src" / "app.py")}),
                                  ("Bash", {"command": "pytest -q"}),
                                  ("Read", {"file_path": str(ledger / "entries" / "x.md")}),
                                  ("Read", {"file_path": str(guard)})):
        payload = {"cwd": str(project), "tool_name": tool_name, "tool_input": tool_input}
        result = run_hook(payload)
        said = result.stderr.decode("utf-8")
        assert result.returncode == 2, (tool_name, said)
        assert "账本边界" in said and str(guard) in said       # which file, so a human can go and fix it
        assert "human" in said and "修不了" in said            # the agent cannot repair it: stop and ask
        # fixed words: not the parser's message, not what the call named
        assert "Traceback" not in said and "LEAKMARK" not in said and str(ledger) not in said

        decision = json.loads(run_hook(payload, "--json").stdout.decode("utf-8"))["hookSpecificOutput"]
        assert decision["permissionDecision"] == "deny"
        assert decision["permissionDecisionReason"] == said.strip()


@pytest.mark.parametrize("sample", READABLE)
def test_a_guard_file_near_an_unreadable_one_is_read(tmp_path: Path, sample: str) -> None:
    # The pi hook reads these too: blocking every call on them here would leave the two hooks disagreeing again.
    project, ledger = setup_project(tmp_path)
    (project / ".dev-circuit" / "guard.json").write_bytes(readable_guard_file(sample, ledger))

    assert verdict(project, "Read", {"file_path": str(ledger / "entries" / "x.md")}) == 2
    assert verdict(project, "Read", {"file_path": str(project / "src" / "app.py")}) == 0
    assert verdict(project, "Bash", {"command": "pytest -q"}) == 0


def test_the_words_for_an_unreadable_guard_file_do_not_depend_on_what_is_wrong_with_it(tmp_path: Path) -> None:
    # What a parser says about a file can quote it, and this file names the ledger.
    project, ledger = setup_project(tmp_path)
    said = set()
    for sample in UNREADABLE:
        (project / ".dev-circuit" / "guard.json").write_bytes(unreadable_guard_file(sample, ledger))
        result = run_hook({"cwd": str(project), "tool_name": "Bash", "tool_input": {"command": "pytest -q"}})
        said.add(result.stderr.decode("utf-8"))

    assert len(said) == 1


def test_a_guard_file_that_cannot_be_opened_blocks_every_call(tmp_path: Path) -> None:
    # Held by another program, or left readable to another user only: the file is there, so a boundary was set.
    project, _ = setup_project(tmp_path)
    guard = project / ".dev-circuit" / "guard.json"

    with held_shut(guard):
        result = run_hook({"cwd": str(project), "tool_name": "Bash", "tool_input": {"command": "pytest -q"}})

    said = result.stderr.decode("utf-8")
    assert result.returncode == 2, said
    assert "读不出来" in said and str(guard) in said and "Traceback" not in said


@pytest.mark.parametrize("deny", ["../notes", 5, {"../notes": True}], ids=["a string", "a number", "an object"])
def test_a_deny_that_is_not_a_list_is_skipped_and_the_ledger_stays_guarded(tmp_path: Path, deny) -> None:
    # Written as a string, `deny` was read letter by letter: "." became a denied path and every file of the
    # project was blocked. Written as a number it raised a traceback and exit 1, which lets the call through.
    project, ledger = setup_project(tmp_path)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger), "deny": deny}), encoding="utf-8")

    blocked = run_hook({"cwd": str(project), "tool_name": "Read",
                        "tool_input": {"file_path": str(ledger / "entries" / "x.md")}})
    assert blocked.returncode == 2, blocked.stderr.decode("utf-8")
    for tool_name, tool_input in (("Read", {"file_path": str(project / "src" / "app.py")}),
                                  ("Bash", {"command": "pytest -q"}),
                                  ("Read", {"file_path": str(tmp_path / "notes" / "a.md")})):   # not a list: no entry
        result = run_hook({"cwd": str(project), "tool_name": tool_name, "tool_input": tool_input})
        assert result.returncode == 0 and b"Traceback" not in result.stderr, (tool_name, result.stderr)


def test_entries_of_deny_that_are_not_paths_are_skipped(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger), "deny": ["../notes", 5, None, {"x": 1}, "", ["../nested"]]}),
        encoding="utf-8")

    assert verdict(project, "Read", {"file_path": str(ledger / "entries" / "x.md")}) == 2
    assert verdict(project, "Read", {"file_path": str(tmp_path / "notes" / "a.md")}) == 2
    assert verdict(project, "Read", {"file_path": str(tmp_path / "nested" / "a.md")}) == 0
    assert verdict(project, "Read", {"file_path": str(project / "src" / "app.py")}) == 0
    assert verdict(project, "Bash", {"command": "pytest -q"}) == 0


def test_space_around_an_entry_is_what_str_strip_takes_away(tmp_path: Path) -> None:
    # The pi hook goes by the same rule; see spaced_guard_file().
    project, ledger = setup_project(tmp_path)
    text, calls = spaced_guard_file(project, ledger)
    (project / ".dev-circuit" / "guard.json").write_bytes(text)

    assert [verdict(project, "Read", {"file_path": str(path)}) == 2 for path, _ in calls] == [
        expected for _, expected in calls]
    assert verdict(project, "Bash", {"command": "pytest -q"}) == 0


def test_a_guard_file_without_a_ledger_is_not_broken(tmp_path: Path) -> None:
    # Where the ledger is kept on the human side, or on a collaborator's machine that has none, guard.json
    # holds {"ledger_side": "human"} alone: there is nothing to guard but the file itself.
    project, _ = setup_project(tmp_path)
    guard = project / ".dev-circuit" / "guard.json"
    guard.write_text(json.dumps({"ledger_side": "human"}), encoding="utf-8")

    assert verdict(project, "Read", {"file_path": str(project / "src" / "app.py")}) == 0
    assert verdict(project, "Bash", {"command": "pytest -q"}) == 0
    assert verdict(project, "Read", {"file_path": str(guard)}) == 2


def test_json_decision_mode(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    payload = {"cwd": str(project), "tool_name": "Read",
               "tool_input": {"file_path": str(ledger / "x.md")}}

    result = run_hook(payload, "--json")
    assert result.returncode == 0
    decision = json.loads(result.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "账本边界" in decision["permissionDecisionReason"]


def status(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HOOK), "--status"], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_status_reports_the_boundary_without_saying_where_the_ledger_is(tmp_path: Path) -> None:
    # An agent can run this script: it used to print the ledger path and every denied path.
    project = tmp_path / "app"
    vault = tmp_path / "vault" / "app"
    (project / ".dev-circuit").mkdir(parents=True)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(vault), "deny": ["../private-notes"]}), encoding="utf-8")

    result = status(project)

    assert result.returncode == 0
    printed = result.stdout
    assert str(project / ".dev-circuit" / "guard.json") in printed
    assert "账本：已配置" in printed
    assert "拒绝：3 个位置" in printed                           # guard.json, the ledger and one deny entry
    assert "vault" not in printed and "private-notes" not in printed

    (project / ".dev-circuit" / "guard.json").write_text(json.dumps({"ledger_side": "human"}), encoding="utf-8")
    printed = status(project).stdout
    assert "账本：未配置" in printed and "拒绝：1 个位置" in printed


def test_status_names_the_two_roots(tmp_path: Path) -> None:
    # Where relative `ledger` and `deny` entries start, and where a relative path in a tool call starts: one
    # folder, until the session is in a linked worktree that borrows the main tree's guard.json.
    project, _ = setup_project(tmp_path)
    tree = linked_worktree(project, tmp_path / "wt-export")

    def said(cwd: Path) -> dict[str, str]:
        return dict(line.split("：", 1) for line in status(cwd).stdout.splitlines() if "：" in line)

    main, linked = said(project), said(tree)
    assert os.path.samefile(main["配置根"], project) and os.path.samefile(main["会话根"], project)
    assert os.path.samefile(linked["配置"], project / ".dev-circuit" / "guard.json")
    assert os.path.samefile(linked["配置根"], project) and os.path.samefile(linked["会话根"], tree)
    assert linked["拒绝"] == main["拒绝"]                         # the count says what guard.json lists


def test_status_says_an_unreadable_guard_file_blocks_everything(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    (project / ".dev-circuit" / "guard.json").write_bytes(unreadable_guard_file("not json", ledger))

    result = status(project)

    assert result.returncode == 1
    assert "读不出来" in result.stdout and "全部工具调用" in result.stdout
    # not the parser's message, which can quote the file
    assert "LEAKMARK" not in result.stdout and "Expecting" not in result.stdout and "账本：" not in result.stdout


def test_bad_input_is_a_non_blocking_error(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, str(HOOK)], input=b"not json",
                            capture_output=True, timeout=60)

    assert result.returncode == 1


def deep_call(cwd: Path, path: Path, depth: int) -> bytes:
    """Hook input for a call that names `path` beside `depth` levels of nesting: valid JSON whatever the depth."""
    return ('{"cwd": %s, "tool_name": "mcp__files__read", "tool_input": {"path": %s, "n": %s}}' % (
        json.dumps(str(cwd)), json.dumps(str(path)), "[" * depth + "]" * depth)).encode("utf-8")


def run_deep(call: bytes, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HOOK), *args], input=call, cwd=cwd, capture_output=True, timeout=60)


def test_a_call_nested_deeper_than_python_reads_is_blocked(tmp_path: Path) -> None:
    # The tool input is the agent's to shape. Python's json gives up some thousands of levels deep on 3.10 to
    # 3.13, some tens of thousands on 3.14: a RecursionError, a traceback and exit 1, which let the call through
    # with the ledger path beside the nesting.
    project, ledger = setup_project(tmp_path)
    call = deep_call(project, ledger / "entries" / "x.md", 200_000)

    result = run_deep(call, project)

    said = result.stderr.decode("utf-8")
    assert result.returncode == 2, said
    assert "账本边界" in said and "嵌套" in said and "Traceback" not in said and str(ledger) not in said
    decision = json.loads(run_deep(call, project, "--json").stdout.decode("utf-8"))["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny" and decision["permissionDecisionReason"] == said.strip()
    # Unread, the input names no folder: the one the hook runs in tells whether a boundary applies. None here.
    plain = tmp_path / "plain"
    plain.mkdir()
    free = run_deep(deep_call(plain, plain / "x.md", 200_000), plain)
    assert free.returncode == 0 and free.stderr == b""


# How deep json.loads and json.dumps follow a nested list in a fresh interpreter: "<loads> <dumps>".
HOW_DEEP = """
import json

def deepest(make):
    low, high = 1, 1_000_000
    while low < high:
        middle = (low + high + 1) // 2
        try:
            make(middle)
            low = middle
        except RecursionError:
            high = middle - 1
    return low

def nested(depth):
    value = 0
    for _ in range(depth):
        value = [value]
    return value

print(deepest(lambda depth: json.loads("[" * depth + "]" * depth)), deepest(lambda depth: json.dumps(nested(depth))))
"""


def test_a_call_python_reads_but_cannot_write_out_is_blocked_too(tmp_path: Path) -> None:
    # Once read, the tool input is written out as JSON text to be matched, and json.dumps can give up short of
    # where json.loads did: on 3.14 for Windows, past some 15,500 of the 16,900 levels json.loads follows. That
    # was the same traceback and exit 1.
    probe = subprocess.run([sys.executable, "-I", "-c", HOW_DEEP], capture_output=True, text=True, encoding="utf-8",
                           timeout=120)
    reads, writes = map(int, probe.stdout.split())
    if reads - writes < 100:
        pytest.skip(f"json.dumps follows as deep as json.loads here ({writes} and {reads} levels)")
    project, ledger = setup_project(tmp_path)

    result = run_deep(deep_call(project, ledger / "entries" / "x.md", (reads + writes) // 2), project)

    said = result.stderr.decode("utf-8")
    assert result.returncode == 2, said
    assert "嵌套" in said and "Traceback" not in said and str(ledger) not in said


def test_blocks_relative_and_traversed_paths(tmp_path: Path) -> None:
    project, _ = setup_project(tmp_path)
    for payload in (
        {"cwd": str(project), "tool_name": "Read",
         "tool_input": {"file_path": "../ledgers/app/entries/x.md"}},
        {"cwd": str(project), "tool_name": "Bash",
         "tool_input": {"command": "cat ../ledgers/app/entries/x.md"}},
        {"cwd": str(project), "tool_name": "Bash",
         "tool_input": {"command": "grep -r decided ../ledgers/app | head"}},
    ):
        assert run_hook(payload).returncode == 2, payload


def test_blocks_a_relative_path_into_a_denied_folder_that_is_not_there_yet(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger), "deny": ["../notes"]}), encoding="utf-8")

    assert verdict(project, "Write", {"file_path": "../notes/2026/a.md", "content": "x"}) == 2
    assert verdict(project, "Write", {"file_path": "../a.md/2026/notes", "content": "x"}) == 0


def test_blocks_a_relative_path_with_a_space_in_it(tmp_path: Path) -> None:
    # Cut at the space, `../my ledgers/app` was two tokens that each led nowhere.
    project = tmp_path / "app"
    (project / ".dev-circuit").mkdir(parents=True)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(tmp_path / "my ledgers" / "app")}), encoding="utf-8")

    for command in ('cat "../my ledgers/app/entries/x.md"',
                    "cat '../my ledgers/app/entries/x.md'",
                    "cat ../my\\ ledgers/app/entries/x.md",                 # as a POSIX shell escapes a space
                    "bash -c \"cat '../my ledgers/app/entries/x.md'\"",
                    'grep -r decided "../my ledgers/app" | head'):
        assert verdict(project, "Bash", {"command": command}) == 2, command
    for command in ('git commit -m "tidy the ledgers page"',
                    "echo hello\\ world",
                    'cat "docs/my notes.md"',
                    "cat ../my\\ other/notes.md",
                    "python -c \"print('a b')\""):
        assert verdict(project, "Bash", {"command": command}) == 0, command


@windows_only
@pytest.mark.parametrize("how", WINDOWS_SPELLINGS)
def test_blocks_the_ledger_however_windows_spells_it(tmp_path: Path, how: str) -> None:
    project, ledger = setup_project(tmp_path)
    (ledger / "entries").mkdir()
    (ledger / "entries" / "x.md").write_text("{}\n", encoding="utf-8")       # a short name needs the file to exist

    assert verdict(project, "Read", {"file_path": spelled(ledger / "entries" / "x.md", how)}) == 2


def missing_drive() -> str:
    """A drive letter with no drive behind it, as `q:`: nothing on it can be asked of the filesystem."""
    for letter in "qrstuvwxyzklmnop":
        if not os.path.exists(f"{letter}:\\"):
            return f"{letter}:"
    pytest.skip("every drive letter is taken")


@windows_only
def test_a_ledger_written_with_the_extended_prefix_is_guarded(tmp_path: Path) -> None:
    # \\?\C:\ledgers\app in guard.json is C:\ledgers\app. Python keeps the prefix on a path that came with
    # one, so the ledger matched no call that named it the ordinary way: nothing was guarded.
    project, ledger = setup_project(tmp_path)
    drive = missing_drive()
    (project / ".dev-circuit" / "guard.json").write_text(json.dumps({
        "ledger": spelled(ledger, "extended prefix"),
        "deny": [spelled(tmp_path / "notes", "extended prefix, forward slashes"), f"\\\\?\\{drive}\\dcu-notes"],
    }), encoding="utf-8")

    assert verdict(project, "Read", {"file_path": str(ledger / "entries" / "x.md")}) == 2
    assert verdict(project, "Bash", {"command": "cat ../ledgers/app/entries/x.md"}) == 2
    assert verdict(project, "Bash", {"command": f"tool --file={ledger}\\x.md"}) == 2     # only the text tells
    assert verdict(project, "Read", {"file_path": spelled(ledger / "entries" / "x.md", "extended prefix")}) == 2
    assert verdict(project, "Write", {"file_path": str(tmp_path / "notes" / "a.md"), "content": "x"}) == 2
    assert verdict(project, "Read", {"file_path": f"{drive}/x/../dcu-notes/a.md"}) == 2  # only resolving it tells
    assert verdict(project, "Read", {"file_path": f"{drive}/x/../dcu-other/a.md"}) == 0
    assert verdict(project, "Read", {"file_path": str(project / "src" / "app.py")}) == 0
    assert verdict(project, "Bash", {"command": "pytest -q"}) == 0


def as_share(path: Path) -> str:
    r"""\\localhost\c$\… for C:\…: a share that is this machine's own drive, so no network is asked."""
    text = str(path)
    return f"\\\\localhost\\{text[0].lower()}${text[2:]}"


@windows_only
def test_a_share_written_with_the_extended_prefix_is_guarded_as_the_share(tmp_path: Path) -> None:
    # The prefix of a share is \\?\UNC\: \\?\UNC\host\share\ledgers is \\host\share\ledgers.
    project, ledger = setup_project(tmp_path)
    share = as_share(ledger)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": "\\\\?\\UNC" + share[1:]}), encoding="utf-8")

    assert verdict(project, "Read", {"file_path": share + "\\entries\\x.md"}) == 2
    assert verdict(project, "Bash", {"command": f"tool --file={share}\\x.md"}) == 2      # only the text tells
    assert verdict(project, "Read", {"file_path": as_share(project / "src" / "app.py")}) == 0


@windows_only
@pytest.mark.parametrize("how", POSIX_SPELLINGS)
def test_blocks_the_ledger_as_git_bash_cygwin_and_wsl_spell_it(tmp_path: Path, how: str) -> None:
    # C:\ledgers\app is /c/ledgers/app in Git Bash, /cygdrive/c/ledgers/app in Cygwin and /mnt/c/ledgers/app
    # in WSL: the same folder, and the hook knew none of the three.
    project, ledger = setup_project(tmp_path)
    target = spelled(ledger / "entries" / "x.md", how)
    around = spelled(project / ".." / "ledgers" / "app" / "entries" / "x.md", how)   # only resolving it tells

    assert verdict(project, "Read", {"file_path": target}) == 2
    assert verdict(project, "Bash", {"command": f"cat '{target}'"}) == 2
    assert verdict(project, "Bash", {"command": "echo " + "a " * 70 + f"; cat {target} | head"}) == 2
    assert verdict(project, "Read", {"file_path": around}) == 2
    assert verdict(project, "Bash", {"command": f'cat "{around}"'}) == 2
    assert verdict(project, "Read", {"file_path": spelled(project / ".dev-circuit" / "guard.json", how)}) == 2
    # the same spelling of a project file, and commands that name other such paths, still pass
    assert verdict(project, "Read", {"file_path": spelled(project / "src" / "app.py", how)}) == 0
    assert verdict(project, "Bash", {"command": f"cat '{spelled(project / 'src' / 'app.py', how)}'"}) == 0
    assert verdict(project, "Bash", {"command": "ls /c/dcu-no-such-folder /cygdrive/c /mnt/data /c /tmp"}) == 0
    assert verdict(project, "Bash", {"command": "pytest -q"}) == 0


@windows_only
def test_a_rooted_path_is_still_read_as_written_too(tmp_path: Path) -> None:
    # /c/x is C:\x in Git Bash, and \c\x on the current drive in cmd and PowerShell. The hook cannot tell which
    # shell will run the command, so it reads the path both ways. Nothing is created at the drive root.
    project = tmp_path / "app"
    drive = os.path.splitdrive(project)[0]                       # the hook is started on this drive below
    (project / ".dev-circuit").mkdir(parents=True)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": f"{drive}\\c\\dcu-no-such-ledger"}), encoding="utf-8")
    payload = {"cwd": str(project), "tool_name": "Read",
               "tool_input": {"file_path": "/c/dcu-no-such-ledger/entries/x.md"}}

    result = subprocess.run([sys.executable, str(HOOK)], cwd=project, input=json.dumps(payload).encode("utf-8"),
                            capture_output=True, timeout=60)

    assert result.returncode == 2, result.stderr.decode("utf-8")


@windows_only
@pytest.mark.parametrize("how", POSIX_SPELLINGS)
def test_blocks_such_a_spelling_as_one_unquoted_word(tmp_path: Path, how: str) -> None:
    plain = tmp_path.parent / "plain"                            # tmp_path has a space in it: not one word
    if " " in str(plain):
        pytest.skip("the temp folder itself has a space in its path")
    plain.mkdir()
    project, _ = setup_project(plain)
    around = spelled(project / ".." / "ledgers" / "app" / "entries" / "x.md", how)

    assert verdict(project, "Bash", {"command": f"cat {around} | head"}) == 2
    assert verdict(project, "Bash", {"command": f"cat {spelled(project / 'src' / 'app.py', how)} | head"}) == 0


def test_blocks_a_ledger_reached_through_a_link(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    (ledger / "entries").mkdir()
    (ledger / "entries" / "x.md").write_text("{}\n", encoding="utf-8")
    link_to(ledger, project / "link")

    for tool_name, tool_input in (
            ("Read", {"file_path": "link/entries/x.md"}),
            ("Read", {"file_path": str(project / "link" / "entries" / "x.md")}),
            ("Write", {"file_path": "link/entries/new.md", "content": "x"}),               # a file not there yet
            ("Write", {"file_path": str(project / "link" / "entries" / "2027" / "new.md"), "content": "x"}),
            ("Bash", {"command": "cat link/entries/*.md"}),                                # no file has this name
            ("Bash", {"command": "ls link/entries/20??"})):
        assert verdict(project, tool_name, tool_input) == 2, tool_input
    assert verdict(project, "Read", {"file_path": "links/entries/x.md"}) == 0
    assert verdict(project, "Bash", {"command": "cat docs/*.md"}) == 0


@windows_only
@pytest.mark.parametrize("how", ["extended prefix", "extended prefix, forward slashes"])
def test_blocks_a_ledger_reached_through_a_link_with_the_extended_prefix(tmp_path: Path, how: str) -> None:
    # Python's realpath follows the link and puts the prefix back on what it returns, when the path came with
    # one; \\?\C:\ledgers\app\x.md did not count as inside C:\ledgers\app.
    project, ledger = setup_project(tmp_path)
    (ledger / "entries").mkdir()
    (ledger / "entries" / "x.md").write_text("{}\n", encoding="utf-8")
    link_to(ledger, project / "link")

    assert verdict(project, "Read", {"file_path": spelled(project / "link" / "entries" / "x.md", how)}) == 2
    assert verdict(project, "Write", {"file_path": spelled(project / "link" / "entries" / "new.md", how),
                                      "content": "x"}) == 2
    assert verdict(project, "Read", {"file_path": spelled(project / "links" / "entries" / "x.md", how)}) == 0
    assert verdict(project, "Read", {"file_path": spelled(project / "src" / "app.py", how)}) == 0


def dangling_links(tmp_path: Path, project: Path) -> None:
    """In `project`: `vault` and `again`, links that lead (the second through the first) to a folder beside
    the project that is not there, and `round` and `about`, which lead to each other."""
    (tmp_path / "vault").mkdir()
    link_to(tmp_path / "vault", project / "vault")
    try:                                                        # as `ln -s vault again` leaves it: relative to the link
        (project / "again").symlink_to("vault", target_is_directory=True)
    except OSError:                                             # Windows without the privilege: a junction, absolute
        link_to(project / "vault", project / "again")
    (tmp_path / "vault").rmdir()
    (project / "round").mkdir()
    link_to(project / "round", project / "about")
    (project / "round").rmdir()
    link_to(project / "about", project / "round")


def test_blocks_a_denied_folder_reached_through_a_link_before_the_folder_is_there(tmp_path: Path) -> None:
    # `deny` may name a folder that is yet to be made. A link towards it that is already in the project leads
    # nowhere, so it "does not exist" either; where it leads is still on record in the link.
    project, ledger = setup_project(tmp_path)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger), "deny": ["../vault/notes"]}), encoding="utf-8")
    dangling_links(tmp_path, project)

    assert verdict(project, "Write", {"file_path": "vault/notes/a.md", "content": "x"}) == 2
    assert verdict(project, "Write", {"file_path": str(project / "vault" / "notes" / "2026" / "a.md"),
                                      "content": "x"}) == 2
    assert verdict(project, "Bash", {"command": "cat vault/notes/*.md"}) == 2
    assert verdict(project, "Write", {"file_path": "again/notes/a.md", "content": "x"}) == 2   # a link to the link
    assert verdict(project, "Write", {"file_path": "vault/other/a.md", "content": "x"}) == 0
    assert verdict(project, "Write", {"file_path": "vaults/notes/a.md", "content": "x"}) == 0
    assert verdict(project, "Read", {"file_path": "round/notes/a.md"}) == 0   # judged, not followed for ever


def test_allows_unrelated_siblings(tmp_path: Path) -> None:
    project, _ = setup_project(tmp_path)
    payload = {"cwd": str(project), "tool_name": "Read",
               "tool_input": {"file_path": "../other/notes.md"}}

    assert run_hook(payload).returncode == 0
