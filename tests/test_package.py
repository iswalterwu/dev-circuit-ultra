import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL_NAMES = ("dev-circuit-ultra", "dev-circuit-archivist", "dev-circuit-ledger")


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


def test_pi_and_dsh_package_manifest():
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "dev-circuit-ultra"
    assert manifest["pi"]["skills"] == ["./skills"]
    assert manifest["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
    assert (ROOT / "index.js").is_file()
    assert (ROOT / "cordis.patch.yml").is_file()
    assert "skills" in manifest["files"]


def test_skill_frontmatter_is_store_compatible():
    for name in SKILL_NAMES:
        fields = _frontmatter(name)
        assert fields["name"] == name
        assert fields["description"]
        assert fields["whenToUse"]

    assert _frontmatter("dev-circuit-archivist")["disable-model-invocation"] == "true"
    assert _frontmatter("dev-circuit-ledger")["disable-model-invocation"] == "true"
    assert "disable-model-invocation" not in _frontmatter("dev-circuit-ultra")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for the DSH plugin smoke test")
def test_dsh_plugin_registers_three_skills():
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
    assert rows["dev-circuit-archivist"]["modelInvocable"] is False
    assert rows["dev-circuit-ledger"]["modelInvocable"] is False

