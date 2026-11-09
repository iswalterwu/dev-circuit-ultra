"""The Claude Code hook is a subprocess contract: JSON in, exit code out."""

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "claude" / "ledger_guard.py"


def setup_project(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "app"
    ledger = tmp_path / "ledgers" / "app"
    project.mkdir()
    ledger.mkdir(parents=True)
    (project / ".dev-circuit").mkdir()
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger)}), encoding="utf-8")
    return project, ledger


def run_hook(payload: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK), *args],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        timeout=60,
    )


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


def test_without_config_the_hook_stays_out_of_the_way(tmp_path: Path) -> None:
    project = tmp_path / "app"
    project.mkdir()
    payload = {"cwd": str(project), "tool_name": "Read",
               "tool_input": {"file_path": str(tmp_path / "anything.md")}}

    assert run_hook(payload).returncode == 0


def test_json_decision_mode(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    payload = {"cwd": str(project), "tool_name": "Read",
               "tool_input": {"file_path": str(ledger / "x.md")}}

    result = run_hook(payload, "--json")
    assert result.returncode == 0
    decision = json.loads(result.stdout.decode("utf-8"))["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "账本边界" in decision["permissionDecisionReason"]


def test_status_reports_the_boundary(tmp_path: Path) -> None:
    project, ledger = setup_project(tmp_path)
    result = subprocess.run([sys.executable, str(HOOK), "--status"], cwd=project,
                            capture_output=True, text=True, encoding="utf-8", timeout=60)

    assert result.returncode == 0
    printed = result.stdout.lower()
    assert str(ledger.resolve()).lower() in printed
    assert "拒绝" in printed


def test_bad_input_is_a_non_blocking_error(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, str(HOOK)], input=b"not json",
                            capture_output=True, timeout=60)

    assert result.returncode == 1


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


def test_allows_unrelated_siblings(tmp_path: Path) -> None:
    project, _ = setup_project(tmp_path)
    payload = {"cwd": str(project), "tool_name": "Read",
               "tool_input": {"file_path": "../other/notes.md"}}

    assert run_hook(payload).returncode == 0
