#!/usr/bin/env python3
"""ledger-guard — Claude Code PreToolUse hook (dev-circuit-ultra)

Blocks tool calls whose arguments name the private ledger or the guard config
itself.

Install with `devcircuit hooks install --harness claude --project <project>`: it
copies this file to <project>/.dev-circuit/hooks/ledger_guard.py and writes the
.claude/settings.json fragment to .dev-circuit/claude-settings.hook.json. Use that
fragment rather than a plain `python ledger_guard.py`: python exits 2 when it
cannot open the script, and Claude Code would then block every tool call on a
branch without this file.

Config:
  <project>/.dev-circuit/guard.json
  {"ledger": "D:\\\\ledgers\\\\my-app", "deny": ["../notes"]}

Where it is looked for: going up from the session's working directory (`cwd` in
the hook input), each folder is asked twice before the next one up.
  1. <folder>/.dev-circuit/guard.json
  2. When <folder> is the top of a linked git worktree (`.git` there is a file
     whose first line is `gitdir: G`, and G/commondir exists): the same file in
     the main working tree, the parent of the git dir that commondir names.
     guard.json is gitignored, so a worktree has no copy of its own. Only those
     two files are read; git is not run.
A place this user may not look into counts as no file there. The first hit
wins. `devcircuit ledger` asks the same two questions, of the `--project`
folder only. A submodule, a --separate-git-dir repository and a worktree of a
bare repository have no main working tree to fall back to.
Because the first hit wins, <folder>/.dev-circuit/guard.json of every folder
asked on the way (the worktree that uses the main tree's file, a subfolder the
session sits in) is blocked like the guard.json in use: written there by the
agent, it would be the boundary from the next call on.

Relative `ledger` and `deny` entries start at the folder that holds
`.dev-circuit` (in case 2, the main working tree). A relative path in a tool
call starts at the folder that answered (in case 2, the worktree).

How it is read, here, in the pi hook and in devcircuit: as UTF-8 with a
leading BOM dropped, holding a JSON object at most 64 `[` and `{` deep (strings
left out of the count), with no NaN or Infinity in it. `ledger` may be left
out; written, it has to be a non-empty string. `deny` is a list of strings;
anything else in its place or among its entries is skipped. Then:
  - no guard.json found: the project has no ledger boundary, nothing is blocked;
  - guard.json says where the ledger is, or leaves it out: calls that name the
    ledger, a `deny` entry or guard.json are blocked;
  - guard.json does not say where the ledger is (it cannot be opened, is not
    UTF-8, is nested deeper, does not parse, is not an object, or `ledger` is
    not a non-empty string): every call is blocked until a human repairs the
    file. The boundary cannot be told, and the agent cannot fix a file it must
    not read.

Exit codes follow the Claude Code hook contract: 0 = allow, 2 = block with the
reason on stderr, 1 = non-blocking error. Pass --json to answer with a
permissionDecision payload instead of exit 2. Input that is no JSON is the
non-blocking error; a call nested deeper than Python's json follows is valid
JSON the agent shaped, and is blocked where a guard.json applies.

What it does: blocks a call whose arguments name the ledger, a `deny` entry or
guard.json in a spelling it can recognise: the path as written (either slash;
on Windows any case, with or without the \\\\?\\ prefix, and the /c/…,
/cygdrive/c/… and /mnt/c/… spellings of a drive), or a token that resolves into
it from the session root with links followed. What it is not: filesystem
isolation. The dev process runs as the same OS user, so a path put together at
run time, a relative path after a `cd`, or a walk of the filesystem goes past
it. For a filesystem-level guarantee use docker/ or a separate OS user;
hooks/README.md lists what the hook misses.
"""

# The hook command runs the first python3 on PATH, which can be older than devcircuit's 3.10 (3.9 on macOS and
# Debian 11). Evaluated there, an annotation such as `str | None` stops the script as it loads, and a hook that
# exits 1 lets every call through. Kept as text, the script runs on 3.8.
from __future__ import annotations

import json
import os
import re
import sys
from itertools import islice
from pathlib import Path

# Raised with every change to this script, together with the pi hook's. `devcircuit hooks` reads the line
# as text to tell whether the copy installed in a project is older or newer than the one it would install.
VERSION = "0.2.0"
CONFIG_DIR = ".dev-circuit"
CONFIG_NAME = "guard.json"
IS_WINDOWS = os.name == "nt"
MAX_DEPTH = 8
MAX_NESTING = 64  # levels of `[` and `{` in guard.json: far more than it needs, far fewer than any parser allows
MAX_TOKENS = 64
TOKEN_SPLIT = re.compile(r"""[\s"'`;|&<>(){}\[\],]+""")
QUOTED = (re.compile(r'"([^"]+)"'), re.compile(r"'([^']+)'"))
POSIX_DRIVE = re.compile(r"^/(?:cygdrive/|mnt/)?([A-Za-z])(?=/|$)")
# Fixed words: a parser's message can quote the file, and the file names the ledger.
BROKEN = ("账本边界：{config} 读不出来（它应该是 UTF-8 的 JSON 对象；写了 ledger 的话，得是非空的路径字符串），"
          "账本在哪里无法判断，所以拦下全部工具调用。这个文件 agent 读不了也修不了：停下来告诉 human，"
          "由 human 修好它，或重新运行 devcircuit hooks install；不要换路径、换工具重试。")
TOO_DEEP = ("账本边界：这次工具调用的参数嵌套太深，ledger-guard 读不完，判断不了它是否碰到账本，所以拦下这一次。"
            "把参数改浅再调用；不要换路径、换工具绕开，需要时停下来问 human。")


def unprefixed(path: str) -> str:
    """`C:\\a` for `\\\\?\\C:\\a` and `\\\\host\\share` for `\\\\?\\UNC\\host\\share`: the same folder either way.

    abspath and realpath leave Windows' extended-length prefix on a path that came with it, so a ledger
    written one way matched no path written the other way.
    """
    if not (IS_WINDOWS and path.startswith("\\\\?\\")):
        return path
    return "\\\\" + path[8:] if path[4:8].upper() == "UNC\\" else path[4:]


def normalize(value: str) -> str:
    text = str(value).strip().strip("\"'")
    if not text:
        return ""
    if text == "~" or text.startswith(("~/", "~\\")):
        text = str(Path.home() / text[1:].lstrip("/\\"))
    normalized = unprefixed(os.path.normpath(os.path.abspath(text)))
    return normalized.lower() if IS_WINDOWS else normalized


def normalize_real(value: str) -> str:
    """Absolute, symlink-resolved, case-folded on Windows. Empty when unusable."""
    try:
        resolved = unprefixed(os.path.realpath(os.path.abspath(os.path.expanduser(value))))
    except (OSError, ValueError):
        return ""
    return resolved.lower() if IS_WINDOWS else resolved


def posix_spelling(path: str) -> str | None:
    """`/c/a/b` for a normalized `c:\\a\\b`, as Git Bash writes it; None off Windows or without a drive.

    Cygwin's /cygdrive/c/a/b and WSL's /mnt/c/a/b contain it, so matching it as text covers all three.
    """
    if IS_WINDOWS and len(path) > 2 and path[1] == ":" and path[0].isalpha():
        return "/" + path[0] + path[2:].replace("\\", "/")
    return None


def drive_spelling(text: str) -> str | None:
    """`c:/a/b` for a `/c/a/b`, `/cygdrive/c/a/b` or `/mnt/c/a/b`, so that it can be resolved; else None."""
    match = POSIX_DRIVE.match(text) if IS_WINDOWS else None
    return f"{match.group(1)}:{text[match.end():] or '/'}" if match else None


def is_file(path: Path) -> bool:
    """Whether `path` is a file; False where this user may not look, as in the pi hook.

    Path.is_file() raises PermissionError there on Python 3.10 to 3.13 (3.14 answers False). Every folder on
    the way up is asked, and a traceback is exit 1, which Claude Code takes for "let the call through".
    """
    return os.path.isfile(path)


def main_tree(top: Path) -> Path | None:
    """The main working tree when `top` is the top of a linked git worktree, else None.

    Read from git's own files, not by running git: the hook runs before every tool call. `.git` there is
    a file naming the worktree's git dir, and `commondir` in that dir leads to the repository's. A
    submodule and a --separate-git-dir repository have the file without the `commondir`.
    """
    try:
        pointer = top / ".git"
        if not is_file(pointer):
            return None
        with open(pointer, encoding="utf-8", errors="replace") as handle:
            first = handle.readline(4096)
        target = first[len("gitdir:"):].strip() if first.startswith("gitdir:") else ""
        if not target:
            return None
        git_dir = os.path.join(top, target)  # a relative one (git worktree add --relative-paths) starts at `top`
        with open(os.path.join(git_dir, "commondir"), encoding="utf-8", errors="replace") as handle:
            common = handle.read(4096).strip()
    except (OSError, ValueError):
        return None
    return Path(os.path.normpath(os.path.join(git_dir, common))).parent if common else None


def folders_up(start: str | None) -> list[Path]:
    """The folder a session works in, then every folder above it."""
    directory = Path(os.path.abspath(start or os.getcwd()))
    return [directory, *directory.parents]


def find_config(start: str | None) -> tuple[Path, Path, Path] | None:
    """Return (guard.json, config root, session root), going up from `start`.

    Each folder is asked twice before the next one up: its own guard.json, then, when it is the top of a
    linked git worktree, the main working tree's (guard.json is gitignored, so a worktree has no copy of
    it). `devcircuit ledger` asks the same two questions of the folder it is given. The config root is
    where relative `ledger` and `deny` entries start; the session root, the folder that answered, is where
    a relative path in a tool call starts.
    """
    for folder in folders_up(start):
        own = folder / CONFIG_DIR / CONFIG_NAME
        if is_file(own):
            return own, folder, folder
        main = main_tree(folder)
        if main and is_file(main / CONFIG_DIR / CONFIG_NAME):
            return main / CONFIG_DIR / CONFIG_NAME, main, folder
    return None


def too_deep(text: str) -> bool:
    """Whether more than MAX_NESTING `[` and `{` are open at once anywhere in `text`, strings left out.

    Counted before parsing, so that whether a file is read does not come down to a parser's recursion limit:
    Python's json gives up somewhere past a thousand levels, by version and stack, and JSON.parse in the pi
    hook does not. The pi hook counts the same way.
    """
    depth, in_string, escaped = 0, False, False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_NESTING:
                return True
        elif char in "]}":
            depth -= 1
    return False


def not_json(constant: str):
    """NaN, Infinity and -Infinity: no JSON. Python's json reads them; JSON.parse in the pi hook does not."""
    raise ValueError(constant)


def any_length(digits: str):
    """An integer as long as it is written; JSON.parse reads one past a double's range as infinity.

    int() refuses more than 4300 digits with a ValueError from 3.11 on, and from 3.8.14, 3.9.14 and 3.10.7, which
    have it as a security fix: a valid file would be unreadable here and readable to the pi hook. The value itself
    is never used.
    """
    try:
        return int(digits)
    except ValueError:
        return float(digits)


def read_config(config_path: Path) -> tuple[str | None, list[str]] | None:
    """(ledger, deny) as guard.json gives them; None when it does not say where the ledger is.

    One rule, here, in the pi hook and in devcircuit's ledger.read_guard: the bytes as strict UTF-8 with a
    leading BOM dropped; no more than MAX_NESTING levels; JSON without NaN or Infinity; an object. `ledger` may
    be left out ({"ledger_side": "human"} alone is a valid file); when it is there it has to be a string that
    str.strip() leaves something of. `deny` only widens the boundary, so a `deny` that is not a list, or an
    entry in it that is not a path, is skipped rather than taking the ledger's protection down with it.
    """
    try:
        text = config_path.read_bytes().decode("utf-8-sig")
        if too_deep(text):
            return None
        raw = json.loads(text, parse_constant=not_json, parse_int=any_length)
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    ledger = raw.get("ledger")
    if "ledger" in raw and not (isinstance(ledger, str) and ledger.strip()):
        return None
    deny = raw.get("deny") if isinstance(raw.get("deny"), list) else []
    return ledger, [entry for entry in deny if isinstance(entry, str) and entry.strip()]


def load_guard(start: str | None) -> dict | None:
    found = find_config(start)
    if not found:
        return None
    config_path, config_root, session_root = found
    # The first guard.json on the way up wins, so the places asked before the one that answered are kept
    # with it. Nothing is there yet (a worktree that borrows the main tree's file, a subfolder the session
    # sits in), and a guard.json written there would be the whole boundary from the next call on.
    guard_files = [config_path]
    for folder in folders_up(start):
        guard_files.append(folder / CONFIG_DIR / CONFIG_NAME)
        if folder == session_root:
            break
    guard = {"config": str(config_path), "root": str(config_root), "base": str(session_root),
             "broken": False, "ledger": False, "places": 1,
             "denied": {normalize(str(path)) for path in guard_files},
             "denied_real": {normalize_real(str(path)) for path in guard_files}}
    read = read_config(config_path)
    if read is None:
        guard["broken"] = True
        return guard
    ledger, deny = read
    entries = ([ledger] if ledger else []) + deny
    for entry in entries:
        absolute = entry if os.path.isabs(entry) or entry.startswith("~") else str(config_root / entry)
        guard["denied"].add(normalize(absolute))
        guard["denied_real"].add(normalize_real(absolute))
    guard["denied_real"].discard("")
    guard["denied"].update(filter(None, map(posix_spelling, list(guard["denied"]))))
    guard["ledger"] = bool(ledger)
    guard["places"] += len(entries)
    return guard


def collect_strings(value, out: list[str], depth: int = 0) -> list[str]:
    if depth > MAX_DEPTH:
        return out
    if isinstance(value, str):
        out.append(value)
        try:
            from urllib.parse import unquote

            out.append(unquote(value))
        except (ValueError, UnicodeDecodeError):
            pass
    elif isinstance(value, dict):
        for item in value.values():
            collect_strings(item, out, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            collect_strings(item, out, depth + 1)
    return out


def escapes(text: str, denied) -> bool:
    if not isinstance(text, str) or len(text) < 3:
        return False
    plain = text.lower() if IS_WINDOWS else text
    slashed_input = plain.replace("\\", "/")
    for target in denied:
        if target in plain:
            return True
        if target.replace("\\", "/") in slashed_input:
            return True
    return False


def candidate_texts(text: str, seen: set):
    """The whole string, its unquoted form, and shell-ish tokens: those not in `seen`, which holds what this
    call has judged already (the raw JSON repeats every string, and a token is judged the same wherever it is).

    A path with a space in it is no single token, so two more readings: what a pair of quotes holds, and
    a token with `\\ ` (how a POSIX shell escapes a space) read as a space.
    """
    def new(items):
        for item in items:
            if item and item not in seen:
                seen.add(item)
                yield item

    yield from new([text, text.strip().strip("\"'")])
    yield from new(TOKEN_SPLIT.split(text)[:MAX_TOKENS])
    for quoted in QUOTED:
        yield from new(match.group(1) for match in islice(quoted.finditer(text), MAX_TOKENS))
    if "\\ " in text:
        tokens = TOKEN_SPLIT.split(text.replace("\\ ", "\0"))[:MAX_TOKENS]
        yield from new(token.replace("\0", " ") for token in tokens if "\0" in token)


def resolve_against(root: str, value: str) -> str:
    """Resolve a maybe-relative path against the session root."""
    expanded = os.path.expanduser(value)
    if not os.path.isabs(expanded):
        expanded = os.path.join(root, expanded)
    return normalize_real(expanded)


def inside(path: str, roots) -> bool:
    return any(path == root or path.startswith(root + os.sep) for root in roots if root)


def violation(payload: dict) -> str | None:
    guard = load_guard(payload.get("cwd"))
    if not guard:
        return None
    if guard["broken"]:
        return BROKEN.format(config=guard["config"])
    texts = collect_strings(payload.get("tool_input") or {}, [])
    texts.append(json.dumps(payload.get("tool_input") or {}, ensure_ascii=False))
    tool = payload.get("tool_name") or "tool"
    seen = set()
    for text in texts:
        if not isinstance(text, str) or len(text) < 3:
            continue
        for candidate in candidate_texts(text, seen):
            hit = escapes(candidate, guard["denied"]) or any(
                inside(resolve_against(guard["base"], spelling), guard["denied_real"])
                for spelling in (candidate, drive_spelling(candidate)) if spelling)
            if hit:
                preview = candidate if len(candidate) <= 120 else candidate[:117] + "…"
                return (f"账本边界：{tool} 试图访问项目外账本（{preview}）。"
                        "开发侧不读账本，不要换路径、换工具绕开，也不要读 .dev-circuit/guard.json 找路径；"
                        "写记录用 devcircuit ledger add，核对用 devcircuit ledger check；需要历史时停下来问 human。")
    return None


def cannot_follow(start: str | None) -> str | None:
    """The answer to a call nested deeper than Python's json follows, read or written out: blocked where a
    guard.json applies to `start`.

    The JSON is valid and the tool input is the agent's to shape. json gives up some thousands of levels deep on
    3.10 to 3.13 and some tens of thousands on 3.14, json.dumps sooner than json.loads, with a RecursionError: a
    traceback would be exit 1, which lets the call through, ledger path and all.
    """
    guard = load_guard(start)
    if not guard:
        return None
    return BROKEN.format(config=guard["config"]) if guard["broken"] else TOO_DEEP


def answer(reason: str | None, use_json: bool) -> int:
    """Let the call through without a reason; else block it: exit 2, or a deny decision with --json."""
    if not reason:
        return 0
    if use_json:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }, ensure_ascii=False))
        return 0
    print(reason, file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            # The reason quotes the call, and a call can hold half a surrogate pair (JSON's "\ud83d"), which
            # UTF-8 has no bytes for: written as an escape, where a strict stream would raise and exit 1.
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError):
            pass
    args = list(sys.argv[1:] if argv is None else argv)
    if "--json" in args:
        args.remove("--json")
        use_json = True
    else:
        use_json = False

    if "--status" in args:
        guard = load_guard(None)
        if not guard:
            print(f"未找到 {CONFIG_DIR}/{CONFIG_NAME}；ledger-guard 不会拦截任何调用。")
            return 0
        # No ledger or deny path here: an agent can run this script, and those are what the hook keeps from it.
        print(f"配置：{guard['config']}")
        if guard["broken"]:
            print("配置读不出来：账本在哪里无法判断，ledger-guard 会拦下全部工具调用，直到 human 修好这个文件。")
            return 1
        print(f"配置根：{guard['root']}")
        print(f"会话根：{guard['base']}")
        print(f"账本：{'已配置' if guard['ledger'] else '未配置'}")
        print(f"拒绝：{guard['places']} 个位置（guard.json、账本和 deny 的每一项各算一个）")
        return 0

    try:
        # Claude Code sends UTF-8 whatever the console says. Reading through sys.stdin would decode
        # with the locale (GBK on Chinese Windows, and -I in the launcher ignores PYTHONIOENCODING),
        # where an odd-length run of UTF-8 bytes swallows the ASCII letter after it, so a path written
        # right after Chinese text, as in 账本：D:\ledgers, would no longer match.
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        payload = json.loads(raw) if raw.strip() else {}
    except RecursionError:
        return answer(cannot_follow(None), use_json)  # unread, the input names no folder: the one the hook runs in
    except (OSError, ValueError, AttributeError) as error:
        print(f"ledger-guard: 无法读取 hook 输入：{error}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        return 0

    try:
        reason = violation(payload)
    except RecursionError:
        reason = cannot_follow(payload.get("cwd"))
    return answer(reason, use_json)


if __name__ == "__main__":
    raise SystemExit(main())
