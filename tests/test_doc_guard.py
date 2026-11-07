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

def test_ignore_glob_skips_paths(tmp_path: Path) -> None:
    write(tmp_path, "docs/legacy/notes.md", "已取代的内容\n")
    write(tmp_path, "vendor/lib/README.md", "decision log\n")
    write(tmp_path, "docs/current.md", "现行说明\n")

    assert [finding.path for finding in scan(tmp_path)] == [
        "docs/legacy/notes.md",
        "vendor/lib/README.md",
    ]
    assert [finding.path for finding in scan(tmp_path, ignores=["docs/legacy"])] == [
        "vendor/lib/README.md",
    ]
    assert [finding.path for finding in scan(tmp_path, ignores=["vendor"])] == [
        "docs/legacy/notes.md",
    ]
    assert scan(tmp_path, ignores=["docs/legacy", "vendor/lib"]) == []


def test_ignore_file_and_disable(tmp_path: Path) -> None:
    write(tmp_path, "docs/legacy/notes.md", "已取代的内容\n")
    write(tmp_path, ".dcuignore", "# comment\n\ndocs/legacy\n")

    assert scan(tmp_path) == []
    assert [f.path for f in scan(tmp_path, use_ignore_file=False)] == ["docs/legacy/notes.md"]
    assert [f.path for f in scan(tmp_path, ignore_file=tmp_path / "absent.txt")] == [
        "docs/legacy/notes.md",
    ]


def test_ignore_by_bare_filename(tmp_path: Path) -> None:
    write(tmp_path, "docs/CHANGELOG.md", "decision log\n")
    assert scan(tmp_path) != []
    assert scan(tmp_path, ignores=["CHANGELOG.md"]) == []


def test_ignore_rule(tmp_path: Path) -> None:
    write(tmp_path, "docs/a.md", "见 D-036\n")
    write(tmp_path, "docs/decisions/x.md", "x\n")

    assert [f.rule for f in scan(tmp_path)] == ["decision-id", "forbidden-path"]
    assert [f.rule for f in scan(tmp_path, ignored_rules=["decision-id"])] == ["forbidden-path"]
    assert scan(tmp_path, ignored_rules=["decision-id", "forbidden-path"]) == []


def test_inline_suppression(tmp_path: Path) -> None:
    write(
        tmp_path,
        "docs/a.md",
        "沿用旧字段（已取代 X）  <!-- doc-guard:ignore -->\n"
        "第二行 已取代\n"
        "<!-- doc-guard:off -->\n"
        "第三行 已取代\n"
        "<!-- doc-guard:on -->\n"
        "第四行 已取代\n",
    )
    assert [(finding.rule, finding.line) for finding in scan(tmp_path)] == [
        ("bookkeeping-phrase", 2),
        ("bookkeeping-phrase", 6),
    ]


def test_code_fences_are_not_document_claims(tmp_path: Path) -> None:
    write(tmp_path, "docs/a.md", "示例：\n```\ngit log --format=%H e8358c6\nD-036\n```\n")
    assert scan(tmp_path) == []


def test_list_rules_and_version(capsys) -> None:
    assert main(["--list-rules"]) == 0
    assert "forbidden-path" in capsys.readouterr().out
    assert main(["--version"]) == 0
    assert "doc_guard" in capsys.readouterr().out


def test_ignore_pattern_separators_and_case(tmp_path: Path) -> None:
    write(tmp_path, "docs/Vendor/notes.md", "decision log\n")

    assert scan(tmp_path, ignores=["docs\\Vendor"]) == []
    if os.name == "nt":
        assert scan(tmp_path, ignores=["docs/vendor"]) == []
    else:
        assert scan(tmp_path, ignores=["docs/vendor"]) != []


def test_explicit_ignore_file_must_exist(tmp_path: Path, capsys) -> None:
    write(tmp_path, "docs/a.md", "clean\n")

    assert main(["--root", str(tmp_path), "--ignore-file", str(tmp_path / "missing.txt")]) == 2
    assert "不存在" in capsys.readouterr().err


def test_include_scans_extra_docs(tmp_path: Path, capsys) -> None:
    write(tmp_path, "notes/scratch.md", "decision log\n")
    write(tmp_path, "app/README.md", "clean\n")

    assert scan(tmp_path) == []
    assert [finding.path for finding in scan(tmp_path, includes=["notes"])] == ["notes/scratch.md"]
    assert [finding.path for finding in scan(tmp_path, includes=["**/scratch.md"])] == [
        "notes/scratch.md",
    ]
    assert scan(tmp_path, includes=["notes"], ignores=["notes"]) == []
    assert main(["--root", str(tmp_path), "--include", "notes"]) == 1
    assert "[bookkeeping-phrase]" in capsys.readouterr().out
