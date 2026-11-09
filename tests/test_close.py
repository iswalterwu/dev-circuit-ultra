"""devcircuit close: checks, ledger check, delete the card, commit, close record, delivery skeleton."""

import json
from pathlib import Path

import devcircuit.cli as cli
from test_ledger import CARD, DEMO, git, setup, write


def designed(tmp_path: Path, capsys, with_record: bool = True) -> tuple[Path, Path]:
    project, ledger_root = setup(tmp_path)
    git(project, "switch", "-q", "-c", "feat/x")
    write(project, "docs/requirements/demo.md",
          DEMO + "- DEMO-3：输出写不进去时给出可读错误。\n  - 例：目录不存在时以 1 退出。\n")
    write(project, "specs/x/spec.md", CARD.format(framework="不变"))
    write(project, "tests/test_export.py", "# DEMO-1\n")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "design(x): 导出")
    if with_record:
        assert cli.main(["ledger", "add", "--project", str(project), "--feature", "x", "--kind", "design",
                         "--decision", "d", "--ids", "DEMO-3"]) == 0
    capsys.readouterr()
    return project, ledger_root


def close(capsys, project: Path, *extra: str) -> tuple[int, str, str]:
    code = cli.main(["close", "x", "--project", str(project), "--summary", "交付导出的出错处理", *extra])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_close_deletes_the_card_commits_records_and_drafts_the_report(tmp_path: Path, capsys) -> None:
    project, ledger_root = designed(tmp_path, capsys)

    code, out, err = close(capsys, project, "--review", "必须改 1 条，已修 1 条")

    assert code == 0, out + err
    assert not (project / "specs" / "x").exists()
    assert git(project, "log", "-1", "--format=%s").strip() == "close x"
    assert git(project, "status", "--short").strip() == ""
    head = git(project, "rev-parse", "HEAD").strip()
    records = [json.loads(line) for line in
               (ledger_root / "entries" / "app" / "x.jsonl").read_text(encoding="utf-8").splitlines()]
    assert records[-1]["kind"] == "close" and records[-1]["commit"] == head
    assert records[-1]["review"] == "必须改 1 条，已修 1 条"
    assert "交付：x" in out and "新增：DEMO-3" in out
    assert "未覆盖的要求：DEMO-3" in out
    assert "账本核对：通过" in out


def test_close_refuses_uncommitted_changes(tmp_path: Path, capsys) -> None:
    project, _ = designed(tmp_path, capsys)
    write(project, "src/export.py", "print(1)\n")

    code, _, err = close(capsys, project)

    assert code == 2 and "src/export.py" in err
    assert (project / "specs" / "x" / "spec.md").is_file()


def test_close_stops_when_the_checks_fail(tmp_path: Path, capsys) -> None:
    project, _ = designed(tmp_path, capsys)
    write(project, "tests/test_stale.py", "# DEMO-9\n")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "test(x): stale")
    before = git(project, "rev-parse", "HEAD").strip()

    code, out, _ = close(capsys, project)

    assert code == 1 and "dangling-ref" in out
    assert git(project, "rev-parse", "HEAD").strip() == before
    assert (project / "specs" / "x" / "spec.md").is_file()


def test_close_stops_when_the_ledger_disagrees(tmp_path: Path, capsys) -> None:
    project, _ = designed(tmp_path, capsys, with_record=False)

    code, out, _ = close(capsys, project)

    assert code == 1 and "[design-missing] x" in out
    assert (project / "specs" / "x" / "spec.md").is_file()


def test_close_without_a_ledger_still_closes(tmp_path: Path, capsys) -> None:
    project, _ = designed(tmp_path, capsys)
    (project / ".dev-circuit" / "guard.json").unlink()

    code, out, _ = close(capsys, project)

    assert code == 0
    assert "没有配置账本" in out
    assert not (project / "specs" / "x").exists()


def test_close_checks_the_feature_name_first(tmp_path: Path, capsys) -> None:
    project, _ = designed(tmp_path, capsys)
    before = git(project, "rev-parse", "HEAD").strip()

    assert cli.main(["close", "ui/login", "--project", str(project), "--summary", "s"]) == 2
    assert "功能名" in capsys.readouterr().err
    assert git(project, "rev-parse", "HEAD").strip() == before


def test_close_needs_the_card_name_exactly(tmp_path: Path, capsys) -> None:
    project, _ = designed(tmp_path, capsys)

    assert cli.main(["close", "X", "--project", str(project), "--summary", "s"]) == 2
    assert "specs/X/spec.md" in capsys.readouterr().err
    assert (project / "specs" / "x" / "spec.md").is_file()


def test_close_restores_the_card_when_the_commit_fails(tmp_path: Path, capsys) -> None:
    project, _ = designed(tmp_path, capsys)
    write(project, ".gitignore", ".dev-circuit/\n*.local\n")
    git(project, "commit", "-q", "-am", "chore: ignore local notes")
    write(project, "specs/x/notes.local", "keep me\n")
    hooks = tmp_path / "failing-hooks"
    hook = write(hooks, "pre-commit", "#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    git(project, "config", "core.hooksPath", str(hooks))
    before = git(project, "rev-parse", "HEAD").strip()

    code, _, err = close(capsys, project)

    assert code == 2 and "提交失败，卡已恢复" in err
    assert git(project, "rev-parse", "HEAD").strip() == before
    assert (project / "specs" / "x" / "spec.md").is_file()
    assert (project / "specs" / "x" / "notes.local").read_text(encoding="utf-8") == "keep me\n"
    assert git(project, "status", "--short").strip() == ""


def test_close_skips_the_ledger_on_a_human_side_setup(tmp_path: Path, capsys) -> None:
    project, ledger_root = designed(tmp_path, capsys)
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": "/not/mounted", "ledger_side": "human"}))

    code, out, err = close(capsys, project)

    assert code == 0, out + err
    assert "账本在 human 一侧" in out and "devcircuit ledger add --feature x --kind close" in out
    assert not (project / "specs" / "x").exists()
    records = (ledger_root / "entries" / "app" / "x.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == 1


def test_close_is_not_blocked_by_another_features_gap(tmp_path: Path, capsys) -> None:
    project, _ = designed(tmp_path, capsys)
    write(project, "specs/y/spec.md", CARD.format(framework="不变"))
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "design(y): 另一个功能")

    code, out, err = close(capsys, project)

    assert code == 0, out + err
    assert "[design-missing] y" in out
    assert not (project / "specs" / "x").exists()


def test_close_refuses_an_empty_summary_before_committing(tmp_path: Path, capsys) -> None:
    project, _ = designed(tmp_path, capsys)
    before = git(project, "rev-parse", "HEAD").strip()

    assert cli.main(["close", "x", "--project", str(project), "--summary", "  "]) == 2
    assert "--summary" in capsys.readouterr().err
    assert git(project, "rev-parse", "HEAD").strip() == before
    assert (project / "specs" / "x" / "spec.md").is_file()
