"""Project and ledger scaffolding, ported from the PowerShell scripts.

`new-project.ps1` and `new-ledger.ps1` are now thin wrappers around these
functions, so the behaviour lives in one place and works on every platform.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ._loader import load_script, skill_root

HOOK_FILE = ".githooks/pre-commit"
HOOK_RULE = ".githooks/** text eol=lf"
AUTO_RULE = "* text=auto eol=lf"

# destination -> (source relative to the skill folder, needs name substitution)
PROJECT_FILES = {
    "AGENTS.md": ("templates/AGENTS.md", True),
    "CLAUDE.md": ("templates/project/CLAUDE.md", False),
    "specs/backlog.md": ("templates/backlog.md", False),
    "docs/README.md": ("templates/project/docs/README.md", False),
    "docs/requirements/README.md": ("templates/project/docs/requirements/README.md", False),
    "scripts/doc_guard.py": ("scripts/doc_guard.py", False),
    "scripts/spec_check.py": ("scripts/spec_check.py", False),
    ".githooks/pre-commit": ("templates/project/.githooks/pre-commit", False),
    ".github/workflows/doc-guard.yml": (
        "templates/project/.github/workflows/doc-guard.yml", False),
    ".gitignore": ("templates/project/.gitignore", False),
    ".dcuignore": ("templates/project/.dcuignore", False),
}


class ScaffoldError(RuntimeError):
    """A precondition failed; the message is meant for the user."""


def read_template(relative: str) -> str:
    path = skill_root() / relative
    if not path.is_file():
        raise ScaffoldError(f"模板缺失：{path}")
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


def make_executable(path: Path) -> None:
    """The pre-commit hook has to be executable in the working tree, not only in the index."""
    if os.name != "nt" and path.is_file():
        path.chmod(path.stat().st_mode | 0o111)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ScaffoldError(f"git {' '.join(args)} 失败（退出码 {result.returncode}）：{detail}")
    return result.stdout


def _prepare_target(path: Path, adopt: bool) -> Path:
    if adopt:
        if not (path / ".git").exists():
            raise ScaffoldError(f"--adopt 需要一个已有的 Git 仓库：{path}")
        return path.resolve()
    if path.exists():
        if any(path.iterdir()):
            raise ScaffoldError(f"目标目录不是空的：{path}。接入已有项目请加 --adopt。")
    else:
        path.mkdir(parents=True)
    return path.resolve()


def _write_missing(root: Path, relative: str, content: str, created: list, skipped: list) -> None:
    target = root / relative
    if target.exists():
        skipped.append(relative)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")
    created.append(relative)


def _ensure_gitattributes(root: Path, adopt: bool, created: list, skipped: list) -> None:
    attributes = root / ".gitattributes"
    if not attributes.exists():
        lines = [HOOK_RULE] if adopt else [AUTO_RULE, HOOK_RULE]
        attributes.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        created.append(".gitattributes")
        return
    existing = attributes.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    if any(line.strip() == HOOK_RULE for line in existing.split("\n")):
        skipped.append(".gitattributes")
        return
    if existing and not existing.endswith("\n"):
        existing += "\n"
    attributes.write_text(existing + HOOK_RULE + "\n", encoding="utf-8", newline="\n")
    created.append(".gitattributes（追加了 hook 换行规则）")


def _run_guards(root: Path) -> tuple[int, int]:
    codes = []
    for name in ("doc_guard", "spec_check"):
        print(f"== {name} ==")
        codes.append(int(load_script(name).main(["--root", str(root)])))
    return codes[0], codes[1]


def init_project(path: Path, name: str | None, adopt: bool = False) -> int:
    """Create a dev-circuit-ultra project skeleton, or fill the gaps in a repo."""
    root = _prepare_target(path, adopt)
    project_name = name or root.name
    created: list[str] = []
    skipped: list[str] = []

    for relative, (source, substitute) in PROJECT_FILES.items():
        content = read_template(source)
        if substitute:
            content = content.replace("<项目名>", project_name)
        _write_missing(root, relative, content, created, skipped)
    _ensure_gitattributes(root, adopt, created, skipped)
    make_executable(root / HOOK_FILE)

    if not adopt:
        git(root, "init", "-q", "-b", "main")
    git(root, "config", "core.hooksPath", ".githooks")

    guard_exit, spec_exit = _run_guards(root)

    if not adopt:
        if guard_exit != 0:
            raise ScaffoldError("新项目骨架没有通过 doc_guard，请检查模板。")
        if spec_exit != 0:
            raise ScaffoldError("新项目骨架没有通过 spec_check，请检查模板。")
        git(root, "add", "-A")
        git(root, "update-index", "--chmod=+x", HOOK_FILE)
        try:
            git(root, "commit", "-q",
                "-m", "chore: 初始化 dev-circuit-ultra 项目骨架",
                "-m", "为什么：从第一天起使用 dev-circuit-ultra 的短入口、设计澄清和防回流检查。")
        except ScaffoldError as error:
            raise ScaffoldError(
                f"{error}\n文件已生成、仓库已初始化并暂存，只差首次提交。"
                "配置 git user.name / git user.email 后运行："
                f"\ngit -C {root} commit -m 'chore: 初始化 dev-circuit-ultra 项目骨架'") from error

    out = sys.stdout
    print(f"项目：{root}", file=out)
    print(f"新建：{'、'.join(created) if created else '无'}", file=out)
    print(f"已存在、未覆盖：{'、'.join(skipped) if skipped else '无'}", file=out)
    print(f"doc_guard 退出码：{guard_exit}", file=out)
    print(f"spec_check 退出码：{spec_exit}", file=out)
    if adopt:
        print("下一步：填写 AGENTS.md 里的项目事实；按上面 doc_guard 报出的问题清理旧文档；"
              "然后 git add -A，运行 git update-index --chmod=+x .githooks/pre-commit，再提交。",
              file=out)
    else:
        print("下一步：填写 AGENTS.md 里的项目事实（命令、代码地图、红线），"
              "然后开始设计澄清，写第一张卡。", file=out)
    print("要把账本边界放到工具调用层："
          "devcircuit hooks install --harness pi --project <项目> --ledger <账本>", file=out)
    return 0


def init_ledger(path: Path, commit: bool = True) -> int:
    """Create the private ledger repository outside the project."""
    template = skill_root() / "templates" / "ledger"
    if not template.is_dir():
        raise ScaffoldError(f"账本模板缺失：{template}")
    if path.exists() and any(path.iterdir()):
        raise ScaffoldError(f"目标目录不是空的：{path}")
    root = path.resolve()
    root.mkdir(parents=True, exist_ok=True)

    for entry in template.iterdir():
        destination = root / entry.name
        if entry.is_dir():
            shutil.copytree(entry, destination, dirs_exist_ok=True)
        else:
            shutil.copyfile(entry, destination)
    (root / "entries").mkdir(parents=True, exist_ok=True)

    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    if commit:
        try:
            git(root, "commit", "-q",
                "-m", "chore: initialize dev-circuit-ultra ledger",
                "-m", "为什么：把决策历史放在项目外，只供 human 回溯。")
        except ScaffoldError as error:
            raise ScaffoldError(
                f"{error}\n请先配置 git user.name / git user.email，或使用 --no-commit。") from error

    out = sys.stdout
    print(f"账本：{root}", file=out)
    print("这是私有仓库：请添加私有 remote，不要把开发容器挂载到这里。", file=out)
    print("下一步：在 dev-circuit-archivist 容器里挂载它；开发容器不要挂载。", file=out)
    return 0
