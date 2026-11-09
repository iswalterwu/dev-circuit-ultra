"""The repo's own docs describe the flow SKILL.md runs, so a reader and an agent see the same steps."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "README.zh-CN.md", "docs/dsh.md", "docs/ledger.md", "demo/README.md",
        "hooks/README.md", "docker/README.md")
RETIRED = ("reviewer.json", "archivist", "五步", "five-step", "Five steps", "five steps", "收尾合并")


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_docs_drop_the_retired_flow():
    for name in DOCS:
        assert [word for word in RETIRED if word in read(name)] == [], name


def test_readmes_name_the_steps_and_commands_the_skill_uses():
    skill = read("skills/dev-circuit-ultra/SKILL.md")
    chinese = read("README.zh-CN.md")
    english = read("README.md")
    for step in ("识别", "框架设计", "功能设计", "审核", "交付"):
        assert step in skill and step in chinese, step
    for step in ("Classify", "Framework design", "Feature design", "Review", "Deliver"):
        assert step in english, step
    for command in ("devcircuit context", "devcircuit ledger add", "devcircuit ledger check", "devcircuit close"):
        assert command in skill and command in chinese and command in english, command
