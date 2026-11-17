"""Make the dev-circuit-ultra script importable by the tests, and keep the machine out of them."""

import functools
import os
import shutil
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "dev-circuit-ultra" / "scripts"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


@pytest.fixture
def tmp_path(tmp_path: Path) -> Path:
    """Every test project lives under a folder whose name has a space and non-ASCII characters.

    The bugs this flow has had on Windows were about paths and encodings; a plain ASCII temp folder hides them.
    """
    path = tmp_path / "项目 目录"
    path.mkdir()
    return path


@pytest.fixture
def gbk_env() -> dict[str, str]:
    """Environment for a child process whose stdio is GBK, as piped output is on Chinese Windows."""
    return {**os.environ, "PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0"}


@pytest.fixture(scope="session")
def _empty_git_config(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("gitconfig") / "config"
    path.write_text("", encoding="utf-8")
    return path


@functools.lru_cache(maxsize=None)  # the same PATH for every test; looking through it costs tens of milliseconds
def _without_an_installed_devcircuit(search_path: str) -> str:
    """PATH without the folders that hold an installed `devcircuit`.

    The pwsh forwarders prefer a `devcircuit` on PATH over this checkout, so with one installed the tests
    that go through them would exercise that build. A folder that also holds the interpreter running the
    tests (a venv with the project installed) stays: dropping it would take python away too.
    """
    interpreter = Path(sys.executable).resolve().parent
    kept = []
    for entry in search_path.split(os.pathsep):
        installed = entry and shutil.which("devcircuit", path=entry)
        if installed and Path(entry).resolve() != interpreter:
            continue
        kept.append(entry)
    return os.pathsep.join(kept)


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch, _empty_git_config: Path):
    """Tests must not depend on the machine's git identity, git config or installed devcircuit."""
    for variable in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(variable, "dcu tests")
    for variable in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(variable, "tests@example.invalid")
    # The system config stays: Git for Windows ships core.autocrlf=true there, and that is worth meeting.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(_empty_git_config))
    # Run from inside a git hook, these would point every `git` the tests start at the outer repository.
    for variable in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX"):
        monkeypatch.delenv(variable, raising=False)
    # A child python that reads or writes a file without naming the encoding fails instead of guessing.
    monkeypatch.setenv("PYTHONWARNDEFAULTENCODING", "1")
    monkeypatch.setenv("PYTHONWARNINGS", "error::EncodingWarning")
    monkeypatch.setenv("PATH", _without_an_installed_devcircuit(os.environ.get("PATH", "")))
