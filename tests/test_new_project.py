import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "spec-loop" / "scripts" / "new-project.ps1"
PWSH = shutil.which("pwsh")

pytestmark = pytest.mark.skipif(PWSH is None, reason="需要 PowerShell 7（pwsh）")

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "spec-loop test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "spec-loop test",
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


SKELETON = [
    "AGENTS.md",
    "CLAUDE.md",
    "specs/backlog.md",
    "docs/README.md",
    "scripts/doc_guard.py",
    ".githooks/pre-commit",
    ".github/workflows/doc-guard.yml",
    ".gitattributes",
]


def test_new_project_creates_skeleton_and_first_commit(tmp_path):
    target = tmp_path / "demo"
    result = run_script("-Path", str(target), "-Name", "Demo")
    assert result.returncode == 0, result.stdout + result.stderr

    for relative in SKELETON:
        assert (target / relative).is_file(), relative
    assert (target / "AGENTS.md").read_text(encoding="utf-8").startswith("# Demo")
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"
    assert b"\r\n" not in (target / ".githooks" / "pre-commit").read_bytes()

    assert git(target, "config", "core.hooksPath").stdout.strip() == ".githooks"
    assert len(git(target, "log", "--oneline").stdout.strip().splitlines()) == 1
    assert git(target, "status", "--short").stdout.strip() == ""
    assert "100755" in git(target, "ls-files", "-s", ".githooks/pre-commit").stdout

    guard = subprocess.run(
        [sys.executable, str(target / "scripts" / "doc_guard.py"), "--root", str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert guard.returncode == 0, guard.stdout


def test_new_project_refuses_non_empty_directory(tmp_path):
    target = tmp_path / "busy"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")

    result = run_script("-Path", str(target))

    assert result.returncode != 0
    assert not (target / "AGENTS.md").exists()


def test_adopt_keeps_existing_files_and_does_not_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert git(repo, "init", "-q", "-b", "main").returncode == 0
    (repo / "AGENTS.md").write_text("# 已有入口\n", encoding="utf-8")
    (repo / ".gitattributes").write_text("*.png binary\n", encoding="utf-8")

    result = run_script("-Path", str(repo), "-Adopt")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == "# 已有入口\n"
    assert (repo / "CLAUDE.md").is_file()
    assert (repo / "scripts" / "doc_guard.py").is_file()
    assert (repo / ".gitattributes").read_text(encoding="utf-8").splitlines() == [
        "*.png binary",
        ".githooks/** text eol=lf",
    ]
    assert git(repo, "config", "core.hooksPath").stdout.strip() == ".githooks"
    assert git(repo, "rev-parse", "--verify", "HEAD").returncode != 0
    assert "AGENTS.md" in result.stdout


def test_adopt_requires_git_repository(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()

    result = run_script("-Path", str(folder), "-Adopt")

    assert result.returncode != 0
    assert not (folder / "AGENTS.md").exists()
