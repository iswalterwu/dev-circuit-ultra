"""devcircuit migrate --check: list what an older project must change, and change nothing."""

import json
import subprocess
from pathlib import Path

import devcircuit.cli as cli


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file() and ".git" not in path.parts}


def test_migrate_lists_what_an_old_project_must_change(tmp_path: Path, capsys) -> None:
    project = tmp_path / "old"
    assert cli.main(["init", "--path", str(project), "--name", "Old"]) == 0
    write(project, "AGENTS.md", "# Old\n\n| 做或续做一个功能 | `specs/<feature>/spec.md`（框架级再读同目录的 `design.md`） |\n")
    write(project, "specs/building/spec.md", "# building\n\n## 目标\n\n楼。\n\n## 规格变化\n\n- 新增 WIN-30\n\n## 切片\n\n- S1：骨架\n")
    write(project, "specs/building/design.md", "# 结构\n")
    write(project, ".dev-circuit/reviewer.json", json.dumps({"mode": "agent"}))
    write(project, "docs/architecture.md", "# 结构\n\n正文\n")
    write(project, "docs/README.md", "# 文档地图\n\n| 文档 | 回答什么 |\n|---|---|\n| [a](a.md) | a |\n")
    write(project, "scripts/doc_guard.py", "# an old copy\n")
    capsys.readouterr()
    before = snapshot(project)

    code = cli.main(["migrate", "--check", "--project", str(project)])
    out = capsys.readouterr().out

    assert code == 1
    for expected in ("specs/building/design.md", "“规格变化”", "“能力：", "reviewer.json",
                     "AGENTS.md 的路由还提到 design.md", "devcircuit context", "审核模型",
                     "docs/architecture.md 缺框架摘要", "scripts/doc_guard.py 不是当前版本",
                     "没有配置账本", "docs/README.md 还有手写的登记表", "specs/ 下有未提交的改动"):
        assert expected in out, expected
    assert snapshot(project) == before


def test_migrate_is_quiet_for_a_current_project(tmp_path: Path, capsys) -> None:
    project, ledger = tmp_path / "app", tmp_path / "ledgers" / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    assert cli.main(["ledger", "init", "--path", str(ledger)]) == 0
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": str(ledger)}))  # gitignored by the template
    assert subprocess.run(["git", "-C", str(project), "status", "--porcelain"], capture_output=True,
                          text=True, check=True).stdout.strip() == ""
    capsys.readouterr()

    code = cli.main(["migrate", "--check", "--project", str(project)])

    assert code == 0, capsys.readouterr().out
    assert "没有要改的" in capsys.readouterr().out


def test_migrate_leaves_a_project_design_doc_alone(tmp_path: Path, capsys) -> None:
    # Only the retired per-feature design.md is old routing; docs/design.md is the project's own doc.
    project = tmp_path / "ui"
    assert cli.main(["init", "--path", str(project), "--name", "UI"]) == 0
    agents = project / "AGENTS.md"
    agents.write_text(agents.read_text(encoding="utf-8") + "\n| 改界面 | `docs/design.md` |\n", encoding="utf-8")
    capsys.readouterr()

    cli.main(["migrate", "--check", "--project", str(project)])
    assert "design.md" not in capsys.readouterr().out


def test_migrate_flags_a_claude_hook_command_that_blocks_without_its_script(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    old = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": f'python3 "{project / ".dev-circuit/hooks/ledger_guard.py"}"'}]}]}}
    write(project, ".claude/settings.local.json", json.dumps(old))
    capsys.readouterr()

    cli.main(["migrate", "--check", "--project", str(project)])
    out = capsys.readouterr().out
    assert ".claude/settings.local.json" in out and "hooks install --harness claude" in out

    write(project, ".claude/settings.local.json", cli.claude_snippet(project / ".dev-circuit/hooks/ledger_guard.py"))
    cli.main(["migrate", "--check", "--project", str(project)])
    assert ".claude/settings.local.json" not in capsys.readouterr().out


def test_migrate_reports_files_over_the_size_limits(tmp_path: Path, capsys) -> None:
    project = tmp_path / "big"
    assert cli.main(["init", "--path", str(project), "--name", "Big"]) == 0
    write(project, "specs/big/spec.md", "# big\n\n能力：BIG（新建）· 框架：不变\n" + "- 行\n" * 85)
    write(project, "docs/requirements/big.md", "# 大\n代号：BIG\n" + "- 行\n" * 401)
    capsys.readouterr()

    assert cli.main(["migrate", "--check", "--project", str(project)]) == 1
    out = capsys.readouterr().out
    assert "specs/big/spec.md" in out and "超过 80 行" in out
    assert "docs/requirements/big.md" in out and "超过 400 行" in out


def test_migrate_accepts_a_human_side_ledger(tmp_path: Path, capsys) -> None:
    # Strong isolation keeps the ledger on the human side; that is a setup, not a to-do.
    project = tmp_path / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": "/not/mounted", "ledger_side": "human"}))
    capsys.readouterr()

    assert cli.main(["migrate", "--check", "--project", str(project)]) == 0, capsys.readouterr().out


def test_migrate_asks_for_a_trunk_line_when_the_remote_default_differs(tmp_path: Path, capsys) -> None:
    """Without a trunk line the base is main / master first; a different remote default needs a decision."""
    remote = tmp_path / "remote"
    write(remote, "README.md", "# r\n")
    for args in (("init", "-q", "-b", "workbench"), ("add", "-A"), ("commit", "-q", "-m", "init")):
        subprocess.run(["git", "-C", str(remote), *args], check=True, capture_output=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(clone), "branch", "main"], check=True, capture_output=True)

    cli.main(["migrate", "--check", "--project", str(clone)])
    assert any("主干" in line and "workbench" in line for line in capsys.readouterr().out.splitlines())
