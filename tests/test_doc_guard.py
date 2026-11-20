"""Behavior checks for the reusable documentation guard."""

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

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


def test_links_written_the_ways_markdown_allows(tmp_path: Path) -> None:
    # A file whose name has a space or non-ASCII characters is linked percent-encoded or in angle brackets, and
    # a quoted title may follow the destination. Each of these was reported as a broken link.
    write(tmp_path, "docs/b c.md", "Target\n")
    write(tmp_path, "docs/订单.md", "Target\n")
    write(tmp_path, "docs/报告 (1).md", "Target\n")
    write(tmp_path, "docs/x 'y'.md", "Target\n")
    write(
        tmp_path,
        "docs/a.md",
        "[0](x 'y'.md)\n"                # not what Markdown reads as the destination, but it resolved as written
        "[1](b%20c.md)\n"
        "[2](<b c.md>)\n"
        "[3](%E8%AE%A2%E5%8D%95.md)\n"
        '[4](订单.md "标题")\n'
        "[5](订单.md '标题')\n"
        '[6](<b c.md> "标题")\n'
        "[7](b%20c.md#sec)\n"
        '[8](订单.md "标题 (注)")\n'
        "[9](<报告 (1).md>)\n"
        "[10](%E6%8A%A5%E5%91%8A%20%281%29.md)\n"
        "[11](<https://example.com/a b>) [12](<#local>)\n"
        "[13]( <报告 (1).md> )\n"         # blanks may surround the destination
        '[14](<报告 (1).md> "标题")\n'
        '[15](<b c.md> "a > b")\n'        # the destination ends at the first ">"
        "[16](<x 'y'.md>)\n",             # inside the brackets a quote is part of the name, not a title
    )

    assert [(finding.rule, finding.line) for finding in scan(tmp_path)] == []


def test_links_to_missing_files_are_reported_however_they_are_written(tmp_path: Path) -> None:
    write(tmp_path, "docs/b c.md", "Target\n")
    write(tmp_path, "docs/订单.md", "Target\n")
    write(
        tmp_path,
        "docs/a.md",
        "[1](missing%20file.md)\n"
        "[2](<gone file.md>)\n"
        '[3](缺.md "标题")\n'
        "[4](<gone.md> '标题')\n"
        "[5](%E7%BC%BA.md)\n"
        "[6](b%20c.md) [7](b%2520c.md)\n"   # decoded once: the second names "b%20c.md", which is not there
        "[8](b c.md's-copy.md)\n"           # a quote inside a name does not start a title
        "[9](<100ms)\n"                     # "<" without ">" does not open a bracketed destination
        "[10](订单.md 不是标题)\n"           # only a quoted title is dropped after the destination
        "[11](b+c.md)\n"                    # "+" stands for itself in a path, not for a space
        "[12](<b c.md>) [13](<gone 2.md>)\n"                # each bracketed destination ends at its own ">"
        '[14](<b c.md> "标题") [15](<gone 3.md> "标题")\n'
        "[16](<100ms) [17](<gone 4.md>)\n",                 # and an unclosed "<" does not reach into the next link
    )

    assert [(finding.rule, finding.line, finding.message) for finding in scan(tmp_path)] == [
        ("broken-link", 1, "链接目标不存在：missing%20file.md"),
        ("broken-link", 2, "链接目标不存在：<gone file.md>"),
        ("broken-link", 3, '链接目标不存在：缺.md "标题"'),
        ("broken-link", 4, "链接目标不存在：<gone.md> '标题'"),
        ("broken-link", 5, "链接目标不存在：%E7%BC%BA.md"),
        ("broken-link", 6, "链接目标不存在：b%2520c.md"),
        ("broken-link", 7, "链接目标不存在：b c.md's-copy.md"),
        ("broken-link", 8, "链接目标不存在：<100ms"),
        ("broken-link", 9, "链接目标不存在：订单.md 不是标题"),
        ("broken-link", 10, "链接目标不存在：b+c.md"),
        ("broken-link", 11, "链接目标不存在：<gone 2.md>"),
        ("broken-link", 12, '链接目标不存在：<gone 3.md> "标题"'),
        ("broken-link", 13, "链接目标不存在：<100ms"),
        ("broken-link", 13, "链接目标不存在：<gone 4.md>"),
    ]


def test_a_link_that_decodes_to_a_path_outside_the_folder_is_not_looked_up(tmp_path: Path, monkeypatch) -> None:
    # Decoding must not widen where the rule looks: "%5C%5Chost%5Cshare" decodes to a network path, which Windows
    # would ask that host about, and a decoded absolute path passes or fails by the machine the check runs on.
    target = write(tmp_path, "docs/b.md", "Target\n")
    drive = target.drive[:1] or "C"
    if os.name != "nt":
        write(tmp_path, f"docs/{drive}:b.md", "Target\n")   # a file name here; on Windows the same text names a drive
    write(
        tmp_path,
        "docs/a.md",
        f"[1]({quote(str(target), safe='')})\n"             # the absolute path of a file that exists
        f"[2]({quote(target.as_posix(), safe='')})\n"
        f"[3](<{quote(str(target), safe='')}>)\n"
        f"[4]({drive}%3Ab.md)\n"                             # "b.md in the current folder of that drive"
        "[5](%5C%5C127.0.0.1%5Cshare%5Ca.md)\n"
        "[6](%2F%2F127.0.0.1%2Fshare%2Fa.md)\n"
        f"[7]({quote(target.as_posix()[len(target.drive):], safe='')})\n",   # from the root of the current drive
    )
    asked: list[Path] = []
    exists = Path.exists

    def recording(self, *args, **kwargs):
        asked.append(self)
        return exists(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "exists", recording)
        findings = scan(tmp_path)

    assert [(finding.rule, finding.line) for finding in findings] == [("broken-link", line) for line in range(1, 8)]
    assert asked and all(path.is_relative_to(tmp_path) for path in asked)


def test_skipped_dirs(tmp_path: Path) -> None:
    write(tmp_path, "node_modules/p/README.md", "D-123\n")

    assert scan(tmp_path) == []


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                          check=True)


@pytest.mark.parametrize("where", [".trees/wt", ".claude/worktrees/x"])
def test_a_linked_worktree_inside_the_project_is_checked_on_its_own(tmp_path: Path, where: str, capsys) -> None:
    # A worktree kept inside the project folder holds another branch, and its documents are that branch's.
    # By default only a README one or two levels down was read; --include reached the rest.
    write(tmp_path, "docs/a.md", "现行说明\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    tree = tmp_path / where
    _git(tmp_path, "worktree", "add", "-q", "-b", "export", str(tree))
    write(tree, "README.md", "见 D-036\n")
    write(tree, "docs/b.md", "decision log\n")
    parent = where.split("/")[0]

    assert scan(tmp_path) == []
    assert scan(tmp_path, includes=[parent]) == []
    assert main(["--root", str(tmp_path), "--include", parent]) == 0
    assert capsys.readouterr().out == "doc_guard：通过（检查了 1 份文档）\n"

    # With the worktree as the root, its own documents are checked like any project's.
    assert [(finding.rule, finding.path) for finding in scan(tree)] == [
        ("decision-id", "README.md"), ("bookkeeping-phrase", "docs/b.md")]


def test_a_nested_repository_is_checked_on_its_own(tmp_path: Path) -> None:
    write(tmp_path, "docs/a.md", "现行说明\n")
    nested = tmp_path / "tool"
    write(nested, "README.md", "见 D-036\n")
    _git(nested, "init", "-q", "-b", "main")

    assert scan(tmp_path) == []
    assert [(finding.rule, finding.path) for finding in scan(nested)] == [("decision-id", "README.md")]

    # The same on a detached HEAD, where HEAD holds a commit instead of naming a branch.
    _git(nested, "add", "-A")
    _git(nested, "commit", "-q", "-m", "init")
    _git(nested, "checkout", "-q", "--detach")
    assert not (nested / ".git" / "HEAD").read_text(encoding="utf-8").startswith("ref:")
    assert scan(tmp_path) == []


def test_a_submodule_is_checked_on_its_own(tmp_path: Path) -> None:
    # A submodule's .git is a file with a relative path (gitdir: ../.git/modules/…), read from the submodule.
    library = tmp_path.parent / "library"
    write(library, "README.md", "见 D-036\n")
    _git(library, "init", "-q", "-b", "main")
    _git(library, "add", "-A")
    _git(library, "commit", "-q", "-m", "init")
    write(tmp_path, "docs/a.md", "现行说明\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(library), "library")
    pointer = (tmp_path / "library" / ".git").read_text(encoding="utf-8")
    assert pointer.startswith("gitdir: ../")

    assert (tmp_path / "library" / "README.md").is_file()
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
def test_a_folder_with_a_dot_git_that_git_accepts_is_checked_on_its_own(tmp_path: Path, kind: str) -> None:
    write(tmp_path, "docs/a.md", "现行说明\n")
    write(tmp_path, "docs/old/notes.md", "见 D-036\n")
    _hand_written_dot_git(tmp_path / "docs" / "old", kind)

    assert scan(tmp_path) == []


@pytest.mark.parametrize("kind", [*_POINTERS_GIT_REFUSES, *_HEADS_GIT_REFUSES, *_COMMONDIRS_GIT_REFUSES,
                                  *_FOLDERS_GIT_REFUSES])
def test_a_folder_with_a_made_up_dot_git_is_still_checked(tmp_path: Path, kind: str) -> None:
    # git goes on tracking a folder that merely holds something named .git, and .git itself is never committed,
    # so a made-up one must not take the folder out of the check. Made up means git would not take it for a
    # repository: it asks for a HEAD that names a branch or a commit, and for objects/ and refs/.
    write(tmp_path, "docs/old/notes.md", "见 D-036\n")
    _hand_written_dot_git(tmp_path / "docs" / "old", kind)

    assert [(finding.rule, finding.path) for finding in scan(tmp_path)] == [("decision-id", "docs/old/notes.md")]


@pytest.mark.parametrize("dot_git", ["a pointer at the project's own .git", "git init"])
def test_a_tracked_folder_is_still_checked_when_a_dot_git_that_git_accepts_is_put_in_it(tmp_path: Path,
                                                                                         dot_git: str) -> None:
    # A .git that git accepts does not take a folder out of the repository that already tracks it: git goes on
    # tracking and committing the files, and .git shows in no status and no commit. Nothing in the folder tells
    # it from another checkout, only the index does, so for a folder with such a .git the check asks git.
    write(tmp_path, "docs/a.md", "现行说明\n")
    write(tmp_path, "docs/old/notes.md", "现行说明\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    if dot_git == "git init":
        _git(tmp_path / "docs" / "old", "init", "-q", "-b", "main")
    else:
        write(tmp_path, "docs/old/.git", "gitdir: ../../.git\n")
    write(tmp_path, "docs/old/notes.md", "见 D-036\n")
    write(tmp_path, "docs/old/new.md", "decision log\n")
    # The premise: the project's repository still takes the change and the new file for its own.
    assert _git(tmp_path, "status", "--porcelain").stdout.splitlines() == [
        " M docs/old/notes.md", "?? docs/old/new.md"]

    assert [(finding.rule, finding.path) for finding in scan(tmp_path)] == [
        ("bookkeeping-phrase", "docs/old/new.md"), ("decision-id", "docs/old/notes.md")]


def test_a_tracked_folder_is_still_checked_when_the_index_spells_it_in_another_case(tmp_path: Path) -> None:
    # Windows and macOS let a folder be renamed to another case without git noticing: the index keeps the old
    # spelling and the files stay tracked. Where case matters the renamed folder is a new one, and it is checked
    # all the same: comparing without case can only add to what is checked.
    write(tmp_path, "docs/Old/notes.md", "见 D-036\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    (tmp_path / "docs" / "Old").rename(tmp_path / "docs" / "moved")
    (tmp_path / "docs" / "moved").rename(tmp_path / "docs" / "OLD")
    write(tmp_path, "docs/OLD/.git", "gitdir: ../../.git\n")

    assert [(finding.rule, finding.path) for finding in scan(tmp_path)] == [("decision-id", "docs/OLD/notes.md")]


def test_a_nested_repository_is_left_out_where_git_cannot_be_asked(tmp_path: Path, monkeypatch) -> None:
    # git is asked only to tell a tracked folder from another checkout. Without it there is no index to say
    # so, the check must still run, and the folder is judged by its .git alone.
    write(tmp_path, "docs/a.md", "现行说明\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    nested = tmp_path / "tool"
    write(nested, "README.md", "见 D-036\n")
    _git(nested, "init", "-q", "-b", "main")
    programs = tmp_path.parent / "no git here"
    programs.mkdir()
    monkeypatch.setenv("PATH", str(programs))
    with pytest.raises(OSError):
        _git(tmp_path, "--version")

    assert scan(tmp_path) == []


def test_git_is_asked_once_and_only_for_a_folder_with_a_dot_git_that_git_accepts(tmp_path: Path, monkeypatch) -> None:
    # Reading files answers everything else, so a project without such a folder is checked without starting
    # git at all, and one with many is checked with a single question.
    asked = []
    run = subprocess.run
    monkeypatch.setattr(subprocess, "run", lambda command, **options: asked.append(command) or run(command, **options))
    write(tmp_path, "docs/a.md", "现行说明\n")
    write(tmp_path, "docs/old/notes.md", "现行说明\n")
    _hand_written_dot_git(tmp_path / "docs" / "old", "points-nowhere")
    assert scan(tmp_path) == []
    assert asked == []

    for folder in ("docs/one", "design/two"):               # under different folders: one question for the walk
        write(tmp_path, f"{folder}/notes.md", "见 D-036\n")
        _hand_written_dot_git(tmp_path / folder, "pointer")
    assert scan(tmp_path) == []
    assert len(asked) == 1


@contextlib.contextmanager
def _unreadable(path: Path):
    """Make a file impossible to open the way each system can: held by a process, or without permission."""
    if os.name == "nt":
        # Locked by this process rather than opened without sharing: _winapi.CreateFile is the ANSI API before
        # Python 3.12 and cannot open a path outside the code page, and every test path here has Chinese in it.
        import msvcrt
        with open(path, "rb") as handle:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, max(path.stat().st_size, 1))
            yield
    else:
        if os.geteuid() == 0:
            pytest.skip("root can read any file")
        path.chmod(0)
        try:
            yield
        finally:
            path.chmod(0o644)


def test_a_dot_git_that_cannot_be_read_does_not_stop_the_check(tmp_path: Path) -> None:
    # Looking into .git must not add a way to crash: before, a folder like this was simply checked.
    write(tmp_path, "docs/old/notes.md", "见 D-036\n")
    marker = write(tmp_path, "docs/old/.git", "gitdir: x\n")
    with _unreadable(marker):
        with pytest.raises(OSError):
            marker.read_text(encoding="utf-8")

        assert [(finding.rule, finding.path) for finding in scan(tmp_path)] == [("decision-id", "docs/old/notes.md")]


def test_a_forbidden_folder_is_reported_even_when_it_is_a_repository(tmp_path: Path) -> None:
    # A ledger is a git repository of its own. Put inside the project it is still a path that must not be there.
    write(tmp_path, "docs/a.md", "现行说明\n")
    write(tmp_path, "ledger/entries/x.jsonl", "{}\n")
    _git(tmp_path / "ledger", "init", "-q", "-b", "main")

    assert [(finding.rule, finding.path) for finding in scan(tmp_path)] == [("forbidden-path", "ledger")]


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
    assert capsys.readouterr().out == "doc_guard：通过（检查了 1 份文档）\n"
    assert main(["--root", str(clean), "--json"]) == 0
    assert capsys.readouterr().out == "[]\n"

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
    # Each rule comes with one line on what it checks, so nobody has to read this file to learn it.
    assert main(["--list-rules"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in lines[:len(doc_guard.RULES)]] == list(doc_guard.RULES)
    assert all(len(line.split(maxsplit=1)) == 2 for line in lines[:len(doc_guard.RULES)])
    assert lines[-1].startswith("范围：") and "嵌套的 git 工作区" in lines[-1]
    assert "百分号编码" in next(line for line in lines if line.startswith("broken-link"))
    assert main(["--version"]) == 0
    assert capsys.readouterr().out == f"doc_guard {doc_guard.VERSION}\n"
    # The first line of the file is the version a project sees when it opens its vendored copy.
    assert doc_guard.__doc__.splitlines()[0] == f"doc_guard v{doc_guard.VERSION}"


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


def test_cli_errors_are_utf8_with_legacy_stdio_encoding(tmp_path: Path, gbk_env) -> None:
    # Standard output was switched to UTF-8 and standard error was left in the console's encoding, so the two
    # streams of one run could not be decoded the same way.
    result = subprocess.run(
        [sys.executable, doc_guard.__file__, "--root", str(tmp_path), "--ignore-file", str(tmp_path / "missing.txt")],
        capture_output=True,
        env=gbk_env,
    )
    assert result.returncode == 2
    assert "--ignore-file 指向的文件不存在" in result.stderr.decode("utf-8")


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


def test_oversize_capability_spec_and_card(tmp_path: Path) -> None:
    # Files the agent reads whole stay small: a capability spec up to 400 lines, a card up to 80.
    write(tmp_path, "docs/requirements/big.md", "代号：BIG\n" + "- line\n" * 400)
    write(tmp_path, "docs/requirements/ok.md", "代号：OK\n" + "- line\n" * 399)
    write(tmp_path, "docs/requirements/README.md", "x\n" * 500)
    write(tmp_path, "specs/f/spec.md", "line\n" * 81)
    write(tmp_path, "specs/g/spec.md", "line\n" * 80)

    findings = [finding for finding in scan(tmp_path) if finding.rule == "oversize"]
    assert [(finding.path, finding.line) for finding in findings] == [
        ("docs/requirements/big.md", 401), ("specs/f/spec.md", 81)]
    assert "400" in findings[0].message and "80" in findings[1].message


def test_architecture_needs_a_short_summary(tmp_path: Path) -> None:
    # The fit check reads only the summary, so it must exist and stay within 60 non-blank lines.
    architecture = write(tmp_path, "docs/architecture.md", "# 结构\n\n正文\n")
    assert [finding.rule for finding in scan(tmp_path)] == ["arch-summary"]

    architecture.write_text('# 结构\n\n<a id="summary"></a>\n## 框架摘要\n\n' + "- 模块\n" * 60
                            + "\n## 细节\n" + "正文\n" * 100, encoding="utf-8")
    assert scan(tmp_path) == []

    architecture.write_text('# 结构\n\n## 框架摘要 <a id="summary"></a>\n' + "- 模块\n" * 61
                            + "## 细节\n正文\n", encoding="utf-8")
    findings = scan(tmp_path)
    assert [finding.rule for finding in findings] == ["arch-summary"]
    assert "61" in findings[0].message


def test_ignore_patterns_may_start_with_a_dot() -> None:
    # Same slip as spec_check: `.lstrip("./")` turned `.github/**` into `github/**`, which never matched.
    ignored = doc_guard.path_is_ignored
    assert ignored(".github/workflows/notes.md", [".github/**"])
    assert ignored("vendor/a.md", ["./vendor/**"])           # a leading ./ is still dropped
    assert not ignored("github/notes.md", [".github/**"])
