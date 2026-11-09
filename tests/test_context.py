"""devcircuit context: read the parts of the current design a task needs, and say what was left out."""

import subprocess
from pathlib import Path

import pytest

import devcircuit.cli as cli
import devcircuit.context as context_module


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


DEMO = """# 导出能力
代号：DEMO

> **读我**：本文列出导出能力的现行要求。

- DEMO-1：导出当前一条记录。
  - 例：选中一条记录后导出，得到该记录。
- DEMO-3：导出后弹出提示。
  - 例：导出完成时看到提示。
"""

SYNC = """# 同步能力
代号：SYNC

- SYNC-1：同步成功后可读回相同的记录。
  - 例：同步两条记录后读回两条相同记录。
"""

CARD = """# add-export：扩充导出

能力：DEMO（已有）· 框架：不变

## 目标

导出选中的多条记录，并支持 CSV。

## 切片

- S1：扩充导出（当前）
  - [ ] 改导出函数
"""


def project(root: Path) -> Path:
    write(root, "docs/requirements/demo.md", DEMO)
    write(root, "docs/requirements/sync.md", SYNC)
    write(root, "docs/requirements/README.md", "# 能力规格\n")
    write(root, "specs/backlog.md", "# 待做池\n\n- 列宽对齐（导出）\n- 中文排序（导出）\n")
    write(root, "docs/architecture.md", '# 结构\n\n<a id="summary"></a>\n## 框架摘要\n\n'
          "- 入口 → 导出服务 → 文件\n- 记录归仓库所有\n\n## 细节\n\n正文\n")
    write(root, "docs/design.md", "# 界面\n\n> **读我**：本文回答导出界面怎么摆；不回答要求。\n")
    write(root, "tests/test_demo.py", "# DEMO-1\n")
    return root


def run(capsys, *args: str) -> tuple[int, str]:
    code = cli.main(["context", *args])
    return code, capsys.readouterr().out


def test_map_lists_capabilities_features_summary_and_docs(tmp_path: Path, capsys) -> None:
    root = project(tmp_path)
    write(root, "specs/add-export/spec.md", CARD)

    code, out = run(capsys, "--map", "--root", str(root))

    assert code == 0
    assert "DEMO" in out and "导出能力" in out and "2 条" in out
    assert "SYNC" in out and "1 条" in out
    assert "add-export" in out and "S1：扩充导出" in out
    assert "docs/architecture.md#summary（2 行）" in out
    assert "docs/design.md：本文回答导出界面怎么摆" in out
    assert "specs/backlog.md 2 条" in out
    assert "例：" not in out


def test_map_says_when_there_is_no_framework_summary(tmp_path: Path, capsys) -> None:
    root = project(tmp_path)
    (root / "docs" / "architecture.md").unlink()

    code, out = run(capsys, "--map", "--root", str(root))

    assert code == 0
    assert "还没有 docs/architecture.md" in out


def test_capability_lists_one_line_per_requirement(tmp_path: Path, capsys) -> None:
    root = project(tmp_path)

    code, out = run(capsys, "--capability", "DEMO", "--root", str(root))

    assert code == 0
    assert "- DEMO-1：导出当前一条记录。" in out and "- DEMO-3：导出后弹出提示。" in out
    assert "例：" not in out
    assert "--ids DEMO-1,DEMO-3" in out


def test_ids_print_full_entries_and_report_unknown_ones(tmp_path: Path, capsys) -> None:
    root = project(tmp_path)

    code, out = run(capsys, "--ids", "DEMO-1,SYNC-1", "--root", str(root))
    assert code == 0
    assert "docs/requirements/demo.md:6" in out
    assert "例：选中一条记录后导出，得到该记录。" in out
    assert "例：同步两条记录后读回两条相同记录。" in out
    assert "DEMO-3" not in out

    code, out = run(capsys, "--ids", "DEMO-9", "--root", str(root))
    assert code == 1
    assert "找不到：DEMO-9" in out


def _feature_branch(root: Path) -> None:
    project(root)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "switch", "-q", "-c", "feat/add-export")
    write(root, "docs/requirements/demo.md", DEMO.replace(
        "- DEMO-1：导出当前一条记录。\n  - 例：选中一条记录后导出，得到该记录。",
        "- DEMO-1：导出当前选中的全部记录。\n  - 例：选中两条时导出两条。\n"
        "- DEMO-2：支持 CSV 导出。\n  - 例：选择 CSV 时生成带表头的 CSV。\n"
        "- DEMO-4：输出文件写不进去时给出可读错误。\n  - 例：目录不存在时以 1 退出，不打印堆栈。",
    ).replace("- DEMO-3：导出后弹出提示。\n  - 例：导出完成时看到提示。\n", ""))
    write(root, "specs/add-export/spec.md", CARD)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "design(add-export)")
    write(root, "src/export.py", "# DEMO-2 SYNC-1\n")


def test_feature_shows_what_the_branch_changed(tmp_path: Path, capsys) -> None:
    _feature_branch(tmp_path)

    code, out = run(capsys, "--feature", "add-export", "--root", str(tmp_path))

    assert code == 0
    assert "导出选中的多条记录，并支持 CSV。" in out
    assert "新增：DEMO-2、DEMO-4" in out and "改写：DEMO-1" in out and "删除：DEMO-3" in out
    assert "例：选择 CSV 时生成带表头的 CSV。" in out
    assert "例：目录不存在时以 1 退出，不打印堆栈。" in out
    assert "例：导出完成时看到提示。" not in out
    assert "例：同步两条记录后读回两条相同记录。" in out
    assert "tests/test_demo.py（DEMO-1）" in out
    assert "框架摘要没改" in out


def test_review_adds_the_base_and_a_diff_summary(tmp_path: Path, capsys) -> None:
    _feature_branch(tmp_path)
    base = git(tmp_path, "rev-parse", "main").strip()

    code, out = run(capsys, "--review", "add-export", "--root", str(tmp_path))

    assert code == 0
    assert base in out
    assert "改动统计" in out and "docs/requirements/demo.md" in out


def test_feature_without_a_base_falls_back_to_the_cards_capabilities(tmp_path: Path, capsys) -> None:
    root = project(tmp_path)
    write(root, "specs/add-export/spec.md", CARD)

    code, out = run(capsys, "--feature", "add-export", "--root", str(root))

    assert code == 0
    assert "没有可比的基线" in out
    assert "- DEMO-1：导出当前一条记录。" in out
    assert "SYNC-1" not in out


def test_feature_needs_its_card(tmp_path: Path, capsys) -> None:
    root = project(tmp_path)

    assert cli.main(["context", "--feature", "absent", "--root", str(root)]) == 2
    assert "specs/absent/spec.md" in capsys.readouterr().err


def test_output_is_capped_and_says_so(tmp_path: Path, capsys) -> None:
    root = project(tmp_path)
    write(root, "docs/requirements/demo.md", "# 导出能力\n代号：DEMO\n\n" + "".join(
        f"- DEMO-{number}：{'很长的要求' * 20}\n  - 例：{'很长的例子' * 20}\n" for number in range(1, 41)))
    ids = ",".join(f"DEMO-{number}" for number in range(1, 41))

    code, out = run(capsys, "--ids", ids, "--max-chars", "800", "--root", str(root))

    assert code == 0
    assert len(out) < 1200
    assert "截断" in out and "--ids" in out


def test_a_renamed_capability_is_not_reported_as_new(tmp_path: Path, capsys) -> None:
    project(tmp_path)
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    git(tmp_path, "switch", "-q", "-c", "feat/add-export")
    git(tmp_path, "mv", "docs/requirements/demo.md", "docs/requirements/export.md")
    renamed = tmp_path / "docs" / "requirements" / "export.md"
    renamed.write_text(renamed.read_text(encoding="utf-8").replace(
        "- DEMO-3：导出后弹出提示。\n  - 例：导出完成时看到提示。\n", ""), encoding="utf-8")
    write(tmp_path, "specs/add-export/spec.md", CARD)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "design(add-export)")

    code, out = run(capsys, "--feature", "add-export", "--root", str(tmp_path))

    assert code == 0
    assert "删除：DEMO-3" in out and "新增" not in out


def test_an_explicit_base_must_exist(tmp_path: Path, capsys) -> None:
    _feature_branch(tmp_path)

    assert cli.main(["context", "--feature", "add-export", "--base", "nope", "--root", str(tmp_path)]) == 2
    assert "nope" in capsys.readouterr().err


def test_ids_accept_the_separators_the_tools_print(tmp_path: Path, capsys) -> None:
    # context and close list IDs with 、, so the same list pasted back must work.
    root = project(tmp_path)

    code, out = run(capsys, "--ids", "DEMO-1、DEMO-3", "--root", str(root))

    assert code == 0
    assert "例：选中一条记录后导出，得到该记录。" in out and "例：导出完成时看到提示。" in out


def _trunk_repo(root: Path, trunk: str) -> Path:
    """A repo whose trunk has one commit."""
    project(root)
    git(root, "init", "-q", "-b", trunk)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def test_the_base_defaults_to_the_trunk_agents_names(tmp_path: Path) -> None:
    _trunk_repo(tmp_path, "workbench")
    write(tmp_path, "AGENTS.md", "# 项目\n\n- 主干：`workbench`（`devcircuit` 默认拿它当对比的基线）\n")
    git(tmp_path, "switch", "-q", "-c", "feat/add-export")

    found = context_module.merge_base(tmp_path, None)
    assert found and found[0] == "workbench"


def test_without_a_named_trunk_the_base_is_the_remotes_default_branch(tmp_path: Path) -> None:
    remote = _trunk_repo(tmp_path / "remote", "workbench")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    git(clone, "switch", "-q", "-c", "feat/add-export")

    found = context_module.merge_base(clone, None)
    assert found and found[0] == "workbench"


def test_a_trunk_agents_names_must_exist(tmp_path: Path, capsys) -> None:
    _trunk_repo(tmp_path, "main")
    write(tmp_path, "AGENTS.md", "# 项目\n\n- 主干：`develop`\n")
    write(tmp_path, "specs/add-export/spec.md", CARD)

    assert cli.main(["context", "--feature", "add-export", "--root", str(tmp_path)]) == 2
    assert "AGENTS.md" in capsys.readouterr().err


def test_the_trunk_line_is_read_in_common_markdown_shapes(tmp_path: Path) -> None:
    """A trunk line the tool cannot read silently falls back to another branch: the wrong base."""
    for line in ("- **主干**：`workbench`", "1. 主干：workbench", "+ 主干：`workbench`",
                 "- 主干 ：workbench", "**主干：** `workbench`", "| 主干 | `workbench` |",
                 "　　主干：`workbench`", "- 主干：　`workbench`", "- 主干： workbench"):
        write(tmp_path, "AGENTS.md", f"# 项目\n\n{line}\n")
        assert context_module.named_trunk(tmp_path) == "workbench", line


def test_a_trunk_line_without_a_branch_is_an_error(tmp_path: Path) -> None:
    write(tmp_path, "AGENTS.md", "# 项目\n\n- 主干：\n- 分支：每个功能在 feat/ 上做\n")
    with pytest.raises(context_module.ContextError, match="主干"):
        context_module.named_trunk(tmp_path)


def test_with_a_trunk_line_and_no_commits_there_is_nothing_to_compare(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q", "-b", "main")
    write(tmp_path, "AGENTS.md", "# 项目\n\n- 主干：`main`\n")
    assert context_module.merge_base(tmp_path, None) is None


def test_a_trunk_that_only_exists_on_origin_is_used_from_there(tmp_path: Path) -> None:
    remote = _trunk_repo(tmp_path / "remote", "workbench")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    git(clone, "switch", "-q", "-c", "feat/add-export")
    git(clone, "branch", "-D", "workbench")
    write(clone, "AGENTS.md", "# 项目\n\n- 主干：`workbench`\n")

    found = context_module.merge_base(clone, None)
    assert found and found[0] == "origin/workbench"


def test_without_a_trunk_line_local_main_still_wins_over_a_stale_remote_default(tmp_path: Path) -> None:
    """0.6 compared against main; a stale origin/HEAD must not silently move an old project's base."""
    remote = _trunk_repo(tmp_path / "remote", "master")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    git(clone, "switch", "-q", "-c", "main")          # the project moved to main; origin/HEAD still says master
    git(clone, "switch", "-q", "-c", "feat/add-export")

    found = context_module.merge_base(clone, None)
    assert found and found[0] == "main"


def test_map_marks_a_card_that_is_not_committed_as_a_draft(tmp_path: Path, capsys) -> None:
    """From 0.7 the card exists before the user settles the design; only a committed card is in progress."""
    _feature_branch(tmp_path)
    write(tmp_path, "specs/add-import/spec.md", CARD.replace("add-export", "add-import"))

    code, out = run(capsys, "--map", "--root", str(tmp_path))
    assert code == 0
    lines = out.splitlines()
    assert any("add-import" in line and "草稿" in line for line in lines)
    assert not any("add-export" in line and "草稿" in line for line in lines)
