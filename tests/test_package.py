import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from devcircuit import scaffold


ROOT = Path(__file__).resolve().parents[1]
SKILL_NAMES = ("dev-circuit-ultra", "dev-circuit-ledger")
NPM = shutil.which("npm")


def _frontmatter(skill_name: str) -> dict[str, str]:
    text = (ROOT / "skills" / skill_name / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, raw, _ = text.split("---", 2)
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            fields[key] = value.strip().strip('"')
    return fields


def _found(relative: str, pattern: str) -> str:
    """The first group of `pattern` in a repo file; frontmatter-indented keys included."""
    text = (ROOT / relative).read_text(encoding="utf-8")
    return re.search(pattern, text, re.MULTILINE).group(1)


def test_one_release_version_everywhere():
    """Versions follow the git tag; only doc_guard and spec_check keep their own line (see CHANGELOG)."""
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    found = {
        "pyproject.toml": _found("pyproject.toml", r'^version = "(.*)"$'),
        "devcircuit.__version__": _found("tools/devcircuit/__init__.py", r'^__version__ = "(.*)"$'),
        "docs/dsh.md": _found("docs/dsh.md", r"--version (\S+)"),
        **{f"skills/{name}/SKILL.md": _found(f"skills/{name}/SKILL.md", r'^ +version: "(.*)"$')
           for name in SKILL_NAMES},
    }
    assert {name: value for name, value in found.items() if value != version} == {}
    assert f"\n## {version}\n" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_pi_and_dsh_package_manifest():
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "dev-circuit-ultra"
    assert manifest["pi"]["skills"] == ["./skills"]
    assert manifest["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
    assert (ROOT / "index.js").is_file()
    assert (ROOT / "cordis.patch.yml").is_file()
    assert "skills" in manifest["files"]


@pytest.mark.skipif(NPM is None, reason="npm is required to list what the npm package would hold")
def test_npm_package_holds_every_template_the_scaffold_reads(tmp_path: Path):
    """npm never packs a file named .gitignore; a template it leaves out stops `devcircuit init` half-way."""
    listing = subprocess.run(
        [NPM, "pack", "--dry-run", "--json"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
        env={**os.environ, "npm_config_cache": str(tmp_path / "npm-cache"), "npm_config_update_notifier": "false"})
    assert listing.returncode == 0, listing.stderr
    packed = {entry["path"] for entry in json.loads(listing.stdout)[0]["files"]}

    skill = "skills/dev-circuit-ultra"
    scaffolded = {f"{skill}/{source}" for source, _ in scaffold.PROJECT_FILES.values()}
    # The rest of templates/ as well: `ledger init` copies its folder as it is, and the skill text sends
    # agents to the others. Any name npm drops (.gitignore, .npmrc, …) shows up here before it ships.
    templates = {path.relative_to(ROOT).as_posix() for path in (ROOT / skill / "templates").rglob("*") if path.is_file()}
    assert f"{skill}/templates/ledger/schema.md" in templates  # the walk is looking at the right folder
    assert sorted((scaffolded | templates) - packed) == []


def test_the_archivist_is_retired():
    assert not (ROOT / "skills" / "dev-circuit-archivist").exists()


def test_skill_frontmatter_is_store_compatible():
    for name in SKILL_NAMES:
        fields = _frontmatter(name)
        assert fields["name"] == name
        assert fields["description"]
        assert fields["whenToUse"]

    assert _frontmatter("dev-circuit-ledger")["disable-model-invocation"] == "true"
    assert "disable-model-invocation" not in _frontmatter("dev-circuit-ultra")


def test_the_machines_git_ignore_and_attributes_files_stay_out_of_the_tests(tmp_path: Path):
    """Without core.excludesFile git still reads $XDG_CONFIG_HOME/git/ignore (or ~/.config/git/ignore): a pattern
    there, such as one for .claude/settings.local.json, would make a test pass here and fail on CI."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name in (".claude/settings.local.json", ".dev-circuit/guard.json", "scratch.tmp", "node_modules/x.js"):
        ignored = subprocess.run(["git", "-C", str(tmp_path), "check-ignore", "-q", "--no-index", name])
        assert ignored.returncode == 1, f"{name} is ignored by a git file of this machine"


@pytest.mark.skipif(not os.environ.get("CI"), reason="only CI promises to have every optional tool")
@pytest.mark.parametrize("tool", ["node", "npm", "pwsh", "sh"])
def test_ci_has_the_tools_the_optional_tests_need(tool: str):
    """The tests that need node, npm, pwsh or sh skip without them; on CI a missing tool has to fail, not skip quietly."""
    assert shutil.which(tool), f"{tool} is not on PATH, so the tests that need it were skipped"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for the DSH plugin smoke test")
def test_dsh_plugin_registers_both_skills():
    index = (ROOT / "index.js").as_uri()
    script = f"""
import {{ apply }} from {json.dumps(index)};
const registered = [];
apply({{ skills: {{ register(skill) {{ registered.push(skill); }} }} }});
console.log(JSON.stringify(registered.map(skill => ({{
  name: skill.name,
  hasContent: skill.content.length > 0,
  modelInvocable: skill.invocation?.modelInvocable !== false,
  hasResourceBase: skill.resourceBase?.kind === 'directory',
}}))));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr
    rows = {row["name"]: row for row in json.loads(result.stdout)}

    assert set(rows) == set(SKILL_NAMES)
    assert all(row["hasContent"] and row["hasResourceBase"] for row in rows.values())
    assert rows["dev-circuit-ultra"]["modelInvocable"] is True
    assert rows["dev-circuit-ledger"]["modelInvocable"] is False

