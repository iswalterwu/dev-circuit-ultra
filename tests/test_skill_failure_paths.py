"""Failure behaviour is part of the design, the definition of done and the review.

Each test pins one place where the skill makes the agent write down, test, run
or probe what happens when an input or an output fails.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "dev-circuit-ultra"


def read(relative: str) -> str:
    return (SKILL / relative).read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    following = text.find("\n## ", start + len(heading))
    return text[start:following] if following != -1 else text[start:]


def test_card_design_requires_failure_behaviour():
    design = section(read("templates/spec.md"), "## 设计")

    assert "失败行为" in design and "必填" in design
    assert "写不进去" in design


def test_capability_spec_asks_for_a_failure_requirement():
    text = read("templates/requirements.md")

    assert "出错时" in text
    assert "无失败路径" in text


def test_skill_ties_failure_behaviour_to_compatibility_tests_and_closeout():
    text = read("SKILL.md")

    assert "必须有「失败行为」" in text
    assert "成功输出不变" in text
    assert "照文档实测" in text
    done = section(text, "## 6. 完成标准")
    assert "失败行为" in done and "实际跑过" in done


def test_reviewer_triggers_failures_and_reads_only_its_rules():
    text = read("reviewer.md")

    assert "先实际触发失败路径" in text
    assert "不读 SKILL.md" in text
    assert "行为承诺不是措辞" in text
    assert "覆盖到的已有命令就算相关" in text
    assert "失败路径：" in section(text, "## 输出")


def test_every_template_the_skill_names_exists():
    text = read("SKILL.md") + read("reviewer.md") + read("templates/AGENTS.md")
    named = set(re.findall(r"templates/[\w./-]+\.md", text))

    assert "templates/guide.md" in named
    assert sorted(name for name in named if not (SKILL / name).is_file()) == []


def test_scaffold_ignores_caches_and_does_not_promise_architecture():
    assert "__pycache__/" in read("templates/project/.gitignore")
    docs_map = read("templates/project/docs/README.md")
    assert "](architecture.md)" not in docs_map
    assert "框架级" in docs_map
