"""The repo's own docs describe the flow SKILL.md runs, so a reader and an agent see the same steps."""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "README.zh-CN.md", "docs/dsh.md", "docs/ledger.md", "demo/README.md",
        "hooks/README.md", "docker/README.md")
RETIRED = ("reviewer.json", "archivist", "五步", "five-step", "Five steps", "five steps", "收尾合并",
           "快车道：修 + 测试", "fast lane: fix + test", "只读 reviewer", "read-only reviewer",
           "改能力规格或 `docs/architecture.md` 的草稿", "capability spec or `docs/architecture.md`")


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_docs_drop_the_retired_flow():
    for name in DOCS:
        assert [word for word in RETIRED if word in read(name)] == [], name


def test_package_descriptions_drop_the_retired_flow():
    """npm and pip show these one-liners before anyone opens the README."""
    pyproject = re.search(r'^description = "(.*)"$', read("pyproject.toml"), re.MULTILINE)
    descriptions = {"package.json": json.loads(read("package.json"))["description"],
                    "pyproject.toml": pyproject.group(1)}
    for name, text in descriptions.items():
        assert [word for word in RETIRED if word in text] == [], name


def test_every_asset_is_shown_by_a_doc():
    """assets/ ships in the npm package: a file no doc shows is stale weight."""
    docs = "".join(read(name) for name in DOCS)
    assert [path.name for path in sorted((ROOT / "assets").iterdir()) if path.name not in docs] == []


def test_banner_uses_readme_tagline():
    tagline = "Less context. Less ceremony. One feature at a time."
    banner = ET.fromstring(read("assets/banner.svg"))
    assert banner.get("aria-label") == f"Dev-circuit-ultra — {tagline}"
    assert tagline in [node.text for node in banner.findall("{http://www.w3.org/2000/svg}text")]
    assert tagline in read("README.md")
    assert tagline in json.loads(read("package.json"))["description"]


def test_readmes_link_xerj_badge_and_pinned_corpus():
    contributor = "https://hub.xerj.org/contributors/iswalterwu"
    corpus = "https://hub.xerj.org/corpus/iswalterwu--dev-circuit-ultra"
    badge = f"[![XERJ Corpus Hub contributor]({contributor}/badge.svg)]({contributor})"
    for name, snapshot_note in (("README.md", "pinned snapshot"),
                                ("README.zh-CN.md", "固定版本快照")):
        text = read(name)
        assert text.count(badge) == 1, name
        assert f"]({corpus})" in text, name
        assert snapshot_note in text, name


def test_hook_docs_do_not_promise_unbypassable_isolation():
    claims = ("the agent cannot reach the ledger", "Not through tool calls:",
              "agent 拿不到账本", "通过工具调用读不到", "agent 无法通过工具拿到账本")
    for name, caveat in (("README.md", "not an unbypassable security boundary"),
                         ("README.zh-CN.md", "不是不可绕过的安全边界"),
                         ("hooks/README.md", "不是不可绕过的安全边界"),
                         ("docs/ledger.md", "不是不可绕过的安全边界")):
        text = read(name)
        assert caveat in text, name
        assert not any(claim in text for claim in claims), name


def test_worktree_instructions_preserve_relative_path_targets():
    for name, heading, terms in (
        ("README.md", "**Does it work in a git worktree?**",
         ("relative paths", "absolute paths", "main working tree", "`deny`", "self-check")),
        ("README.zh-CN.md", "**能在 git worktree 里用吗？**",
         ("相对路径", "绝对路径", "主工作区", "`deny`", "拦截自检")),
    ):
        section = read(name).split(heading, 1)[1].split("\n**", 1)[0]
        assert all(term in section for term in terms), name


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
