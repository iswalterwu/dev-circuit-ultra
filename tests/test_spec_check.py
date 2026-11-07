"""Behavior checks for requirement IDs, in-flight changes and code references."""

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

import spec_check
from spec_check import main, report, scan


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_no_requirements_passes(tmp_path, monkeypatch):
    write(tmp_path, "AGENTS.md", "# Project\n")
    assert scan(tmp_path) == []
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0


def test_requirements_readme_skipped(tmp_path):
    write(tmp_path, "docs/requirements/README.md", "# Requirements\n")
    assert scan(tmp_path) == []


def test_header_rules(tmp_path):
    write(tmp_path, "docs/requirements/a.md", "# Missing header\n")
    write(tmp_path, "docs/requirements/b.md", "代号：DEMO\n- SYNC-1：wrong code\n")
    write(tmp_path, "docs/requirements/c.md", "代号:DEMO\n")
    assert Counter(f.rule for f in scan(tmp_path)) == {"bad-header": 3}


def test_dup_code_id(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n- DEMO-1: two\n")
    findings = scan(tmp_path)
    assert [(f.rule, f.line) for f in findings] == [("dup-id", 3)]


def test_ac_ids_scoped_per_file(tmp_path):
    write(tmp_path, "docs/requirements/a.md", "代号：AAA\n- AC-001-1：one\n- AC-001-1：two\n")
    write(tmp_path, "docs/requirements/b.md", "代号：BBB\n- AC-001-1：one\n")
    findings = scan(tmp_path)
    assert [(f.rule, f.path, f.line) for f in findings] == [
        ("dup-id", "docs/requirements/a.md", 3),
    ]


def test_card_targets(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "docs/requirements/b.md", "代号：BBB\n- AC-001-1：old\n")
    write(tmp_path, "specs/change/spec.md", """# Change
## 规格变化
- 修改 DEMO-9：missing
- 删除 BBB:AC-009-9
- 新增 DEMO-1：exists
- 新增 XYZ-1：unknown code
- 新增 BBB:AC-002-1：cannot add old-style IDs
- 修改 BBB:AC-001-1：valid old target
- 删除 DEMO-1
## 其他
- 修改 DEMO-99：outside section
""")
    findings = scan(tmp_path)
    assert Counter(f.rule for f in findings) == {
        "unknown-target": 3, "id-exists": 1, "unknown-code": 1,
    }
    assert next(f.message for f in findings if f.line == 3) == "目标编号不存在：DEMO-9"
    assert next(f.message for f in findings if f.line == 7) == "新增要求须使用代号-数字：BBB:AC-002-1"


def test_merged_changes_require_heading_update(tmp_path, capsys):
    requirements = write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n- DEMO-2：two\n")
    card = write(tmp_path, "specs/change/spec.md", """# Change
## 规格变化
- 新增 DEMO-3：three
- 修改 DEMO-1：updated
- 删除 DEMO-2
""")
    write(tmp_path, "tests/test_demo.py", "# DEMO-1 DEMO-3\n")
    assert scan(tmp_path) == []

    requirements.write_text("代号：DEMO\n- DEMO-1：updated\n- DEMO-3：three\n", encoding="utf-8")
    args = ["--root", str(tmp_path), "--json"]
    assert main(args) == 1
    findings = json.loads(capsys.readouterr().out)
    assert [(f["rule"], f["line"]) for f in findings] == [("id-exists", 3), ("unknown-target", 5)]
    hint = "（如果是本卡收尾已合并，把本节标题改为'## 规格变化（已合并）'）"
    assert all(f["message"].endswith(hint) for f in findings)

    card.write_text(card.read_text(encoding="utf-8").replace("## 规格变化", "## 规格变化（已合并）"),
                    encoding="utf-8")
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert card.exists()


def test_bom_in_requirements_and_card(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "\ufeff代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "specs/add/spec.md", "\ufeff## 规格变化\n- 新增 DEMO-2：two\n")
    write(tmp_path, "tests/test_demo.py", "\ufeff# DEMO-1 DEMO-2\n")
    assert scan(tmp_path) == []


def test_malformed_change_bullets_reported_only_in_active_section(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n")
    write(tmp_path, "specs/change/spec.md", """# Change
## 范围
- 做：导出
## 规格变化
- 新增：DEMO-1
- 修改 DEMO-one：bad ID
- 删除
- 新增 DEMO-2：valid
  - 例：嵌套说明

普通说明。
## 规格变化（已合并）
- 新增：DEMO-3
## 其他
- 不做：上传
""")
    assert [(f.rule, f.path, f.line) for f in scan(tmp_path)] == [
        ("bad-change", "specs/change/spec.md", 5),
        ("bad-change", "specs/change/spec.md", 6),
        ("bad-change", "specs/change/spec.md", 7),
    ]


@pytest.mark.parametrize("args", [[], ["--json"], ["--json", "--report"]])
def test_cli_outputs_utf8_with_legacy_stdio_encoding(tmp_path, args):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "tests/test_demo.py", "# DEMO-99\n")
    result = subprocess.run(
        [sys.executable, spec_check.__file__, "--root", str(tmp_path), *args],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0"},
    )
    assert result.returncode == 1
    output = result.stdout.decode("utf-8")
    assert "引用的编号不存在：DEMO-99" in output
    if "--json" in args:
        assert json.loads(output)[0]["rule"] == "dangling-ref"
    if "--report" in args:
        assert result.stderr.decode("utf-8").splitlines() == ["未被测试引用：DEMO-1"]


def test_conflicting_cards(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    for name in ("a", "b"):
        write(tmp_path, f"specs/{name}/spec.md", "## 规格变化\n- 修改 DEMO-1：changed\n")
    findings = scan(tmp_path)
    assert [(f.rule, f.path, f.line) for f in findings] == [
        ("conflict", "specs/b/spec.md", 2),
    ]


def test_dangling_ref(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n")
    write(tmp_path, "src/x.py", "# source\n# DEMO-99\n")
    findings = scan(tmp_path)
    assert [(f.rule, f.path, f.line) for f in findings] == [
        ("dangling-ref", "src/x.py", 2),
    ]


def test_inflight_added_id_is_defined(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "specs/add/spec.md", "## 规格变化\n- 新增 DEMO-2：two\n")
    write(tmp_path, "tests/t.py", "# DEMO-2\n")
    assert scan(tmp_path) == []


def test_no_false_positives(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n")
    write(tmp_path, "src/x.py", "# UTF-8 SHA-256 GPT-6 ISO-8601 "
          "e634f1ad-99a8-42ac-b642-cf7f5016b921 XDEMO-1 DEMO-1a\n")
    assert scan(tmp_path) == []


def test_ac_refs_in_code_ignored(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n")
    write(tmp_path, "src/x.py", "# AC-123-4\n")
    assert scan(tmp_path) == []


def test_skipped_dirs(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n")
    write(tmp_path, "node_modules/p/i.js", "// DEMO-99\n")
    assert scan(tmp_path) == []


def test_report_and_cli(tmp_path, capsys):
    write(tmp_path, "docs/requirements/demo.md", """代号：DEMO
- DEMO-1：one
  - 证明：tests/t.py
- DEMO-2：two
- DEMO-3：three
  - 证明：演示
""")
    write(tmp_path, "tests/t.py", "# DEMO-1\n")
    write(tmp_path, "src/demo.py", "# DEMO-2\n")
    expected = ["未被测试引用：DEMO-2", "演示要求：DEMO-3"]
    assert report(tmp_path) == expected
    assert main(["--root", str(tmp_path), "--report"]) == 0
    assert capsys.readouterr().out.splitlines() == expected

    assert main(["--root", str(tmp_path), "--json", "--report"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == []
    assert output.err.splitlines() == expected

    for name in ("test_demo.py", "demo_test.go", "demo.test.ts", "demo.spec.js",
                 "DemoTest.java", "DemoTests.cs", "DemoSpec.kt"):
        test_path = write(tmp_path, f"src/{name}", "// DEMO-2\n")
        assert report(tmp_path) == ["演示要求：DEMO-3"]
        test_path.unlink()

    write(tmp_path, "src/x.py", "# DEMO-99\n")
    assert main(["--root", str(tmp_path), "--report"]) == 1
    output = capsys.readouterr().out
    assert "[dangling-ref]" in output
    assert "未被测试引用：DEMO-2" in output
    assert main(["--root", str(tmp_path), "--json"]) == 1
    items = json.loads(capsys.readouterr().out)
    assert len(items) == 1
    assert set(items[0]) == {"rule", "path", "line", "message"}
    assert items[0]["rule"] == "dangling-ref"
    assert main(["--root", str(tmp_path / "absent")]) == 2
    assert main(["--invalid"]) == 2
def test_english_specs(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "Code: DEMO\n- DEMO-1: one\n")
    write(tmp_path, "specs/add/spec.md", "## Spec changes\n- add DEMO-2: two\n- modify DEMO-1: tweak\n")
    write(tmp_path, "tests/test_demo.py", "def test_demo():\n    assert 'DEMO-1' and 'DEMO-2'\n")

    assert scan(tmp_path) == []


def test_english_merged_heading_is_inactive(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "capability: DEMO\n- DEMO-1: one\n")
    write(tmp_path, "specs/change/spec.md", "## Specification changes (merged)\n- add DEMO-1: exists\n")

    assert scan(tmp_path) == []


def test_relaxed_definition_shapes(tmp_path):
    write(
        tmp_path,
        "docs/requirements/demo.md",
        "code: DEMO\n"
        "\n"
        "- DEMO-1：one\n"
        "* DEMO-2: two\n"
        "+ DEMO-3：three\n"
        "1. DEMO-4: four\n"
        "- **DEMO-5**：five\n"
        "| DEMO-6 | six |\n",
    )
    write(tmp_path, "tests/test_demo.py", "# DEMO-1 DEMO-2 DEMO-3 DEMO-4 DEMO-5 DEMO-6\n")

    assert scan(tmp_path) == []


def test_change_bullets_accept_other_markers(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(
        tmp_path,
        "specs/change/spec.md",
        "## 规格变化\n"
        "1. 修改 DEMO-1：x\n"
        "* 新增 DEMO-2：y\n"
        "- 删除 DEMO-9：missing\n",
    )
    write(tmp_path, "tests/test_demo.py", "# DEMO-2\n")

    assert [(f.rule, f.line) for f in scan(tmp_path)] == [("unknown-target", 4)]


def test_nested_bullets_are_notes_not_entries(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n")
    write(tmp_path, "specs/change/spec.md", "## 规格变化\n- 新增 DEMO-1：x\n  - 例：随便写\n")

    assert scan(tmp_path) == []


def test_ignore_paths_and_rules(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "vendor/lib/a.py", "# DEMO-9\n")

    assert [f.rule for f in scan(tmp_path)] == ["dangling-ref"]
    assert scan(tmp_path, ignores=["vendor"]) == []
    assert scan(tmp_path, ignored_rules=["dangling-ref"]) == []


def test_ignore_file_is_shared_with_doc_guard(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "vendor/lib/a.py", "# DEMO-9\n")
    write(tmp_path, ".dcuignore", "vendor\n")

    assert scan(tmp_path) == []


def test_list_rules_and_version(capsys):
    assert main(["--list-rules"]) == 0
    assert "dangling-ref" in capsys.readouterr().out
    assert main(["--version"]) == 0
    assert "spec_check" in capsys.readouterr().out


def test_ignore_pattern_separators(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "vendor/lib/a.py", "# DEMO-9\n")

    assert scan(tmp_path, ignores=["vendor\\lib"]) == []


def test_explicit_ignore_file_must_exist(tmp_path, capsys):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n")

    assert main(["--root", str(tmp_path), "--ignore-file", str(tmp_path / "missing.txt")]) == 2
    assert "不存在" in capsys.readouterr().err


def test_vendored_guard_examples_are_not_references(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "scripts/spec_check.py", '# example: - DEMO-9：x and DEMO:AC-001-1\n')
    write(tmp_path, "src/app.py", "# DEMO-8\n")

    assert [f.path for f in scan(tmp_path)] == ["src/app.py"]


def test_legacy_reference_must_exist(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- AC-001-1：old\n")
    write(tmp_path, "tests/test_a.py", "# DEMO:AC-001-1 and DEMO:AC-009-9\n")

    assert [(f.rule, f.message) for f in scan(tmp_path)] == [
        ("dangling-ref", "引用的编号不存在：DEMO:AC-009-9"),
    ]


def test_merged_hint_follows_the_card_language(tmp_path, capsys):
    write(tmp_path, "docs/requirements/demo.md", "Code: DEMO\n- DEMO-1: one\n")
    write(tmp_path, "specs/add/spec.md", "## Spec changes\n- add DEMO-1: merged already\n")

    assert main(["--root", str(tmp_path), "--json"]) == 1
    finding = json.loads(capsys.readouterr().out)[0]
    assert finding["rule"] == "id-exists"
    assert "Spec changes (merged)" in finding["message"]
    assert "规格变化" not in finding["message"]


def test_chinese_cards_keep_the_chinese_hint(tmp_path, capsys):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "specs/add/spec.md", "## 规格变化\n- 新增 DEMO-1：已合并\n")

    assert main(["--root", str(tmp_path), "--json"]) == 1
    finding = json.loads(capsys.readouterr().out)[0]
    assert "规格变化（已合并）" in finding["message"]
