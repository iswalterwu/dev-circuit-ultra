import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "dev-circuit-ultra" / "scripts" / "new-ledger.ps1"
PWSH = shutil.which("pwsh")

pytestmark = pytest.mark.skipif(PWSH is None, reason="需要 PowerShell 7（pwsh）")

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "dev-circuit-ultra test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "dev-circuit-ultra test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def run_script(*args):
    return subprocess.run(
        [PWSH, "-NoProfile", "-File", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **GIT_IDENTITY},
    )


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **GIT_IDENTITY},
    )


def test_new_ledger_creates_private_repo_outside_project(tmp_path):
    ledger = tmp_path / "ledger"
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("project\n", encoding="utf-8")

    result = run_script("-Path", str(ledger))

    assert result.returncode == 0, result.stdout + result.stderr
    for relative in ("README.md", "schema.md", "access.jsonl", "entries/.gitkeep"):
        assert (ledger / relative).is_file(), relative
    assert len(git(ledger, "log", "--oneline").stdout.strip().splitlines()) == 1
    assert git(ledger, "status", "--short").stdout.strip() == ""
    assert not (project / "ledger").exists()
    assert not (project / "schema.md").exists()


def test_new_ledger_refuses_non_empty_directory(tmp_path):
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "keep.txt").write_text("keep\n", encoding="utf-8")

    result = run_script("-Path", str(ledger))

    assert result.returncode != 0
    assert not (ledger / "README.md").exists()
