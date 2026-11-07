"""Find the skill tree, the guard scripts and the hook assets.

Installed wheel layout (built from pyproject.toml force-include):

    devcircuit/assets/skills/dev-circuit-ultra/scripts/doc_guard.py
    devcircuit/assets/skills/dev-circuit-ultra/templates/...
    devcircuit/assets/hooks/pi/ledger-guard.js

Source checkout layout:

    <repo>/skills/dev-circuit-ultra/...
    <repo>/hooks/pi/ledger-guard.js
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

PACKAGE_DIR = Path(__file__).resolve().parent
SOURCE_ROOT = PACKAGE_DIR.parents[1]
SKILL_NAMES = ("dev-circuit-ultra", "dev-circuit-archivist", "dev-circuit-ledger")


def _pick(installed: Path, checkout: Path) -> Path:
    if installed.exists():
        return installed
    return checkout


def skills_dir() -> Path:
    """Directory that holds the three skill folders."""
    path = _pick(PACKAGE_DIR / "assets" / "skills", SOURCE_ROOT / "skills")
    if not path.is_dir():
        raise RuntimeError(
            "找不到 skills 目录：既不在已安装的 devcircuit/assets，也不在源码树。"
            "请重新安装（pipx install --force <仓库>）。"
        )
    return path


def skill_root(name: str = "dev-circuit-ultra") -> Path:
    return skills_dir() / name


def script_path(name: str) -> Path:
    """Return the path of `doc_guard` or `spec_check`."""
    path = skill_root() / "scripts" / f"{name}.py"
    if not path.is_file():
        raise RuntimeError(f"找不到 {name}.py：{path}")
    return path


def load_script(name: str):
    """Import a guard script as a module so its main() can be called directly."""
    path = script_path(name)
    spec = spec_from_file_location(f"devcircuit._guard_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 {path}")
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def asset_path(*parts: str) -> Path:
    """Return a hook asset, installed or from the source tree."""
    path = _pick(PACKAGE_DIR.joinpath("assets", "hooks", *parts), SOURCE_ROOT.joinpath("hooks", *parts))
    if not path.is_file():
        raise RuntimeError(f"找不到 hook 资源：{'/'.join(parts)}")
    return path
