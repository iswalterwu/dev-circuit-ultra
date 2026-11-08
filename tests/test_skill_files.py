"""The skill's own files stay consistent with what the skill text tells the agent to read."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "dev-circuit-ultra"


def read(relative: str) -> str:
    return (SKILL / relative).read_text(encoding="utf-8")


def test_every_template_the_skill_names_exists():
    text = read("SKILL.md") + read("reviewer.md") + read("templates/AGENTS.md")
    named = set(re.findall(r"templates/[\w./-]+\.md", text))

    assert named
    assert sorted(name for name in named if not (SKILL / name).is_file()) == []


def test_review_runs_only_on_request():
    skill = read("SKILL.md")
    reviewer = read("reviewer.md")

    assert "只在用户要求时做" in skill
    assert "reviewer.json" not in skill + reviewer
    assert "model:" not in reviewer


def test_scaffold_ignores_caches_and_does_not_promise_architecture():
    assert "__pycache__/" in read("templates/project/.gitignore")
    docs_map = read("templates/project/docs/README.md")
    assert "](architecture.md)" not in docs_map
    assert "框架级" in docs_map
