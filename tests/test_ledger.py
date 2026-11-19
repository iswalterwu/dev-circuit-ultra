"""devcircuit ledger: the dev agent appends records it cannot read back; check compares the ledger with the repo."""

import contextlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import devcircuit.cli as cli
import devcircuit.ledger as ledger_module
from test_ledger_hook import READABLE as HOOKS_READABLE, UNREADABLE as HOOKS_UNREADABLE
from test_ledger_hook import readable_guard_file as hooks_readable, unreadable_guard_file as hooks_unreadable


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


DEMO = "# 导出能力\n代号：DEMO\n\n- DEMO-1：导出一条记录。\n  - 例：导出得到该记录。\n" \
       "- DEMO-2：导出后弹出提示。\n  - 例：看到提示。\n"
CARD = "# x：导出\n\n能力：DEMO（已有）· 框架：{framework}\n\n## 目标\n\n导出。\n\n## 切片\n\n- S1：导出（当前）\n"


def setup(tmp_path: Path) -> tuple[Path, Path]:
    project, ledger = tmp_path / "app", tmp_path / "ledgers" / "app"
    write(project, "docs/requirements/demo.md", DEMO)
    write(project, "specs/backlog.md", "# 待做池\n")
    write(project, ".gitignore", ".dev-circuit/\n")
    git(project, "init", "-q", "-b", "main")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "base")
    assert cli.main(["ledger", "init", "--path", str(ledger)]) == 0
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": str(ledger)}))
    return project, ledger


def ledger(capsys, *args: str) -> tuple[int, str, str]:
    code = cli.main(["ledger", *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def entries(ledger_root: Path, feature: str) -> list[dict]:
    path = ledger_root / "entries" / "app" / f"{feature}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def names_the_ledger(ledger_root: Path, text: str) -> bool:
    """Whether product output gives the ledger away: its path in any spelling, a record file, a traceback."""
    escaped = repr(str(ledger_root))[1:-1]            # how an OSError prints the path: backslashes doubled
    return any(clue in text for clue in (str(ledger_root), ledger_root.as_posix(), escaped, ".jsonl", "Traceback"))


def test_add_appends_one_record_and_prints_only_a_receipt(tmp_path: Path, capsys) -> None:
    project, ledger_root = setup(tmp_path)
    capsys.readouterr()

    code, out, _ = ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "design",
                          "--decision", "只选 amount 时输出合计", "--rejected", "裸合计：无法和数据行区分",
                          "--ids", "DEMO-1,DEMO-2")

    assert code == 0
    assert out.startswith("已记录：")
    assert "合计" not in out and "区分" not in out and str(ledger_root) not in out
    [record] = entries(ledger_root, "x")
    assert record["kind"] == "design" and record["decision"] == "只选 amount 时输出合计"
    assert record["discarded"] == [{"idea": "裸合计", "why": "无法和数据行区分"}]
    assert record["ids"] == ["DEMO-1", "DEMO-2"]
    assert record["commit"] == git(project, "rev-parse", "HEAD").strip()
    assert record["source"] == "dev-agent" and record["human_only"] is True
    assert git(ledger_root, "status", "--short").strip() == ""
    assert "x design" in git(ledger_root, "log", "-1", "--format=%s")


def test_add_needs_a_configured_ledger(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"
    write(project, "AGENTS.md", "app\n")

    code, _, err = ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "design",
                          "--decision", "d")

    assert code == 2
    assert "ledger init" in err and "hooks install" in err


def test_add_refuses_a_commit_that_does_not_exist(tmp_path: Path, capsys) -> None:
    project, ledger_root = setup(tmp_path)
    capsys.readouterr()

    code, _, err = ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "design",
                          "--decision", "d", "--commit", "0" * 40)

    assert code == 2 and "提交不存在" in err
    assert not (ledger_root / "entries" / "app" / "x.jsonl").exists()


def test_add_reports_a_write_failure_without_the_ledger_path(tmp_path: Path, capsys) -> None:
    # An OSError from the write was an uncaught traceback, and its message carries the ledger's absolute path.
    project, ledger_root = setup(tmp_path)
    write(ledger_root, "entries/app", "这里本该是目录\n")     # a file where the project's folder has to be made
    capsys.readouterr()

    code, out, err = ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "design",
                            "--decision", "d")

    assert code == 2 and "写不进去" in err
    assert not names_the_ledger(ledger_root, out + err)


def test_check_reports_unreadable_records_without_the_ledger_path(tmp_path: Path, capsys) -> None:
    project, ledger_root = setup(tmp_path)
    (ledger_root / "entries" / "app" / "x.jsonl").mkdir(parents=True)   # a folder cannot be read as a record file
    capsys.readouterr()

    code, out, err = ledger(capsys, "check", "--project", str(project))

    assert code == 2 and "读不出来" in err
    assert not names_the_ledger(ledger_root, out + err)


def no_looking_into(folder: Path, monkeypatch) -> None:
    """Make looking into `folder` fail the way it does for a process without permission.

    On Python 3.12 and older Path.is_dir() raises PermissionError there. 3.14 answers False instead, and on
    Windows no file mode produces the error. Hence the stub: of the platform, not of the product.
    """
    real = Path.is_dir

    def is_dir(self, *args, **kwargs):
        if folder == self or folder in self.parents:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_dir", is_dir)


@contextlib.contextmanager
def out_of_sight(folder: Path):
    """Take this user's access to a folder and all below it away, as when the ledger belongs to another OS user."""
    everyone = "*S-1-1-0"  # the well-known SID: the group's name differs with the language of Windows
    if os.name == "nt":
        # Listing, traversing and reading attributes, not (RX) as a whole: that takes READ_CONTROL too, and under
        # the temp folder pytest makes with mode 0o700 not even the owner could then give the access back.
        subprocess.run(["icacls", str(folder), "/deny", f"{everyone}:(OI)(CI)(RD,X,RA,REA)", "/Q"],
                       check=True, capture_output=True)
    else:
        folder.chmod(0)
    try:
        yield
    finally:
        if os.name == "nt":
            subprocess.run(["icacls", str(folder), "/remove:d", everyone, "/T", "/Q"], check=True, capture_output=True)
        else:
            folder.chmod(0o700)


@pytest.mark.parametrize("command", [
    ("add", "--feature", "x", "--kind", "design", "--decision", "d"), ("check",)], ids=["add", "check"])
def test_a_ledger_that_cannot_be_looked_into_is_a_readable_error_without_its_path(tmp_path: Path, capsys,
                                                                                  monkeypatch, command) -> None:
    # The strong isolation tier: the ledger belongs to another user. Any OSError on the way to it was an
    # uncaught traceback, and the message of an OSError names the file it failed on.
    project, ledger_root = setup(tmp_path)
    no_looking_into(ledger_root, monkeypatch)
    capsys.readouterr()

    code, out, err = ledger(capsys, command[0], "--project", str(project), *command[1:])

    assert code == 2 and "账本目录查不了（Permission denied）" in err
    assert not names_the_ledger(ledger_root, out + err)


def test_check_reports_a_project_folder_it_may_not_list_instead_of_finding_no_records(tmp_path: Path,
                                                                                      capsys) -> None:
    # Path.glob() takes a folder it may not list for an empty one: check then said every feature in progress had
    # no design record, and close sent the agent to record one with `ledger add`, which failed as well.
    project, ledger_root = setup(tmp_path)
    write(project, "specs/x/spec.md", CARD.format(framework="不变"))
    assert ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "design",
                  "--decision", "d")[0] == 0
    folder = ledger_root / "entries" / "app"
    capsys.readouterr()

    with out_of_sight(folder):
        try:
            list(folder.iterdir())
        except OSError:
            code, out, err = ledger(capsys, "check", "--project", str(project))
        else:
            pytest.skip("这个用户照样列得出（比如 root）")

    assert code == 2 and "账本记录读不出来" in err and "design-missing" not in out
    assert not names_the_ledger(ledger_root, out + err)


def test_check_takes_a_record_line_nested_too_deep_for_a_malformed_one(tmp_path: Path, capsys) -> None:
    """json raises RecursionError on it, not ValueError, and that was a traceback."""
    project, ledger_root = setup(tmp_path)
    write(project, "specs/x/spec.md", CARD.format(framework="不变"))
    assert ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "design",
                  "--decision", "d")[0] == 0
    path = ledger_root / "entries" / "app" / "x.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "[" * 100_000 + "\n", encoding="utf-8")
    capsys.readouterr()

    code, out, err = ledger(capsys, "check", "--project", str(project))

    assert code == 0 and "ledger check：通过（1 条记录，1 个功能）" in out
    assert "Traceback" not in out + err


def test_check_reads_only_the_record_files_of_the_project(tmp_path: Path, capsys) -> None:
    """A backup or a note beside the record files is not a record, whatever it holds."""
    project, ledger_root = setup(tmp_path)
    write(project, "specs/x/spec.md", CARD.format(framework="不变"))
    record = json.dumps({"id": "20260101T000000Z-abcdef", "feature": "x", "kind": "design", "decision": "d"})
    for name in ("x.jsonl.bak", "notes.txt", "x.json"):
        write(ledger_root, f"entries/app/{name}", record + "\n")
    capsys.readouterr()

    code, out, _ = ledger(capsys, "check", "--project", str(project))

    assert code == 1 and "[design-missing] x" in out


def test_check_walks_a_feature_from_design_to_close(tmp_path: Path, capsys) -> None:
    project, ledger_root = setup(tmp_path)
    git(project, "switch", "-q", "-c", "feat/x")
    write(project, "docs/requirements/demo.md", DEMO.replace("- DEMO-2：导出后弹出提示。\n  - 例：看到提示。\n", ""))
    write(project, "specs/x/spec.md", CARD.format(framework="不变"))
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "design(x): 导出")
    capsys.readouterr()

    code, out, _ = ledger(capsys, "check", "--project", str(project))
    assert code == 1
    assert "[design-missing] x" in out
    assert "[removal-unrecorded] DEMO-2" in out

    ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "design",
           "--decision", "机密的决定", "--rejected", "方案乙：机密的原因", "--ids", "DEMO-1", "--removed-ids", "DEMO-2")
    code, out, _ = ledger(capsys, "check", "--project", str(project))
    assert code == 0, out
    assert "通过" in out and "机密" not in out

    (project / "specs" / "x" / "spec.md").unlink()
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "close x")
    code, out, _ = ledger(capsys, "check", "--project", str(project))
    assert code == 1 and "[close-missing] x" in out

    ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "close", "--decision", "交付导出")
    code, out, _ = ledger(capsys, "check", "--project", str(project))
    assert code == 0, out


def test_check_wants_a_framework_record_when_the_card_says_so(tmp_path: Path, capsys) -> None:
    project, _ = setup(tmp_path)
    write(project, "specs/x/spec.md", CARD.format(framework="已改"))
    ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "design", "--decision", "d")

    code, out, _ = ledger(capsys, "check", "--project", str(project))
    assert code == 1 and "[framework-missing] x" in out

    ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "framework", "--decision", "f")
    assert ledger(capsys, "check", "--project", str(project))[0] == 0


@pytest.mark.parametrize("line, changed", [
    ("**能力**：DEMO（已有）· **框架**：已改", True), ("能力：DEMO（已有）· 框架：**已改**", True),
    ("**能力：** DEMO（已有）· **框架：** 已改", True), ("| 能力 | DEMO（已有）· 框架：已改 |", True),
    ("**能力**：DEMO（已有）· **框架**：不变", False),
], ids=["bold-label", "bold-value", "bold-label-and-colon", "table-row", "bold-unchanged"])
def test_check_reads_a_framework_change_written_in_bold(tmp_path: Path, capsys, line: str, changed: bool) -> None:
    """context reads the capability line in bold too; the framework mark on such a line went unseen."""
    project, _ = setup(tmp_path)
    write(project, "specs/x/spec.md", CARD.format(framework="不变").replace("能力：DEMO（已有）· 框架：不变", line))
    ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "design", "--decision", "d")

    code, out, _ = ledger(capsys, "check", "--project", str(project))

    assert (code, "[framework-missing] x" in out) == ((1, True) if changed else (0, False))


def test_check_flags_missing_commits_and_stale_ids_until_corrected(tmp_path: Path, capsys) -> None:
    project, ledger_root = setup(tmp_path)
    write(project, "specs/y/spec.md", CARD.format(framework="不变"))
    ledger(capsys, "add", "--project", str(project), "--feature", "y", "--kind", "design",
           "--decision", "d", "--ids", "DEMO-2")
    path = ledger_root / "entries" / "app" / "y.jsonl"
    record = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(path.read_text(encoding="utf-8") + json.dumps({**record, "id": "orphan", "commit": "f" * 40})
                    + "\n", encoding="utf-8")
    # The requirement goes away later without a record of why.
    write(project, "docs/requirements/demo.md", DEMO.replace("- DEMO-2：导出后弹出提示。\n  - 例：看到提示。\n", ""))
    git(project, "commit", "-q", "-am", "chore: drop DEMO-2")

    code, out, _ = ledger(capsys, "check", "--project", str(project))
    assert code == 1
    assert "[commit-missing] y" in out and "ffffff" in out
    assert "[id-stale] DEMO-2" in out

    ledger(capsys, "add", "--project", str(project), "--feature", "y", "--kind", "correction",
           "--decision", "提示不要了", "--removed-ids", "DEMO-2")
    code, out, _ = ledger(capsys, "check", "--project", str(project))
    assert code == 0, out


def test_check_never_echoes_free_text_found_in_a_record(tmp_path: Path, capsys) -> None:
    # `ledger add` validates what it writes, but a record edited by hand, or an old one, can hold a sentence
    # where an ID belongs. check printed those fields as they were: ledger content, handed to the dev side.
    project, ledger_root = setup(tmp_path)
    write(project, "specs/y/spec.md", CARD.format(framework="不变"))
    head = git(project, "rev-parse", "HEAD").strip()
    records = [
        {"id": "备注：先别告诉开发", "feature": "被否：改用方案乙（供应商泄露）", "kind": "design", "commit": head,
         "decision": "d", "ids": ["DEMO-1", "否决了外包方案，原因是预算"]},
        {"id": "写给 human 的话", "feature": "y", "kind": "design", "commit": "合同在老板手里", "decision": "d"},
        {"id": "20261101T000000Z-abc123", "feature": "y", "kind": "design", "commit": "f" * 40, "decision": "d"},
        {"feature": "y", "kind": "design", "commit": "e" * 40, "decision": "d"},
    ]
    write(ledger_root, "entries/app/y.jsonl",
          "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))
    capsys.readouterr()

    code, out, err = ledger(capsys, "check", "--project", str(project))

    assert code == 1
    assert "[id-stale] （格式不对，已略）：（格式不对，已略） 的记录" in out
    assert "[commit-missing] y：记录 （格式不对，已略） 指向的提交 （格式不对，已略） 不在仓库里" in out
    assert "[commit-missing] y：记录 20261101T000000Z-abc123 指向的提交 fffffff 不在仓库里" in out   # well-formed: as before
    assert "[commit-missing] y：记录 ? 指向的提交 eeeeeee 不在仓库里" in out      # and so is a record without a number
    for written in ("备注", "告诉", "被否", "方案乙", "泄露", "否决", "外包", "预算", "写给", "合同", "老板"):
        assert written not in out + err


def test_check_shows_a_record_number_only_in_the_shape_add_writes_it(tmp_path: Path, capsys) -> None:
    # The rule took up to 16 letters and digits after the time: a word written there by hand was printed as it was.
    project, ledger_root = setup(tmp_path)
    write(project, "specs/y/spec.md", CARD.format(framework="不变"))
    numbers = {"20261101T000000Z-SECRETWORD": "a", "20261101T000000Z-abc1234": "b", "20261101T000000Z-ABC123": "c",
               "2026-11-01T00:00:00Z-abc123": "d", "٢٠٢٦١١٠١T000000Z-abc123": "9", "20261101T000000Z-abc123": "e"}
    write(ledger_root, "entries/app/y.jsonl", "".join(
        json.dumps({"id": number, "feature": "y", "kind": "design", "commit": letter * 40, "decision": "d"},
                   ensure_ascii=False) + "\n" for number, letter in numbers.items()))
    capsys.readouterr()

    code, out, _ = ledger(capsys, "check", "--project", str(project))

    assert code == 1
    for number, letter in numbers.items():
        shown = number if letter == "e" else "（格式不对，已略）"   # only the last is what `add` writes
        assert f"[commit-missing] y：记录 {shown} 指向的提交 {letter * 7} 不在仓库里" in out, number


def test_check_reports_fields_of_the_wrong_type_instead_of_crashing(tmp_path: Path, capsys) -> None:
    # A hand edit can also leave a number or a list where a name or a list of IDs belongs. check died on those
    # with a TypeError, and so did every `devcircuit close`. They are malformed fields, as a sentence is.
    project, ledger_root = setup(tmp_path)
    write(project, "specs/y/spec.md", CARD.format(framework="不变"))
    head = git(project, "rev-parse", "HEAD").strip()
    common = {"feature": "y", "kind": "design", "commit": head, "decision": "d"}
    # `ids: 5` and `ids: "DEMO-9"` sit under names of their own: findings that read the same are reported
    # once, so under y the next record's would stand in for theirs whether or not they were looked at.
    records = [
        {**common, "id": "a", "feature": "z", "ids": 5},
        {**common, "id": "b", "ids": [["DEMO-1"], {"n": 1}, "DEMO-1"]},
        {**common, "id": "c", "ids_removed": [["DEMO-2"], 7]},
        {**common, "id": "d", "feature": ["y"]},
        {**common, "id": "e", "kind": ["correction"]},
        {**common, "id": {"n": 1}, "commit": ["f" * 40]},
        {**common, "id": "g", "ids": "DEMO-1"},                    # one ID, not in a list: read as that ID,
        {**common, "id": "h", "feature": "w", "ids": "DEMO-9"},    # not letter by letter
    ]
    write(ledger_root, "entries/app/y.jsonl", "".join(json.dumps(record) + "\n" for record in records))
    capsys.readouterr()

    code, out, err = ledger(capsys, "check", "--project", str(project))

    assert code == 1, out + err
    assert [line for line in out.splitlines() if not line.startswith("说明：")] == [
        "[commit-missing] y：记录 （格式不对，已略） 指向的提交 （格式不对，已略） 不在仓库里",
        "[id-stale] DEMO-9：w 的记录里的这条要求已经不在能力规格里，也没有删除记录",
        "[id-stale] （格式不对，已略）：y 的记录里的这条要求已经不在能力规格里，也没有删除记录",
        "[id-stale] （格式不对，已略）：z 的记录里的这条要求已经不在能力规格里，也没有删除记录",
        "ledger check：4 处不一致",
    ]


def test_ledger_path_flag_still_creates_a_ledger(tmp_path: Path, capsys) -> None:
    target = tmp_path / "ledgers" / "old-style"
    assert cli.main(["ledger", "--path", str(target), "--no-commit"]) == 0
    assert (target / "schema.md").is_file()


def test_environment_points_the_ledger_side_at_a_mounted_ledger(tmp_path: Path, capsys, monkeypatch) -> None:
    # In the container tier the human runs ledger commands where the ledger is mounted; guard.json holds a host path.
    project, ledger_root = setup(tmp_path)
    (project / ".dev-circuit" / "guard.json").unlink()
    monkeypatch.setenv("DEVCIRCUIT_LEDGER", str(ledger_root))
    monkeypatch.setenv("DEVCIRCUIT_PROJECT", "app")
    capsys.readouterr()

    code, out, _ = ledger(capsys, "add", "--project", str(project), "--feature", "z", "--kind", "design",
                          "--decision", "d")

    assert code == 0 and out.startswith("已记录：")
    assert entries(ledger_root, "z")[0]["project"] == "app"


def test_short_commit_ids_in_older_records_still_resolve(tmp_path: Path, capsys) -> None:
    project, ledger_root = setup(tmp_path)
    write(project, "specs/x/spec.md", CARD.format(framework="不变"))
    short = git(project, "rev-parse", "--short=7", "HEAD").strip()
    path = ledger_root / "entries" / "app" / "x.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"id": "old", "feature": "x", "kind": "design", "commit": short,
                                "decision": "d", "human_only": True}) + "\n", encoding="utf-8")
    capsys.readouterr()

    code, out, _ = ledger(capsys, "check", "--project", str(project))
    assert code == 0, out


def test_ids_split_on_chinese_separators_and_must_exist(tmp_path: Path, capsys) -> None:
    project, ledger_root = setup(tmp_path)
    capsys.readouterr()
    base = ["add", "--project", str(project), "--feature", "x", "--kind", "design", "--decision", "d"]

    assert ledger(capsys, *base, "--ids", "DEMO-1、DEMO-2；DEMO-1")[0] == 0
    assert entries(ledger_root, "x")[0]["ids"] == ["DEMO-1", "DEMO-2"]

    code, _, err = ledger(capsys, *base, "--ids", "DEMO-9")
    assert code == 2 and "DEMO-9" in err
    code, _, err = ledger(capsys, *base, "--removed-ids", "not an id")
    assert code == 2 and "not" in err
    assert len(entries(ledger_root, "x")) == 1


def test_relative_ledger_path_resolves_from_the_project_root(tmp_path: Path, capsys, monkeypatch) -> None:
    project, _ = setup(tmp_path)
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": "../ledgers/app"}))
    monkeypatch.chdir(tmp_path)
    capsys.readouterr()

    code, out, err = ledger(capsys, "check", "--project", "app")
    assert code == 0, out + err


def test_a_human_side_ledger_is_not_written_from_the_dev_side(tmp_path: Path, capsys) -> None:
    project, _ = setup(tmp_path)
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": "/not/mounted", "ledger_side": "human"}))
    capsys.readouterr()

    code, _, err = ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "design",
                          "--decision", "d")
    assert code == 2 and "human" in err


def test_guard_ledger_must_be_a_path(tmp_path: Path, capsys) -> None:
    project, _ = setup(tmp_path)
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": 42}))
    capsys.readouterr()

    code, _, err = ledger(capsys, "check", "--project", str(project))
    assert code == 2 and "guard.json" in err


def test_commit_missing_is_reported_only_for_features_in_progress(tmp_path: Path, capsys) -> None:
    # Squash merges drop branch commits from history; closed features must not flood the check.
    project, ledger_root = setup(tmp_path)
    folder = ledger_root / "entries" / "app"
    folder.mkdir(parents=True, exist_ok=True)
    for feature in ("done", "x"):
        (folder / f"{feature}.jsonl").write_text(json.dumps(
            {"id": feature, "feature": feature, "kind": "design", "commit": "f" * 40, "decision": "d"})
            + "\n", encoding="utf-8")
    write(project, "specs/x/spec.md", CARD.format(framework="不变"))
    capsys.readouterr()

    code, out, _ = ledger(capsys, "check", "--project", str(project))
    assert code == 1
    assert "[commit-missing] x" in out and "done" not in out


def test_card_names_outside_the_rule_are_reported_readably(tmp_path: Path, capsys) -> None:
    project, _ = setup(tmp_path)
    write(project, "specs/导出/spec.md", CARD.format(framework="不变"))
    capsys.readouterr()

    code, out, _ = ledger(capsys, "check", "--project", str(project))
    assert code == 1
    assert "[bad-feature-name] 导出" in out and "design-missing" not in out


def test_check_says_when_it_cannot_tell_which_requirements_the_branch_removed(tmp_path: Path, capsys) -> None:
    # Without a base to compare against, or sitting on the base itself, removal-unrecorded has nothing to look
    # at. check passed without a word, which read as "no removal went unrecorded".
    project, _ = setup(tmp_path)
    git(project, "branch", "-m", "main", "develop")   # no main, master or remote, and AGENTS.md names no trunk
    git(project, "switch", "-q", "-c", "feat/x")
    write(project, "docs/requirements/demo.md", DEMO.replace("- DEMO-2：导出后弹出提示。\n  - 例：看到提示。\n", ""))
    git(project, "commit", "-q", "-am", "design(x): 不要提示了")
    capsys.readouterr()

    code, out, _ = ledger(capsys, "check", "--project", str(project))
    assert code == 0 and "ledger check：通过" in out            # a note, not a finding
    assert "removal-unrecorded 没查" in out and "找不到可比的基线" in out

    code, out, _ = ledger(capsys, "check", "--project", str(project), "--base", "develop")
    assert code == 1 and "[removal-unrecorded] DEMO-2" in out and "没查" not in out

    git(project, "switch", "-q", "develop")                    # on the base itself: HEAD is the fork point
    code, out, _ = ledger(capsys, "check", "--project", str(project), "--base", "develop")
    assert code == 0 and "ledger check：通过" in out
    assert "removal-unrecorded 没查" in out and "基线 develop" in out


def test_close_recorded_counts_only_a_close_record_at_or_after_the_commit(tmp_path: Path) -> None:
    # A rerun of `devcircuit close` asks this before it writes. Yes when the close is on record, also when a
    # human recorded it later from a newer commit; no for the close of an earlier feature that used the name.
    project, ledger_root = setup(tmp_path)
    commits = []
    for subject in ("earlier", "closing", "later"):
        git(project, "commit", "-q", "--allow-empty", "-m", subject)
        commits.append(git(project, "rev-parse", "HEAD").strip())
    earlier, closing, later = commits

    def recorded(*records: dict) -> bool:
        write(ledger_root, "entries/app/x.jsonl",
              "".join(json.dumps({"id": "r", "feature": "x", "decision": "d", **record}) + "\n" for record in records))
        return ledger_module.close_recorded(project, "x", closing)

    assert not recorded()
    assert not recorded({"kind": "close", "commit": earlier})
    assert not recorded({"kind": "design", "commit": closing})
    assert not recorded({"kind": "close", "commit": closing, "feature": "y"})
    assert not recorded({"kind": "close", "commit": "f" * 40})
    assert not recorded({"kind": "close"})
    assert recorded({"kind": "close", "commit": closing})
    assert recorded({"kind": "close", "commit": closing[:7]})          # older records hold short SHAs
    assert recorded({"kind": "close", "commit": later})
    assert recorded({"kind": "close", "commit": earlier}, {"kind": "close", "commit": later})


def test_close_recorded_counts_a_close_record_written_after_the_commit_was_made(tmp_path: Path, monkeypatch) -> None:
    # A close recorded by hand need not point at the close commit or above it: `ledger add` takes HEAD, and
    # the human may have been on the trunk, or in another clone. Such a record is still newer than the close
    # commit, and a rerun that only followed commits wrote the close a second time.
    project, ledger_root = setup(tmp_path)
    git(project, "commit", "-q", "--allow-empty", "-m", "earlier")
    earlier = git(project, "rev-parse", "HEAD").strip()
    made = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    for variable in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
        monkeypatch.setenv(variable, f"{int(made.timestamp())} +0000")
    git(project, "commit", "-q", "--allow-empty", "-m", "closing")
    closing = git(project, "rev-parse", "HEAD").strip()
    before, same, after = "2026-03-01T11:59:59Z", "2026-03-01T12:00:00Z", "2026-03-01T12:00:01Z"

    def recorded(*records: dict) -> bool:
        write(ledger_root, "entries/app/x.jsonl",
              "".join(json.dumps({"id": "r", "feature": "x", "decision": "d", **record}) + "\n" for record in records))
        return ledger_module.close_recorded(project, "x", closing)

    assert recorded({"kind": "close", "commit": earlier, "ts": after})      # recorded from the trunk since
    assert recorded({"kind": "close", "commit": "f" * 40, "ts": after})     # or where the repository differs
    assert recorded({"kind": "close", "ts": after})
    assert not recorded({"kind": "close", "commit": earlier, "ts": before})  # an earlier feature of that name
    assert not recorded({"kind": "close", "commit": earlier, "ts": same})    # within the second: order unknown
    assert not recorded({"kind": "design", "commit": earlier, "ts": after})
    assert not recorded({"kind": "close", "commit": earlier, "ts": after, "feature": "y"})
    assert not recorded({"kind": "close", "commit": earlier, "ts": "昨天下午"})   # not a time: tells nothing
    assert not recorded({"kind": "close", "commit": earlier, "ts": 99999999999})
    write(ledger_root, "entries/app/x.jsonl", json.dumps({"feature": "x", "kind": "close", "ts": after}) + "\n")
    assert not ledger_module.close_recorded(project, "x", "f" * 40)             # no such commit: no time to compare


def test_a_linked_worktree_uses_the_projects_ledger(tmp_path: Path, capsys) -> None:
    # guard.json is machine-local and gitignored, so a git worktree has no copy of it. `ledger add` said no
    # ledger was configured, and `close` then closed the feature without writing any record.
    project, ledger_root = setup(tmp_path)
    tree = tmp_path / "wt-export"
    git(project, "worktree", "add", "-q", "-b", "feat/x", str(tree))
    write(tree, "specs/x/spec.md", CARD.format(framework="不变"))
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "design(x)")
    capsys.readouterr()

    code, out, _ = ledger(capsys, "add", "--project", str(tree), "--feature", "x", "--kind", "design",
                          "--decision", "导出")

    assert code == 0 and out.startswith("已记录：")
    assert [record["kind"] for record in entries(ledger_root, "x")] == ["design"]   # filed under the project
    assert not (ledger_root / "entries" / "wt-export").exists()                     # not under the worktree's name
    assert ledger(capsys, "check", "--project", str(tree))[0] == 0


def test_a_linked_worktree_closes_into_the_projects_ledger(tmp_path: Path, capsys) -> None:
    # `close` asks whether a ledger is configured before it writes: in a worktree it used to say no, close
    # the feature and write nothing. The worktree sits inside the project here, so a relative ledger path
    # in guard.json only resolves if it is read from the main working tree.
    project, ledger_root = setup(tmp_path)
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": "../ledgers/app"}))
    write(project, ".gitignore", ".dev-circuit/\n.trees/\n")
    git(project, "commit", "-q", "-am", "ignore worktrees")
    tree = project / ".trees" / "wt"
    git(project, "worktree", "add", "-q", "-b", "feat/x", str(tree))
    write(tree, "specs/x/spec.md", CARD.format(framework="不变"))
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "design(x)")
    assert ledger(capsys, "add", "--project", str(tree), "--feature", "x", "--kind", "design",
                  "--decision", "导出")[0] == 0

    assert cli.main(["close", "x", "--project", str(tree), "--summary", "交付导出"]) == 0

    assert "没有配置账本" not in capsys.readouterr().out
    assert [record["kind"] for record in entries(ledger_root, "x")] == ["design", "close"]


def hook_environment(tree: Path, hooks: Path) -> dict[str, str]:
    """GIT_DIR and GIT_INDEX_FILE as git hands them to a hook run in `tree`, and so to an agent a hook starts."""
    hooks.mkdir(parents=True)
    hook = hooks / "post-commit"
    hook.write_bytes(b"#!/bin/sh\nprintf '%s\\n' \"$GIT_DIR\" \"$GIT_INDEX_FILE\" >&2\n")
    hook.chmod(0o755)
    probe = subprocess.run(["git", "-C", str(tree), "-c", f"core.hooksPath={hooks}", "commit", "-q", "--allow-empty",
                            "-m", "probe"], capture_output=True, text=True, encoding="utf-8", check=True)
    git_dir, index = probe.stderr.splitlines()[-2:]
    return {"GIT_DIR": git_dir, "GIT_INDEX_FILE": index}


def ledger_commits(ledger_root: Path, since: str) -> int:
    return int(git(ledger_root, "rev-list", "--count", f"{since}..HEAD"))


def test_records_written_from_a_git_hook_of_a_linked_worktree_go_to_the_ledger(tmp_path: Path, capsys) -> None:
    # In a linked worktree git hands a hook absolute GIT_DIR and GIT_INDEX_FILE, and an agent the hook starts inherits
    # them. `git -C <ledger> add / commit` then went by those: the whole record file was committed onto the feature
    # branch, decisions and all, the ledger repository got nothing, and the command still said 已记录.
    project, ledger_root = setup(tmp_path)
    tree = tmp_path / "wt"
    git(project, "worktree", "add", "-q", "-b", "feat/x", str(tree))
    write(tree, "specs/x/spec.md", CARD.format(framework="不变"))
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "design(x)")
    hooked = hook_environment(tree, tmp_path / "hooks")
    assert Path(hooked["GIT_DIR"]) == Path(git(tree, "rev-parse", "--absolute-git-dir").strip())
    assert Path(hooked["GIT_INDEX_FILE"]) == Path(hooked["GIT_DIR"]) / "index"
    head, index = git(tree, "rev-parse", "HEAD"), git(tree, "ls-files", "--stage")
    start = git(ledger_root, "rev-parse", "HEAD").strip()
    capsys.readouterr()

    with pytest.MonkeyPatch.context() as environment:
        for name, value in hooked.items():
            environment.setenv(name, value)
        code, out, _ = ledger(capsys, "add", "--project", str(tree), "--feature", "x", "--kind", "design",
                              "--decision", "机密的决定")

    assert code == 0 and out.startswith("已记录：") and "提醒" not in out
    assert (git(tree, "rev-parse", "HEAD"), git(tree, "ls-files", "--stage")) == (head, index)
    assert git(project, "log", "--all", "--name-only", "--format=").count("entries/") == 0
    assert ledger_commits(ledger_root, start) == 1 and git(ledger_root, "status", "--porcelain").strip() == ""

    with pytest.MonkeyPatch.context() as environment:
        for name, value in hooked.items():
            environment.setenv(name, value)
        code = cli.main(["close", "x", "--project", str(tree), "--summary", "交付导出"])
    out = capsys.readouterr().out

    assert code == 0, out
    assert git(tree, "log", "-1", "--format=%s").strip() == "close x" and git(tree, "rev-parse", "HEAD~1") == head
    assert git(tree, "status", "--porcelain").strip() == ""
    assert git(project, "log", "--all", "--name-only", "--format=").count("entries/") == 0
    assert ledger_commits(ledger_root, start) == 2 and git(ledger_root, "status", "--porcelain").strip() == ""
    assert [record["kind"] for record in entries(ledger_root, "x")] == ["design", "close"]

    # A rerun asks the ledger repository whether the record is committed (settle). Asked of the project instead, the
    # record file showed as untracked there, the commit meant to settle it found nothing, and the report said the
    # ledger repository had not committed.
    head = git(tree, "rev-parse", "HEAD")
    with pytest.MonkeyPatch.context() as environment:
        for name, value in hooked.items():
            environment.setenv(name, value)
        code = cli.main(["close", "x", "--project", str(tree), "--summary", "交付导出"])
    out = capsys.readouterr().out

    assert code == 0, out
    assert "没有重复写" in out and "没有提交成功" not in out
    assert git(tree, "rev-parse", "HEAD") == head and git(tree, "status", "--porcelain").strip() == ""
    assert ledger_commits(ledger_root, start) == 2 and git(ledger_root, "status", "--porcelain").strip() == ""


def test_a_record_written_with_git_dir_naming_the_project_goes_to_the_ledger(tmp_path: Path, capsys) -> None:
    project, ledger_root = setup(tmp_path)
    head, index = git(project, "rev-parse", "HEAD"), git(project, "ls-files", "--stage")
    start = git(ledger_root, "rev-parse", "HEAD").strip()
    capsys.readouterr()

    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("GIT_DIR", str(project / ".git"))
        code, out, _ = ledger(capsys, "add", "--project", str(project), "--feature", "x", "--kind", "design",
                              "--decision", "机密的决定")

    assert code == 0 and "提醒" not in out
    assert (git(project, "rev-parse", "HEAD"), git(project, "ls-files", "--stage")) == (head, index)
    assert ledger_commits(ledger_root, start) == 1 and git(ledger_root, "status", "--porcelain").strip() == ""


def test_a_ledger_made_with_git_dir_naming_the_project_is_a_repository_of_its_own(tmp_path: Path, capsys) -> None:
    project, _ = setup(tmp_path)
    head, index = git(project, "rev-parse", "HEAD"), git(project, "ls-files", "--stage")
    second = tmp_path / "ledgers" / "second"

    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("GIT_DIR", str(project / ".git"))
        environment.setenv("GIT_INDEX_FILE", str(project / ".git" / "index"))
        assert cli.main(["ledger", "init", "--path", str(second)]) == 0

    assert (git(project, "rev-parse", "HEAD"), git(project, "ls-files", "--stage")) == (head, index)
    assert Path(git(second, "rev-parse", "--absolute-git-dir").strip()) == second.resolve() / ".git"
    assert git(second, "rev-list", "--count", "HEAD").strip() == "1" and git(second, "status", "--porcelain") == ""


def test_git_on_the_ledger_leaves_out_every_variable_that_ties_git_to_a_repository(tmp_path: Path,
                                                                                 monkeypatch) -> None:
    """The list is written out in the module; this holds it against the git that runs the tests."""
    listed = subprocess.run(["git", "rev-parse", "--local-env-vars"], cwd=tmp_path, capture_output=True, text=True,
                            encoding="utf-8", check=True).stdout.split()
    assert "GIT_DIR" in listed and "GIT_INDEX_FILE" in listed
    assert sorted(set(listed) - set(ledger_module.LOCAL_GIT_ENV)) == []
    for name in (*listed, "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
        monkeypatch.setenv(name, "elsewhere")

    kept = ledger_module.ledger_environment()

    assert [name for name, value in kept.items() if value == "elsewhere"] == []
    assert kept["GIT_AUTHOR_NAME"] == "dcu tests" and kept["GIT_CONFIG_GLOBAL"] == os.environ["GIT_CONFIG_GLOBAL"]


def test_a_folder_inside_the_project_is_not_the_project(tmp_path: Path, capsys) -> None:
    # The worktree fallback must not make every folder of the repository look configured: the card and the
    # capability specs are looked up under the folder given, so a check from src/ would pass on nothing.
    project, _ = setup(tmp_path)
    (project / "src").mkdir()

    code, out, err = ledger(capsys, "check", "--project", str(project / "src"))

    assert code == 2 and "没有配置账本" in out + err

    tree = tmp_path / "wt"                                   # the same inside a linked worktree
    git(project, "worktree", "add", "-q", "-b", "feat/x", str(tree))
    (tree / "src").mkdir()
    code, out, err = ledger(capsys, "check", "--project", str(tree / "src"))

    assert code == 2 and "没有配置账本" in out + err


NOT_JSON, TOO_DEEP, NOT_AN_OBJECT, NOT_A_PATH = (
    "不是合法的 UTF-8 JSON", "嵌套超过 64 层", "内容不是一个 JSON 对象", "ledger 应该是非空的路径字符串")
# guard.json files that every reader turns down by the one rule they share: both hooks, `hooks status` and
# `hooks install`, the ledger commands, `close` and `migrate`. Each names the ledger where it can, so a reader
# that echoed the file would give the ledger's path away.
UNREADABLE_GUARDS = {
    "cut-short": NOT_JSON, "empty": NOT_JSON, "utf-16": NOT_JSON, "gbk": NOT_JSON,
    "nan": NOT_JSON, "infinity": NOT_JSON, "minus-infinity": NOT_JSON,
    "nested-65": TOO_DEEP, "nested-100000": TOO_DEEP,
    "an-array": NOT_AN_OBJECT, "null": NOT_AN_OBJECT, "a-number": NOT_AN_OBJECT,
    "ledger-null": NOT_A_PATH, "ledger-empty": NOT_A_PATH, "ledger-blank": NOT_A_PATH,
    "ledger-json-whitespace": NOT_A_PATH, "ledger-a-number": NOT_A_PATH, "ledger-a-list": NOT_A_PATH,
    "ledger-next-line": NOT_A_PATH, "ledger-file-separator": NOT_A_PATH,
}


def unreadable_guard(kind: str, ledger_root: Path) -> bytes:
    """The bytes of one of UNREADABLE_GUARDS."""
    named = json.dumps(str(ledger_root))
    text = {
        "cut-short": f'{{"ledger": {named}, ',
        "empty": "",
        "utf-16": f'{{"ledger": {named}}}',                       # what PowerShell 5's `>` writes
        "gbk": f'{{"ledger": {named}, "note": "账本"}}',           # the ANSI code page of Chinese Windows
        "nan": f'{{"ledger": {named}, "deny": [NaN]}}',            # python's json takes these three, JSON.parse does not
        "infinity": f'{{"ledger": {named}, "since": Infinity}}',
        "minus-infinity": f'{{"ledger": {named}, "since": -Infinity}}',
        "nested-65": f'{{"ledger": {named}, "deep": ' + "[" * 64 + "]" * 64 + "}",
        "nested-100000": "[" * 100_000,                             # past python's recursion limit, not past node's
        "an-array": f"[{named}]",
        "null": "null",
        "a-number": "7",
        "ledger-null": '{"ledger": null}',
        "ledger-empty": '{"ledger": ""}',
        "ledger-blank": '{"ledger": "   "}',
        "ledger-json-whitespace": '{"ledger": " \\t\\n\\r"}',          # the four JSON calls whitespace
        # Blank is what python's str.strip() takes away, as in both hooks, which strip entries so before
        # turning them into paths; JS's trim() would leave these two.
        "ledger-next-line": '{"ledger": "\\u0085"}',
        "ledger-file-separator": '{"ledger": "\\u001c"}',
        "ledger-a-number": '{"ledger": 5}',
        "ledger-a-list": f'{{"ledger": [{named}]}}',
    }[kind]
    return text.encode({"utf-16": "utf-16", "gbk": "gbk"}.get(kind, "utf-8"))


# guard.json files every reader takes by the same rule, at the edges of UNREADABLE_GUARDS; written as UTF-8.
READABLE_GUARDS = {
    "bom": chr(0xFEFF) + '{"ledger": "x"}',                                # as Windows PowerShell writes UTF-8
    "no-ledger": '{"ledger_side": "human"}',                                  # no ledger at all is a valid file
    "deny-not-a-list": '{"ledger": "x", "deny": "../notes"}',                 # the hooks skip such a deny
    "deny-entry-not-text": '{"ledger": "x", "deny": ["../notes", 7]}',
    "nested-64": '{"ledger": "x", "deep": ' + "[" * 63 + "]" * 63 + "}",      # 64 levels: the limit, not past it
    "many-shallow": '{"ledger": "x", "many": [' + ",".join(["[]"] * 70) + "]}",  # 140 brackets, never 4 open
    "brackets-in-a-string": '{"ledger": "x", "note": "' + "[" * 70 + '\\"' + "{" * 70 + '"}',
    "overflow": '{"ledger": "x", "big": 1e999}',                              # infinity, as both hooks read it
    "integer-past-4300-digits": '{"ledger": "x", "big": ' + "1" * 4301 + "}",  # more than python's int() takes
    "negative-integer-past-4300-digits": '{"ledger": "x", "big": -' + "1" * 4301 + "}",
    "ledger-a-bom": '{"ledger": "\\ufeff"}',   # not whitespace to str.strip(): the hooks read it as a name too
}
# What read_guard makes of those json.loads alone does not read so: past 4300 digits, infinity, as in node.
@pytest.mark.parametrize("sample", HOOKS_UNREADABLE)
def test_the_ledger_commands_turn_down_what_the_hooks_turn_down(tmp_path: Path, sample: str) -> None:
    """The two hooks and the CLI were written apart; the hooks' samples are checked against read_guard here, so a
    guard.json the hooks block every call on is never one `hooks status` or the ledger commands call fine."""
    guard = tmp_path / "guard.json"
    guard.write_bytes(hooks_unreadable(sample, tmp_path / "ledgers" / "app"))

    assert ledger_module.read_guard(guard)[0] is None


@pytest.mark.parametrize("sample", HOOKS_READABLE)
def test_the_ledger_commands_read_what_the_hooks_read(tmp_path: Path, sample: str) -> None:
    guard = tmp_path / "guard.json"
    guard.write_bytes(hooks_readable(sample, tmp_path / "ledgers" / "app"))

    config, problem = ledger_module.read_guard(guard)
    assert problem == "" and config is not None


READ_AS = {"bom": {"ledger": "x"}, "integer-past-4300-digits": {"ledger": "x", "big": float("inf")},
           "negative-integer-past-4300-digits": {"ledger": "x", "big": float("-inf")}}


@pytest.mark.parametrize("kind", UNREADABLE_GUARDS)
def test_read_guard_turns_down_what_the_hooks_cannot_read_and_says_why_in_a_fixed_sentence(tmp_path: Path,
                                                                                          kind: str) -> None:
    ledger_root = tmp_path / "ledgers" / "app"
    guard = write(tmp_path, "app/.dev-circuit/guard.json", "")
    guard.write_bytes(unreadable_guard(kind, ledger_root))

    assert ledger_module.read_guard(guard) == (None, UNREADABLE_GUARDS[kind])


@pytest.mark.parametrize("kind", READABLE_GUARDS)
def test_read_guard_reads_what_the_hooks_read(tmp_path: Path, kind: str) -> None:
    text = READABLE_GUARDS[kind]
    guard = write(tmp_path, "app/.dev-circuit/guard.json", "")
    guard.write_bytes(text.encode("utf-8"))

    config, problem = ledger_module.read_guard(guard)

    assert problem == "" and config == (READ_AS[kind] if kind in READ_AS else json.loads(text))


@pytest.mark.skipif(not hasattr(sys, "set_int_max_str_digits"), reason="python 3.10.6 及更早没有整数位数上限")
@pytest.mark.parametrize("limit, digits, expected", [(0, 4301, float("inf")), (640, 700, float("inf")),
                                                     (640, 600, int("1" * 600))], ids=["no-limit", "past", "within"])
def test_read_guard_reads_a_long_integer_the_same_whatever_int_takes(tmp_path: Path, limit: int, digits: int,
                                                                     expected) -> None:
    """PYTHONINTMAXSTRDIGITS moves the limit of int(): the file is read all the same, past 4300 digits as infinity."""
    guard = write(tmp_path, "app/.dev-circuit/guard.json", '{"ledger": "x", "big": ' + "1" * digits + "}")
    before = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(limit)
    try:
        assert ledger_module.read_guard(guard) == ({"ledger": "x", "big": expected}, "")
    finally:
        sys.set_int_max_str_digits(before)


def test_read_guard_counts_the_nesting_outside_strings_only(tmp_path: Path) -> None:
    """A string that ends in an escaped backslash ends there: the brackets after it are counted."""
    guard = write(tmp_path, "app/.dev-circuit/guard.json", "")
    guard.write_bytes(('{"ledger": "x", "s": "a\\\\", "deep": ' + "[" * 64 + "]" * 64 + "}").encode("utf-8"))

    assert ledger_module.read_guard(guard) == (None, TOO_DEEP)
    assert ledger_module.read_guard(tmp_path / "app" / "missing.json") == (None, "读不出这个文件")


@pytest.mark.parametrize("kind", UNREADABLE_GUARDS)
def test_a_guard_file_the_hooks_cannot_read_stops_the_ledger_commands_readably(tmp_path: Path, capsys,
                                                                               kind: str) -> None:
    """Both hooks block every tool call on such a guard.json; "no ledger configured" would send the human the wrong
    way, and a deeply nested file was a traceback."""
    project, ledger_root = setup(tmp_path)
    (project / ".dev-circuit" / "guard.json").write_bytes(unreadable_guard(kind, ledger_root))
    capsys.readouterr()

    for command in (("check", "--project", str(project)),
                    ("add", "--project", str(project), "--feature", "x", "--kind", "design", "--decision", "导出")):
        code, out, err = ledger(capsys, *command)

        assert code == 2, command
        assert f"guard.json 无法解析：{UNREADABLE_GUARDS[kind]}" in err, command
        assert "拦下全部工具调用" in err and "human" in err, command
        assert "没有配置账本" not in out + err and not names_the_ledger(ledger_root, out + err), command
    assert not (ledger_root / "entries" / "app").exists()


def test_a_guard_file_without_a_ledger_entry_is_still_no_ledger(tmp_path: Path, capsys) -> None:
    """Leaving the key out is how a project says it has no ledger here; only a key the hooks cannot read is an error."""
    project, _ = setup(tmp_path)
    write(project, ".dev-circuit/guard.json", json.dumps({"deny": ["../notes"]}))

    code, out, err = ledger(capsys, "check", "--project", str(project))

    assert code == 2 and "没有配置账本" in out + err


def test_a_worktree_with_its_own_guard_file_still_files_under_the_project(tmp_path: Path, capsys) -> None:
    project, ledger_root = setup(tmp_path)
    tree = tmp_path / "wt-export"
    git(project, "worktree", "add", "-q", "-b", "feat/x", str(tree))
    write(tree, ".dev-circuit/guard.json", json.dumps({"ledger": str(ledger_root)}))   # copied in by hand
    write(tree, "specs/x/spec.md", CARD.format(framework="不变"))
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "design(x)")

    assert ledger(capsys, "add", "--project", str(tree), "--feature", "x", "--kind", "design",
                  "--decision", "导出")[0] == 0

    assert [record["kind"] for record in entries(ledger_root, "x")] == ["design"]
