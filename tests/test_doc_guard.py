"""Behavior checks for the reusable documentation guard."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import doc_guard
from doc_guard import main, scan


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_clean_tree_has_no_findings(tmp_path: Path) -> None:
    write(tmp_path, "AGENTS.md", "Project entry\n")
    write(tmp_path, "docs/a.md", "See [details](b.md).\n")
    write(tmp_path, "docs/b.md", "Details\n")
    write(tmp_path, "specs/f/spec.md", "Current requirements\n")

    assert scan(tmp_path) == []


def test_forbidden_paths(tmp_path: Path) -> None:
    write(tmp_path, "docs/decisions/x.md", "D-036\n")
    write(tmp_path, "HANDOFF.md", "Handoff\n")
    write(tmp_path, "specs/f/plan.md", "Plan\n")
    write(tmp_path, "specs/f/history/r1.md", "History\n")
    write(tmp_path, "docs/x/history/a.md", "History\n")
    write(tmp_path, "specs/f/spec.md", "Current spec\n")

    findings = scan(tmp_path)
    assert len(findings) == 5
    assert {finding.rule for finding in findings} == {"forbidden-path"}
    assert {finding.path for finding in findings} == {
        "docs/decisions",
        "HANDOFF.md",
        "specs/f/plan.md",
        "specs/f/history",
        "docs/x/history",
    }
    assert all(finding.line == 0 for finding in findings)


def test_product_code_paths_not_forbidden(tmp_path: Path) -> None:
    write(tmp_path, "backend/workflow/state/x.json", "{}\n")
    write(tmp_path, "frontend/src/history/x.md", "Old content\n")

    assert scan(tmp_path) == []


def test_decision_ids_with_line_numbers(tmp_path: Path) -> None:
    write(tmp_path, "docs/a.md", "First line\n见 D-036\nDL-04 与 AC-001-2\n")

    findings = scan(tmp_path)
    assert len(findings) == 1
    assert (findings[0].rule, findings[0].path, findings[0].line) == (
        "decision-id", "docs/a.md", 2,
    )


def test_colors_numbers_uuids_not_hashes(tmp_path: Path) -> None:
    write(
        tmp_path,
        "docs/a.md",
        "#C98A8F #c98a8f 2026110 deadbeef "
        "e634f1ad-99a8-42ac-b642-cf7f5016b921\n",
    )

    assert scan(tmp_path) == []


def test_hashes_flagged(tmp_path: Path) -> None:
    write(
        tmp_path,
        "docs/a.md",
        "基线 e8358c6\n" + "a1" * 20 + "\n" + "b2" * 32 + "\n",
    )

    findings = scan(tmp_path)
    assert [(finding.rule, finding.line) for finding in findings] == [
        ("short-hash", 1),
        ("long-hash", 2),
        ("long-hash", 3),
    ]


def test_bookkeeping_phrases_flagged(tmp_path: Path) -> None:
    write(tmp_path, "docs/a.md", "## 轮次记录\n由 gpt via openai 完成\n")

    findings = scan(tmp_path)
    assert [(finding.rule, finding.line) for finding in findings] == [
        ("bookkeeping-phrase", 1),
        ("bookkeeping-phrase", 2),
    ]


def test_links(tmp_path: Path) -> None:
    write(tmp_path, "docs/b.md", "Target\n")
    write(
        tmp_path,
        "docs/a.md",
        "[missing](missing.md) [existing](b.md#sec) "
        "[web](https://example.com) [local](#local) "
        "[absolute](/missing-absolute.md) [drive](C:/missing-drive.md)\n"
        "```md\n[x](nope.md)\n```python\n[y](still-nope.md)\n```\n",
    )

    findings = scan(tmp_path)
    assert len(findings) == 1
    assert (findings[0].rule, findings[0].path, findings[0].line) == (
        "broken-link", "docs/a.md", 1,
    )
    assert doc_guard._is_absolute_target("C:/missing-drive.md")


def test_skipped_dirs(tmp_path: Path) -> None:
    write(tmp_path, "node_modules/p/README.md", "D-123\n")

    assert scan(tmp_path) == []


@pytest.mark.parametrize("args", [[], ["--json"]])
def test_cli_outputs_utf8_with_legacy_stdio_encoding(tmp_path, args):
    write(tmp_path, "docs/a.md", "见 D-036\n")
    result = subprocess.run(
        [sys.executable, doc_guard.__file__, "--root", str(tmp_path), *args],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0"},
    )
    assert result.returncode == 1
    output = result.stdout.decode("utf-8")
    assert "决策编号：D-036" in output
    if "--json" in args:
        assert json.loads(output)[0]["rule"] == "decision-id"


def test_cli(tmp_path: Path, capsys) -> None:
    clean = tmp_path / "clean"
    clean.mkdir()
    write(clean, "AGENTS.md", "Current rules\n")
    assert main(["--root", str(clean)]) == 0
    assert capsys.readouterr().out == ""

    bad = tmp_path / "bad"
    write(bad, "docs/a.md", "见 D-036\n")
    assert main(["--root", str(bad)]) == 1
    assert capsys.readouterr().out.startswith("docs/a.md:1: [decision-id]")

    assert main(["--root", str(bad), "--json"]) == 1
    items = json.loads(capsys.readouterr().out)
    assert len(items) == 1
    assert set(items[0]) == {"rule", "path", "line", "message"}
    assert items[0]["rule"] == "decision-id"

    assert main(["--root", str(tmp_path / "absent")]) == 2


def test_ledger_dir_and_old_design_phrases_flagged(tmp_path: Path) -> None:
    write(tmp_path, "ledger/entries/x.jsonl", "{}\n")
    write(
        tmp_path,
        "docs/a.md",
        "旧版本原为 A\n后来已取代 B\n放弃的备选 C\n",
    )

    findings = scan(tmp_path)
    assert {finding.rule for finding in findings} == {
        "forbidden-path",
        "bookkeeping-phrase",
    }
    assert any(finding.path == "ledger" for finding in findings)
    assert sum(finding.rule == "bookkeeping-phrase" for finding in findings) == 3
