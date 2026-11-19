"""The pi extension blocks tool calls that name the ledger.

Node is optional: without it these tests skip instead of failing. The harness
registers the real extension against a stub `pi` object and asks it to judge a
list of tool calls.
"""

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from test_ledger_hook import HOOK as PYTHON_HOOK
from test_ledger_hook import (LARGE_SOURCE, POSIX_SPELLINGS, UNREADABLE, WINDOWS_SPELLINGS, as_share, dangling_links,
                              held_shut, link_to, linked_worktree, missing_drive, run_hook, spelled,
                              unreadable_guard_file, windows_only)

NODE = shutil.which("node")
HOOK = Path(__file__).resolve().parents[1] / "hooks" / "pi" / "ledger-guard.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

HARNESS = """
import { readFileSync } from "node:fs"
import { pathToFileURL } from "node:url"
const [,, hookPath, sessionsPath] = process.argv
const hook = await import(pathToFileURL(hookPath).href)
const handlers = {}
hook.default({ on: (name, fn) => { handlers[name] = fn } })
const out = []
for (const [cwd, cases] of JSON.parse(readFileSync(sessionsPath, "utf8"))) {
  const notes = []
  const ctx = { cwd, ui: { notify: (message, level) => { notes.push([level, message]) } } }
  if (handlers.session_start) await handlers.session_start({}, ctx)
  const results = []
  for (const [toolName, input] of cases) {
    results.push((await handlers.tool_call({ toolName, input }, ctx)) ?? null)
  }
  out.push({ results, notes })
}
process.stdout.write(JSON.stringify(out))
"""


def setup_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "app"
    ledger = tmp_path / "ledgers" / "app"
    project.mkdir()
    ledger.mkdir(parents=True)
    (project / ".dev-circuit").mkdir()
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger)}), encoding="utf-8")
    return project, ledger


def run_sessions(scratch: Path, sessions: list) -> list[dict]:
    """Start one pi session per (cwd, cases) in a single node process.

    Each answers {"results": one verdict per case, "notes": what the hook told the user}. The cases travel in
    a file: a command line has a length limit and its own quoting rules.
    """
    harness = scratch / "harness.mjs"
    harness.write_text(HARNESS, encoding="utf-8")
    listed = scratch / "sessions.json"
    listed.write_text(json.dumps([[str(cwd), cases] for cwd, cases in sessions]), encoding="utf-8")
    result = subprocess.run(
        [NODE, str(harness), str(HOOK), str(listed)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def judge(project: Path, tmp_path: Path, cases: list) -> list:
    return run_sessions(tmp_path, [(project, cases)])[0]["results"]


def blocked(project: Path, tmp_path: Path, cases: list) -> list[bool]:
    return [result is not None and result["block"] is True for result in judge(project, tmp_path, cases)]


def test_the_script_carries_the_claude_hooks_version_on_a_line_of_its_own() -> None:
    # The CLI reads this line, without running the script, to tell an installed copy that is older or newer
    # than its own. The two hooks implement one rule, so they change together.
    lines = HOOK.read_text(encoding="utf-8").splitlines()
    python = [line for line in PYTHON_HOOK.read_text(encoding="utf-8").splitlines() if line.startswith("VERSION = ")]

    assert [line for line in lines if re.fullmatch(r'const VERSION = "\d+\.\d+\.\d+";', line)] \
        == [f"const {line};" for line in python] == ['const VERSION = "0.2.0";']


def test_the_script_does_not_promise_isolation() -> None:
    # Its header said "the agent cannot reach the ledger through a tool call"; it blocks the spellings it knows.
    text = " ".join(HOOK.read_text(encoding="utf-8").replace("\n *", "\n").split())

    assert "cannot reach the ledger" not in text and "out of the dev agent's reach" not in text
    assert "What it is not: filesystem isolation." in text


def test_blocks_ledger_access(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    cases = [
        ["read", {"path": str(ledger / "entries" / "2026.md")}],
        ["bash", {"command": f'ls "{ledger}"'}],
        ["read", {"path": str(project / ".dev-circuit" / "guard.json")}],
        ["grep", {"pattern": "decided", "path": str(ledger)}],
    ]

    for result in judge(project, tmp_path, cases):
        assert result is not None and result["block"] is True
        assert "账本边界" in result["reason"]
        assert "绕开" in result["reason"]  # the skill leaves this guidance to the block message
        assert "devcircuit ledger add" in result["reason"]


def test_half_a_surrogate_pair_in_a_call_does_not_let_it_through(tmp_path: Path) -> None:
    # JSON can carry half a surrogate pair, UTF-8 cannot; the Claude Code hook failed to print its reason.
    project, ledger = setup_project(tmp_path)

    result = judge(project, tmp_path, [["bash", {"command": f'echo \ud83d; cat "{ledger}/entries/x.md"'}]])[0]

    assert result is not None and result["block"] is True and "\ud83d" in result["reason"]


def test_allows_normal_work(tmp_path: Path) -> None:
    project, _ = setup_project(tmp_path)
    cases = [
        ["read", {"path": str(project / "src" / "app.py")}],
        ["bash", {"command": "pytest -q"}],
        ["write", {"path": str(project / "docs" / "a.md"), "content": "hi"}],
    ]

    assert judge(project, tmp_path, cases) == [None, None, None]


def test_a_large_write_is_judged_in_time(tmp_path: Path) -> None:
    # Every string of a call is also read as one path, and in source code each "/" makes one more folder of
    # it. Stepping out of them one at a time takes minutes on a file of a few hundred KB.
    project, _ = setup_project(tmp_path)
    started = time.monotonic()

    assert blocked(project, tmp_path, [["write", {"path": str(project / "src" / "big.py"),
                                                  "content": LARGE_SOURCE}]]) == [False]
    assert time.monotonic() - started < 30


def test_without_config_nothing_is_blocked(tmp_path: Path) -> None:
    project = tmp_path / "app"
    project.mkdir()
    cases = [["read", {"path": str(tmp_path / "ledgers" / "app" / "x.md")}]]

    assert judge(project, tmp_path, cases) == [None]


def test_a_linked_worktree_outside_the_project_uses_the_main_trees_guard_file(tmp_path: Path) -> None:
    # guard.json is machine-local and gitignored, so a linked worktree has no copy. The ledger commands fell
    # back to the main working tree; the hook only walked up, found nothing from a worktree outside the
    # project folder, and let every call through without a word.
    project, ledger = setup_project(tmp_path)
    tree = linked_worktree(project, tmp_path / "wt-export")
    (tree / "src").mkdir()
    cases = [
        ["read", {"path": str(ledger / "entries" / "x.md")}],
        ["read", {"path": str(project / ".dev-circuit" / "guard.json")}],
        ["read", {"path": str(tree / "src" / "app.py")}],
        ["bash", {"command": "pytest -q"}],
    ]

    assert blocked(tree, tmp_path, cases) == [True, True, False, False]
    # the walk up still runs
    assert blocked(tree / "src", tmp_path, [["bash", {"command": f'cat "{ledger}/entries/x.md"'}]]) == [True]


def test_a_worktrees_own_guard_file_wins(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    tree = linked_worktree(project, tmp_path / "wt-export")
    own = tmp_path / "ledgers" / "own"
    (tree / ".dev-circuit").mkdir()
    (tree / ".dev-circuit" / "guard.json").write_text(json.dumps({"ledger": str(own)}), encoding="utf-8")
    cases = [
        ["read", {"path": str(own / "entries" / "x.md")}],
        ["read", {"path": str(tree / ".dev-circuit" / "guard.json")}],
        ["read", {"path": str(ledger / "entries" / "x.md")}],            # the main tree's is not asked
    ]

    assert blocked(tree, tmp_path, cases) == [True, True, False]


def test_a_guard_file_cannot_be_planted_nearer_than_the_one_in_use(tmp_path: Path) -> None:
    # The nearest guard.json wins. In a worktree that borrows the main tree's, and in a subfolder a session
    # sits in, the nearer place is empty: a `{}` written there was the whole boundary from the next call on.
    project, _ = setup_project(tmp_path)
    tree = linked_worktree(project, tmp_path / "wt-export")
    (tree / "src").mkdir()
    (project / "src").mkdir()
    planted = tree / ".dev-circuit" / "guard.json"

    def below(session: Path) -> list:
        return [["write", {"path": str(session / ".dev-circuit" / "guard.json"), "content": "{}"}],
                ["bash", {"command": "echo {} > src/.dev-circuit/guard.json"}]]

    at_top, in_tree, in_project = run_sessions(tmp_path, [
        (tree, [["write", {"path": str(planted), "content": "{}"}],
                ["write", {"path": ".dev-circuit/guard.json", "content": "{}"}],
                ["bash", {"command": "mkdir -p .dev-circuit && echo {} > .dev-circuit/guard.json"}],
                ["bash", {"command": f"tool --out={planted}"}],                     # only the text tells
                # nothing else in such a folder, and no other guard.json, is taken for one
                ["read", {"path": str(tree / ".dev-circuit" / "hooks" / "ledger_guard.py")}],
                ["write", {"path": str(tree / "docs" / "guard.json"), "content": "{}"}]]),
        # every folder that is asked before the one that answered
        (tree / "src", [["write", {"path": str(planted), "content": "{}"}], *below(tree / "src"),
                        ["write", {"path": str(tree / "src" / "app.py"), "content": "x"}]]),
        (project / "src", below(project / "src")),
    ])

    assert [result is not None for result in at_top["results"]] == [True, True, True, True, False, False]
    assert [result is not None for result in in_tree["results"]] == [True, True, True, False]
    assert [result is not None for result in in_project["results"]] == [True, True]


def test_relative_paths_in_a_call_resolve_from_the_worktree(tmp_path: Path) -> None:
    # The session runs in the worktree: a relative path in a tool call starts there, not in the main
    # working tree that holds guard.json.
    project, _ = setup_project(tmp_path)
    tree = linked_worktree(project, tmp_path / "deep" / "wt")
    cases = [
        ["read", {"path": "../../ledgers/app/entries/x.md"}],
        ["bash", {"command": "cat ../../ledgers/app/entries/x.md"}],
        ["read", {"path": "../ledgers/app/entries/x.md"}],               # the ledger only from the main tree
    ]

    assert blocked(tree, tmp_path, cases) == [True, True, False]


def test_relative_entries_in_the_main_guard_file_resolve_from_the_main_tree(tmp_path: Path) -> None:
    project = tmp_path / "app"
    (project / ".dev-circuit").mkdir(parents=True)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": "../ledgers/app", "deny": ["../notes"]}), encoding="utf-8")
    tree = linked_worktree(project, tmp_path / "deep" / "wt")
    cases = [
        ["read", {"path": str(tmp_path / "ledgers" / "app" / "entries" / "x.md")}],
        ["read", {"path": str(tmp_path / "notes" / "a.md")}],
        # what the same entries would name if they were read from the worktree
        ["read", {"path": str(tmp_path / "deep" / "ledgers" / "app" / "entries" / "x.md")}],
        ["read", {"path": str(tmp_path / "deep" / "notes" / "a.md")}],
    ]

    assert blocked(tree, tmp_path, cases) == [True, True, False, False]


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

    assert blocked(tree, tmp_path, [["read", {"path": str(ledger / "entries" / "x.md")}]]) == [True]


def test_a_git_file_that_is_not_a_linked_worktree_does_not_fall_back(tmp_path: Path) -> None:
    # A submodule and a `git init --separate-git-dir` repository keep a `.git` file too, but the folder it
    # names has no `commondir`: there is no main working tree to borrow a guard.json from.
    store, ledger = setup_project(tmp_path)                     # a configured folder that holds the git dir
    (store / "module").mkdir()
    library = tmp_path / "lib"
    library.mkdir()
    (library / ".git").write_text("gitdir: ../app/module\n", encoding="utf-8")

    assert blocked(library, tmp_path, [["read", {"path": str(ledger / "entries" / "x.md")}]]) == [False]


def test_a_guard_file_with_a_bom_still_blocks(tmp_path: Path) -> None:
    # Notepad and Windows PowerShell write UTF-8 with a byte order mark. JSON.parse refuses it, and the hook
    # took that for a broken file and let every call through.
    project, ledger = setup_project(tmp_path)
    guard = project / ".dev-circuit" / "guard.json"
    guard.write_bytes(b"\xef\xbb\xbf" + guard.read_bytes())
    cases = [["read", {"path": str(ledger / "entries" / "x.md")}], ["bash", {"command": "pytest -q"}]]

    session = run_sessions(tmp_path, [(project, cases)])[0]

    assert [result is not None for result in session["results"]] == [True, False]
    assert session["notes"] == []


def test_a_ledger_path_written_as_utf8_text_is_guarded(tmp_path: Path) -> None:
    # `hooks install` writes the path as text, not as \u escapes, and tmp_path has Chinese in it. Only bytes
    # that are not UTF-8 make the file unreadable.
    project, ledger = setup_project(tmp_path)
    guard = project / ".dev-circuit" / "guard.json"
    guard.write_text(json.dumps({"ledger": str(ledger), "project": "账本"}, ensure_ascii=False), encoding="utf-8")
    cases = [
        ["read", {"path": str(ledger / "entries" / "x.md")}],
        ["read", {"path": str(project / "src" / "app.py")}],
        ["bash", {"command": "pytest -q"}],
    ]

    session = run_sessions(tmp_path, [(project, cases)])[0]

    assert [result is not None for result in session["results"]] == [True, False, False]
    assert session["notes"] == []


@pytest.mark.parametrize("sample", UNREADABLE)
def test_an_unreadable_guard_file_blocks_every_call(tmp_path: Path, sample: str) -> None:
    # A human set a boundary on this machine and it can no longer be read, so the ledger could be anywhere.
    # The hook used to warn and pass every call, a read of guard.json included. A file in another encoding
    # (the "gbk" sample) it read as a valid one naming some other folder, and passed a read of the ledger.
    project, ledger = setup_project(tmp_path)
    guard = project / ".dev-circuit" / "guard.json"
    guard.write_bytes(unreadable_guard_file(sample, ledger))
    cases = [
        ["read", {"path": str(project / "src" / "app.py")}],
        ["bash", {"command": "pytest -q"}],
        ["read", {"path": str(ledger / "entries" / "x.md")}],
        ["read", {"path": str(guard)}],
    ]

    session = run_sessions(tmp_path, [(project, cases)])[0]

    said = [result["reason"] for result in session["results"] if result is not None and result["block"] is True]
    assert len(said) == len(cases)
    # told once more when the session starts, in the same words
    assert session["notes"] == [["warning", said[0]]]
    for reason in said:
        assert "账本边界" in reason and str(guard) in reason     # which file, so a human can go and fix it
        assert "human" in reason and "修不了" in reason          # the agent cannot repair it: stop and ask
        # fixed words: not the parser's message (Node quotes the file in it), not what the call named
        assert "LEAKMARK" not in reason and "JSON at" not in reason and str(ledger) not in reason


def test_the_words_for_an_unreadable_guard_file_are_the_claude_hooks(tmp_path: Path) -> None:
    # One text for both hooks, whatever is wrong with the file: what a parser says about it can quote it.
    project, ledger = setup_project(tmp_path)
    call = {"command": "pytest -q"}
    said = set()
    for sample in UNREADABLE:
        (project / ".dev-circuit" / "guard.json").write_bytes(unreadable_guard_file(sample, ledger))
        said.add(judge(project, tmp_path, [["bash", call]])[0]["reason"])
    python = run_hook({"cwd": str(project), "tool_name": "Bash", "tool_input": call})

    assert said == {python.stderr.decode("utf-8").strip()}


def test_a_guard_file_that_cannot_be_opened_blocks_every_call(tmp_path: Path) -> None:
    # Held by another program, or left readable to another user only: the file is there, so a boundary was set.
    project, _ = setup_project(tmp_path)
    guard = project / ".dev-circuit" / "guard.json"

    with held_shut(guard):
        session = run_sessions(tmp_path, [(project, [["bash", {"command": "pytest -q"}]])])[0]

    result = session["results"][0]
    assert result is not None and result["block"] is True
    assert "读不出来" in result["reason"] and str(guard) in result["reason"]
    assert session["notes"] == [["warning", result["reason"]]]


@pytest.mark.parametrize("deny", ["../notes", 5, {"../notes": True}], ids=["a string", "a number", "an object"])
def test_a_deny_that_is_not_a_list_is_skipped_and_the_ledger_stays_guarded(tmp_path: Path, deny) -> None:
    project, ledger = setup_project(tmp_path)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger), "deny": deny}), encoding="utf-8")
    cases = [
        ["read", {"path": str(ledger / "entries" / "x.md")}],
        ["read", {"path": str(project / "src" / "app.py")}],
        ["bash", {"command": "pytest -q"}],
        ["read", {"path": str(tmp_path / "notes" / "a.md")}],            # not a list: no entry
    ]

    assert blocked(project, tmp_path, cases) == [True, False, False, False]


def test_entries_of_deny_that_are_not_paths_are_skipped(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger), "deny": ["../notes", 5, None, {"x": 1}, "", ["../nested"]]}),
        encoding="utf-8")
    cases = [
        ["read", {"path": str(ledger / "entries" / "x.md")}],
        ["read", {"path": str(tmp_path / "notes" / "a.md")}],
        ["read", {"path": str(tmp_path / "nested" / "a.md")}],
        ["read", {"path": str(project / "src" / "app.py")}],
        ["bash", {"command": "pytest -q"}],
    ]

    assert blocked(project, tmp_path, cases) == [True, True, False, False, False]


def test_a_guard_file_without_a_ledger_is_not_broken(tmp_path: Path) -> None:
    # Where the ledger is kept on the human side, or on a collaborator's machine that has none, guard.json
    # holds {"ledger_side": "human"} alone: there is nothing to guard but the file itself.
    project, _ = setup_project(tmp_path)
    guard = project / ".dev-circuit" / "guard.json"
    guard.write_text(json.dumps({"ledger_side": "human"}), encoding="utf-8")
    cases = [
        ["read", {"path": str(project / "src" / "app.py")}],
        ["bash", {"command": "pytest -q"}],
        ["read", {"path": str(guard)}],
    ]

    session = run_sessions(tmp_path, [(project, cases)])[0]

    assert [result is not None for result in session["results"]] == [False, False, True]
    assert session["notes"] == []


def test_relative_ledger_path_resolves_against_the_project(tmp_path: Path) -> None:
    project = tmp_path / "app"
    ledger = tmp_path / "app-nav" / "ledger"
    project.mkdir()
    ledger.mkdir(parents=True)
    (project / ".dev-circuit").mkdir()
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": "../app-nav/ledger"}), encoding="utf-8")

    cases = [["read", {"path": str(ledger / "entries" / "x.md")}]]
    result = judge(project, tmp_path, cases)[0]
    assert result is not None and result["block"] is True


def test_blocks_relative_paths(tmp_path: Path) -> None:
    project, _ = setup_project(tmp_path)
    cases = [
        ["read", {"path": "../ledgers/app/entries/x.md"}],
        ["bash", {"command": "cat ../ledgers/app/entries/x.md"}],
    ]

    for result in judge(project, tmp_path, cases):
        assert result is not None and result["block"] is True


def test_blocks_a_relative_path_into_a_denied_folder_that_is_not_there_yet(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger), "deny": ["../notes"]}), encoding="utf-8")
    cases = [
        ["write", {"path": "../notes/2026/a.md", "content": "x"}],
        ["write", {"path": "../a.md/2026/notes", "content": "x"}],
    ]

    assert blocked(project, tmp_path, cases) == [True, False]


def test_blocks_a_relative_path_with_a_space_in_it(tmp_path: Path) -> None:
    # Cut at the space, `../my ledgers/app` was two tokens that each led nowhere.
    project = tmp_path / "app"
    (project / ".dev-circuit").mkdir(parents=True)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(tmp_path / "my ledgers" / "app")}), encoding="utf-8")
    named = ['cat "../my ledgers/app/entries/x.md"',
             "cat '../my ledgers/app/entries/x.md'",
             "cat ../my\\ ledgers/app/entries/x.md",                        # as a POSIX shell escapes a space
             "bash -c \"cat '../my ledgers/app/entries/x.md'\"",
             'grep -r decided "../my ledgers/app" | head']
    ordinary = ['git commit -m "tidy the ledgers page"',
                "echo hello\\ world",
                'cat "docs/my notes.md"',
                "cat ../my\\ other/notes.md",
                "python -c \"print('a b')\""]

    verdicts = blocked(project, tmp_path, [["bash", {"command": command}] for command in named + ordinary])

    assert verdicts == [True] * len(named) + [False] * len(ordinary)


@windows_only
@pytest.mark.parametrize("how", WINDOWS_SPELLINGS)
def test_blocks_the_ledger_however_windows_spells_it(tmp_path: Path, how: str) -> None:
    project, ledger = setup_project(tmp_path)
    (ledger / "entries").mkdir()
    (ledger / "entries" / "x.md").write_text("{}\n", encoding="utf-8")       # a short name needs the file to exist

    assert blocked(project, tmp_path, [["read", {"path": spelled(ledger / "entries" / "x.md", how)}]]) == [True]


@windows_only
def test_a_ledger_written_with_the_extended_prefix_is_guarded(tmp_path: Path) -> None:
    # \\?\C:\ledgers\app in guard.json is C:\ledgers\app, however a call names it.
    project, ledger = setup_project(tmp_path)
    drive = missing_drive()
    (project / ".dev-circuit" / "guard.json").write_text(json.dumps({
        "ledger": spelled(ledger, "extended prefix"),
        "deny": [spelled(tmp_path / "notes", "extended prefix, forward slashes"), f"\\\\?\\{drive}\\dcu-notes"],
    }), encoding="utf-8")
    cases = [
        ["read", {"path": str(ledger / "entries" / "x.md")}],
        ["bash", {"command": "cat ../ledgers/app/entries/x.md"}],
        ["bash", {"command": f"tool --file={ledger}\\x.md"}],                    # only the text tells
        ["read", {"path": spelled(ledger / "entries" / "x.md", "extended prefix")}],
        ["write", {"path": str(tmp_path / "notes" / "a.md"), "content": "x"}],
        ["read", {"path": f"{drive}/x/../dcu-notes/a.md"}],                      # only resolving it tells
        ["read", {"path": f"{drive}/x/../dcu-other/a.md"}],
        ["read", {"path": str(project / "src" / "app.py")}],
        ["bash", {"command": "pytest -q"}],
    ]

    assert blocked(project, tmp_path, cases) == [True] * 6 + [False] * 3


@windows_only
def test_a_share_written_with_the_extended_prefix_is_guarded_as_the_share(tmp_path: Path) -> None:
    # The prefix of a share is \\?\UNC\: \\?\UNC\host\share\ledgers is \\host\share\ledgers.
    project, ledger = setup_project(tmp_path)
    share = as_share(ledger)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": "\\\\?\\UNC" + share[1:]}), encoding="utf-8")
    cases = [
        ["read", {"path": share + "\\entries\\x.md"}],
        ["bash", {"command": f"tool --file={share}\\x.md"}],                     # only the text tells
        ["read", {"path": as_share(project / "src" / "app.py")}],
    ]

    assert blocked(project, tmp_path, cases) == [True, True, False]


@windows_only
@pytest.mark.parametrize("how", POSIX_SPELLINGS)
def test_blocks_the_ledger_as_git_bash_cygwin_and_wsl_spell_it(tmp_path: Path, how: str) -> None:
    # C:\ledgers\app is /c/ledgers/app in Git Bash, /cygdrive/c/ledgers/app in Cygwin and /mnt/c/ledgers/app
    # in WSL: the same folder, and the hook knew none of the three.
    project, ledger = setup_project(tmp_path)
    target = spelled(ledger / "entries" / "x.md", how)
    around = spelled(project / ".." / "ledgers" / "app" / "entries" / "x.md", how)   # only resolving it tells
    cases = [
        ["read", {"path": target}],
        ["bash", {"command": f"cat '{target}'"}],
        ["bash", {"command": "echo " + "a " * 70 + f"; cat {target} | head"}],
        ["read", {"path": around}],
        ["bash", {"command": f'cat "{around}"'}],
        ["read", {"path": spelled(project / ".dev-circuit" / "guard.json", how)}],
        # the same spelling of a project file, and commands that name other such paths, still pass
        ["read", {"path": spelled(project / "src" / "app.py", how)}],
        ["bash", {"command": f"cat '{spelled(project / 'src' / 'app.py', how)}'"}],
        ["bash", {"command": "ls /c/dcu-no-such-folder /cygdrive/c /mnt/data /c /tmp"}],
        ["bash", {"command": "pytest -q"}],
    ]

    assert blocked(project, tmp_path, cases) == [True] * 6 + [False] * 4


@windows_only
def test_a_rooted_path_is_still_read_as_written_too(tmp_path: Path) -> None:
    # /c/x is C:\x in Git Bash, and \c\x on the current drive in cmd and PowerShell. The hook cannot tell which
    # shell will run the command, so it reads the path both ways. Nothing is created at the drive root.
    project = tmp_path / "app"
    drive = os.path.splitdrive(os.getcwd())[0]                   # node is started on this drive
    (project / ".dev-circuit").mkdir(parents=True)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": f"{drive}\\c\\dcu-no-such-ledger"}), encoding="utf-8")

    assert blocked(project, tmp_path, [["read", {"path": "/c/dcu-no-such-ledger/entries/x.md"}]]) == [True]


@windows_only
@pytest.mark.parametrize("how", POSIX_SPELLINGS)
def test_blocks_such_a_spelling_as_one_unquoted_word(tmp_path: Path, how: str) -> None:
    plain = tmp_path.parent / "plain"                            # tmp_path has a space in it: not one word
    if " " in str(plain):
        pytest.skip("the temp folder itself has a space in its path")
    plain.mkdir()
    project, _ = setup_project(plain)
    around = spelled(project / ".." / "ledgers" / "app" / "entries" / "x.md", how)
    cases = [
        ["bash", {"command": f"cat {around} | head"}],
        ["bash", {"command": f"cat {spelled(project / 'src' / 'app.py', how)} | head"}],
    ]

    assert blocked(project, tmp_path, cases) == [True, False]


def test_blocks_a_ledger_reached_through_a_link(tmp_path: Path) -> None:
    # Where the path did not exist yet, the hook kept it as written, link and all, and saw a project file.
    project, ledger = setup_project(tmp_path)
    (ledger / "entries").mkdir()
    (ledger / "entries" / "x.md").write_text("{}\n", encoding="utf-8")
    link_to(ledger, project / "link")
    cases = [
        ["read", {"path": "link/entries/x.md"}],
        ["read", {"path": str(project / "link" / "entries" / "x.md")}],
        ["write", {"path": "link/entries/new.md", "content": "x"}],                       # a file not there yet
        ["write", {"path": str(project / "link" / "entries" / "2027" / "new.md"), "content": "x"}],
        ["bash", {"command": "cat link/entries/*.md"}],                                   # no file has this name
        ["bash", {"command": "ls link/entries/20??"}],
        ["read", {"path": "links/entries/x.md"}],
        ["bash", {"command": "cat docs/*.md"}],
    ]

    assert blocked(project, tmp_path, cases) == [True] * 6 + [False] * 2


@windows_only
@pytest.mark.parametrize("how", ["extended prefix", "extended prefix, forward slashes"])
def test_blocks_a_ledger_reached_through_a_link_with_the_extended_prefix(tmp_path: Path, how: str) -> None:
    project, ledger = setup_project(tmp_path)
    (ledger / "entries").mkdir()
    (ledger / "entries" / "x.md").write_text("{}\n", encoding="utf-8")
    link_to(ledger, project / "link")
    cases = [
        ["read", {"path": spelled(project / "link" / "entries" / "x.md", how)}],
        ["write", {"path": spelled(project / "link" / "entries" / "new.md", how), "content": "x"}],
        ["read", {"path": spelled(project / "links" / "entries" / "x.md", how)}],
        ["read", {"path": spelled(project / "src" / "app.py", how)}],
    ]

    assert blocked(project, tmp_path, cases) == [True, True, False, False]


def test_blocks_a_denied_folder_reached_through_a_link_before_the_folder_is_there(tmp_path: Path) -> None:
    # `deny` may name a folder that is yet to be made. A link towards it that is already in the project leads
    # nowhere, so it "does not exist" either, and the hook kept the path as written from the link on.
    project, ledger = setup_project(tmp_path)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger), "deny": ["../vault/notes"]}), encoding="utf-8")
    dangling_links(tmp_path, project)
    cases = [
        ["write", {"path": "vault/notes/a.md", "content": "x"}],
        ["write", {"path": str(project / "vault" / "notes" / "2026" / "a.md"), "content": "x"}],
        ["bash", {"command": "cat vault/notes/*.md"}],
        ["write", {"path": "again/notes/a.md", "content": "x"}],                         # a link to the link
        ["write", {"path": "vault/other/a.md", "content": "x"}],
        ["write", {"path": "vaults/notes/a.md", "content": "x"}],
        ["read", {"path": "round/notes/a.md"}],                                          # judged, not followed for ever
    ]

    assert blocked(project, tmp_path, cases) == [True] * 4 + [False] * 3


def test_allows_unrelated_siblings(tmp_path: Path) -> None:
    project, _ = setup_project(tmp_path)
    cases = [["read", {"path": "../other/notes.md"}]]

    assert judge(project, tmp_path, cases) == [None]
