"""Behavior checks for requirement IDs, in-flight changes and code references."""

import json
from collections import Counter
from pathlib import Path

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
    assert Counter(f.rule for f in scan(tmp_path)) == {
        "unknown-target": 3, "id-exists": 1, "unknown-code": 1,
    }


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
    expected = ["未被测试引用：DEMO-2", "未被测试引用：DEMO-3", "演示要求：DEMO-3"]
    assert report(tmp_path) == expected
    assert main(["--root", str(tmp_path), "--report"]) == 0
    assert capsys.readouterr().out.splitlines() == expected

    assert main(["--root", str(tmp_path), "--json", "--report"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == []
    assert output.err.splitlines() == expected

    for name in ("test_demo.py", "demo_test.go", "demo.test.ts", "demo.spec.js",
                 "DemoTest.java", "DemoTests.cs", "DemoSpec.kt"):
        test_path = write(tmp_path, f"src/{name}", "// DEMO-3\n")
        assert report(tmp_path) == ["未被测试引用：DEMO-2", "演示要求：DEMO-3"]
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
