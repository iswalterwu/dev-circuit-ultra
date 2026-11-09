"""The skill's own files stay consistent with what the skill text tells the agent to read."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "dev-circuit-ultra"


def read(relative: str) -> str:
    return (SKILL / relative).read_text(encoding="utf-8")


def test_every_file_the_skill_names_exists():
    skill = read("SKILL.md")
    for name in ("setup.md", "framework.md", "large.md", "reviewer.md"):
        assert f"`{name}`" in skill and (SKILL / name).is_file()

    text = skill + "".join(read(name) for name in (
        "setup.md", "framework.md", "large.md", "reviewer.md", "templates/AGENTS.md"))
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
    # Both design modes stop after the summary. Before the user settles it only drafts are written, so what
    # the user approves is the text that gets committed; nothing is committed and no code changes.
    for name in ("SKILL.md", "framework.md"):
        text = read(name)
        assert "结束本轮回复" in text
        assert "的草稿，不提交、不改代码" in text
        assert "之前不写文件" not in text


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


def test_big_work_is_split_and_key_features_get_more_review():
    # agent-dock: the user approved 370 lines "as recommended"; the independent design review found the gaps,
    # and most implementation fixes were failure paths, state boundaries and real contracts.
    skill, large, reviewer = read("SKILL.md"), read("large.md"), read("reviewer.md")
    assert "12 条" in skill and "3 份" in skill and "重点功能" in skill
    assert "拆分方案" in large
    for mode in ("要求审", "骨架审"):
        assert mode in large and mode in reviewer
    assert "构建者检查" in reviewer.split("## 要求审")[1]
    assert "重点：" in read("templates/spec.md")


def test_framework_changes_get_a_structure_review_by_default():
    framework, reviewer = read("framework.md"), read("reviewer.md")
    assert "结构审" in framework and "用户明说不审才跳过" in framework
    assert "用户要求才做" not in reviewer


def test_visual_changes_start_with_a_prototype():
    skill = read("SKILL.md")
    assert "视觉密集" in skill and "真实数据截图" in skill


def test_the_goal_puts_review_quality_before_cost():
    # Validation: cost about level with OpenSpec, review the main source of quality; the user chose quality.
    skill = read("SKILL.md")
    assert "质量优先" in skill and "成本低于 OpenSpec" not in skill


def test_drafts_have_a_way_back():
    # Drafts are not committed: rejecting the feature restores them, a design change edits them, and a
    # later session must not mistake an uncommitted card for a settled one.
    skill = read("SKILL.md")
    assert "还原改过的能力规格" in skill
    assert "改能力规格或 `docs/architecture.md` 的草稿" in skill
    assert "卡还没提交就是草稿" in skill


def test_each_review_mode_gets_inputs_it_can_use():
    # Draft reviews see nothing in `git diff <base>...HEAD`, and a structure review has no card yet.
    skill, reviewer, framework = read("SKILL.md"), read("reviewer.md"), read("framework.md")
    assert "同一个工作区" in skill
    assert "git diff <base> -- docs/requirements" in reviewer.split("## 要求审")[1]
    assert "骨架路径" in framework and "迁移与回滚" in framework
    assert "这个切片列出的要求编号" in reviewer.split("## 骨架审")[1]


def test_the_summary_limit_leaves_room_for_every_requirement_line():
    assert "其余部分不超过 25 行" in read("SKILL.md")


def test_feature_drafts_hold_only_specs_and_the_card():
    # 0.7 validation B-2 put a line of architecture detail into the design commit; the user chose to keep
    # feature drafts to specs and the card, with architecture detail committed alongside the code.
    skill = read("SKILL.md")
    assert "草稿只有能力规格和卡" in skill
    assert "实现时随代码提交" in skill
