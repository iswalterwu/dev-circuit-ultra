"""The pi extension blocks tool calls that name the ledger.

Node is optional: without it these tests skip instead of failing. The harness
registers the real extension against a stub `pi` object and asks it to judge a
list of tool calls.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
HOOK = Path(__file__).resolve().parents[1] / "hooks" / "pi" / "ledger-guard.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

HARNESS = """
const [,, hookPath, cwd, casesJson] = process.argv
const { pathToFileURL } = await import("node:url")
const hook = await import(pathToFileURL(hookPath).href)
const handlers = {}
hook.default({ on: (name, fn) => { handlers[name] = fn } })
const ctx = { cwd, ui: { notify: () => {} } }
const results = []
for (const [toolName, input] of JSON.parse(casesJson)) {
  const result = await handlers.tool_call({ toolName, input }, ctx)
  results.push(result ?? null)
}
process.stdout.write(JSON.stringify(results))
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


def judge(project: Path, tmp_path: Path, cases: list) -> list:
    harness = tmp_path / "harness.mjs"
    harness.write_text(HARNESS, encoding="utf-8")
    result = subprocess.run(
        [NODE, str(harness), str(HOOK), str(project), json.dumps(cases)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


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


def test_allows_normal_work(tmp_path: Path) -> None:
    project, _ = setup_project(tmp_path)
    cases = [
        ["read", {"path": str(project / "src" / "app.py")}],
        ["bash", {"command": "pytest -q"}],
        ["write", {"path": str(project / "docs" / "a.md"), "content": "hi"}],
    ]

    assert judge(project, tmp_path, cases) == [None, None, None]


def test_without_config_nothing_is_blocked(tmp_path: Path) -> None:
    project = tmp_path / "app"
    project.mkdir()
    cases = [["read", {"path": str(tmp_path / "ledgers" / "app" / "x.md")}]]

    assert judge(project, tmp_path, cases) == [None]


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


def test_allows_unrelated_siblings(tmp_path: Path) -> None:
    project, _ = setup_project(tmp_path)
    cases = [["read", {"path": "../other/notes.md"}]]

    assert judge(project, tmp_path, cases) == [None]
