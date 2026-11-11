"""devcircuit ledger: the dev agent appends records it cannot read back; check compares the ledger with the repo."""

import json
import subprocess
from pathlib import Path

import devcircuit.cli as cli


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
