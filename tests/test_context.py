"""devcircuit context: read the parts of the current design a task needs, and say what was left out."""

import re
import shlex
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


# ---------------------------------------------------------------- slice lines on the card

SLICE_FORM = "写成 `- S<n>：<标题>`，在做的加（当前），做完的加 ✓"


def _card(*slices: str) -> str:
    """A card whose slice section holds these lines; the first one is line 11."""
    return ("# f：功能\n\n能力：DEMO（已有）· 框架：不变\n\n## 范围\n\n- 做：S3 存储桶的读写\n\n## 切片\n\n"
            + "\n".join(slices) + "\n")


def _status(tmp_path: Path, *slices: str) -> str:
    return context_module._slice_status(write(tmp_path, "specs/f/spec.md", _card(*slices)))


@pytest.mark.parametrize("line, shown", [
    ("- S3：读回", "S3：读回"), ("- S3: 读回", "S3: 读回"), ("* S3：读回", "S3：读回"), ("+ S3：读回", "S3：读回"),
    ("3. S3：读回", "S3：读回"), ("3) S3：读回", "S3：读回"), ("- [ ] S3：读回", "S3：读回"),
    ("- **S3**：读回", "S3：读回"), ("- **S3：读回**", "S3：读回"), ("- **S3：** 读回", "S3： 读回"),
    ("- S3 ：读回", "S3：读回"), ("- s3：读回", "S3：读回"),
    # a small s is a slice unless a Latin name runs straight on from a half-width colon (`s3:GetObject`)
    ("- s3:读回", "S3:读回"), ("- s3: read back", "S3: read back"), ("- s3：Read back", "S3：Read back"),
    ("- S3:Read back", "S3:Read back"),
])
def test_a_slice_line_is_read_in_common_markdown_shapes(tmp_path: Path, line: str, shown: str) -> None:
    """Only `- S3：…` was read: any other shape was skipped without a word and --map named S4 as the next slice."""
    assert _status(tmp_path, "- S1：建表 ✓", "- S2：写入 ✓", line, "- S4：对账", "- S5：告警") == f"下一个：{shown}"


@pytest.mark.parametrize("line, shown", [
    ("- S3：读回（当前）", "S3：读回"), ("- S3：读回(当前)", "S3：读回"), ("- S3: 读回 (当前)", "S3: 读回"),
    ("* S3：读回（当前）", "S3：读回"), ("- [ ] S3：读回（当前）", "S3：读回"), ("- **S3：读回**（当前）", "S3：读回"),
    ("- S3：读回（当前）先做校验", "S3：读回"), ("- S3：读回 ✓（当前）", "S3：读回 ✓"),
])
def test_the_current_slice_is_the_one_marked_after_its_title(tmp_path: Path, line: str, shown: str) -> None:
    assert _status(tmp_path, "- S1：建表 ✓", "- S2：写入", line, "- S4：对账") == f"当前：{shown}"


@pytest.mark.parametrize("line", [
    "- S3：读回 ✓", "- S3：读回 ✓ 已合入", "- S3：✓ 读回", "- [x] S3：读回", "- [X] S3：读回", "* **S3：读回** ✓",
])
def test_a_finished_slice_is_not_offered_as_the_next_one(tmp_path: Path, line: str) -> None:
    """Done has one rule: a ✓ in the title, or a ticked task box."""
    assert _status(tmp_path, "- S1：建表 ✓", "- S2：写入 ✓", line, "- S4：对账") == "下一个：S4：对账"
    assert _status(tmp_path, line) == "切片都已完成"


@pytest.mark.parametrize("line", [
    "- S3（下一个）：读回",        # the line a downstream card had: skipped, and --map answered "下一个：S4"
    "- S3（当前）：读回", "- （当前）S3：读回", "- [当前] S3：读回", "- 【当前】S3：读回", "- ✓ S3：读回", "- ✅ S3：读回",
    "- S3 读回", "- S3. 读回", "- S3 — 读回", "### S3：读回", "| S3 | 读回 | 当前 |", "- [] S3：读回",
    "- S3a：读回", "- S3-1：读回", "- S3–S4：读回", "- `S3`：读回", "- ~~S3：读回~~", "- 切片 3：读回", "- 切片 S3：读回",
    # the same lines behind another bullet, and a bracketed word longer than 当前
    "* S3（下一个）：读回", "+ S3 读回", "1. S3 读回", "3) S3 读回", "- （下一个）S3：读回", "- （进行中）S3：读回",
    # a task box or bold together with a word before the number: each is a shape that is read on its own
    "- [ ] （当前）S3：读回", "- [ ] (当前) S3：读回", "- [x] （完成）S3：读回", "- **（当前）S3：读回**",
    "- **（当前）** S3：读回", "- **（下一个）S3**：读回", "1. [ ] 【当前】S3：读回", "- [ ] **（当前）S3：读回**",
    "- [ ] **（当前）** S3：读回",
    # no space after the bullet, italics, and the longest bracketed word that is still taken for a state
    "-S3：读回", "*S3*：读回", "- _S3_：读回", "- （已完成，等待合入）S3：读回",
])
def test_a_slice_line_that_cannot_be_read_is_shown_not_skipped(tmp_path: Path, line: str) -> None:
    status = _status(tmp_path, "- S1：建表 ✓", "- S2：写入 ✓", line, "- S4：对账")

    assert status == f"切片行读不懂（第 13 行）：{line}  ← {SLICE_FORM}"
    assert "对账" not in status and "下一个：" not in status   # no state built from the lines that did parse


@pytest.mark.parametrize("line", [
    "- S3：读回（进行中）", "- S3：读回（在做）", "- S3：读回（下一个）", "- S3：读回（待做）", "- S3：读回（完成）",
    "- S3：读回（已完成）", "- S3：读回（做完）", "- S3：读回 (进行中)", "- S3：读回【进行中】", "- S3：读回 [下一个]",
    "- S3：读回【当前】", "- S3：读回 [当前]", "- S3：读回（ 当前 ）", "- S3：读回 **（进行中）**", "- **S3：读回**（进行中）",
    "- [ ] S3：读回（完成）", "- S3：读回 ✅", "- S3：读回 ✔", "- S3：读回 ☑", "- S3：读回 √", "- S3：读回（当前）✅",
    "- S3：读回（进行中）。", "- S3：读回（完成）；", "- S3：读回 (下一个).",     # a slice line may end in a full stop
    "- S3：读回（进行中），", "- S3：读回（完成）,",                             # or a comma
    "- S3：读回 _（进行中）_", "- S3：读回 `（进行中）`", "- S3：读回 ~~（完成）~~",  # and the word may be in any mark
])
def test_a_state_in_a_word_that_is_not_read_is_shown_not_read_past(tmp_path: Path, line: str) -> None:
    """Two marks are read, ✓ and （当前）. A slice marked （进行中） was read as not started: with an earlier
    slice still open --map named that one, and nothing in its answer said S3 was marked."""
    status = _status(tmp_path, "- S1：建表 ✓", "- S2：写入", line, "- S4：对账")

    assert status == f"切片行读不懂（第 13 行）：{line}  ← {SLICE_FORM}"


@pytest.mark.parametrize("line", [
    "- S3：导出（CSV）", "- S3：读回（完成后通知）", "- S3：读回（下一个版本再对账）", "- S3：列表里标出（进行中）的任务",
    "- S3：进行中的任务排在前面", "- S3：**读回**", "- S3：读回（完成后通知）。", "- S3：读回。",
])
def test_other_words_after_the_title_stay_part_of_the_title(tmp_path: Path, line: str) -> None:
    """Only a bracketed state word that ends the title is taken for a state; a title may say 完成 or end in brackets."""
    assert _status(tmp_path, "- S1：建表 ✓", "- S2：写入 ✓", line, "- S4：对账") == f"下一个：{line[2:]}"


@pytest.mark.parametrize("line", ["- s3://bucket/raw 的读写", "- S3://bucket/raw 的读写",
                                  "- [s3://bucket](https://example.com)"])
def test_an_address_is_not_a_slice_line(tmp_path: Path, line: str) -> None:
    """With a small s read as well, `- s3://…` became slice S3 titled //…."""
    assert _status(tmp_path, "- S1：建表 ✓", line, "- S2：写入", "- S4：对账") == "下一个：S2：写入"


@pytest.mark.parametrize("line", ["- s3:GetObject 权限", "- s3:* 全部权限", "- s3:PutObject", "- s12:build"])
def test_a_small_s_run_into_a_name_is_shown_not_read_as_a_slice(tmp_path: Path, line: str) -> None:
    """With a small s read as well, a permission written `- s3:GetObject` became slice S3, and --map named it
    as the next one. It may as well be a slice written without a space, so it is shown and not guessed."""
    status = _status(tmp_path, "- S1：建表 ✓", line, "- S2：写入")

    assert status == f"切片行读不懂（第 12 行）：{line}  ← {SLICE_FORM}"


def test_a_link_in_front_is_not_taken_for_a_state_word(tmp_path: Path) -> None:
    """A bracketed word in front of S<n> is taken for a state up to eight characters: a link's address is longer."""
    line = "- [设计文档](docs/design.md) S3 桶的读写"
    assert _status(tmp_path, "- S1：建表 ✓", line, "- S2：写入", "- S4：对账") == "下一个：S2：写入"


def test_map_reports_the_unreadable_line_and_still_lists_the_rest(tmp_path: Path, capsys) -> None:
    root = project(tmp_path)
    write(root, "specs/f/spec.md", _card("- S1：建表 ✓", "- S2 写入", "- S3 读回", "- S4：对账"))
    write(root, "specs/add-export/spec.md", CARD)

    code, out = run(capsys, "--map", "--root", str(root))

    assert code == 0                                           # one card that cannot be read does not fail the map
    row = next(line for line in out.splitlines() if line.startswith("- f "))
    assert row == f"- f  specs/f/spec.md  切片行读不懂（第 12 行，另有 1 行）：- S2 写入  ← {SLICE_FORM}"
    assert "- add-export  specs/add-export/spec.md  当前：S1：扩充导出" in out.splitlines()


def test_an_unreadable_slice_line_is_quoted_up_to_160_characters(tmp_path: Path) -> None:
    status = _status(tmp_path, "- S1 " + "很长的标题" * 60)

    assert status == f"切片行读不懂（第 11 行）：- S1 {('很长的标题' * 60)[:155]}…  ← {SLICE_FORM}"


def test_only_top_level_lines_of_the_slice_section_are_slices(tmp_path: Path) -> None:
    # "- 做：S3 存储桶的读写" sits under 范围 in _card; indented lines are steps.
    assert _status(tmp_path, "- S1：建表（当前）", "  - [ ] S3 桶的权限", "  - [x] S9：这只是一步") == "当前：S1：建表"
    card = "# g\n\n## 范围\n\n- S3：桶\n- S4 桶\n\n## 切片\n\n- S1：建表\n\n## 备注\n\n- S7：不是切片（当前）\n- S8 也不是\n"
    assert context_module._slice_status(write(tmp_path, "specs/g/spec.md", card)) == "下一个：S1：建表"


def test_the_slice_section_ends_at_the_next_heading_of_its_level_or_above(tmp_path: Path) -> None:
    card = "# h\n\n### 切片\n\n- S1：建表 ✓\n\n#### 第二批\n\n- S2：写入\n\n## 备注\n\n- S3：不是切片（当前）\n"
    assert context_module._slice_status(write(tmp_path, "specs/h/spec.md", card)) == "下一个：S2：写入"


@pytest.mark.parametrize("block", [
    "```bash\n# 先备份\n## 再迁移\n```", "  ```\n# 先备份\n  ```",
    "~~~~\n# 先备份\n```\n## 再迁移\n~~~~",                    # a fence closes with its own character
    "````\n```\n# 先备份\n```\n````",                          # with at least as many of them
    "```\n```bash\n# 先备份\n```",                             # and with nothing after them
])
def test_a_heading_inside_a_code_block_does_not_end_the_slice_section(tmp_path: Path, block: str) -> None:
    """A shell comment in a fenced block was taken for a level-1 heading: the slices after it were dropped
    and --map answered 切片都已完成."""
    card = f"# m\n\n## 切片\n\n- S1：建表 ✓\n{block}\n- S2：写入\n- S3：读回\n\n## 备注\n\n- S9：不是切片（当前）\n"
    assert context_module._slice_status(write(tmp_path, "specs/m/spec.md", card)) == "下一个：S2：写入"


def test_inline_code_at_the_start_of_a_line_does_not_open_a_code_block(tmp_path: Path) -> None:
    """Taken for an opening fence it was never closed: the section ran to the end of the card, and a line
    under a later heading was read as the slice in progress."""
    card = ("# m\n\n## 切片\n\n- S1：建表 ✓\n- S2：写入\n\n```make test``` 通过后再提交。\n\n## 备注\n\n"
            "- S9：不是切片（当前）\n")
    assert context_module._slice_status(write(tmp_path, "specs/m/spec.md", card)) == "下一个：S2：写入"


@pytest.mark.parametrize("heading", ["## 切片\n\n", ""])
def test_a_slice_line_inside_a_code_block_is_read_like_any_other(tmp_path: Path, heading: str) -> None:
    """As 0.7.1 read it, under the heading and on a card without one. A fence is followed only so that a `#`
    inside it does not end the section."""
    card = f"# m\n\n{heading}- S1：建表 ✓\n```text\n- S2：写入（当前）\n```\n- S3：读回\n"
    assert context_module._slice_status(write(tmp_path, "specs/m/spec.md", card)) == "当前：S2：写入"


@pytest.mark.parametrize("heading", ["## 切片 3 个", "## 切片 S1-S5", "## 切片（S1–S5）", "## 切片计划", "# 切片", "###### 切片"])
def test_the_slice_heading_may_say_more_than_the_word(tmp_path: Path, heading: str) -> None:
    """`## 切片 3 个` was taken for a slice written as a heading, and the card for one that cannot be read."""
    level = heading.split("切片")[0].strip()
    card = f"# n\n\n{heading}\n\n- S1：建表 ✓\n- S2：写入\n\n{level} 备注\n\n- S3：不是切片（当前）\n"
    assert context_module._slice_status(write(tmp_path, "specs/n/spec.md", card)) == "下一个：S2：写入"


def test_every_section_headed_by_the_word_is_read(tmp_path: Path) -> None:
    """Only the first was: `## 切片原则` in front of the slices hid them all, a second batch behind them was dropped."""
    card = "# p\n\n## 切片原则\n\n按风险排。\n\n## 切片\n\n- S1：建表 ✓\n- S2：写入（当前）\n"
    assert context_module._slice_status(write(tmp_path, "specs/p/spec.md", card)) == "当前：S2：写入"
    card = "# p\n\n## 切片\n\n- S1：建表\n\n## 切片（第二批）\n\n- S2：写入\n\n## 备注\n\n- S3：不是切片（当前）\n"
    assert [item.id for item in context_module.read_slices(card)[0]] == ["S1", "S2"]     # both, and nothing after
    assert context_module._slice_status(write(tmp_path, "specs/p/spec.md", card)) == "下一个：S1：建表"


def test_a_deeper_heading_that_starts_with_the_word_stays_inside_the_section(tmp_path: Path) -> None:
    """Were `### 切片说明` taken for a new section, the next `###` heading would end it and hide the slices below."""
    card = ("# r\n\n## 切片\n\n- S1：建表 ✓\n\n### 切片说明\n\n按风险排。\n\n### 第二批\n\n- S2：写入\n\n## 备注\n\n"
            "- S3：不是切片（当前）\n")
    assert context_module._slice_status(write(tmp_path, "specs/r/spec.md", card)) == "下一个：S2：写入"


def test_a_heading_written_like_a_slice_does_not_end_the_slice_section(tmp_path: Path) -> None:
    """It ended the section before it was looked at: S1 was all that was read, and the answer was 切片都已完成."""
    card = "# q\n\n## 切片\n\n- S1：建表 ✓\n\n## S2：写入\n\n- [ ] 写入\n\n## 备注\n\n- S3：不是切片\n"
    status = context_module._slice_status(write(tmp_path, "specs/q/spec.md", card))
    assert status == f"切片行读不懂（第 7 行）：## S2：写入  ← {SLICE_FORM}"


def test_a_card_without_a_slice_heading_is_read_whole(tmp_path: Path) -> None:
    card = "# i\n\n能力：DEMO（已有）\n\n**切片**\n\n- S1：建表 ✓\n- S2：写入\n"
    assert context_module._slice_status(write(tmp_path, "specs/i/spec.md", card)) == "下一个：S2：写入"
    card = "# s3-sync：同步到 S3\n\n能力：DEMO（已有）\n\n- 做：S3 桶\n"       # the card's own title is not a slice line
    assert context_module._slice_status(write(tmp_path, "specs/s3-sync/spec.md", card)) == "还没有切片"
    # Read whole, nothing tells a slice line from a line about S3 elsewhere on the card: that one is shown too.
    card = "# i\n\n## 范围\n\n- S3 存储桶的读写\n\n**切片**\n\n- S1：建表\n"
    status = context_module._slice_status(write(tmp_path, "specs/i/spec.md", card))
    assert status == f"切片行读不懂（第 5 行）：- S3 存储桶的读写  ← {SLICE_FORM}"
    card = card.replace("**切片**", "## 切片")                                # under the heading, only its section is read
    assert context_module._slice_status(write(tmp_path, "specs/i/spec.md", card)) == "下一个：S1：建表"
    card = "# i\n\n## 权限\n\n- s3:GetObject\n- s3:PutObject\n"               # was read as slices S3 and S3
    status = context_module._slice_status(write(tmp_path, "specs/i/spec.md", card))
    assert status == f"切片行读不懂（第 5 行，另有 1 行）：- s3:GetObject  ← {SLICE_FORM}"


@pytest.mark.parametrize("word", ["切片 ", "切片", "切片 S", "切片 s"])
def test_slices_written_as_headings_are_shown_not_taken_for_the_slice_section(tmp_path: Path, word: str) -> None:
    card = f"# j\n\n## {word}1：建表\n\n- [x] 建表\n\n## {word}2：写入\n\n- [ ] 写入\n"
    status = context_module._slice_status(write(tmp_path, "specs/j/spec.md", card))
    assert status == f"切片行读不懂（第 3 行，另有 1 行）：## {word}1：建表  ← {SLICE_FORM}"


def test_a_slice_section_without_slice_lines_says_so(tmp_path: Path) -> None:
    assert _status(tmp_path, "  - S1：建表", "  - S2：写入") == f"没读到切片行：{SLICE_FORM}"      # all indented
    assert _status(tmp_path, "- 第一步：建表") == f"没读到切片行：{SLICE_FORM}"
    assert _status(tmp_path) == "还没有切片"                                                  # an empty section
    assert context_module._slice_status(write(tmp_path, "specs/k/spec.md", "# k\n\n能力：DEMO（已有）\n")) == "还没有切片"


def test_read_slices_takes_the_cards_text_and_returns_slices_and_unreadable_lines() -> None:
    slices, unreadable = context_module.read_slices(_card(
        "- S1：建表 ✓", "- [x] S2：写入", "- S3：读回（当前）", "  - [ ] 一步", "- S4 对账  ", "- S5：告警", "- s6:  归档 ",
        "- S7：导出（完成）  ", "- S8：对账（当前）✓"))

    # (id, title, done, current, line on the card, label as --map shows it)
    assert [(item.id, item.title, item.done, item.current, item.line, item.label) for item in slices] == [
        ("S1", "建表 ✓", True, False, 11, "S1：建表 ✓"), ("S2", "写入", True, False, 12, "S2：写入"),
        ("S3", "读回", False, True, 13, "S3：读回"), ("S5", "告警", False, False, 16, "S5：告警"),
        ("S6", "归档", False, False, 17, "S6:  归档"),
        ("S8", "对账", True, True, 19, "S8：对账")]                         # a ✓ counts wherever it is in the title
    # neither is a slice that is not done; the spaces that ended the line are not part of what is quoted
    assert unreadable == [(15, "- S4 对账"), (18, "- S7：导出（完成）")]


def test_the_card_template_is_read_without_unreadable_lines() -> None:
    """The template's example and the reader must not drift apart."""
    template = Path(__file__).resolve().parents[1] / "skills" / "dev-circuit-ultra" / "templates" / "spec.md"

    slices, unreadable = context_module.read_slices(template.read_text(encoding="utf-8"))

    assert [(item.id, item.done, item.current) for item in slices] == [
        ("S1", True, False), ("S2", False, True), ("S3", False, False)]
    assert unreadable == []


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
    assert "要原文和例子" not in out                            # the card's capability list is only the fallback


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

    # What follows the · is about the framework: a capability named there is not one the card works on.
    write(root, "specs/add-export/spec.md", CARD.replace("框架：不变", "框架：已改（SYNC 的边界）"))
    code, out = run(capsys, "--feature", "add-export", "--root", str(root))
    assert code == 0 and "- DEMO-1：导出当前一条记录。" in out and "SYNC-1" not in out


@pytest.mark.parametrize("line", [
    "**能力**：DEMO（已有）· **框架**：不变", "**能力：** DEMO（已有）· 框架：不变", "- 能力：DEMO（已有）", "* **能力**: DEMO",
    "1. 能力：DEMO（已有）", "- 能力 ：DEMO（已有）· 框架：不变", "| 能力 | DEMO（已有） |",
])
def test_the_capability_line_is_read_in_the_shapes_the_trunk_line_is(tmp_path: Path, capsys, line: str) -> None:
    """Only a bare `能力：…` was read; bold or a bullet in front and the promised list came out empty."""
    root = project(tmp_path)
    write(root, "specs/add-export/spec.md", CARD.replace("能力：DEMO（已有）· 框架：不变", line))

    code, out = run(capsys, "--feature", "add-export", "--root", str(root))

    assert code == 0
    assert "- DEMO-1：导出当前一条记录。" in out and "SYNC-1" not in out
    assert "没有清单可列" not in out


NO_LIST = "所以没有清单可列。规范写法：`能力：<代号>（已有 / 新建）`；代号见 devcircuit context --map"


@pytest.mark.parametrize("line, said", [
    ("能力：DEMX（已有）· 框架：不变", "卡的“能力：”一行写的是 DEMX，docs/requirements/ 里没有对应的能力规格，" + NO_LIST),
    ("能力：导出（已有）· 框架：不变", "没从卡里读到“能力：”一行的代号，" + NO_LIST),
    ("涉及的能力是 DEMO。", "没从卡里读到“能力：”一行的代号，" + NO_LIST),
])
def test_a_card_that_names_no_capability_spec_is_told_so(tmp_path: Path, capsys, line: str, said: str) -> None:
    """The fallback printed "下面按卡里的“能力：”列出要求清单" and then nothing, exit 0."""
    root = project(tmp_path)
    write(root, "specs/add-export/spec.md", CARD.replace("能力：DEMO（已有）· 框架：不变", line))

    code, out = run(capsys, "--feature", "add-export", "--root", str(root))

    assert code == 0 and "没有可比的基线" in out
    assert said in out.split("== 要求 ==")[1].splitlines()
    assert "DEMO-1" not in out


@pytest.mark.parametrize("named, said", [
    ("DEMO", "- DEMO-1：导出当前一条记录。"),
    ("DEMX", "卡的“能力：”一行写的是 DEMX，docs/requirements/ 里没有对应的能力规格，" + NO_LIST),
])
def test_a_branch_that_touched_no_requirement_lists_the_cards_capabilities_or_says_it_cannot(
        tmp_path: Path, capsys, named: str, said: str) -> None:
    _trunk_repo(tmp_path, "main")
    git(tmp_path, "switch", "-q", "-c", "feat/add-export")
    write(tmp_path, "specs/add-export/spec.md", CARD.replace("DEMO", named))

    code, out = run(capsys, "--feature", "add-export", "--root", str(tmp_path))

    assert code == 0 and "这个分支相对基线还没有改要求" in out
    assert said in out.splitlines()


def test_feature_needs_its_card(tmp_path: Path, capsys) -> None:
    root = project(tmp_path)

    assert cli.main(["context", "--feature", "absent", "--root", str(root)]) == 2
    assert "specs/absent/spec.md" in capsys.readouterr().err


def test_output_is_capped_and_says_so(tmp_path: Path, capsys, monkeypatch) -> None:
    root = project(tmp_path)
    write(root, "docs/requirements/demo.md", "# 导出能力\n代号：DEMO\n\n" + "".join(
        f"- DEMO-{number}：{'很长的要求' * 20}\n  - 例：{'很长的例子' * 20}\n" for number in range(1, 41)))
    ids = ",".join(f"DEMO-{number}" for number in range(1, 41))
    monkeypatch.chdir(root)  # not --root: the note repeats it, and the length of this machine's temp path is not the point

    code, out = run(capsys, "--ids", ids, "--max-chars", "800")

    assert code == 0
    assert len(out) < 1200
    assert "截断" in out and "--ids" in out


ENTRY = re.compile(r"^docs/requirements/data\.md:\d+\n- (DATA-\d+)：", re.MULTILINE)


def _big_feature(root: Path, count: int = 100) -> list[str]:
    """A feature whose code cites `count` requirements of about 250 characters each: twice the default limit."""
    project(root)
    write(root, "docs/requirements/data.md", "# 数据\n代号：DATA\n\n" + "".join(
        f"- DATA-{number}：{'很长的要求' * 20}\n  - 例：{'很长的例子' * 20}\n" for number in range(1, count + 1)))
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "switch", "-q", "-c", "feat/big")
    write(root, "specs/big/spec.md", CARD.replace("add-export", "big").replace("DEMO", "DATA"))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "design(big)")
    write(root, "src/big.py", "".join(f"# DATA-{number}\n" for number in range(1, count + 1)))
    return [f"DATA-{number}" for number in range(1, count + 1)]


def _follow_ups(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("devcircuit ")]


def _run_printed(command: str, capsys) -> tuple[int, str]:
    """Run a command exactly as the tool printed it."""
    argv = shlex.split(command)
    assert argv[0] == "devcircuit"
    code = cli.main(argv[1:])
    return code, capsys.readouterr().out


@pytest.mark.parametrize("mode, where", [
    ("--feature", "inside"), ("--review", "inside"), ("--ids", "inside"),
    ("--feature", "elsewhere"), ("--review", "elsewhere with a base"), ("--ids", "elsewhere"),
])
def test_every_follow_up_command_runs_as_printed_and_together_they_name_all_that_was_cut(
        tmp_path: Path, capsys, monkeypatch, mode: str, where: str) -> None:
    """The note named the first 10 IDs and then `…`: run as printed it answered `找不到：DATA-82…`, the IDs
    after the tenth were named nowhere, and a call made with --root got commands for the current directory."""
    root = tmp_path / "项目"
    wanted = _big_feature(root)
    elsewhere = tmp_path / "别处"
    elsewhere.mkdir()
    monkeypatch.chdir(root if where == "inside" else elsewhere)
    args = ["--ids", ",".join(wanted), "--max-chars", "800"] if mode == "--ids" else [mode, "big"]
    carried = {"inside": [], "elsewhere": ["--root", str(root)],
               "elsewhere with a base": ["--base", "main", "--root", "../项目"]}[where]

    code, out = run(capsys, *args, *carried)
    seen = ENTRY.findall(out)
    commands = _follow_ups(out)

    assert code == 0 and "截断" in out and 0 < len(seen) < len(wanted)
    assert len(commands) >= 2                                  # more was cut than one default limit holds
    answers = []
    for command in commands:
        assert "…" not in command and "<" not in command
        assert "\\" not in command                             # a Windows root goes out with forward slashes
        if where == "inside":
            assert re.fullmatch(r"devcircuit context --ids DATA-\d+(,DATA-\d+)*", command)
        if where == "elsewhere with a base":
            assert command.endswith(' --base "main" --root "../项目"')
        code, text = _run_printed(command, capsys)
        assert code == 0 and "找不到" not in text and "截断" not in text
        batch = ENTRY.findall(text)
        assert batch and not set(batch) & set(seen)            # nothing twice
        seen += batch
        answers.append(text)
    assert sorted(seen) == sorted(wanted)                      # and nothing missing
    for answer, following in zip(answers, answers[1:]):        # and no more commands than the default limit needs:
        held = len(answer.rstrip("\n")) + 2                    # each one could not have taken the requirement after it
        assert held + len(following.split("\n\n")[0].rstrip("\n")) + 2 > context_module.DEFAULT_MAX_CHARS


def test_the_truncation_note_costs_a_few_characters_per_requirement(tmp_path: Path, capsys, monkeypatch) -> None:
    """The note is not counted against --max-chars, so it must stay a list of IDs: no titles, no text."""
    _big_feature(tmp_path)
    monkeypatch.chdir(tmp_path)

    _, out = run(capsys, "--feature", "big")
    note = out[out.index("（截断"):out.index("== 相关测试 ==")]
    commands = _follow_ups(note)
    left_out = sum(command.count("DATA-") for command in commands)

    assert f"还有 {left_out} 条" in note and left_out > 40
    assert len(note) < 100 + 12 * left_out + 30 * len(commands)


@pytest.mark.parametrize("mode", ["--feature", "--ids"])
def test_the_truncation_note_is_not_counted_against_the_limit(
        tmp_path: Path, capsys, monkeypatch, mode: str) -> None:
    """--max-chars limits the requirement text. The note grows with what was cut; counted in, a longer
    list of what was left out would show fewer requirements."""
    shown = []
    for count in (60, 200):
        root = tmp_path / str(count)
        ids = _big_feature(root, count)
        monkeypatch.chdir(root)
        _, out = run(capsys, *(["--ids", ",".join(ids), "--max-chars", "3000"] if mode == "--ids" else [mode, "big"]))
        assert f"还有 {count - len(ENTRY.findall(out))} 条没列出" in out
        shown.append(ENTRY.findall(out))

    assert shown[0] == shown[1] and len(shown[0]) > 5


def test_a_requirement_longer_than_the_limit_gets_a_command_to_itself(tmp_path: Path, capsys, monkeypatch) -> None:
    root = project(tmp_path)
    write(root, "docs/requirements/data.md", "# 数据\n代号：DATA\n\n" + "".join(
        f"- DATA-{number}：{'很长的要求' * (2600 if number == 3 else 20)}\n" for number in range(1, 6)))
    monkeypatch.chdir(root)

    code, out = run(capsys, "--ids", "DATA-1,DATA-2,DATA-3,DATA-4,DATA-5", "--max-chars", "200")

    assert code == 0
    assert _follow_ups(out) == ["devcircuit context --ids DATA-2", "devcircuit context --ids DATA-3",
                                "devcircuit context --ids DATA-4,DATA-5"]
    for command in _follow_ups(out):
        code, text = _run_printed(command, capsys)
        assert code == 0 and "截断" not in text


def test_follow_up_commands_carry_the_root_and_base_of_the_call_quoted() -> None:
    assert context_module.carried_flags(".", None) == ""
    assert context_module.carried_flags("../x y/项目", "main") == ' --base "main" --root "../x y/项目"'
    # $ and ` are read inside double quotes by bash and PowerShell; single quotes keep them literal there.
    assert context_module.carried_flags("a$b `c`", None) == " --root 'a$b `c`'"
    assert context_module.carried_flags("a$b", None) == " --root 'a$b'"       # either of them is enough
    assert context_module.carried_flags("a`b", None) == " --root 'a`b'"
    assert shlex.split(context_module.carried_flags('x"y', None)) == ["--root", 'x"y']
    # A backslash stays in a root on POSIX and in whatever --base was typed: before the closing " it would escape it.
    assert shlex.split(context_module.carried_flags(".", "x\\")) == ["--base", "x\\"]


@pytest.mark.parametrize("situation", ["outside git", "no requirement touched", "some left out"])
def test_the_other_commands_an_answer_prints_reach_the_project_from_elsewhere(
        tmp_path: Path, capsys, monkeypatch, situation: str) -> None:
    """`要原文和例子：` and `== 省略 ==` named commands without the --root of the call: run as printed from
    another directory they looked there, and answered 找不到."""
    root = project(tmp_path / "项目")
    if situation != "outside git":
        _trunk_repo(root, "main")
        git(root, "switch", "-q", "-c", "feat/add-export")
    write(root, "specs/add-export/spec.md", CARD)
    if situation == "some left out":
        write(root, "src/export.py", "# DEMO-1\n")             # cites one of DEMO's two requirements
    elsewhere = tmp_path / "别处"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    base = [] if situation == "outside git" else ["--base", "main"]
    carried = (' --base "main"' if base else "") + ' --root "../项目"'

    code, out = run(capsys, "--feature", "add-export", *base, "--root", "../项目")
    assert code == 0
    if situation == "some left out":                           # the list is one command further on
        line = "DEMO 另有 1 条没列出：devcircuit context --capability DEMO" + carried
        assert line in out.splitlines()
        code, out = _run_printed(line.split("：", 1)[1], capsys)
        assert code == 0 and "- DEMO-3：导出后弹出提示。" in out
    line = "要原文和例子：devcircuit context --ids DEMO-1,DEMO-3" + carried
    assert line in out.splitlines()
    code, text = _run_printed(line.split("：", 1)[1], capsys)
    assert code == 0 and "找不到" not in text and "例：导出完成时看到提示。" in text


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


def _in_progress_line(out: str) -> str:
    return next(line for line in out.splitlines() if line.startswith("在研功能"))


def test_map_says_it_lists_this_worktree_only_and_names_its_branch(tmp_path: Path, capsys) -> None:
    """"在研功能" read as the whole project's features in progress; it is the cards in this worktree's specs/."""
    first = tmp_path / "主检出"
    _feature_branch(first)
    second = tmp_path / "第二棵 工作树"
    git(first, "worktree", "add", "-q", "-b", "feat/add-import", str(second), "main")
    write(second, "specs/add-import/spec.md", CARD.replace("add-export", "add-import"))

    code, out = run(capsys, "--map", "--root", str(first))
    assert code == 0
    assert _in_progress_line(out) == ("在研功能（只列本工作树的 specs/，当前分支 feat/add-export；"
                                      "上下文：devcircuit context --feature <名>）")
    assert "specs/add-export/spec.md" in out and "add-import" not in out

    code, out = run(capsys, "--map", "--root", str(second))
    assert code == 0
    assert "只列本工作树的 specs/，当前分支 feat/add-import；" in _in_progress_line(out)
    assert "specs/add-import/spec.md" in out and "add-export" not in out


def test_map_on_a_detached_head_names_the_commit(tmp_path: Path, capsys) -> None:
    _feature_branch(tmp_path)
    git(tmp_path, "checkout", "-q", "--detach")
    head = git(tmp_path, "rev-parse", "--short=7", "HEAD").strip()

    code, out = run(capsys, "--map", "--root", str(tmp_path))

    assert code == 0
    assert f"只列本工作树的 specs/，当前不在分支上：游离 HEAD {head}；" in _in_progress_line(out)


def test_map_in_a_repository_without_commits_names_the_branch_to_be(tmp_path: Path, capsys) -> None:
    project(tmp_path)
    git(tmp_path, "init", "-q", "-b", "main")

    code, out = run(capsys, "--map", "--root", str(tmp_path))

    assert code == 0
    assert "只列本工作树的 specs/，当前分支 main；" in _in_progress_line(out)


def test_outside_git_map_and_feature_read_exactly_as_before(tmp_path: Path, capsys, monkeypatch) -> None:
    root = project(tmp_path)
    write(root, "specs/add-export/spec.md", CARD)

    assert run(capsys, "--map", "--root", str(root)) == (0, (
        "能力（docs/requirements/；要求清单：devcircuit context --capability <代号>）\n"
        "- DEMO  demo.md  导出能力  2 条\n"
        "- SYNC  sync.md  同步能力  1 条\n"
        "在研功能（specs/；上下文：devcircuit context --feature <名>）\n"
        "- add-export  specs/add-export/spec.md  当前：S1：扩充导出\n"
        "框架摘要：docs/architecture.md#summary（2 行）\n"
        "其他文档\n"
        "- docs/design.md：本文回答导出界面怎么摆\n"
        "待做：specs/backlog.md 2 条\n"))
    monkeypatch.chdir(root)  # not --root: the command on the last line now repeats it
    assert run(capsys, "--feature", "add-export") == (0, (
        "== 卡：specs/add-export/spec.md ==\n" + CARD.strip() + "\n"
        "== 要求 ==\n"
        "没有可比的基线（不是 git 仓库、还没有提交，或找不到 main / master / 远端默认分支；"
        "可以用 --base 指定，或在 AGENTS.md 写一行主干）。下面按卡里的“能力：”列出要求清单。\n"
        "DEMO  导出能力（docs/requirements/demo.md，2 条）\n"
        "- DEMO-1：导出当前一条记录。\n"
        "- DEMO-3：导出后弹出提示。\n"
        "要原文和例子：devcircuit context --ids DEMO-1,DEMO-3\n"))


def _first_line(out: str) -> str:
    return out.splitlines()[0]


@pytest.mark.parametrize("mode", ["--feature", "--review"])
def test_feature_starts_with_the_branch_and_the_base(tmp_path: Path, capsys, mode: str) -> None:
    _feature_branch(tmp_path)
    fork = git(tmp_path, "rev-parse", "--short=7", "main").strip()

    code, out = run(capsys, mode, "add-export", "--root", str(tmp_path))

    assert code == 0
    assert _first_line(out) == f"分支：feat/add-export；基线：main（分叉点 {fork}）"
    assert out.splitlines()[1] == "== 卡：specs/add-export/spec.md =="
    assert "全部改动" not in out


@pytest.mark.parametrize("mode", ["--feature", "--review"])
def test_feature_on_another_branch_says_the_changes_are_that_branchs(tmp_path: Path, capsys, mode: str) -> None:
    """--feature compares the checked-out branch with the base; it never checked whose branch that is."""
    _feature_branch(tmp_path)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "feat(add-export)")
    git(tmp_path, "switch", "-q", "-c", "feat/add-import")
    fork = git(tmp_path, "rev-parse", "--short=7", "main").strip()

    code, out = run(capsys, mode, "add-export", "--root", str(tmp_path))

    assert code == 0
    assert _first_line(out) == (f"分支：feat/add-import，不是 feat/add-export；基线：main（分叉点 {fork}）。"
                                "下面是当前分支相对基线的全部改动，不一定都属于 add-export。")
    assert "新增：DEMO-2、DEMO-4" in out                       # the comparison itself is unchanged


def test_feature_on_the_trunk_says_only_uncommitted_changes_are_compared(tmp_path: Path, capsys) -> None:
    _trunk_repo(tmp_path, "main")
    write(tmp_path, "specs/add-export/spec.md", CARD)
    head = git(tmp_path, "rev-parse", "--short=7", "HEAD").strip()

    code, out = run(capsys, "--feature", "add-export", "--root", str(tmp_path))

    assert code == 0
    assert _first_line(out) == (f"分支：main，不是 feat/add-export；基线：main（分叉点 {head}）。"
                                "下面是当前分支相对基线的全部改动：当前分支就是基线，所以只有还没提交的部分。")


def test_feature_on_a_detached_head_names_the_commit(tmp_path: Path, capsys) -> None:
    _feature_branch(tmp_path)
    git(tmp_path, "checkout", "-q", "--detach")
    head = git(tmp_path, "rev-parse", "--short=7", "HEAD").strip()
    fork = git(tmp_path, "rev-parse", "--short=7", "main").strip()

    code, out = run(capsys, "--feature", "add-export", "--root", str(tmp_path))

    assert code == 0
    assert _first_line(out) == (f"分支：没有（游离 HEAD {head}）；基线：main（分叉点 {fork}）。"
                                "下面是当前提交相对基线的全部改动，不一定都属于 add-export。")


def test_feature_without_a_base_still_names_the_branch(tmp_path: Path, capsys) -> None:
    _trunk_repo(tmp_path, "develop")                          # no main, no master, no remote, no 主干 line
    git(tmp_path, "switch", "-q", "-c", "feat/add-export")
    write(tmp_path, "specs/add-export/spec.md", CARD)

    code, out = run(capsys, "--feature", "add-export", "--root", str(tmp_path))

    assert code == 0 and "没有可比的基线" in out
    assert _first_line(out) == "分支：feat/add-export；基线：没有可比的"


def test_a_capability_file_with_a_non_ascii_name_is_compared_too(tmp_path: Path) -> None:
    # git quotes non-ASCII paths by default, so "docs/requirements/订单.md" came back escaped, failed the
    # suffix check, and the branch's new requirements were silently missing from context, close and ledger check.
    project(tmp_path)
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    git(tmp_path, "config", "core.quotepath", "true")        # git's default, whatever this machine's config says
    git(tmp_path, "switch", "-q", "-c", "feat/orders")
    write(tmp_path, "docs/requirements/订单.md", "# 订单\n代号：ORDER\n\n- ORDER-1：下单。\n  - 例：下单成功。\n")

    base = context_module.merge_base(tmp_path, None)
    added, _, _ = context_module.requirement_changes(tmp_path, base[1])

    assert list(added) == ["ORDER-1"]
