"""Copy the skill folders into the agent skill directories."""

import os
import shutil
import sys
from pathlib import Path

from . import __version__
from ._loader import SKILL_NAMES, skills_dir

LEGACY_SKILLS = ("spec-loop", "design-loop", "dev-circuit-archivist")


def default_targets() -> list[Path]:
    home = Path.home()
    dsh_home = Path(os.environ["DSH_HOME"]) if os.environ.get("DSH_HOME") else home / ".dsh"
    return [
        home / ".claude" / "skills",
        home / ".agents" / "skills",
        dsh_home / "skills",
    ]


def _skip_caches(directory: str, names: list[str]) -> list[str]:
    return [name for name in names if name == "__pycache__" or name.endswith(".pyc")]


def sync(targets: list[Path] | None = None) -> int:
    """Install or refresh the skills in every target directory and remove retired ones."""
    source = skills_dir()
    for name in SKILL_NAMES:
        if not (source / name).is_dir():
            raise RuntimeError(f"技能目录缺失：{source / name}")

    out = sys.stdout
    for target in targets or default_targets():
        target.mkdir(parents=True, exist_ok=True)
        for legacy in LEGACY_SKILLS:
            old = target / legacy
            if old.exists():
                shutil.rmtree(old)
                print(f"移除旧技能：{old}", file=out)
        for name in SKILL_NAMES:
            destination = target / name
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source / name, destination, ignore=_skip_caches)
        print(f"{target}: {len(SKILL_NAMES)} skills synced (devcircuit {__version__})", file=out)
    return 0
