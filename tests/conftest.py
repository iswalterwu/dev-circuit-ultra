"""Make the dev-circuit-ultra script importable by the tests."""

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "dev-circuit-ultra" / "scripts"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch):
    """Tests must not depend on the machine's git identity."""
    for variable in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(variable, "dcu tests")
    for variable in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(variable, "tests@example.invalid")
