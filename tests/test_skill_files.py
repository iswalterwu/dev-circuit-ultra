"""The skill's own files stay consistent with what the skill text tells the agent to read."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "dev-circuit-ultra"


def read(relative: str) -> str:
    return (SKILL / relative).read_text(encoding="utf-8")


def test_every_file_the_skill_names_exists():
    skill = read("SKILL.md")
    for name in ("setup.md", "framework.md", "reviewer.md"):
        assert f"`{name}`" in skill and (SKILL / name).is_file()

    text = skill + "".join(read(name) for name in (
        "setup.md", "framework.md", "reviewer.md", "templates/AGENTS.md"))
    named = set(re.findall(r"templates/[\w./-]+\.md", text))

    assert named
    assert sorted(name for name in named if not (SKILL / name).is_file()) == []


def test_every_request_is_classified_before_design():
    skill = read("SKILL.md")
    for category in ("在研功能的续做或修正", "已有能力的变化", "新能力", "bug"):
        assert category in skill
    assert "衔接四问" in skill and "devcircuit context --map" in skill
    assert "衔接四问" in read("framework.md")


def test_design_waits_for_the_users_go_ahead():
    # Both design modes stop after the summary; nothing is written before the user settles it.
    for name in ("SKILL.md", "framework.md"):
        text = read(name)
        assert "结束本轮回复" in text
        assert "之前不写文件、不改代码" in text


def test_a_reply_that_answers_or_adds_is_not_the_go_ahead():
    # A clarification ending with "其他按你的建议" was read as "定了" in 3 of 9 validation runs.
    # The stop point says such a reply is not the go-ahead; framework design uses the same rule.
    stop = next(line for line in read("SKILL.md").splitlines() if "**停止点**" in line)
    assert "其他按你的建议" in stop and "不算定了" in stop and "定了吗" in stop
    assert "SKILL.md ③的停止点" in read("framework.md")


def test_review_runs_once_per_feature_with_one_fix_round():
    skill = read("SKILL.md")
    reviewer = read("reviewer.md")

    assert "请用户验收前审一次" in skill
    assert "修一轮" in skill and "复查一次" in skill
    assert "200 行" in skill and "200 行" in reviewer
    assert "devcircuit context --review" in skill and "devcircuit context --review" in reviewer
    assert "先动手试" in reviewer
    assert "reviewer.json" not in skill + reviewer
    assert "model:" not in reviewer


def test_ledger_is_write_only_for_the_agent():
    skill = read("SKILL.md")
    assert "只写不读" in skill
    for command in ("devcircuit ledger add", "devcircuit ledger check", "devcircuit close"):
        assert command in skill
    assert "archivist" not in skill
    assert "--kind framework" in read("framework.md")


def test_delivery_report_has_five_parts():
    skill = read("SKILL.md")
    for part in ("做了什么：", "怎么验收：", "审核：", "潜在问题：", "下一步建议："):
        assert part in skill


def test_framework_structure_is_written_once():
    # Structure goes straight into docs/architecture.md; no feature design doc waits to be merged.
    assert not (SKILL / "templates" / "design.md").exists()
    texts = [read(name) for name in ("SKILL.md", "framework.md", "reviewer.md", "setup.md")]
    texts += [path.read_text(encoding="utf-8") for path in (SKILL / "templates").rglob("*.md")]
    assert [text for text in texts if "design.md" in text] == []
    framework = read("framework.md")
    assert "docs/architecture.md" in framework
    assert '<a id="summary"></a>' in framework and "60 行" in framework


def test_tests_carry_the_proof():
    # The requirement ID in a test is the proof. The template asks for no test paths, which drifted
    # from the real tests, and no link to another document, which agents filled by inventing one.
    template = read("templates/requirements.md")
    assert "<测试文件>" not in template and "](<路径>)" not in template
    assert "证明：演示" in template
    assert "能力规格里不写测试路径" in read("SKILL.md")


def test_requirements_template_asks_for_failure_behaviour():
    template = read("templates/requirements.md")
    assert "出错时的要求" in template and "无失败路径" in template


def test_card_names_capability_and_framework():
    card = read("templates/spec.md")
    assert "能力：" in card and "框架：" in card
    assert "80 行" in card


def test_agents_template_routes_through_context():
    agents = read("templates/AGENTS.md")
    assert "devcircuit context --feature" in agents
    assert "feat/<feature>" in agents
    assert "审核模型" in agents


def test_scaffold_ignores_caches_and_does_not_hand_register_docs():
    assert "__pycache__/" in read("templates/project/.gitignore")
    docs_map = read("templates/project/docs/README.md")
    requirements_map = read("templates/project/docs/requirements/README.md")
    assert "](architecture.md)" not in docs_map
    assert "框架设计" in docs_map
    for text in (docs_map, requirements_map):
        assert "devcircuit context --map" in text
        assert "|---|" not in text


def test_feature_names_follow_one_rule():
    # Card folder, branch and ledger records share the name, so the skill states the rule once.
    assert "功能名只用字母、数字、点、下划线和连字符" in read("SKILL.md")


def test_the_reviewer_gets_this_skills_reviewer_file():
    # A re-check given only "reviewer.md" read an older installed copy during validation.
    assert "`reviewer.md` 的完整路径" in read("SKILL.md")


def test_compatibility_keeps_old_inputs_working_and_allows_readable_errors():
    # Validation runs kept tracebacks "to stay consistent with export" in 9 of 9 runs; turning a crash
    # into a readable error does not break compatibility, for the designer and the reviewer alike.
    skill = read("SKILL.md")
    assert "以前能成功的输入照样成功" in skill
    assert "把崩溃改成可读错误不算破坏兼容" in skill
    assert "不算破坏兼容" in read("reviewer.md")
