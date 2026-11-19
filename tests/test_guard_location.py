"""One rule says where guard.json is; the ledger commands and the two hooks each implement it.

Going up from where the session (or `--project`) starts, every folder is asked twice before the next one:
its own .dev-circuit/guard.json, then, when it is the top of a linked git worktree, the main working tree's.
The one difference allowed: the ledger commands ask the starting folder only, the hooks keep going up.

The layouts are built once with real `git init` / `git worktree add`. Every guard.json names a ledger of its
own, so "which file did the pi hook use" can be read from what it blocks, without the hook exporting
anything for the tests.
"""

import functools
import importlib.util
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from devcircuit import ledger as ledger_commands
from test_ledger_hook import HOOK as PYTHON_HOOK
from test_pi_hook import NODE, run_sessions

# Where all three agree, from the top of a working tree (or of a plain folder).
AGREE = (
    "main-top",                        # 主工作树顶层
    "wt-outside",                      # 项目外的 linked worktree
    "wt-inside",                       # 项目内的 linked worktree
    "wt-own-guard",                    # 自带 guard.json 的 linked worktree
    "wt-guard-is-a-folder",            # linked worktree 里的 .dev-circuit/guard.json 是个目录：不算，用主工作树的
    "wt-in-other-configured",          # 建在另一个已配置目录里的 linked worktree，主工作树有配置
    "wt-relative-paths",               # git worktree add --relative-paths
    "plain-with-guard",                # 不是 git 仓库，自带 guard.json
    "plain-without",                   # 不是 git 仓库，没有配置
    "main-unconfigured",               # 主工作树没有配置
    "wt-of-unconfigured",              # linked worktree，主工作树也没有配置
    "submodule",                       # 子模块：.git 是文件，它指的目录里没有 commondir
    "wt-of-submodule",                 # 子模块的 linked worktree：不回退到子模块
    "separate-git-dir",                # git init --separate-git-dir 的主工作树
    "wt-of-separate-git-dir",          # 它的 linked worktree：不回退
    "wt-of-bare",                      # bare 仓库的 worktree：没有主工作树可回退
    "wt-of-bare-guard-beside",         # bare 仓库旁边放了 guard.json：三方都取裸仓库所在的目录
)
# The one difference allowed: the hooks keep going up, the ledger commands stop at the folder they were given.
HOOKS_GO_UP = (
    "subfolder-of-main",               # 主工作树的子目录
    "subfolder-of-wt",                 # linked worktree 的子目录
    "subfolder-of-relative-wt",        # --relative-paths 的 linked worktree 的子目录
    "wt-in-other-configured-main-unconfigured",   # 建在另一个已配置目录里，主工作树没有配置
)


@dataclass(frozen=True)
class Row:
    start: Path
    hooks: Path | None        # the guard.json the hooks are to use
    commands: Path | None     # the guard.json the ledger commands are to use
    session: Path             # where the hooks resolve a relative path of a tool call from


class Layouts:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.rows: dict[str, Row | None] = {}        # None: this git cannot build the layout
        self.ledgers: dict[Path, Path] = {}          # guard.json -> the ledger it names
        config = base / "gitconfig"
        config.write_text("", encoding="utf-8")
        (base / "xdg-config").mkdir()
        # conftest sets these per test; the layouts are built once per module, before any test's fixtures.
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": str(config), "XDG_CONFIG_HOME": str(base / "xdg-config"),
                    "GIT_AUTHOR_NAME": "dcu tests", "GIT_COMMITTER_NAME": "dcu tests",
                    "GIT_AUTHOR_EMAIL": "tests@example.invalid", "GIT_COMMITTER_EMAIL": "tests@example.invalid"}
        for variable in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_COMMON_DIR"):
            self.env.pop(variable, None)

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", env=self.env)
        assert result.returncode == 0 or not check, result.stderr
        return result

    def repository(self, path: Path, *flags: str) -> Path:
        path.mkdir(parents=True)
        self.git("init", "-q", "-b", "main", *flags, str(path))
        (path / ".gitignore").write_text(".dev-circuit/guard.json\n.trees/\n", encoding="utf-8")
        self.git("-C", str(path), "add", "-A")
        self.git("-C", str(path), "commit", "-q", "-m", "base")
        return path

    def worktree(self, repository: Path, path: Path, *flags: str, check: bool = True) -> Path | None:
        path.parent.mkdir(parents=True, exist_ok=True)
        added = self.git("-C", str(repository), "worktree", "add", "-q", *flags, str(path), check=check)
        return path if added.returncode == 0 else None

    def guard(self, directory: Path, name: str) -> Path:
        """A guard.json in `directory` naming a ledger no other guard.json names."""
        path = directory / ".dev-circuit" / "guard.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        ledger = self.base / "ledgers" / name
        path.write_text(json.dumps({"ledger": str(ledger)}), encoding="utf-8")
        self.ledgers[path] = ledger
        return path

    def row(self, name: str, start: Path, hooks: Path | None, commands: Path | None, session: Path | None = None):
        self.rows[name] = Row(start, hooks, commands, session or start)

    def from_session_root(self, row: Row) -> list:
        """A read of the row's ledger by a relative path, written from where such paths are to start."""
        if not row.hooks:
            return []
        return [["read", {"path": os.path.relpath(self.ledgers[row.hooks] / "entries" / "x.md", row.session)}]]

    @functools.cached_property
    def pi(self) -> dict[str, tuple[list[Path], list[Path], list[bool]]]:
        """Per row: the guard files and the ledgers the pi hook blocks a read of, out of every one built here,
        and whether it blocks the row's read by a relative path."""
        guards = list(self.ledgers)
        cases = [["read", {"path": str(guard)}] for guard in guards]
        cases += [["read", {"path": str(self.ledgers[guard] / "entries" / "x.md")}] for guard in guards]
        names = [name for name, row in self.rows.items() if row]
        sessions = run_sessions(self.base, [(self.rows[name].start, cases + self.from_session_root(self.rows[name]))
                                            for name in names])
        found = {}
        for name, session in zip(names, sessions):
            hit = [result is not None and result["block"] is True for result in session["results"]]
            found[name] = ([guard for guard, blocked in zip(guards, hit) if blocked],
                           [self.ledgers[guard] for guard, blocked in zip(guards, hit[len(guards):]) if blocked],
                           hit[2 * len(guards):])
        return found


def build(base: Path) -> Layouts:
    made = Layouts(base)

    app = made.repository(base / "a" / "app")
    main = made.guard(app, "main")
    made.row("main-top", app, main, main)
    (app / "src").mkdir()
    made.row("subfolder-of-main", app / "src", main, None, session=app)

    outside = made.worktree(app, base / "a" / "wt-out", "-b", "wt/out")
    made.row("wt-outside", outside, main, main)
    (outside / "src").mkdir()
    made.row("subfolder-of-wt", outside / "src", main, None, session=outside)

    inside = made.worktree(app, app / ".trees" / "wt-in", "-b", "wt/in")
    made.row("wt-inside", inside, main, main)

    owned = made.worktree(app, base / "a" / "wt-own", "-b", "wt/own")
    own = made.guard(owned, "own")
    made.row("wt-own-guard", owned, own, own)

    odd = made.worktree(app, base / "a" / "wt-odd", "-b", "wt/odd")
    (odd / ".dev-circuit" / "guard.json").mkdir(parents=True)  # there, and not a file: not a guard.json
    made.row("wt-guard-is-a-folder", odd, main, main)

    # Each folder is asked both questions before the next one up: the worktree's main tree comes before the
    # unrelated configured folder the worktree happens to sit in.
    made.guard(base / "a" / "other", "nested")
    nested = made.worktree(app, base / "a" / "other" / "sub" / "wt-nested", "-b", "wt/nested")
    made.row("wt-in-other-configured", nested, main, main)

    relative = made.worktree(app, base / "a" / "wt-rel", "--relative-paths", "-b", "wt/rel", check=False)
    if relative:                                               # git 2.48+
        made.row("wt-relative-paths", relative, main, main)
        (relative / "src").mkdir()
        made.row("subfolder-of-relative-wt", relative / "src", main, None, session=relative)
    else:
        made.rows["wt-relative-paths"] = made.rows["subfolder-of-relative-wt"] = None

    plain = base / "b" / "plain"
    plain.mkdir(parents=True)
    alone = made.guard(plain, "plain")
    made.row("plain-with-guard", plain, alone, alone)
    (base / "b" / "empty").mkdir()
    made.row("plain-without", base / "b" / "empty", None, None)

    bare_of_config = made.repository(base / "c" / "app")
    made.row("main-unconfigured", bare_of_config, None, None)
    lonely = made.worktree(bare_of_config, base / "c" / "wt", "-b", "wt/lonely")
    made.row("wt-of-unconfigured", lonely, None, None)
    host = base / "c" / "other"
    hosted = made.guard(host, "lonely")
    stray = made.worktree(bare_of_config, host / "sub" / "wt-nested", "-b", "wt/stray")
    made.row("wt-in-other-configured-main-unconfigured", stray, hosted, None, session=host)

    # A submodule keeps a `.git` file too, but the folder it names has no `commondir`. Its own linked worktree
    # has one, and it leads to the module's git dir inside the superproject, not to a working tree.
    superproject = made.repository(base / "d" / "super")
    for name in ("lib", "lib-own"):
        made.git("-C", str(superproject), "-c", "protocol.file.allow=always", "submodule", "add", "-q",
                 str(bare_of_config), name)
    made.git("-C", str(superproject), "commit", "-q", "-m", "submodules")
    made.row("submodule", superproject / "lib", None, None)
    made.guard(superproject / "lib-own", "lib")
    module_tree = made.worktree(superproject / "lib-own", base / "d" / "lib-wt", "-b", "wt/lib")
    made.row("wt-of-submodule", module_tree, None, None)

    (base / "e" / "gitdirs").mkdir(parents=True)
    separate = made.repository(base / "e" / "app", "--separate-git-dir", str(base / "e" / "gitdirs" / "app.git"))
    apart = made.guard(separate, "sep")
    made.row("separate-git-dir", separate, apart, apart)
    made.row("wt-of-separate-git-dir", made.worktree(separate, base / "e" / "wt", "-b", "wt/sep"), None, None)

    for folder in ("f", "g"):
        made.git("clone", "-q", "--bare", str(bare_of_config), str(base / folder / "repo.git"))
    made.row("wt-of-bare", made.worktree(base / "f" / "repo.git", base / "f-wt", "-b", "wt/bare"), None, None)
    beside = made.guard(base / "g", "bare")
    made.row("wt-of-bare-guard-beside", made.worktree(base / "g" / "repo.git", base / "g-wt", "-b", "wt/beside"),
             beside, beside)

    assert set(made.rows) == set(AGREE) | set(HOOKS_GO_UP)
    return made


@pytest.fixture(scope="module")
def layouts(tmp_path_factory) -> Layouts:
    base = tmp_path_factory.mktemp("guard-location") / "项目 目录"
    base.mkdir()
    return build(base)


@functools.lru_cache(maxsize=None)
def python_hook():
    spec = importlib.util.spec_from_file_location("ledger_guard_under_test", PYTHON_HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def commands_guard(start: Path) -> Path | None:
    """The guard.json the ledger commands read for `--project start`."""
    guard = ledger_commands._home(start) / ledger_commands.GUARD
    return guard if guard.is_file() else None


def same(found, expected) -> bool:
    if found is None or expected is None:
        return found is None and expected is None
    return os.path.normcase(os.path.realpath(found)) == os.path.normcase(os.path.realpath(expected))


def row_of(layouts: Layouts, name: str) -> Row:
    row = layouts.rows[name]
    if row is None:
        pytest.skip("this git has no `git worktree add --relative-paths` (git 2.48+)")
    return row


def python_found(row: Row):
    """(guard.json, config root, session root) as the Python hook locates them, or three Nones."""
    return python_hook().find_config(str(row.start)) or (None, None, None)


@pytest.mark.parametrize("name", AGREE)
def test_the_ledger_commands_and_the_python_hook_find_the_same_guard_file(layouts: Layouts, name: str) -> None:
    row = row_of(layouts, name)
    assert row.hooks == row.commands                   # what this list is for
    config, config_root, session_root = python_found(row)

    assert same(commands_guard(row.start), row.commands)
    assert same(config, row.hooks)
    if row.hooks:
        assert same(config_root, row.hooks.parent.parent)      # relative `ledger` and `deny` start here
        assert same(session_root, row.session)                 # relative paths of a tool call start here


@pytest.mark.parametrize("name", HOOKS_GO_UP)
def test_the_hooks_keep_going_up_where_the_ledger_commands_stop(layouts: Layouts, name: str) -> None:
    # `--project` has to be the top of a working tree: the card and the capability specs are looked up under
    # it. A session can sit anywhere below, so the hook goes on up to the drive root.
    row = row_of(layouts, name)
    config, config_root, session_root = python_found(row)

    assert commands_guard(row.start) is None and row.commands is None
    assert row.hooks is not None and same(config, row.hooks)
    assert same(config_root, row.hooks.parent.parent)
    assert same(session_root, row.session)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("name", AGREE + HOOKS_GO_UP)
def test_the_pi_hook_guards_through_the_same_guard_file(layouts: Layouts, name: str) -> None:
    row = row_of(layouts, name)
    guards, ledgers, relative = layouts.pi[name]

    assert guards == ([row.hooks] if row.hooks else [])
    assert ledgers == ([layouts.ledgers[row.hooks]] if row.hooks else [])
    # A relative path in a call starts at the folder that answered, wherever below it the session sits; the
    # Python hook's session root is compared in the two tests above.
    assert relative == ([True] if row.hooks else [])


@pytest.mark.parametrize("name", ["main-top", "wt-outside", "wt-inside"])
def test_the_probe_hooks_status_gives_is_one_both_hooks_block(layouts: Layouts, name: str, tmp_path: Path) -> None:
    """`hooks status` tells the human to have the agent read <config root>/.dev-circuit/guard.json.selftest: a hook
    that is loaded has to answer it with 账本边界. That contract spans the CLI and both scripts, so it is pinned here."""
    import contextlib
    import io
    import re
    import devcircuit.cli as cli

    row = row_of(layouts, name)
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        cli.main(["hooks", "status", "--project", str(row.start)])
    probe = re.search(r"让 agent 读 (.+?)（一个不存在的文件）", printed.getvalue()).group(1)
    assert same(probe, row.hooks.parent / "guard.json.selftest")

    from test_ledger_hook import run_hook
    blocked = run_hook({"cwd": str(row.start), "tool_name": "Read", "tool_input": {"file_path": probe}})
    assert blocked.returncode == 2 and "账本边界" in blocked.stderr.decode("utf-8")
    if NODE is not None:
        [session] = run_sessions(tmp_path, [(row.start, [["read", {"path": probe}]])])
        [verdict] = session["results"]
        assert verdict and verdict.get("block") and "账本边界" in verdict.get("reason", "")
