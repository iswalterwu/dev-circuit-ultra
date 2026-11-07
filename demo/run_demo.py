"""End-to-end demo for dev-circuit-ultra.

The demo is deliberately project-specific and disposable; it is not part of the
skill. It checks the methodology boundaries:

- a current design card, no rejected alternatives;
- design change by overwriting, not appending;
- implementation and tests derived from the design;
- a private ledger outside the project;
- discarded ideas only in the ledger;
- a human-only brief that excludes discarded ideas;
- doc_guard rejects a ledger directory in the project;
- the tool-layer hook blocks a read of the ledger before it happens.
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
ARCHIVIST = ROOT / "demo" / "archivist_standin.py"

CARD_V1 = """# add-greet：向用户打招呼

## 目标
给 demo 项目加一个最小的 `greet` 命令。

## 范围
- 做：一个名字，输出问候。
- 不做：网络、配置文件。
- 反目标：空名字也输出问候。

## 结构影响
- 动哪些模块：新增 `greet.py`。
- 新契约 / 新数据结构 / 全局机制：无。
- 结论：普通。

## 设计
- `greet(name)` 去掉首尾空格；空名字抛 `ValueError`。
- CLI：`python -m greet --name NAME`，输出 `HELLO, NAME!`。
- 只保留这一种输出；不讨论其他风格。
- 失败行为：`--name` 缺失或去掉空格后为空时，CLI 用 argparse 报错，退出码 2，不输出问候。

## 规格变化
- 新增 GREET-1：`greet` 输出问候。例：`greet("Ada")` → `HELLO, Ada!`。

## 风险
- 风险档：低。
- 风险加项：无。
- 验收方式：功能结束时一起验收。

## 切片
- S1：实现 greet 和测试。
  - [x] 写 greet.py 和 tests/test_greet.py。

## 待定
无。
"""

CARD_V2 = """# add-greet：向用户打招呼

## 目标
给 demo 项目加一个最小的 `greet` 命令。

## 范围
- 做：一个名字，输出问候。
- 不做：网络、配置文件。
- 反目标：空名字也输出问候。

## 结构影响
- 动哪些模块：新增 `greet.py`。
- 新契约 / 新数据结构 / 全局机制：无。
- 结论：普通。

## 设计
- `greet(name)` 去掉首尾空格；空名字抛 `ValueError`。
- CLI：`python -m greet --name NAME`，输出 `Hello, NAME!`。
- 保留输入的大小写，不做自动大写。
- 失败行为：`--name` 缺失或去掉空格后为空时，CLI 用 argparse 报错，退出码 2，不输出问候。

## 规格变化
- 新增 GREET-1：`greet` 输出问候。例：`greet("Ada")` → `Hello, Ada!`。

## 风险
- 风险档：低。
- 风险加项：无。
- 验收方式：功能结束时一起验收。

## 切片
- S1：实现 greet 和测试。
  - [x] 写 greet.py 和 tests/test_greet.py。

## 待定
无。
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


def test_GREET_1_greets_name():
    assert greet("Ada") == "Hello, Ada!"


def test_GREET_1_trims_name():
    assert greet("  Ada  ") == "Hello, Ada!"


def test_GREET_1_rejects_empty_name():
    with pytest.raises(ValueError):
        greet("   ")
'''

STUB = """# Greet

代号：GREET
"""

REQUIREMENTS = """# Greet

代号：GREET

- GREET-1：`greet(name)` 输出去掉首尾空格后的问候；空名字报错。
  - 例：`greet("Ada")` → `Hello, Ada!`。
  - 证明：`tests/test_greet.py` 中的 `test_GREET_1_greets_name`。
"""


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "demo",
        "GIT_AUTHOR_EMAIL": "demo@example.invalid",
        "GIT_COMMITTER_NAME": "demo",
        "GIT_COMMITTER_EMAIL": "demo@example.invalid",
    }
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"command failed: {' '.join(args)}")
    return result


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

        run([PWSH, "-NoProfile", "-File", str(NEW_PROJECT), "-Path", str(project), "-Name", "Demo"])
        run([PWSH, "-NoProfile", "-File", str(NEW_LEDGER), "-Path", str(ledger)])

        write(card, CARD_V1)
        run(
            [
                sys.executable,
                str(ARCHIVIST),
                "--ledger",
                str(ledger),
                "--project",
                str(project),
                "--feature",
                "add-greet",
                "--kind",
                "design",
                "--decision",
                "输出 HELLO, NAME!（全大写）",
            ]
        )

        # Design change: overwrite the card, delete the rejected style from the project.
        write(card, CARD_V2)
        run(
            [
                sys.executable,
                str(ARCHIVIST),
                "--ledger",
                str(ledger),
                "--project",
                str(project),
                "--feature",
                "add-greet",
                "--kind",
                "design-change",
                "--decision",
                "保留输入大小写，输出 Hello, NAME!",
                "--discarded",
                json.dumps(
                    [{"idea": "输出 HELLO, NAME!（全大写）", "why": "demo 决定保留输入大小写"}],
                    ensure_ascii=False,
                ),
                "--constraints",
                json.dumps(["保留输入大小写"], ensure_ascii=False),
            ]
        )

        write(project / "greet.py", GREET)
        write(project / "tests" / "test_greet.py", TEST)
        # The capability code exists from the start; the new ID is only merged at close.
        write(project / "docs" / "requirements" / "greet.md", STUB)

        checks = ["pytest", "scripts/doc_guard.py", "scripts/spec_check.py"]
        run([sys.executable, "-m", "pytest", "-q"], cwd=project)
        run([sys.executable, "scripts/doc_guard.py"], cwd=project)
        run([sys.executable, "scripts/spec_check.py"], cwd=project)

        # Close: merge the current requirement, then delete the card.
        write(project / "docs" / "requirements" / "greet.md", REQUIREMENTS)
        card_text = card.read_text(encoding="utf-8").replace("## 规格变化", "## 规格变化（已合并）")
        write(card, card_text)
        # The card is deleted immediately after the merge; spec_check runs on the
        # final tree, where the requirement exists only in the capability spec.
        shutil.rmtree(project / "specs" / "add-greet")
        run([sys.executable, "scripts/doc_guard.py"], cwd=project)
        run([sys.executable, "scripts/spec_check.py"], cwd=project)

        run(
            [
                sys.executable,
                str(ARCHIVIST),
                "--ledger",
                str(ledger),
                "--project",
                str(project),
                "--feature",
                "add-greet",
                "--kind",
                "close",
                "--decision",
                "最终保留 Hello, NAME!；卡已删除",
                "--constraints",
                json.dumps(["保留输入大小写"], ensure_ascii=False),
            ]
        )

        # Boundary assertions.
        assert not (project / "ledger").exists()
        assert ledger.is_dir()
        assert not card.exists()
        project_text = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in project.rglob("*")
            if path.is_file() and ".git" not in path.parts
        )
        assert "HELLO" not in project_text
        assert "全大写" not in project_text
        ledger_text = "\n".join(path.read_text(encoding="utf-8") for path in ledger.rglob("*.jsonl"))
        assert "全大写" in ledger_text
        entries = [json.loads(line) for line in ledger_text.splitlines() if line.strip()]
        brief = "\n".join(constraint for entry in entries for constraint in entry.get("constraints", []))
        assert "全大写" not in brief

        # The guard rejects a ledger directory inside the project.
        bad = project / "ledger"
        bad.mkdir()
        write(bad / "x.jsonl", "{}\n")
        guard = subprocess.run(
            [sys.executable, "scripts/doc_guard.py"],
            cwd=project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert guard.returncode != 0, "doc_guard should reject a project ledger directory"
        shutil.rmtree(bad)
        run([sys.executable, "scripts/doc_guard.py"], cwd=project)

        # The tool-layer hook stops the same read before it happens.
        hook = ROOT / "hooks" / "claude" / "ledger_guard.py"
        write(project / ".dev-circuit" / "guard.json",
              json.dumps({"ledger": str(ledger)}, ensure_ascii=False) + "\n")

        def hook_verdict(tool_name: str, tool_input: dict) -> int:
            payload = {"cwd": str(project), "tool_name": tool_name, "tool_input": tool_input}
            return subprocess.run(
                [sys.executable, str(hook)],
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            ).returncode

        assert hook_verdict("Read", {"file_path": str(ledger / "entries" / "x.jsonl")}) == 2, \
            "the hook should block a read of the ledger"
        assert hook_verdict("Read", {"file_path": "../" + ledger.name + "/entries/x.jsonl"}) == 2, \
            "the hook should block a relative path into the ledger"
        assert hook_verdict("Read", {"file_path": str(project / "greet.py")}) == 0
        checks.append("hook")

        final_spec = (project / "docs" / "requirements" / "greet.md").read_text(encoding="utf-8")
        print("PASS dev-circuit-ultra demo")
        print(f"project: {project}")
        print(f"ledger:  {ledger}")
        print(f"final spec lines: {len(final_spec.splitlines())}")
        print(f"checks: {', '.join(checks)}")
        print("boundaries: no ledger content in project (only a gitignored guard config); "
              "discarded idea only in ledger; doc_guard rejects a ledger dir; hook blocks the read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
