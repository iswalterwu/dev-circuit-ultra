"""devcircuit close: checks, ledger check, delete the card, commit, close record, delivery skeleton."""

import json
import os
import stat
from pathlib import Path

import pytest

import devcircuit.cli as cli
import devcircuit.ledger as ledger_module
from test_ledger import CARD, DEMO, entries, git, names_the_ledger, no_looking_into, setup, write


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
    assert "合并 feat/x" in out
    assert "补写了账本的收尾记录" not in out               # that is what a rerun says


@pytest.mark.parametrize("move, expected", [
    (("branch", "-m", "topic/export"), "合并 topic/export"),
    (("switch", "-q", "--detach"), "不在任何分支上"),
], ids=["another-branch", "detached"])
def test_close_names_the_branch_it_is_on(tmp_path: Path, capsys, move, expected) -> None:
    # The closing line said "合并 feat/x" whatever the branch was called, pointing at a branch that may not exist.
    project, _ = designed(tmp_path, capsys)
    git(project, *move)

    code, out, err = close(capsys, project)

    assert code == 0, out + err
    assert expected in out and "feat/x" not in out


def test_close_on_the_trunk_says_what_it_could_not_compare(tmp_path: Path, capsys) -> None:
    # HEAD is the fork point there, so nothing tells which requirements the feature changed. The report showed
    # no changes and no uncovered requirements, as if that had been checked, and still said to merge feat/x.
    project, _ = designed(tmp_path, capsys)
    git(project, "switch", "-q", "main")
    git(project, "merge", "-q", "--ff-only", "feat/x")
    git(project, "branch", "-q", "-D", "feat/x")

    code, out, err = close(capsys, project)

    assert code == 0, out + err
    assert "要求变化和未覆盖的要求没比，账本的 removal-unrecorded 也没查：" in out and "基线 main" in out
    assert "新增：" not in out and "未覆盖的要求：" not in out
    assert "feat/x" not in out and "就在 main 上" in out


@pytest.mark.parametrize("with_ledger", [True, False], ids=["ledger", "no-ledger"])
def test_close_without_a_base_to_compare_against_says_so(tmp_path: Path, capsys, with_ledger) -> None:
    project, _ = designed(tmp_path, capsys)
    git(project, "branch", "-m", "main", "develop")   # no main, master or remote, and AGENTS.md names no trunk
    if not with_ledger:
        (project / ".dev-circuit" / "guard.json").unlink()

    code, out, err = close(capsys, project)

    assert code == 0, out + err
    assert "要求变化和未覆盖的要求没比" in out and "找不到可比的基线" in out
    assert "新增：" not in out and "未覆盖的要求：" not in out
    # The ledger's own check skipped the same thing, and that is said only where a ledger was checked.
    assert ("removal-unrecorded 也没查" in out) == with_ledger


def test_close_refuses_uncommitted_changes(tmp_path: Path, capsys) -> None:
    project, _ = designed(tmp_path, capsys)
    write(project, "src/export.py", "print(1)\n")

    code, _, err = close(capsys, project)

    assert code == 2 and "src/export.py" in err
    assert (project / "specs" / "x" / "spec.md").is_file()


def test_close_names_a_dirty_file_with_a_non_ascii_name_readably(tmp_path: Path, capsys) -> None:
    # git quotes and octal-escapes such names unless told not to; context and spec_check already tell it.
    project, _ = designed(tmp_path, capsys)
    write(project, "src/应用.py", "print(1)\n")

    code, _, err = close(capsys, project)

    assert code == 2 and "src/应用.py" in err
    assert "\\345" not in err and '"' not in err


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


def test_close_runs_both_checkers_before_it_stops(tmp_path: Path, capsys) -> None:
    # When doc_guard failed spec_check never ran, so its findings only showed once the first round was fixed.
    project, _ = designed(tmp_path, capsys)
    write(project, "docs/notes.md", "见 [设计](missing.md)。\n")
    write(project, "tests/test_stale.py", "# DEMO-9\n")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "docs(x): notes")

    code, out, _ = close(capsys, project)

    assert code == 1 and "broken-link" in out and "dangling-ref" in out
    assert (project / "specs" / "x" / "spec.md").is_file()


def test_close_stops_when_the_ledger_disagrees(tmp_path: Path, capsys) -> None:
    project, _ = designed(tmp_path, capsys, with_record=False)

    code, out, _ = close(capsys, project)

    assert code == 1 and "[design-missing] x" in out
    assert (project / "specs" / "x" / "spec.md").is_file()


def test_close_stops_readably_when_the_ledger_cannot_be_looked_into(tmp_path: Path, capsys, monkeypatch) -> None:
    # Before the commit an OSError on the way to the ledger was a traceback, with the ledger's path in it.
    project, ledger_root = designed(tmp_path, capsys)
    before = git(project, "rev-parse", "HEAD").strip()
    no_looking_into(ledger_root, monkeypatch)

    code, out, err = close(capsys, project)

    assert code == 2 and "Permission denied" in err and "没有收尾" in err
    assert not names_the_ledger(ledger_root, out + err)
    assert git(project, "rev-parse", "HEAD").strip() == before
    assert (project / "specs" / "x" / "spec.md").is_file()


def test_close_without_a_ledger_still_closes(tmp_path: Path, capsys) -> None:
    project, _ = designed(tmp_path, capsys)
    (project / ".dev-circuit" / "guard.json").unlink()

    code, out, _ = close(capsys, project)

    assert code == 0
    assert "没有配置账本" in out
    assert not (project / "specs" / "x").exists()

    head = git(project, "rev-parse", "HEAD").strip()
    code, out, err = close(capsys, project)                # the same command again: nothing left to do

    assert code == 0, out + err
    assert "没有配置账本" in out and "交付：x" in out
    assert git(project, "rev-parse", "HEAD").strip() == head


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


@pytest.mark.parametrize("commits", [
    [("close nope", None)],
    [("design(nope)", "write"), ("chore: nope 不做了", "delete")],
    [("design(nope)", "write"), ("close other", "delete")],
    [("design(nope)", "write"), ("close nope", "write"), ("chore: nope 不做了", "delete")],
], ids=["subject-alone", "deletion-alone", "close-of-another-feature", "close-that-kept-the-card"])
def test_a_rerun_needs_a_close_commit_that_deleted_the_card(tmp_path: Path, capsys, commits) -> None:
    # A rerun only fills in the ledger for a commit that is `close <feature>` and took the card away. The
    # subject line can be anybody's, and a card dropped under another subject was not closed: not under the
    # close of another feature either, nor by a later commit when `close nope` itself only edited the card.
    project, ledger_root = designed(tmp_path, capsys)
    for subject, card in commits:
        if card == "write":
            write(project, "specs/nope/spec.md", CARD.format(framework="不变") + f"\n写于：{subject}\n")
            git(project, "add", "-A")
        elif card == "delete":
            git(project, "rm", "-r", "-q", "specs/nope")
        git(project, "commit", "-q", "--allow-empty", "-m", subject)

    assert cli.main(["close", "nope", "--project", str(project), "--summary", "s"]) == 2
    err = capsys.readouterr().err
    assert "找不到卡：specs/nope/spec.md" in err and "close nope 提交" in err
    assert not (ledger_root / "entries" / "app" / "nope.jsonl").exists()


def test_a_card_whose_deletion_was_never_committed_is_restored_not_resumed(tmp_path: Path, capsys) -> None:
    # The process died between `git rm` and `git commit`: the deletion is staged and HEAD still has the card.
    # The rerun said the card was missing and nothing more. An older `close x` in the history, from a feature
    # that used the name before, must not make this one look closed.
    project, ledger_root = designed(tmp_path, capsys)
    git(project, "rm", "-r", "-q", "specs/x")
    git(project, "commit", "-q", "-m", "close x")
    write(project, "specs/x/spec.md", CARD.format(framework="不变"))
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "design(x): 又一个 x")
    before = git(project, "rev-parse", "HEAD").strip()
    git(project, "rm", "-r", "-q", "specs/x")

    code, _, err = close(capsys, project)

    assert code == 2
    assert "git reset -q HEAD -- specs/x" in err and "git checkout HEAD -- specs/x" in err
    assert git(project, "rev-parse", "HEAD").strip() == before
    assert [record["kind"] for record in entries(ledger_root, "x")] == ["design"]
    git(project, "reset", "-q", "HEAD", "--", "specs/x")           # the two commands it names
    git(project, "checkout", "HEAD", "--", "specs/x")
    assert (project / "specs" / "x" / "spec.md").is_file() and git(project, "status", "--short").strip() == ""


def test_an_uncommitted_deletion_is_seen_when_the_project_is_a_folder_of_a_larger_repository(tmp_path: Path,
                                                                                             capsys) -> None:
    # Whether HEAD still has the card was asked with a path read from the top of the repository. With the
    # project in a folder of it the answer was always no, so an older `close x` made a card whose deletion
    # was only staged look closed: exit 0, and nothing said about restoring it.
    repository, ledger_root = tmp_path / "mono", tmp_path / "ledgers" / "app"
    project = repository / "app"
    write(project, "docs/requirements/demo.md", DEMO)
    write(project, "specs/backlog.md", "# 待做池\n")
    write(repository, ".gitignore", ".dev-circuit/\n")
    git(repository, "init", "-q", "-b", "main")
    assert cli.main(["ledger", "init", "--path", str(ledger_root)]) == 0
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": str(ledger_root)}))
    write(project, "specs/x/spec.md", CARD.format(framework="不变"))
    git(repository, "add", "-A")
    git(repository, "commit", "-q", "-m", "design(x): 导出")
    assert cli.main(["ledger", "add", "--project", str(project), "--feature", "x", "--kind", "design",
                     "--decision", "d"]) == 0
    capsys.readouterr()

    code, out, err = close(capsys, project)                 # closing, and running it again, work from the folder
    assert code == 0, out + err
    code, out, err = close(capsys, project)
    assert code == 0 and "没有重复写" in out, out + err

    write(project, "specs/x/spec.md", CARD.format(framework="不变"))   # the name is used again
    git(repository, "add", "-A")
    git(repository, "commit", "-q", "-m", "design(x): 又一个 x")
    before = git(repository, "rev-parse", "HEAD").strip()
    git(project, "rm", "-r", "-q", "specs/x")

    code, out, err = close(capsys, project)

    assert code == 2, out + err
    assert "git reset -q HEAD -- specs/x" in err and "git checkout HEAD -- specs/x" in err
    assert git(repository, "rev-parse", "HEAD").strip() == before
    assert [record["kind"] for record in entries(ledger_root, "x")] == ["design", "close"]


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


def test_a_ledger_write_that_fails_after_the_commit_still_reports_and_a_rerun_fills_it_in(tmp_path: Path,
                                                                                          capsys) -> None:
    # The close commit comes first and the record second. When the record could not be written the command
    # died with a traceback that named the ledger's path, and a rerun only said the card was missing.
    project, ledger_root = designed(tmp_path, capsys)
    record_file = ledger_root / "entries" / "app" / "x.jsonl"
    record_file.chmod(stat.S_IREAD)
    if os.access(record_file, os.W_OK):
        pytest.skip("这个用户写得进只读文件（root），造不出写入失败")

    code, out, err = close(capsys, project, "--review", "必须改 0 条")

    assert code == 1
    assert git(project, "log", "-1", "--format=%s").strip() == "close x"
    assert "交付：x" in out and "审核：必须改 0 条" in out
    assert "项目已收尾，不用回退" in out and "重跑同一条 devcircuit close 命令" in out
    assert not names_the_ledger(ledger_root, out + err)
    assert [record["kind"] for record in entries(ledger_root, "x")] == ["design"]

    record_file.chmod(stat.S_IREAD | stat.S_IWRITE)
    head = git(project, "rev-parse", "HEAD").strip()
    code, out, err = close(capsys, project, "--review", "必须改 0 条")   # the same command, once the ledger is fixed

    assert code == 0, out + err
    assert "交付：x" in out and "账本核对：通过" in out and "补写了账本的收尾记录" in out
    assert "新增：DEMO-3" in out and "未覆盖的要求：DEMO-3" in out     # the report is the whole one again
    assert git(project, "rev-parse", "HEAD").strip() == head and git(project, "status", "--short").strip() == ""
    records = entries(ledger_root, "x")
    assert [record["kind"] for record in records] == ["design", "close"]
    assert records[-1]["commit"] == head and records[-1]["review"] == "必须改 0 条"
    assert git(ledger_root, "status", "--short").strip() == ""

    commits = git(ledger_root, "rev-list", "--count", "HEAD")
    code, out, err = close(capsys, project, "--review", "必须改 0 条")   # and once more: nothing to add

    assert code == 0, out + err
    assert "没有重复写" in out and "账本核对：通过" in out
    assert len(entries(ledger_root, "x")) == 2 and git(ledger_root, "rev-list", "--count", "HEAD") == commits


def test_an_unexpected_os_error_after_the_commit_never_names_the_ledger(tmp_path: Path, capsys,
                                                                        monkeypatch) -> None:
    # ledger.add turns its own write failures into a readable error; this is the net under it, for an OSError
    # from anywhere else in the ledger step. Stubbed: nothing real is left that raises a bare one there.
    project, ledger_root = designed(tmp_path, capsys)

    def fail(*args, **kwargs):
        raise PermissionError(13, "Permission denied", str(ledger_root / "entries" / "app" / "x.jsonl"))

    monkeypatch.setattr(ledger_module, "add", fail)

    code, out, err = close(capsys, project)

    assert code == 1
    assert "交付：x" in out and "Permission denied" in out and "重跑同一条 devcircuit close 命令" in out
    assert not names_the_ledger(ledger_root, out + err)


def test_a_check_that_fails_after_the_record_was_written_says_the_record_is_there(tmp_path: Path, capsys) -> None:
    # Writing the record and checking again are two steps, and the report says which one did not happen: after
    # "没写成" a rerun writes the record, after this there is nothing left to write. A hook of the ledger
    # repository breaks the ledger right after the record is committed, so nothing is stubbed.
    project, ledger_root = designed(tmp_path, capsys)
    hooks = tmp_path / "ledger-hooks"
    write(hooks, "post-commit", "#!/bin/sh\nmkdir entries/app/broken.jsonl\n").chmod(0o755)
    git(ledger_root, "config", "core.hooksPath", str(hooks))

    code, out, err = close(capsys, project)

    assert code == 1
    assert "收尾记录已写入，但再核对没做成" in out and "读不出来" in out and "项目已收尾，不用回退" in out
    assert "交付：x" in out and not names_the_ledger(ledger_root, out + err)
    assert [record["kind"] for record in entries(ledger_root, "x")] == ["design", "close"]

    (ledger_root / "entries" / "app" / "broken.jsonl").rmdir()
    code, out, err = close(capsys, project)                # the same command: the record is not written twice

    assert code == 0, out + err
    assert "没有重复写" in out and "账本核对：通过" in out
    assert [record["kind"] for record in entries(ledger_root, "x")] == ["design", "close"]


def test_a_rerun_commits_the_record_the_ledger_repository_could_not_commit(tmp_path: Path, capsys) -> None:
    project, ledger_root = designed(tmp_path, capsys)
    hooks = tmp_path / "failing-hooks"
    write(hooks, "pre-commit", "#!/bin/sh\nexit 1\n").chmod(0o755)
    git(ledger_root, "config", "core.hooksPath", str(hooks))

    code, out, _ = close(capsys, project)

    assert code == 1 and "账本仓库没有提交成功" in out and "重跑同一条 devcircuit close 命令" in out
    assert git(ledger_root, "status", "--short").strip() != ""

    git(ledger_root, "config", "--unset", "core.hooksPath")
    code, out, err = close(capsys, project)

    assert code == 0, out + err
    assert [record["kind"] for record in entries(ledger_root, "x")] == ["design", "close"]   # not written twice
    assert git(ledger_root, "status", "--short").strip() == ""
    assert "x close" in git(ledger_root, "log", "-1", "--format=%s")


def test_a_rerun_does_not_call_the_ledger_committed_when_git_cannot_tell(tmp_path: Path, capsys) -> None:
    # Whether the record still has to be committed is asked of the ledger repository. A `git status` that
    # fails prints nothing either, and that is not "nothing left to commit": the rerun must not exit 0 on it.
    project, ledger_root = designed(tmp_path, capsys)
    assert close(capsys, project)[0] == 0
    index = ledger_root / ".git" / "index"
    intact = index.read_bytes()
    index.write_bytes(b"not an index")                      # git stops on it, as it does where there is no repository

    code, out, err = close(capsys, project)

    assert code == 1 and "账本仓库没有提交成功" in out, out + err
    assert not names_the_ledger(ledger_root, out + err)

    index.write_bytes(intact)
    code, out, err = close(capsys, project)

    assert code == 0 and "没有重复写" in out, out + err


def test_a_close_made_by_hand_gets_its_record_from_the_command(tmp_path: Path, capsys) -> None:
    # The same state as a close whose process died right after the commit: the card is gone, the close commit
    # is there, the ledger has no record. Here the branch was merged first, so the commit sits behind a merge.
    project, ledger_root = designed(tmp_path, capsys)
    git(project, "rm", "-r", "-q", "specs/x")
    git(project, "commit", "-q", "-m", "close x")
    closed = git(project, "rev-parse", "HEAD").strip()
    git(project, "switch", "-q", "main")
    git(project, "merge", "-q", "--no-ff", "-m", "merge feat/x", "feat/x")
    head = git(project, "rev-parse", "HEAD").strip()

    code, out, err = close(capsys, project)

    assert code == 0, out + err
    assert git(project, "rev-parse", "HEAD").strip() == head and git(project, "status", "--short").strip() == ""
    records = entries(ledger_root, "x")
    assert [record["kind"] for record in records] == ["design", "close"] and records[-1]["commit"] == closed
    assert closed[:7] in out and "交付：x" in out and "账本核对：通过" in out


def test_a_rerun_picks_up_the_newest_close_when_the_name_was_closed_before(tmp_path: Path, capsys) -> None:
    # A name can be used, closed and used again, so the history can hold more than one `close x` that deleted
    # the card. The older one has its record; a rerun that took it found nothing missing and left the second
    # close without one. The second close is made by hand here: the state a close leaves when its record fails.
    project, ledger_root = designed(tmp_path, capsys)
    assert close(capsys, project)[0] == 0
    first = git(project, "rev-parse", "HEAD").strip()
    write(project, "specs/x/spec.md", CARD.format(framework="不变"))
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "design(x): 又一个 x")
    assert cli.main(["ledger", "add", "--project", str(project), "--feature", "x", "--kind", "design",
                     "--decision", "d2"]) == 0
    git(project, "rm", "-r", "-q", "specs/x")
    git(project, "commit", "-q", "-m", "close x")
    second = git(project, "rev-parse", "HEAD").strip()
    capsys.readouterr()

    code, out, err = close(capsys, project)

    assert code == 0, out + err
    assert [record["commit"] for record in entries(ledger_root, "x") if record["kind"] == "close"] == [first, second]
    assert f"提交 {second[:7]}" in out and "补写了账本的收尾记录" in out and "账本核对：通过" in out
    assert "新增：DEMO-3" in out and "未覆盖的要求：DEMO-3" in out     # a rerun drafts the whole report too


def test_a_rerun_dates_the_close_commit_it_picked_up(tmp_path: Path, capsys, monkeypatch) -> None:
    # Only the name ties a rerun to a close commit, and the name may have been closed before. Here the second
    # x is still open on its own branch and the command is run on the trunk: it finds the close of the first
    # x, has nothing to add and exits 0. That read as "this x is closed". The line now says when the commit
    # was made and that the newest `close x` on this history is all the command went by.
    project, ledger_root = designed(tmp_path, capsys)
    monkeypatch.setenv("GIT_AUTHOR_DATE", "1600000000 +0000")       # written on 2020-09-13,
    monkeypatch.setenv("GIT_COMMITTER_DATE", "1700000000 +0000")    # on this history since 2023-11-14
    assert close(capsys, project)[0] == 0
    for variable in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
        monkeypatch.delenv(variable)
    closed = git(project, "rev-parse", "HEAD").strip()
    git(project, "switch", "-q", "main")
    git(project, "merge", "-q", "--ff-only", "feat/x")
    git(project, "commit", "-q", "--allow-empty", "-m", "chore: 后续")   # the trunk has moved on since
    git(project, "switch", "-q", "-c", "feat/x-2")
    write(project, "specs/x/spec.md", CARD.format(framework="不变"))
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "design(x): 又一个 x")
    git(project, "switch", "-q", "main")                            # the wrong branch: the card is on feat/x-2

    code, out, err = close(capsys, project)

    assert code == 0, out + err
    assert f"已经收尾过：x（提交 {closed[:7]}，2023-11-14）" in out
    assert "最新的 close x 提交" in out and "日期对不上" in out
    assert "已经有这个提交的收尾记录，没有重复写" in out and len(entries(ledger_root, "x")) == 2
    assert git(project, "ls-tree", "--name-only", "feat/x-2", "specs/x/spec.md").strip() == "specs/x/spec.md"


def test_a_rerun_adds_nothing_after_the_close_was_recorded_by_hand(tmp_path: Path, capsys) -> None:
    # A human who saw close-missing may have run `ledger add --kind close` since, from a newer commit.
    project, ledger_root = designed(tmp_path, capsys)
    git(project, "rm", "-r", "-q", "specs/x")
    git(project, "commit", "-q", "-m", "close x")
    git(project, "commit", "-q", "--allow-empty", "-m", "chore: 后续")
    assert cli.main(["ledger", "add", "--project", str(project), "--feature", "x", "--kind", "close",
                     "--decision", "人工补记"]) == 0
    capsys.readouterr()

    code, out, err = close(capsys, project)

    assert code == 0, out + err
    assert [record["kind"] for record in entries(ledger_root, "x")] == ["design", "close"]
    assert "没有重复写" in out


def test_a_rerun_adds_nothing_after_the_close_was_recorded_from_another_branch(tmp_path: Path, capsys,
                                                                               monkeypatch) -> None:
    # `ledger add` records the HEAD it is run from. From the trunk, before the branch is merged, that is a
    # commit below the close commit, and the rerun on the branch wrote the close a second time.
    project, ledger_root = designed(tmp_path, capsys)
    git(project, "rm", "-r", "-q", "specs/x")
    for variable in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):       # closed a while ago, recorded only now
        monkeypatch.setenv(variable, "1700000000 +0000")
    git(project, "commit", "-q", "-m", "close x")
    for variable in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
        monkeypatch.delenv(variable)
    git(project, "switch", "-q", "main")
    assert cli.main(["ledger", "add", "--project", str(project), "--feature", "x", "--kind", "close",
                     "--decision", "人工补记"]) == 0
    git(project, "switch", "-q", "feat/x")
    capsys.readouterr()

    code, out, err = close(capsys, project)

    assert code == 0, out + err
    assert [record["kind"] for record in entries(ledger_root, "x")] == ["design", "close"]
    assert "没有重复写" in out


def test_close_skips_the_ledger_on_a_human_side_setup(tmp_path: Path, capsys) -> None:
    project, ledger_root = designed(tmp_path, capsys)
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": "/not/mounted", "ledger_side": "human"}))

    code, out, err = close(capsys, project)

    assert code == 0, out + err
    assert "账本在 human 一侧" in out and "devcircuit ledger add --feature x --kind close" in out
    assert "--review" not in out
    assert not (project / "specs" / "x").exists()
    records = (ledger_root / "entries" / "app" / "x.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == 1

    head = git(project, "rev-parse", "HEAD").strip()
    code, out, err = close(capsys, project)                # the same command again prints the same command

    assert code == 0, out + err
    assert f"devcircuit ledger add --feature x --kind close --commit {head}" in out
    assert git(project, "rev-parse", "HEAD").strip() == head


def test_the_human_side_command_carries_the_review(tmp_path: Path, capsys) -> None:
    # Without it the review verdict never reached the ledger on a human-side setup.
    project, _ = designed(tmp_path, capsys)
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": "/not/mounted", "ledger_side": "human"}))

    code, out, err = close(capsys, project, "--review", "必须改 1 条，已修 1 条")

    assert code == 0, out + err
    assert '--decision "交付导出的出错处理" --review "必须改 1 条，已修 1 条"' in out


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
