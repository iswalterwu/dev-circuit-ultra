"""End-to-end demo for dev-circuit-ultra.

The demo is deliberately project-specific and disposable; it is not part of the
skill. It walks one feature through the flow and checks the boundaries:

- the settled design is written once: requirement in the capability spec, card with goal, scope, slices;
- a design change overwrites the requirement; the rejected idea goes to the ledger only;
- the dev side writes the ledger with `devcircuit ledger add` and gets a receipt, never the content;
- `devcircuit context` returns the requirement text the feature needs;
- `devcircuit close` checks, cross-checks the ledger, deletes the card, commits and records the close;
- doc_guard rejects a ledger directory in the project;
- the tool-layer hook blocks a read of the ledger and lets `devcircuit ledger add` through.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
NEW_PROJECT = ROOT / "skills" / "dev-circuit-ultra" / "scripts" / "new-project.ps1"
NEW_LEDGER = ROOT / "skills" / "dev-circuit-ultra" / "scripts" / "new-ledger.ps1"
ENV = {
    **os.environ,
    "PYTHONPATH": str(ROOT / "tools"),
    "GIT_AUTHOR_NAME": "demo",
    "GIT_AUTHOR_EMAIL": "demo@example.invalid",
    "GIT_COMMITTER_NAME": "demo",
    "GIT_COMMITTER_EMAIL": "demo@example.invalid",
}

CARD = """# add-greet：向用户打招呼

能力：GREET（新建）· 框架：不变

## 目标
给 demo 项目加一个最小的 `greet` 命令。

## 范围
- 做：一个名字，输出问候。
- 不做：网络、配置文件。

## 切片
- S1：实现 greet 和测试。
  - [x] 写 greet.py 和 tests/test_greet.py。
"""

GREET = '''"""Minimal greet CLI for the dev-circuit-ultra demo."""

import argparse


def greet(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("name is required")
    return f"Hello, {name}!"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    try:
        print(greet(args.name))
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TEST = '''import pytest

from greet import greet


# GREET-1
def test_GREET_1_greets_name():
    assert greet("Ada") == "Hello, Ada!"


def test_GREET_1_trims_name():
    assert greet("  Ada  ") == "Hello, Ada!"


# GREET-2
def test_GREET_2_rejects_empty_name():
    with pytest.raises(ValueError):
        greet("   ")
'''

REQUIREMENTS_V1 = """# Greet

代号：GREET

- GREET-1：`greet(name)` 输出去掉首尾空格后的问候。
  - 例：`greet("Ada")` → `HELLO, Ada!`。
- GREET-2：空名字报错。
  - 例：`greet("   ")` 抛出 ValueError。
"""

REQUIREMENTS = """# Greet

代号：GREET

- GREET-1：`greet(name)` 输出去掉首尾空格后的问候。
  - 例：`greet("Ada")` → `Hello, Ada!`。
- GREET-2：空名字报错。
  - 例：`greet("   ")` 抛出 ValueError。
"""


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=ENV)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"command failed: {' '.join(args)}")
    return result


def devcircuit(*args: str, cwd: Path) -> str:
    return run([sys.executable, "-m", "devcircuit.cli", *args], cwd=cwd).stdout


def git(project: Path, *args: str) -> str:
    return run(["git", "-C", str(project), *args]).stdout


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def main() -> int:
    if PWSH is None:
        raise SystemExit("pwsh 7 is required")

    with tempfile.TemporaryDirectory(prefix="dcu-demo-") as tmp:
        base = Path(tmp)
        project = base / "project"
        ledger = base / "ledger"
        card = project / "specs" / "add-greet" / "spec.md"
        requirements = project / "docs" / "requirements" / "greet.md"

        run([PWSH, "-NoProfile", "-File", str(NEW_PROJECT), "-Path", str(project), "-Name", "Demo"])
        run([PWSH, "-NoProfile", "-File", str(NEW_LEDGER), "-Path", str(ledger)])
        write(project / ".dev-circuit" / "guard.json", json.dumps({"ledger": str(ledger)}) + "\n")

        # The user settled the design: one branch, the requirement written once, the card, one record.
        git(project, "switch", "-q", "-c", "feat/add-greet")
        write(requirements, REQUIREMENTS_V1)
        write(card, CARD)
        git(project, "add", "-A")
        git(project, "commit", "-q", "-m", "design(add-greet): 打招呼", "-m", "为什么：demo 的第一个功能。")
        receipt = devcircuit("ledger", "add", "--feature", "add-greet", "--kind", "design",
                             "--decision", "输出 HELLO, NAME!（全大写）", "--ids", "GREET-1,GREET-2", cwd=project)
        assert receipt.startswith("已记录：") and "全大写" not in receipt

        # Design change: overwrite the requirement; the rejected style leaves the project for the ledger.
        write(requirements, REQUIREMENTS)
        git(project, "commit", "-q", "-am", "design(add-greet): 保留大小写", "-m", "为什么：用户改了输出样式。")
        devcircuit("ledger", "add", "--feature", "add-greet", "--kind", "design-change",
                   "--decision", "保留输入大小写，输出 Hello, NAME!",
                   "--rejected", "输出 HELLO, NAME!（全大写）：demo 决定保留输入大小写", "--ids", "GREET-1",
                   cwd=project)

        # Each session starts from the feature's context, not from whole documents.
        context = devcircuit("context", "--feature", "add-greet", cwd=project)
        assert "GREET-1" in context and "`Hello, Ada!`" in context

        write(project / "greet.py", GREET)
        write(project / "tests" / "test_greet.py", TEST)
        checks = ["pytest", "scripts/doc_guard.py", "scripts/spec_check.py"]
        run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=project)
        git(project, "add", "-A")
        git(project, "commit", "-q", "-m", "feat(add-greet): greet 和测试", "-m", "验证：pytest、两个检查器。")

        # Close: checks, ledger cross-check, card deleted, close commit and record, in one command.
        closed = devcircuit("close", "add-greet", "--summary", "交付 greet 命令",
                            "--review", "必须改 0 条", cwd=project)
        assert "交付：add-greet" in closed and "账本核对：通过" in closed
        assert not card.exists()
        assert git(project, "log", "-1", "--format=%s").strip() == "close add-greet"
        assert "通过" in devcircuit("ledger", "check", cwd=project)
        checks += ["devcircuit close", "ledger check"]

        # Boundary assertions.
        assert not (project / "ledger").exists()
        project_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in project.rglob("*")
            if path.is_file() and ".git" not in path.parts
        )
        assert "HELLO" not in project_text
        assert "全大写" not in project_text
        ledger_text = "\n".join(path.read_text(encoding="utf-8") for path in ledger.rglob("*.jsonl"))
        assert "全大写" in ledger_text
        kinds = [json.loads(line)["kind"] for line in ledger_text.splitlines() if line.strip()]
        assert kinds == ["design", "design-change", "close"]

        # The guard rejects a ledger directory inside the project.
        bad = project / "ledger"
        bad.mkdir()
        write(bad / "x.jsonl", "{}\n")
        guard = subprocess.run([sys.executable, "scripts/doc_guard.py"], cwd=project, capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
        assert guard.returncode != 0, "doc_guard should reject a project ledger directory"
        shutil.rmtree(bad)
        run([sys.executable, "scripts/doc_guard.py"], cwd=project)

        # The tool-layer hook stops a read of the ledger and lets the write-only command through.
        hook = ROOT / "hooks" / "claude" / "ledger_guard.py"

        def hook_verdict(tool_name: str, tool_input: dict) -> int:
            payload = {"cwd": str(project), "tool_name": tool_name, "tool_input": tool_input}
            return subprocess.run([sys.executable, str(hook)], input=json.dumps(payload, ensure_ascii=False),
                                  capture_output=True, text=True, encoding="utf-8", errors="replace").returncode

        assert hook_verdict("Read", {"file_path": str(ledger / "entries" / "x.jsonl")}) == 2, \
            "the hook should block a read of the ledger"
        assert hook_verdict("Read", {"file_path": "../" + ledger.name + "/entries/x.jsonl"}) == 2, \
            "the hook should block a relative path into the ledger"
        assert hook_verdict("Bash", {"command": "devcircuit ledger add --feature x --kind design --decision d"}) == 0
        assert hook_verdict("Read", {"file_path": str(project / "greet.py")}) == 0
        checks.append("hook")

        final_spec = requirements.read_text(encoding="utf-8")
        print("PASS dev-circuit-ultra demo")
        print(f"project: {project}")
        print(f"ledger:  {ledger}")
        print(f"final spec lines: {len(final_spec.splitlines())}")
        print(f"checks: {', '.join(checks)}")
        print("boundaries: no ledger content in project (only a gitignored guard config); "
              "discarded idea only in ledger; ledger add answers with a receipt; doc_guard rejects a "
              "ledger dir; hook blocks the read and lets ledger add through")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
