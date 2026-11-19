"""The environments this flow has broken in on Windows: linked worktrees, line endings, console encodings, shells.

Every combination here was probed and found to behave, with nothing holding it in place. The tests sit in
one file because the environment, not the component, is what they have in common.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import devcircuit.cli as cli
import devcircuit.context as context_module
import doc_guard
import spec_check

TOOLS = str(Path(cli.__file__).resolve().parents[1])

DEMO = ("# 导出能力\n代号：DEMO\n\n"
        "- DEMO-1：导出一条记录。\n  - 例：导出得到该记录。\n"
        "- DEMO-2：导出后弹出提示。\n  - 例：看到提示。\n")
ADDED = "- DEMO-3：导出 CSV。\n  - 例：有表头。\n"
CARD = ("# add-export：导出 CSV\n\n能力：DEMO（已有）· 框架：不变\n\n## 目标\n\n导出 CSV。\n\n"
        "## 切片\n\n- S1：导出 CSV（当前）\n")


def write(root: Path, rel: str, text: str, newline: str = "\n") -> Path:
    """Write the line ending asked for: text mode would write the platform's, and half of these tests are about it."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return path


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def own_python_first() -> dict[str, str]:
    """The pre-commit hook and the Claude hook command find python on PATH; make it the one running the tests."""
    return {**os.environ, "PATH": os.pathsep.join([str(Path(sys.executable).parent), os.environ["PATH"]])}


def commit(root: Path, message: str) -> subprocess.CompletedProcess:
    """A real `git commit`, pre-commit hook included; the caller says whether it should get through."""
    return subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=own_python_first())


def trunk(root: Path) -> Path:
    """A repository whose main has one commit: a capability spec and an empty backlog."""
    write(root, "docs/requirements/demo.md", DEMO)
    write(root, "specs/backlog.md", "# 待做池\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def trunk_moves_on(root: Path) -> str:
    """Land someone else's requirement on main, from whichever branch `root` has checked out; return main's tip.

    Until main moves, its tip, the fork point and (for a linked worktree) the HEAD of the main working tree
    are all one commit, and a base taken from the wrong one of them cannot be told from the right one.
    """
    branch = git(root, "branch", "--show-current").strip()
    git(root, "switch", "-q", "main")
    write(root, "docs/requirements/demo.md", DEMO + "- DEMO-4：导出后归档。\n  - 例：归档里有它。\n")
    git(root, "commit", "-q", "-am", "docs: 归档的要求")
    git(root, "switch", "-q", branch)
    return git(root, "rev-parse", "main").strip()


def changed_requirements(root: Path) -> tuple[list[str], list[str], list[str]]:
    """(added, rewritten, removed) against the trunk: what `context --feature` and `close` work from."""
    base = context_module.merge_base(root, None)
    added, rewritten, removed = context_module.requirement_changes(root, base[1])
    return list(added), list(rewritten), list(removed)


# ---------------------------------------------------------------- linked worktrees

def test_the_real_pre_commit_enforces_the_design_gate_in_a_linked_worktree(tmp_path: Path) -> None:
    """A feature is usually built in `git worktree add -b feat/<name>`, where .git is a file and the hook
    runs from another folder; the gate had only ever been tested by calling scan() in a plain checkout."""
    project = tmp_path / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    write(project, "docs/requirements/demo.md", DEMO)
    git(project, "add", "-A")
    assert commit(project, "docs: 导出能力").returncode == 0
    tree = tmp_path / "wt-add-export"
    git(project, "worktree", "add", "-q", "-b", "feat/add-export", str(tree))

    def ahead() -> int:
        return int(git(tree, "rev-list", "--count", "main..HEAD"))

    def main_tree_is_clean() -> bool:
        return git(project, "status", "--porcelain") == ""

    # The drafts are written, as they are while the design is still open, and only the code is staged:
    # what settles the design is the card in this worktree's HEAD, not the card file being there.
    write(tree, "docs/requirements/demo.md", DEMO + ADDED)
    write(tree, "specs/add-export/spec.md", CARD)
    write(tree, "src/app.py", "print(1)\n")
    git(tree, "add", "src/app.py")
    refused = commit(tree, "feat(add-export): 先写了代码")
    assert refused.returncode != 0
    assert "[code-before-design]" in refused.stdout + refused.stderr
    assert ahead() == 0 and main_tree_is_clean()

    git(tree, "reset", "-q", "--", "src/app.py")
    git(tree, "add", "docs", "specs")
    design = commit(tree, "design(add-export): 导出 CSV")
    assert design.returncode == 0, design.stdout + design.stderr
    assert ahead() == 1 and main_tree_is_clean()

    git(tree, "add", "-A")
    code = commit(tree, "feat(add-export): 导出 CSV")
    assert code.returncode == 0, code.stdout + code.stderr
    assert ahead() == 2 and main_tree_is_clean()

    # The three commits above turn on HEAD and the index, which git hands to the hook. The files the
    # checkers read have to be this worktree's as well: a document broken only here stops a commit here.
    write(tree, "docs/notes.md", "[缺](missing.md)\n")
    git(tree, "add", "docs/notes.md")
    broken = commit(tree, "docs(add-export): 备注")
    assert broken.returncode != 0
    assert "[broken-link]" in broken.stdout + broken.stderr
    assert ahead() == 2 and main_tree_is_clean()


def test_context_reads_a_linked_worktree_like_a_plain_checkout(tmp_path: Path, capsys, monkeypatch) -> None:
    """HEAD and the index of a linked worktree live under the main repository's .git; context must not care."""
    # The two checkouts belong to two repositories. With the dates fixed, the same history gets the same
    # commit ids in both, so a line that prints one of them can be compared like any other.
    for name in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
        monkeypatch.setenv(name, "2024-01-01T00:00:00+00:00")
    plain = trunk(tmp_path / "plain")
    git(plain, "switch", "-q", "-c", "feat/add-export")
    app, tree = trunk(tmp_path / "app"), tmp_path / "wt"
    git(app, "worktree", "add", "-q", "-b", "feat/add-export", str(tree))
    fork = git(tree, "rev-parse", "HEAD").strip()
    tip, tip_in_plain = trunk_moves_on(app), trunk_moves_on(plain)
    assert tip == tip_in_plain != fork
    for root in (plain, tree):
        write(root, "docs/requirements/demo.md", DEMO + ADDED)
        write(root, "specs/add-export/spec.md", CARD)

    def context(root: Path, *args: str) -> str:
        monkeypatch.chdir(root)          # run inside the checkout, as an agent does: a --root comes back in hints
        assert cli.main(["context", *args]) == 0
        return capsys.readouterr().out

    def about(printed: str) -> list[str]:
        """The lines that speak of the capability or the feature: what the two checkouts have to agree on."""
        return [line for line in printed.splitlines() if "DEMO" in line or "add-export" in line]

    def drafts(printed: str) -> list[str]:
        return [line for line in about(printed) if "add-export" in line and "草稿" in line]

    drafted = context(tree, "--map")
    assert about(drafted) == about(context(plain, "--map"))
    assert drafts(drafted)                           # the card is written, not committed

    for root in (plain, tree):
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "design(add-export)")
    settled = context(tree, "--map")
    assert about(settled) == about(context(plain, "--map"))
    assert about(settled) and not drafts(settled)

    feature = context(tree, "--feature", "add-export")
    assert about(feature) == about(context(plain, "--feature", "add-export"))
    # compared against the fork point, not against where main is now: what main gained since is not
    # something this branch took away
    assert fork[:7] in feature and tip[:7] not in feature
    assert "DEMO-4" not in feature
    # the requirement the branch added is named in a line of its own: not the line of its text, and not
    # a list of everything the capability has
    assert [line for line in feature.splitlines()
            if "DEMO-3" in line and "DEMO-1" not in line and not line.startswith("- DEMO-3")]
    monkeypatch.chdir(tmp_path)                      # and asked from outside any checkout, by the root alone
    assert context_module.merge_base(tree, None) == ("main", fork)
    assert changed_requirements(tree) == (["DEMO-3"], [], [])


def test_a_detached_worktree_has_no_design_gate(tmp_path: Path) -> None:
    """The reviewer writes probes in `git worktree add --detach <tmp> HEAD`: the feature's commit, without
    its branch. The gate belongs to feat/<name>; the base to compare against is still the trunk."""
    project = trunk(tmp_path / "app")
    fork = git(project, "rev-parse", "main").strip()
    git(project, "switch", "-q", "-c", "feat/add-export")
    write(project, "docs/requirements/demo.md", DEMO + ADDED)
    git(project, "commit", "-q", "-am", "docs: 导出 CSV 的要求")       # ahead of main, and no card yet
    trunk_moves_on(project)
    copy = tmp_path / "review-copy"
    git(project, "worktree", "add", "-q", "--detach", str(copy), "HEAD")
    for root in (project, copy):
        write(root, "src/probe.py", "print(1)  # DEMO-3\n")

    assert [finding.rule for finding in spec_check.scan(project)] == ["code-before-design"]   # on the branch
    assert spec_check.scan(copy) == []

    assert context_module.merge_base(copy, None) == ("main", fork)
    assert changed_requirements(copy) == (["DEMO-3"], [], [])


# ---------------------------------------------------------------- line endings

def test_a_crlf_checkout_does_not_make_requirements_look_rewritten(tmp_path: Path, capsys) -> None:
    """Git for Windows ships core.autocrlf=true: the blob is LF, the working copy CRLF, the requirement the same."""
    project = trunk(tmp_path)
    spec = project / "docs" / "requirements" / "demo.md"
    git(project, "config", "core.autocrlf", "true")
    spec.unlink()
    git(project, "checkout", "--", "docs/requirements/demo.md")
    assert b"\r\n" in spec.read_bytes()
    git(project, "switch", "-q", "-c", "feat/add-export")

    assert changed_requirements(project) == ([], [], [])

    # an editor keeps the file's line endings: one requirement changes, every line still ends in CRLF
    spec.write_bytes(spec.read_bytes().replace("导出一条记录".encode("utf-8"), "导出选中的记录".encode("utf-8")))
    write(project, "specs/add-export/spec.md", CARD, newline="\r\n")
    # a card with no slice marked as the current one: its slice line is echoed right up to where it ends
    write(project, "specs/add-header/spec.md",
          "# add-header：表头\n\n能力：DEMO（已有）· 框架：不变\n\n## 切片\n\n- S1：写出表头\n", newline="\r\n")
    # the framework document, new on this branch: --feature prints its summary, which has two lines to join
    write(project, "docs/architecture.md",
          '# 结构\n\n<a id="summary"></a>\n## 框架摘要\n\n- 入口 → 导出服务\n- 数据归属：导出服务\n', newline="\r\n")
    assert changed_requirements(project) == ([], ["DEMO-1"], [])

    printed = {}
    for mode in (["--map"], ["--capability", "DEMO"], ["--ids", "DEMO-1,DEMO-2"], ["--feature", "add-export"]):
        assert cli.main(["context", *mode, "--root", str(project)]) == 0
        printed[mode[0]] = capsys.readouterr().out              # capsys keeps line endings as printed
    assert "\r" not in "".join(printed.values())
    assert all("导出选中的记录" in printed[mode] for mode in ("--capability", "--ids", "--feature"))
    assert "导出 CSV" in printed["--map"] and "写出表头" in printed["--map"]      # both cards' slice lines were read
    assert "数据归属：导出服务" in printed["--feature"]                          # and the summary, to its last line


def test_the_pre_commit_hook_stays_lf_in_a_clone_with_autocrlf(tmp_path: Path) -> None:
    """A CRLF hook starts with `#!/bin/sh\\r` and no commit gets through, so the project's .gitattributes has
    to outrank the clone's own autocrlf. The other LF check on this hook only runs where pwsh is installed."""
    source = tmp_path / "app"
    assert cli.main(["init", "--path", str(source), "--name", "App"]) == 0
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "-c", "core.autocrlf=true", str(source), str(clone)],
                   check=True, capture_output=True)
    assert git(clone, "config", "core.autocrlf").strip() == "true"

    assert b"\r" not in (clone / ".githooks" / "pre-commit").read_bytes()

    if shutil.which("sh") is None:
        pytest.skip("没有 sh：只确认了克隆里的 pre-commit 是 LF，没有试跑")
    ran = subprocess.run(["sh", ".githooks/pre-commit"], cwd=clone, env=own_python_first(), capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    assert ran.returncode == 0, ran.stdout + ran.stderr


def both_line_endings(root: Path, files: dict[str, str]) -> tuple[Path, Path]:
    """The same project twice: every file LF in one, CRLF in the other."""
    for name, newline in (("lf", "\n"), ("crlf", "\r\n")):
        for rel, text in files.items():
            write(root / name, rel, text, newline)
    return root / "lf", root / "crlf"


def test_spec_check_reads_crlf_files_like_lf_files(tmp_path: Path) -> None:
    """A Windows working copy is CRLF: the header must still be one clean line, IDs resolve, line numbers hold."""
    lf, crlf = both_line_endings(tmp_path, {
        "docs/requirements/demo.md": DEMO + "- DEMO-3：导出 CSV。\n  - 证明：人工演示\n",
        "tests/test_demo.py": "# DEMO-1\n\n# DEMO-9\n",
    })

    found = spec_check.scan(crlf)

    # no bad-header, DEMO-1 resolves, and the one dangling reference is on the line an editor shows
    assert [(finding.rule, finding.path, finding.line) for finding in found] == [
        ("dangling-ref", "tests/test_demo.py", 3)]
    assert found == spec_check.scan(lf)
    assert spec_check.report(crlf) == spec_check.report(lf)
    assert "DEMO-1" not in "".join(spec_check.report(crlf))      # it has a test, in either line ending


def test_doc_guard_reads_crlf_files_like_lf_files(tmp_path: Path) -> None:
    """Same for the documents: the summary anchor is found, a fence closes, a link at the end of a line is
    followed, and a finding names the right line."""
    lf, crlf = both_line_endings(tmp_path, {
        "docs/architecture.md": '# 结构\n\n<a id="summary"></a>\n## 框架摘要\n\n- 入口 → 导出服务 → 文件\n\n'
                                "## 细节\n\n```\nD-001\n```\n\n见 D-036\n",
        "docs/a.md": "[框架摘要](architecture.md#summary)\n\n[缺](missing.md)\n",
    })

    found = doc_guard.scan(crlf)

    # the link to the summary resolves and the one to nothing is on line 3; no arch-summary, nothing from
    # inside the fence, and D-036 on line 14
    assert [(finding.rule, finding.path, finding.line) for finding in found] == [
        ("broken-link", "docs/a.md", 3), ("decision-id", "docs/architecture.md", 14)]
    assert found == doc_guard.scan(lf)


# ---------------------------------------------------------------- console encoding

@pytest.mark.parametrize("args, code, printed, complained", [
    (["context", "--map", "--root", "<project>"], 0, "订单能力", ""),
    (["check", "--root", "<project>"], 0, "通过", ""),
    (["rules"], 0, "决策台账", ""),
    (["migrate", "--check", "--project", "<project>"], 1, "迁移检查", ""),
    (["context", "--map", "--root", "<project>/没有这个目录"], 2, "", "没有这个目录"),
], ids=["context --map", "check", "rules", "migrate --check", "context --map without its folder"])
def test_cli_output_is_utf8_under_a_gbk_console(tmp_path: Path, gbk_env: dict[str, str], args: list[str],
                                                code: int, printed: str, complained: str) -> None:
    """Piped on Chinese Windows, stdout and stderr default to GBK; an agent reads what devcircuit prints as UTF-8.

    The checkers run as scripts and the stderr of `ledger check` had this pinned; the commands an agent
    reads first did not. The last case is there for stderr: the four before it print nothing to it, and
    this one has to name the folder it was given, so what is looked for there is Chinese as well.
    """
    write(tmp_path, "docs/requirements/order.md", "# 订单能力\n代号：ORDER\n\n- ORDER-1：下单。\n  - 例：下单成功。\n")
    write(tmp_path, "specs/backlog.md", "# 待做池\n")
    args = [arg.replace("<project>", str(tmp_path)) for arg in args]
    env = {**gbk_env, "PYTHONPATH": TOOLS}
    for name in ("DEVCIRCUIT_LEDGER", "DEVCIRCUIT_PROJECT"):     # a ledger side's settings stay out of migrate
        env.pop(name, None)

    result = subprocess.run([sys.executable, "-m", "devcircuit.cli", *args], capture_output=True,
                            cwd=tmp_path, env=env)

    out, err = result.stdout.decode("utf-8"), result.stderr.decode("utf-8")     # strict: GBK bytes do not decode
    assert result.returncode == code, out + err
    assert printed in out and complained in err


# ---------------------------------------------------------------- shells

def in_shell(shell: str, command: str, payload: bytes, cwd: Path) -> subprocess.CompletedProcess:
    """Hand the command line to `shell` as a harness would; skip where this machine has no such shell."""
    found = shutil.which(shell) if shell != "cmd" or os.name == "nt" else None
    if found is None:
        pytest.skip(f"这台机器上没有 {shell}")
    # On Windows a `bash` in System32 or WindowsApps is the WSL launcher: it runs, but in another system,
    # where the hook's C:/… path names nothing. Hooks on Windows run in Git Bash, not in there.
    if os.name == "nt" and shell == "bash" and Path(found).parent.name.lower() in ("system32", "windowsapps"):
        pytest.skip("PATH 上的 bash 是 WSL 的启动器，不是这台机器上的 shell")
    argv = {"cmd": f'cmd /d /s /c "{command}"',
            "pwsh": [found, "-NoProfile", "-Command", command]}.get(shell, [found, "-c", command])
    return subprocess.run(argv, cwd=cwd, input=payload, capture_output=True, env=own_python_first(), timeout=120)


def names(text: str, path: Path) -> bool:
    """Whether the text spells this path, in either slash direction and any case."""
    return str(path).replace("\\", "/").casefold() in text.replace("\\", "/").casefold()


def hook_call(project: Path, ledger: Path, capsys) -> tuple[str, bytes]:
    """Install the Claude hook for `project`; return its command line and a call that reads from `ledger`.

    The call reaches the ledger without spelling where it is, so the answer has no reason to either.
    The bytes are what a harness sends: UTF-8 with the non-ASCII part of the project's path as it is,
    not as backslash-u escapes, so each shell also has to hand them to the hook untouched.
    """
    project.mkdir(parents=True)
    ledger.mkdir(parents=True)
    assert cli.main(["hooks", "install", "--harness", "claude",
                     "--project", str(project), "--ledger", str(ledger)]) == 0
    capsys.readouterr()
    snippet = json.loads((project / ".dev-circuit" / "claude-settings.hook.json").read_text(encoding="utf-8"))
    reach = Path(os.path.relpath(ledger / "entries" / "x.md", project)).as_posix()
    payload = json.dumps({"cwd": str(project), "tool_name": "Read", "tool_input": {"file_path": reach}},
                         ensure_ascii=False).encode("utf-8")
    assert not payload.isascii()
    return snippet["hooks"]["PreToolUse"][0]["hooks"][0]["command"], payload


@pytest.mark.parametrize("shell", ["cmd", "sh", "bash", "pwsh"])
def test_the_claude_hook_command_works_in_each_shell(tmp_path: Path, capsys, shell: str) -> None:
    """Claude Code hands the hook command to whichever shell the machine has; the other test of this
    command tries the platform's default one only (cmd on Windows, sh elsewhere).

    The contract is exit 2 to block and exit 0 when the script is not there. `pwsh -Command` folds a
    native exit code into 0 or 1, so the 2 arrives as 1: the test says "not 0" for pwsh because that is
    what happens there, not because 1 is known to block.
    """
    project, ledger = tmp_path / "app", tmp_path / "ledgers" / "app"
    command, payload = hook_call(project, ledger, capsys)

    blocked = in_shell(shell, command, payload, project)
    said = blocked.stdout.decode("utf-8", errors="replace") + blocked.stderr.decode("utf-8", errors="replace")
    if shell == "pwsh":
        assert blocked.returncode != 0, said
    else:
        assert blocked.returncode == 2, said
    assert "账本边界" in blocked.stderr.decode("utf-8", errors="replace")
    assert not names(said, ledger)

    # e.g. an older branch checked out, with no .dev-circuit/hooks yet: step aside, do not block every call
    (project / ".dev-circuit" / "hooks" / "ledger_guard.py").unlink()
    gone = in_shell(shell, command, payload, project)
    assert gone.returncode == 0, gone.stderr.decode("utf-8", errors="replace")


EXPANDED = pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="已知缺口，产品没修：hook 命令把脚本路径放在双引号里，目录名里的 $NAME（sh、bash、pwsh）或 %NAME%（cmd）"
           "被 shell 展开，路径对不上，启动器当成脚本不在而放行")


@pytest.mark.parametrize("shell, folder", [
    pytest.param("sh", "a$HOME b", marks=EXPANDED), pytest.param("bash", "a$HOME b", marks=EXPANDED),
    pytest.param("pwsh", "a$HOME b", marks=EXPANDED), ("cmd", "a$HOME b"),
    pytest.param("cmd", "100%OS% x", marks=EXPANDED), ("sh", "100%OS% x"),
])
def test_the_claude_hook_command_blocks_under_a_folder_name_a_shell_would_expand(tmp_path: Path, capsys, shell: str,
                                                                                 folder: str) -> None:
    """A gap in the product, pinned as it stands until it is closed: take the mark off the cases that pass.

    The command spells the script's path inside double quotes, where sh, bash and pwsh still expand $NAME
    and cmd expands %NAME%. The path the launcher gets then names nothing, it takes the script for absent
    and steps aside, and the ledger boundary is off without a word. The two unmarked cases are the same
    folders under a shell that leaves the name alone: the folder name by itself breaks nothing.
    """
    project, ledger = tmp_path / folder / "app", tmp_path / folder / "ledgers" / "app"
    command, payload = hook_call(project, ledger, capsys)

    blocked = in_shell(shell, command, payload, project)

    assert blocked.returncode != 0, blocked.stderr.decode("utf-8", errors="replace")
