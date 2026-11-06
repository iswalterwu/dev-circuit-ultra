from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_skill_asks_once_and_stores_reviewer_choice():
    text = (ROOT / "skills/dev-circuit-ultra/SKILL.md").read_text(encoding="utf-8")

    assert ".dev-circuit/reviewer.json" in text
    assert '{"mode": "same-model"}' in text
    assert '{"mode": "agent", "agent": "my-reviewer"}' in text
    assert '{"mode": "ask"}' in text
    assert "第一次进入项目、文件不存在时，先问一次" in text
    assert "不要静默换成别的 agent" in text
    assert "每个功能开始时问一次" in text


def test_reviewer_instructions_do_not_pin_a_model():
    text = (ROOT / "skills/dev-circuit-ultra/reviewer.md").read_text(encoding="utf-8")

    assert "SKILL §1.2" in text
    assert "model:" not in text
    assert "同模型 / 指定 agent / 每次再问" in text
