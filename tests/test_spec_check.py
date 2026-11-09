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


def test_bom_in_requirements_and_references(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "\ufeff代号：DEMO\n- DEMO-1：one\n- DEMO-2：two\n")
    write(tmp_path, "tests/test_demo.py", "\ufeff# DEMO-1 DEMO-2\n")
    assert scan(tmp_path) == []


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
        assert result.stderr.decode("utf-8").splitlines() == [
            "1 条要求：0 条有测试引用，0 条靠演示，1 条既没有测试也没有演示", "未被测试引用：DEMO-1"]


def test_dangling_ref(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n")
    write(tmp_path, "src/x.py", "# source\n# DEMO-99\n")
    findings = scan(tmp_path)
    assert [(f.rule, f.path, f.line) for f in findings] == [
        ("dangling-ref", "src/x.py", 2),
    ]


def test_cards_do_not_define_requirements(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "specs/add/spec.md", "## 规格变化\n- 新增 DEMO-2：two\n- 删除：随便写\n")
    write(tmp_path, "tests/t.py", "# DEMO-2\n")
    assert [(f.rule, f.path) for f in scan(tmp_path)] == [("dangling-ref", "tests/t.py")]


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
    assert main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "spec_check：通过（1 份能力规格，3 条要求）\n"
    header = "3 条要求：1 条有测试引用，1 条靠演示，1 条既没有测试也没有演示"
    assert main(["--root", str(tmp_path), "--report"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "spec_check：通过（1 份能力规格，3 条要求）", header, *expected]

    assert main(["--root", str(tmp_path), "--json", "--report"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == []
    assert output.err.splitlines() == [header, *expected]

    # A demonstrated requirement that also has a test counts once, as tested.
    more = write(tmp_path, "tests/test_more.py", "# DEMO-3\n")
    assert main(["--root", str(tmp_path), "--report"]) == 0
    assert "3 条要求：2 条有测试引用，0 条靠演示，1 条既没有测试也没有演示" in capsys.readouterr().out
    more.unlink()

    for name in ("test_demo.py", "demo_test.go", "demo.test.ts", "demo.spec.js",
                 "DemoTest.java", "DemoTests.cs", "DemoSpec.kt"):
        test_path = write(tmp_path, f"src/{name}", "// DEMO-2\n")
        assert report(tmp_path) == ["演示要求：DEMO-3"]
        test_path.unlink()

    write(tmp_path, "src/x.py", "# DEMO-99\n")
    assert main(["--root", str(tmp_path), "--report"]) == 1
    output = capsys.readouterr().out
    assert "[dangling-ref]" in output and "通过" not in output
    assert "未被测试引用：DEMO-2" in output
    assert main(["--root", str(tmp_path), "--json"]) == 1
    items = json.loads(capsys.readouterr().out)
    assert len(items) == 1
    assert set(items[0]) == {"rule", "path", "line", "message"}
    assert items[0]["rule"] == "dangling-ref"
    assert main(["--root", str(tmp_path / "absent")]) == 2
    assert main(["--invalid"]) == 2


def test_english_specs(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "Code: DEMO\n- DEMO-1: one\n- DEMO-2: two\n")
    write(tmp_path, "tests/test_demo.py", "def test_demo():\n    assert 'DEMO-1' and 'DEMO-2'\n")

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
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in lines[:len(spec_check.RULES)]] == list(spec_check.RULES)
    assert all(len(line.split(maxsplit=1)) == 2 for line in lines[:len(spec_check.RULES)])
    assert lines[-1].startswith("范围：")
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


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True)


def test_code_before_design_on_a_feature_branch(tmp_path):
    # On feat/<name>, code may change only after the card is committed: the requirement text and the card are
    # drafted before the user settles the design, and committed once they do.
    write(tmp_path, "specs/backlog.md", "# 待做池\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    write(tmp_path, "src/app.py", "print(1)\n")
    assert scan(tmp_path) == []

    _git(tmp_path, "switch", "-q", "-c", "feat/export")
    findings = scan(tmp_path)
    assert [(finding.rule, finding.path) for finding in findings] == [
        ("code-before-design", "specs/export/spec.md")]
    assert "src/app.py" in findings[0].message

    write(tmp_path, "specs/export/spec.md", "# export\n")
    assert [finding.rule for finding in scan(tmp_path)] == ["code-before-design"]   # a draft is not settled
    _git(tmp_path, "add", "specs")
    _git(tmp_path, "commit", "-q", "-m", "design(export)")
    assert scan(tmp_path) == []


def test_code_before_design_needs_a_dev_circuit_git_project(tmp_path):
    write(tmp_path, "src/app.py", "print(1)\n")
    assert scan(tmp_path) == []                          # not a git repository
    _git(tmp_path, "init", "-q", "-b", "feat/export")
    assert scan(tmp_path) == []                          # no specs/: not a dev-circuit-ultra project
    write(tmp_path, "specs/backlog.md", "# 待做池\n")
    assert [finding.rule for finding in scan(tmp_path)] == ["code-before-design"]
    assert scan(tmp_path, ignored_rules=["code-before-design"]) == []
    assert scan(tmp_path, ignores=["src"]) == []         # ignored paths do not count as code changes


def test_code_before_design_explains_a_branch_name_it_cannot_map(tmp_path):
    write(tmp_path, "specs/backlog.md", "# 待做池\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    _git(tmp_path, "switch", "-q", "-c", "feat/ui/login")
    write(tmp_path, "src/app.py", "print(1)\n")

    findings = scan(tmp_path)
    assert [finding.rule for finding in findings] == ["code-before-design"]
    assert "feat/ui/login" in findings[0].message and "功能名" in findings[0].message


def test_report_counts_legacy_ids_cited_with_their_code(tmp_path, capsys):
    write(tmp_path, "docs/requirements/dock.md", """代号：DOCK
- DOCK-1：new
- AC-001-1：old, tested
- AC-001-2：old, untested
- AC-001-3：old, shown
  - 证明：演示
""")
    write(tmp_path, "tests/test_dock.py", "# DOCK-1 DOCK:AC-001-1\n")

    assert main(["--root", str(tmp_path), "--report"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "spec_check：通过（1 份能力规格，4 条要求）",
        "4 条要求（含 3 条旧编号）：2 条有测试引用，1 条靠演示，1 条既没有测试也没有演示",
        "未被测试引用：DOCK:AC-001-2",
        "演示要求：DOCK:AC-001-3",
    ]


def test_the_commit_that_settles_the_design_is_not_blocked_by_other_work(tmp_path):
    # The pre-commit hook runs on the design commit itself: a staged card with no staged code passes,
    # whatever else sits in the working tree.
    write(tmp_path, "specs/backlog.md", "# 待做池\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    _git(tmp_path, "switch", "-q", "-c", "feat/export")
    write(tmp_path, "specs/export/spec.md", "# export\n")
    write(tmp_path, "scratch.py", "print(1)\n")
    _git(tmp_path, "add", "specs")
    assert scan(tmp_path) == []

    _git(tmp_path, "add", "scratch.py")
    assert [finding.rule for finding in scan(tmp_path)] == ["code-before-design"]
