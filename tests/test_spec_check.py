"""Behavior checks for requirement IDs, in-flight changes and code references."""

import contextlib
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


@pytest.mark.parametrize("where", [".trees/wt", ".claude/worktrees/x"])
def test_a_linked_worktree_inside_the_project_is_checked_on_its_own(tmp_path, where, capsys):
    # A worktree kept inside the project folder holds another branch. Its code and tests were read as the main
    # tree's: that branch's references came out as dangling here, and its tests counted as coverage here.
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    tree = tmp_path / where
    _git(tmp_path, "worktree", "add", "-q", "-b", "export", str(tree))
    write(tree, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n- DEMO-2：two\n")
    write(tree, "tests/test_export.py", "# DEMO-1 DEMO-2\n")
    write(tree, "src/export.py", "# DEMO-9\n")

    assert scan(tmp_path) == []
    assert report(tmp_path) == ["未被测试引用：DEMO-1"]
    assert main(["--root", str(tmp_path), "--report"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "spec_check：通过（1 份能力规格，1 条要求）",
        "1 条要求：0 条有测试引用，0 条靠演示，1 条既没有测试也没有演示",
        "未被测试引用：DEMO-1"]

    # With the worktree as the root, its own files are checked like any project's.
    assert [(f.rule, f.path, f.message) for f in scan(tree)] == [
        ("dangling-ref", "src/export.py", "引用的编号不存在：DEMO-9")]
    assert report(tree) == []


def test_a_nested_repository_is_checked_on_its_own(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    nested = tmp_path / "vendor" / "tool"
    write(nested, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(nested, "tests/test_tool.py", "# DEMO-1 DEMO-9\n")
    _git(nested, "init", "-q", "-b", "main")

    assert scan(tmp_path) == []
    assert report(tmp_path) == ["未被测试引用：DEMO-1"]
    assert [(f.rule, f.path) for f in scan(nested)] == [("dangling-ref", "tests/test_tool.py")]

    # The same on a detached HEAD, where HEAD holds a commit instead of naming a branch.
    _git(nested, "add", "-A")
    _git(nested, "commit", "-q", "-m", "init")
    _git(nested, "checkout", "-q", "--detach")
    assert not (nested / ".git" / "HEAD").read_text(encoding="utf-8").startswith("ref:")
    assert scan(tmp_path) == []


def test_a_submodule_is_checked_on_its_own(tmp_path):
    # A submodule's .git is a file with a relative path (gitdir: ../../.git/modules/…), read from the submodule.
    library = tmp_path.parent / "library"
    write(library, "src/lib.py", "# DEMO-9\n")
    _git(library, "init", "-q", "-b", "main")
    _git(library, "add", "-A")
    _git(library, "commit", "-q", "-m", "init")
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(library), "libs/library")
    pointer = (tmp_path / "libs" / "library" / ".git").read_text(encoding="utf-8")
    assert pointer.startswith("gitdir: ../")

    assert (tmp_path / "libs" / "library" / "src" / "lib.py").is_file()
    assert scan(tmp_path) == []


def _git_dir(folder: Path, head: bytes | None = b"ref: refs/heads/main\n", objects: bool = True,
             refs: bool = True) -> None:
    """Write by hand what git asks of a git directory, so a test can leave one part out or get it wrong."""
    folder.mkdir(parents=True, exist_ok=True)
    if head is not None:
        (folder / "HEAD").write_bytes(head)
    if objects:
        (folder / "objects").mkdir()
    if refs:
        (folder / "refs").mkdir()


# Hand-written .git that git takes for a repository. Each made-up one further down is one step away from one of
# these, so it is that step that makes it made up.
_POINTERS_GIT_ACCEPTS = {                                  # a .git file beside the git directory "x" it names
    "pointer": b"gitdir: x\n",
    "pointer-ending-in-crlf-and-blank-lines": b"gitdir: x\r\n\r\n",
}
_HEADS_GIT_ACCEPTS = {                                     # HEAD in a .git folder that has objects/ and refs/
    "head-naming-a-branch": b"ref: refs/heads/main\n",
    "head-with-no-blank-after-ref": b"ref:refs/heads/main\n",
    "head-with-a-line-break-after-ref": b"ref:\n\t refs/heads/main\n",
    "head-naming-a-branch-not-in-utf8": "ref: refs/heads/分支\n".encode("gbk"),
    "head-naming-a-commit-in-capitals": b"0123456789ABCDEF0123456789ABCDEF01234567\n",
}
_COMMONDIRS_GIT_ACCEPTS = {                                # commondir in a worktree's git directory "x"
    "commondir-naming-the-repository": b"../common\n",
}
# What git refuses: it reads these files whole, takes nothing but "gitdir: " before a path, and nothing but
# blanks, tabs and line breaks between "ref:" and "refs/".
_POINTERS_GIT_REFUSES = {
    "pointer-without-gitdir": b"folder: x\n",
    "pointer-without-the-blank": b"gitdir:x\n",
    "pointer-after-a-blank": b" gitdir: x\n",
    "pointer-with-two-blanks": b"gitdir:  x\n",
    "pointer-with-a-blank-after-the-path": b"gitdir: x \n",
    "pointer-with-a-second-line": b"gitdir: x\nmore\n",
    "pointer-not-utf8": "gitdir: D:/项目/.git/worktrees/x\n".encode("gbk"),
    "pointer-with-nul-in-the-path": b"gitdir: a\x00b\n",
    "pointer-empty": b"",
}
_HEADS_GIT_REFUSES = {
    "head-empty": b"",
    "head-naming-nothing-under-refs": b"ref: main\n",
    "head-after-a-blank": b" ref: refs/heads/main\n",
    "head-with-a-form-feed-after-ref": b"ref:\x0crefs/heads/main\n",
    "head-with-a-wide-blank-after-ref": "ref:\u3000refs/heads/main\n".encode("utf-8"),
    "head-one-digit-short-of-a-commit": b"0123456789abcdef0123456789abcdef0123456\n",
}
_COMMONDIRS_GIT_REFUSES = {
    "commondir-naming-nothing": b"../nowhere\n",
    "commondir-after-a-blank": b" ../common\n",
    "commondir-with-a-second-line": b"../common\nmore\n",
}
_FOLDERS_GIT_REFUSES = ("points-nowhere", "points-at-a-plain-folder", "points-at-a-folder-with-only-head",
                        "no-path-in-a-folder-laid-out-like-a-git-directory", "empty-folder",
                        "folder-with-only-an-empty-head", "folder-without-head", "folder-without-objects",
                        "folder-without-refs")


def _hand_written_dot_git(folder: Path, kind: str) -> None:
    marker = folder / ".git"
    pointer = {**_POINTERS_GIT_ACCEPTS, **_POINTERS_GIT_REFUSES}.get(kind)
    head = {**_HEADS_GIT_ACCEPTS, **_HEADS_GIT_REFUSES}.get(kind)
    commondir = {**_COMMONDIRS_GIT_ACCEPTS, **_COMMONDIRS_GIT_REFUSES}.get(kind)
    if pointer is not None:
        _git_dir(folder / "x")
        marker.write_bytes(pointer)
    elif head is not None:
        _git_dir(marker, head=head)
    elif commondir is not None:
        # A linked worktree: git looks for objects/ and refs/ where commondir says, not beside it.
        _git_dir(folder / "common")
        _git_dir(folder / "x", objects=kind in _COMMONDIRS_GIT_REFUSES, refs=kind in _COMMONDIRS_GIT_REFUSES)
        (folder / "x" / "commondir").write_bytes(commondir)
        marker.write_bytes(b"gitdir: x\n")
    elif kind == "points-nowhere":
        marker.write_bytes(b"gitdir: x\n")
    elif kind == "points-at-a-plain-folder":
        (folder / "x").mkdir()
        marker.write_bytes(b"gitdir: x\n")
    elif kind == "points-at-a-folder-with-only-head":
        _git_dir(folder / "x", objects=False, refs=False)
        marker.write_bytes(b"gitdir: x\n")
    elif kind == "no-path-in-a-folder-laid-out-like-a-git-directory":
        _git_dir(folder)
        marker.write_bytes(b"gitdir: \n")
    elif kind == "empty-folder":
        marker.mkdir()
    elif kind == "folder-with-only-an-empty-head":
        _git_dir(marker, head=b"", objects=False, refs=False)
    elif kind == "folder-without-head":
        _git_dir(marker, head=None)
    elif kind == "folder-without-objects":
        _git_dir(marker, objects=False)
    else:
        assert kind == "folder-without-refs"
        _git_dir(marker, refs=False)


@pytest.mark.parametrize("kind", [*_POINTERS_GIT_ACCEPTS, *_HEADS_GIT_ACCEPTS, *_COMMONDIRS_GIT_ACCEPTS])
def test_a_folder_with_a_dot_git_that_git_accepts_is_checked_on_its_own(tmp_path, kind):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "src/app.py", "# DEMO-9\n")
    _hand_written_dot_git(tmp_path / "src", kind)

    assert scan(tmp_path) == []


@pytest.mark.parametrize("kind", [*_POINTERS_GIT_REFUSES, *_HEADS_GIT_REFUSES, *_COMMONDIRS_GIT_REFUSES,
                                  *_FOLDERS_GIT_REFUSES])
def test_a_folder_with_a_made_up_dot_git_is_still_checked(tmp_path, kind):
    # git goes on tracking a folder that merely holds something named .git, and .git itself is never committed,
    # so a made-up one must not take the folder out of the check. Made up means git would not take it for a
    # repository: it asks for a HEAD that names a branch or a commit, and for objects/ and refs/.
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "src/app.py", "# DEMO-9\n")
    _hand_written_dot_git(tmp_path / "src", kind)

    assert [(f.rule, f.path) for f in scan(tmp_path)] == [("dangling-ref", "src/app.py")]


@pytest.mark.parametrize("dot_git", ["a pointer at the project's own .git", "git init"])
def test_a_tracked_folder_is_still_checked_when_a_dot_git_that_git_accepts_is_put_in_it(tmp_path, dot_git):
    # A .git that git accepts does not take a folder out of the repository that already tracks it: git goes on
    # tracking and committing the files, and .git shows in no status and no commit. Nothing in the folder tells
    # it from another checkout, only the index does, so for a folder with such a .git the check asks git.
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n- DEMO-2：two\n")
    write(tmp_path, "src/app.py", "# DEMO-1\n")
    write(tmp_path, "src/tests/test_app.py", "# DEMO-2\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    if dot_git == "git init":
        _git(tmp_path / "src", "init", "-q", "-b", "main")
    else:
        write(tmp_path, "src/.git", "gitdir: ../.git\n")
    write(tmp_path, "src/app.py", "# DEMO-9\n")
    write(tmp_path, "src/new.py", "# DEMO-8\n")
    # The premise: the project's repository still takes the change and the new file for its own.
    assert _git(tmp_path, "status", "--porcelain").stdout.splitlines() == [" M src/app.py", "?? src/new.py"]

    assert [(f.rule, f.path) for f in scan(tmp_path)] == [
        ("dangling-ref", "src/app.py"), ("dangling-ref", "src/new.py")]
    assert report(tmp_path) == ["未被测试引用：DEMO-1"]


def test_a_tracked_folder_is_still_checked_when_the_index_spells_it_in_another_case(tmp_path):
    # Windows and macOS let a folder be renamed to another case without git noticing: the index keeps the old
    # spelling and the files stay tracked. Where case matters the renamed folder is a new one, and it is checked
    # all the same: comparing without case can only add to what is checked.
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "Src/app.py", "# DEMO-9\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    (tmp_path / "Src").rename(tmp_path / "moved")
    (tmp_path / "moved").rename(tmp_path / "SRC")
    write(tmp_path, "SRC/.git", "gitdir: ../.git\n")

    assert [(f.rule, f.path) for f in scan(tmp_path)] == [("dangling-ref", "SRC/app.py")]


def test_a_nested_repository_is_left_out_where_git_cannot_be_asked(tmp_path, monkeypatch):
    # git is asked only to tell a tracked folder from another checkout. Without it there is no index to say
    # so, the check must still run, and the folder is judged by its .git alone.
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    nested = tmp_path / "vendor" / "tool"
    write(nested, "tests/test_tool.py", "# DEMO-9\n")
    _git(nested, "init", "-q", "-b", "main")
    programs = tmp_path.parent / "no git here"
    programs.mkdir()
    monkeypatch.setenv("PATH", str(programs))
    with pytest.raises(OSError):
        _git(tmp_path, "--version")

    assert scan(tmp_path) == []


def test_git_is_asked_once_and_only_for_a_folder_with_a_dot_git_that_git_accepts(tmp_path, monkeypatch):
    # Reading files answers everything else, so a project without such a folder is checked without starting
    # git at all, and one with many is checked with a single question.
    asked = []
    run = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda command, **options: asked.append(command) or run(command, **options))
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "src/app.py", "# DEMO-1\n")
    _hand_written_dot_git(tmp_path / "src", "points-nowhere")
    assert scan(tmp_path) == []
    assert asked == []

    for name in ("one", "two"):
        write(tmp_path, f"vendor/{name}/app.py", "# DEMO-9\n")
        _hand_written_dot_git(tmp_path / "vendor" / name, "pointer")
    assert scan(tmp_path) == []
    assert len(asked) == 1


@contextlib.contextmanager
def _unreadable(path: Path):
    """Make a file impossible to open the way each system can: held by a process, or without permission."""
    if os.name == "nt":
        import _winapi
        handle = _winapi.CreateFile(str(path), _winapi.GENERIC_READ, 0, 0, _winapi.OPEN_EXISTING, 0, 0)
        try:
            yield
        finally:
            _winapi.CloseHandle(handle)
    else:
        if os.geteuid() == 0:
            pytest.skip("root can read any file")
        path.chmod(0)
        try:
            yield
        finally:
            path.chmod(0o644)


def test_a_dot_git_that_cannot_be_read_does_not_stop_the_check(tmp_path):
    # Looking into .git must not add a way to crash: before, a folder like this was simply checked.
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "src/app.py", "# DEMO-9\n")
    marker = write(tmp_path, "src/.git", "gitdir: x\n")
    with _unreadable(marker):
        with pytest.raises(OSError):
            marker.read_text(encoding="utf-8")

        assert [(f.rule, f.path) for f in scan(tmp_path)] == [("dangling-ref", "src/app.py")]


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
    assert lines[-1].startswith("范围：") and "嵌套的 git 工作区" in lines[-1]
    assert main(["--version"]) == 0
    assert capsys.readouterr().out == f"spec_check {spec_check.VERSION}\n"
    # The first line of the file is the version a project sees when it opens its vendored copy.
    assert spec_check.__doc__.splitlines()[0] == f"spec_check v{spec_check.VERSION}"


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


def _project(tmp_path):
    write(tmp_path, "specs/backlog.md", "# 待做池\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")


def test_ignore_patterns_may_start_with_a_dot():
    # `.lstrip("./")` also ate the leading dot, so `.pi/**` became `pi/**` and never matched: a project could
    # not allowlist a dot-directory, and nothing said the entry was dead.
    ignored = spec_check.path_is_ignored
    assert ignored(".pi/extensions/ledger-guard.js", [".pi/**"])
    assert ignored(".dev-circuit/hooks/ledger_guard.py", [".dev-circuit/hooks/ledger_guard.py"])
    assert ignored(".eslintrc.js", [".eslintrc.js"])
    assert ignored("vendor/a.py", ["./vendor/**"])          # a leading ./ is still dropped
    assert not ignored("pi/extensions/a.js", [".pi/**"])


def test_code_before_design_sees_code_files_with_non_ascii_names(tmp_path):
    # git quotes non-ASCII paths by default ("src/\345\272\224\347\224\250.py"), so the suffix never matched.
    _project(tmp_path)
    _git(tmp_path, "config", "core.quotepath", "true")       # git's default, whatever this machine's config says
    _git(tmp_path, "switch", "-q", "-c", "feat/export")
    write(tmp_path, "src/应用.py", "print(1)\n")
    findings = scan(tmp_path)
    assert [finding.rule for finding in findings] == ["code-before-design"]
    assert "src/应用.py" in findings[0].message


def test_installed_hook_files_are_not_feature_code(tmp_path):
    # `devcircuit hooks install` leaves its script in the project. A new project's first feature commits a
    # framework draft before any card exists, and the script made that commit fail as code before design.
    _project(tmp_path)
    _git(tmp_path, "switch", "-q", "-c", "feat/first")
    write(tmp_path, ".dev-circuit/hooks/ledger_guard.py", "print(1)\n")
    write(tmp_path, ".pi/extensions/ledger-guard.js", "export default 1\n")
    assert scan(tmp_path) == []


def test_the_commit_that_settles_the_framework_is_not_blocked_by_other_work(tmp_path):
    # A framework draft is committed before the card exists. Like the design commit, it holds no code, so
    # unrelated uncommitted code in the working tree must not block it.
    _project(tmp_path)
    _git(tmp_path, "switch", "-q", "-c", "feat/first")
    write(tmp_path, "scratch.py", "print(1)\n")
    write(tmp_path, "docs/architecture.md", "# 架构\n")
    assert [finding.rule for finding in scan(tmp_path)] == ["code-before-design"]   # still a draft

    _git(tmp_path, "add", "docs/architecture.md")
    assert scan(tmp_path) == []

    _git(tmp_path, "add", "scratch.py")
    assert [finding.rule for finding in scan(tmp_path)] == ["code-before-design"]


def test_a_design_draft_may_delete_a_requirement_that_tests_still_cite(tmp_path):
    # The design commit holds only the specs and the card. Deleting a requirement left its ID in the tests:
    # dangling-ref refused the commit, and staging the fixed test tripped code-before-design. Until the card
    # is committed the citation is tolerated; the first code commit has to clean it up.
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：a\n- DEMO-2：b\n- AC-001-1：c\n")
    write(tmp_path, "tests/test_demo.py", "# DEMO-2 DEMO:AC-001-1\n")
    _project(tmp_path)
    _git(tmp_path, "switch", "-q", "-c", "feat/trim")
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：a\n")
    write(tmp_path, "specs/trim/spec.md", "# trim\n")
    assert scan(tmp_path) == []

    _git(tmp_path, "add", "docs", "specs")
    assert scan(tmp_path) == []                                   # the design commit itself
    _git(tmp_path, "commit", "-q", "-m", "design(trim)")
    assert [(finding.rule, finding.path) for finding in scan(tmp_path)] == [
        ("dangling-ref", "tests/test_demo.py"), ("dangling-ref", "tests/test_demo.py")]


def test_a_reference_that_never_existed_is_dangling_even_in_a_draft(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：a\n")
    write(tmp_path, "tests/test_demo.py", "# DEMO-9\n")
    _project(tmp_path)
    _git(tmp_path, "switch", "-q", "-c", "feat/trim")
    write(tmp_path, "specs/trim/spec.md", "# trim\n")
    assert [finding.rule for finding in scan(tmp_path)] == ["dangling-ref"]


def test_code_before_design_points_bug_fixes_to_another_branch(tmp_path):
    # A bug fix has no card. On feat/<name> the gate used to answer "commit the design first", which sent
    # the agent to write a card for a bug.
    _project(tmp_path)
    _git(tmp_path, "switch", "-q", "-c", "feat/fix-trim")
    write(tmp_path, "src/app.py", "print(1)\n")
    assert "fix/" in scan(tmp_path)[0].message


def _cited(tmp_path):
    """HEAD defines DEMO-1 and DEMO-2, and a test cites DEMO-2."""
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：a\n- DEMO-2：b\n")
    write(tmp_path, "tests/test_demo.py", "# DEMO-2\n")
    _project(tmp_path)


def _delete_demo_2(tmp_path):
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：a\n")
    return [finding.rule for finding in scan(tmp_path)]


@pytest.mark.parametrize("branch", ["main", "fix/trim", "feat/trim"])
def test_only_a_feature_draft_may_leave_a_deleted_requirement_cited(tmp_path, branch):
    # The tolerance is for the design commit of feat/<name> and nothing else. Elsewhere the citation would
    # reach the trunk; on a feat/ branch with no card being drafted, no later commit would ever report it.
    _cited(tmp_path)
    if branch != "main":
        _git(tmp_path, "switch", "-q", "-c", branch)
    if branch == "fix/trim":
        write(tmp_path, "specs/trim/spec.md", "# trim\n")      # a card of the same name changes nothing here
    assert _delete_demo_2(tmp_path) == ["dangling-ref"]


def test_once_the_card_is_committed_a_deleted_requirement_must_not_stay_cited(tmp_path):
    _cited(tmp_path)
    _git(tmp_path, "switch", "-q", "-c", "feat/trim")
    write(tmp_path, "specs/trim/spec.md", "# trim\n")
    _git(tmp_path, "add", "specs")
    _git(tmp_path, "commit", "-q", "-m", "design(trim)")
    assert _delete_demo_2(tmp_path) == ["dangling-ref"]


def test_the_tolerance_reads_capability_specs_the_way_the_check_does(tmp_path):
    # Only what counted as a requirement at HEAD is tolerated. A BOM, table rows and legacy IDs are read as
    # they are in the working tree; notes in a subfolder, the README and ignored files define nothing.
    write(tmp_path, "docs/requirements/订单.md", chr(0xFEFF) + "代号：ORDER\n| ORDER-1 | a |\n- AC-001-1：b\n")
    write(tmp_path, "docs/requirements/notes/ideas.md", "- ORDER-7：maybe\n")
    write(tmp_path, "docs/requirements/README.md", "- ORDER-8：example\n")
    write(tmp_path, "docs/requirements/old.md", "代号：ORDER\n- ORDER-9：gone\n")
    write(tmp_path, ".dcuignore", "docs/requirements/old.md\n")
    write(tmp_path, "tests/test_order.py", "# ORDER-1 ORDER:AC-001-1\n")
    write(tmp_path, "tests/test_other.py", "# ORDER-7 ORDER-8 ORDER-9\n")
    _project(tmp_path)
    _git(tmp_path, "config", "core.quotepath", "true")
    _git(tmp_path, "switch", "-q", "-c", "feat/trim")
    write(tmp_path, "docs/requirements/订单.md", "代号：ORDER\n- ORDER-2：c\n")
    write(tmp_path, "specs/trim/spec.md", "# trim\n")

    assert [(finding.rule, finding.path) for finding in scan(tmp_path)] == [("dangling-ref", "tests/test_other.py")] * 3
