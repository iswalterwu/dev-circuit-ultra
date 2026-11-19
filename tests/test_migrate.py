"""devcircuit migrate --check: list what an older project must change, and change nothing."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import devcircuit.cli as cli
import devcircuit.migrate as migrate
from devcircuit._loader import script_path


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file() and ".git" not in path.parts}


def test_migrate_lists_what_an_old_project_must_change(tmp_path: Path, capsys) -> None:
    project = tmp_path / "old"
    assert cli.main(["init", "--path", str(project), "--name", "Old"]) == 0
    write(project, "AGENTS.md", "# Old\n\n| 做或续做一个功能 | `specs/<feature>/spec.md`（框架级再读同目录的 `design.md`） |\n")
    write(project, "specs/building/spec.md", "# building\n\n## 目标\n\n楼。\n\n## 规格变化\n\n- 新增 WIN-30\n\n## 切片\n\n- S1：骨架\n")
    write(project, "specs/building/design.md", "# 结构\n")
    write(project, ".dev-circuit/reviewer.json", json.dumps({"mode": "agent"}))
    write(project, "docs/architecture.md", "# 结构\n\n正文\n")
    write(project, "docs/README.md", "# 文档地图\n\n| 文档 | 回答什么 |\n|---|---|\n| [a](a.md) | a |\n")
    write(project, "scripts/doc_guard.py", "# an old copy\n")
    capsys.readouterr()
    before = snapshot(project)

    code = cli.main(["migrate", "--check", "--project", str(project)])
    out = capsys.readouterr().out

    assert code == 1
    for expected in ("specs/building/design.md", "“规格变化”", "“能力：", "reviewer.json",
                     "AGENTS.md 的路由还提到 design.md", "devcircuit context", "审核模型",
                     "docs/architecture.md 缺框架摘要", "scripts/doc_guard.py 不是当前版本",
                     "没有配置账本", "docs/README.md 还有手写的登记表", "specs/ 下有未提交的改动"):
        assert expected in out, expected
    assert snapshot(project) == before


def test_migrate_is_quiet_for_a_current_project(tmp_path: Path, capsys) -> None:
    project, ledger = tmp_path / "app", tmp_path / "ledgers" / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    assert cli.main(["ledger", "init", "--path", str(ledger)]) == 0
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": str(ledger)}))  # gitignored by the template
    assert subprocess.run(["git", "-C", str(project), "status", "--porcelain"], capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout.strip() == ""
    capsys.readouterr()

    code = cli.main(["migrate", "--check", "--project", str(project)])

    assert code == 0, capsys.readouterr().out
    assert "没有要改的" in capsys.readouterr().out


@pytest.mark.parametrize("older, newer", [
    ('VERSION = "0.9.0"\n', 'VERSION = "0.10.0"\n'),
    ('"""A checker."""\n\nVERSION = \'0.7.1\'\n', 'import re\n\nVERSION = "0.7.2"\nRULES = ()\n'),
    ("outdated\n", 'VERSION = "0.0.1"\n'),
    ('VERSION = "next"\n', 'VERSION = "0.0.1"\n'),
    ('MIN_VERSION = "9.9"\nVERSION = "0.0.1"\n', 'VERSION = "0.0.2"\n'),
], ids=["numbers-not-text", "anywhere-in-the-file", "no-version", "not-a-number", "another-constant-ending-in-version"])
def test_checker_versions_compare_as_numbers_and_an_unreadable_one_is_the_oldest(older: str, newer: str) -> None:
    """`vendor` and `migrate --check` tell a copy to refresh from one to leave alone by this order."""
    assert migrate.checker_version(older) < migrate.checker_version(newer)


@pytest.mark.parametrize("name", ["doc_guard", "spec_check"])
def test_the_packaged_checkers_declare_a_version_the_comparison_reads(name: str) -> None:
    """Without a readable VERSION in the packaged copy, every project copy would look newer or the same."""
    assert migrate.checker_version(script_path(name).read_text(encoding="utf-8")) > (0,)


def declare_version(checker: Path, version: str) -> None:
    """Give a vendored checker another VERSION, as a copy from an older or a later devcircuit has."""
    lines = checker.read_text(encoding="utf-8").splitlines(keepends=True)
    [index] = [index for index, line in enumerate(lines) if line.startswith("VERSION = ")]
    lines[index] = f'VERSION = "{version}"\n'
    checker.write_text("".join(lines), encoding="utf-8", newline="\n")


def test_migrate_says_which_way_a_vendored_checker_differs(tmp_path: Path, capsys) -> None:
    """`devcircuit vendor` is the wrong advice for a copy newer than this machine's devcircuit: it is the tool that is behind."""
    project = tmp_path / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    declare_version(project / "scripts" / "spec_check.py", "99.0.0")
    declare_version(project / "scripts" / "doc_guard.py", "0.0.1")
    capsys.readouterr()

    assert cli.main(["migrate", "--check", "--project", str(project)]) == 1
    lines = capsys.readouterr().out.splitlines()
    [newer] = [line for line in lines if "scripts/spec_check.py" in line]
    [older] = [line for line in lines if "scripts/doc_guard.py" in line]
    assert "scripts/spec_check.py 比本机 devcircuit 带的新：先升级本机 devcircuit，不要跑 vendor" in newer
    assert "devcircuit vendor" not in newer
    assert "scripts/doc_guard.py 不是当前版本：devcircuit vendor --project" in older


def test_migrate_leaves_a_project_design_doc_alone(tmp_path: Path, capsys) -> None:
    # Only the retired per-feature design.md is old routing; docs/design.md is the project's own doc.
    project = tmp_path / "ui"
    assert cli.main(["init", "--path", str(project), "--name", "UI"]) == 0
    agents = project / "AGENTS.md"
    agents.write_text(agents.read_text(encoding="utf-8") + "\n| 改界面 | `docs/design.md` |\n", encoding="utf-8")
    capsys.readouterr()

    cli.main(["migrate", "--check", "--project", str(project)])
    assert "design.md" not in capsys.readouterr().out


def test_migrate_flags_a_claude_hook_command_that_blocks_without_its_script(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    old = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
        {"type": "command", "command": f'python3 "{project / ".dev-circuit/hooks/ledger_guard.py"}"'}]}]}}
    write(project, ".claude/settings.local.json", json.dumps(old))
    capsys.readouterr()

    cli.main(["migrate", "--check", "--project", str(project)])
    out = capsys.readouterr().out
    assert ".claude/settings.local.json" in out and "hooks install --harness claude" in out

    write(project, ".claude/settings.local.json", cli.claude_snippet(project / ".dev-circuit/hooks/ledger_guard.py"))
    cli.main(["migrate", "--check", "--project", str(project)])
    assert ".claude/settings.local.json" not in capsys.readouterr().out


def test_migrate_reports_files_over_the_size_limits(tmp_path: Path, capsys) -> None:
    project = tmp_path / "big"
    assert cli.main(["init", "--path", str(project), "--name", "Big"]) == 0
    write(project, "specs/big/spec.md", "# big\n\n能力：BIG（新建）· 框架：不变\n" + "- 行\n" * 85)
    write(project, "docs/requirements/big.md", "# 大\n代号：BIG\n" + "- 行\n" * 401)
    capsys.readouterr()

    assert cli.main(["migrate", "--check", "--project", str(project)]) == 1
    out = capsys.readouterr().out
    assert "specs/big/spec.md" in out and "超过 80 行" in out
    assert "docs/requirements/big.md" in out and "超过 400 行" in out


def test_migrate_names_uncommitted_files_with_non_ascii_names_as_they_are(tmp_path: Path, capsys) -> None:
    """Left alone, git quotes a non-ASCII path and prints it octal-escaped; nobody can read which card that is."""
    project = tmp_path / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    write(project, "specs/订单导出/spec.md", "# 订单导出\n\n能力：ORD（新建）· 框架：不变\n")
    capsys.readouterr()

    assert cli.main(["migrate", "--check", "--project", str(project)]) == 1
    assert "specs/ 下有未提交的改动（specs/订单导出/spec.md）" in capsys.readouterr().out


def test_migrate_accepts_a_human_side_ledger(tmp_path: Path, capsys) -> None:
    # Strong isolation keeps the ledger on the human side; that is a setup, not a to-do.
    project = tmp_path / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": "/not/mounted", "ledger_side": "human"}))
    capsys.readouterr()

    assert cli.main(["migrate", "--check", "--project", str(project)]) == 0, capsys.readouterr().out


def test_migrate_flags_a_ci_workflow_that_never_runs_on_the_trunk(tmp_path: Path, capsys) -> None:
    """An earlier adopt wrote main into the workflow whatever the trunk was, and no command compared the two."""
    project = tmp_path / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    agents = project / "AGENTS.md"
    agents.write_text(agents.read_text(encoding="utf-8").replace("主干：`main`", "主干：`workbench`"),
                      encoding="utf-8")
    capsys.readouterr()

    assert cli.main(["migrate", "--check", "--project", str(project)]) == 1
    flagged = [line for line in capsys.readouterr().out.splitlines() if ".github/workflows/" in line]
    assert len(flagged) == 2
    assert ".github/workflows/doc-guard.yml:5：push 只在 main 上触发，AGENTS.md 的主干是 workbench" in flagged[0]
    assert ".github/workflows/doc-guard.yml:7：pull_request 只在 main 上触发，AGENTS.md 的主干是 workbench" in flagged[1]
    assert all("把 workbench 写进这里的 branches" in line and ".dcuignore" in line for line in flagged)


def workflow_actions(project: Path, workflow: str, trunk: str | None = "workbench", name: str = "ci.yml") -> list[str]:
    """What `migrate --check` lists about the CI workflows of a project whose AGENTS.md names `trunk`."""
    write(project, "AGENTS.md", "# 项目\n" + (f"\n- 主干：`{trunk}`\n" if trunk else ""))
    path = project / ".github" / "workflows" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(workflow.encode("utf-8"))  # bytes: a CRLF or a BOM in the text reaches the file as written
    return [action for action in migrate.check(project) if action.startswith(".github/workflows/")]


@pytest.mark.parametrize("workflow, trunk, lines", [
    ('name: Doc guard\n\non:\n  push:\n    branches: [ "main" ]\n  pull_request:\n    branches: [ "main" ]\n'
     "  workflow_dispatch:\n\njobs:\n  doc-guard:\n    steps:\n      - uses: some/action@v1\n        with:\n"
     "          branches: nope\n", "workbench", [5, 7]),
    ("on:\n  pull_request:\n    branches: [main, 'release/**']\njobs: {}\n", "workbench", [3]),
    ("on:\n  push:\n    branches:\n      - main\n      - 'release/**'\n  pull_request:\njobs: {}\n", "workbench", [3]),
    ("on:\n  push:\n    branches:\n    - main\n    - develop\njobs: {}\n", "workbench", [3]),
    ("on:\n  push:\n    branches: main\n", "workbench", [3]),
    ('"on":\n  push:\n    branches: [main]\n', "workbench", [3]),
    ("\ufeffon:  # triggers\r\n  push:\r\n    branches: [ main ]  # the trunk, once\r\n", "workbench", [3]),
    ("on:\n  push:\n    branches: ['rel*']\n", "workbench", [3]),
    ("on:\n  push:\n    branches: ['*']\n", "team/trunk", [3]),
    ("on:\n  pull_request:\n    branches-ignore: [main]\n  push:\n    branches: [main]\n", "workbench", [5]),
    ("on:\n  push:\n    # don't run on feature branches\n    branches:\n      - main\n      # isn't the trunk\n"
     "      - develop\n", "workbench", [4]),
    ("on:\n  push:\n    branches: [main]\n# don't run on feature branches\n  pull_request:\n    branches: [main]\n",
     "workbench", [3, 6]),
    ('on:\n  push:\n    branches: [main]  # don\'t add more\n  pull_request:\n    branches: main  # "main" only\n',
     "workbench", [3, 5]),
    ('on:\n  "push":\n    \'branches\': [main]\n', "workbench", [3]),
    ("on:\n  push:\n    branches: [main, develop,]\n", "workbench", [3]),
    ("on:\n  push:\n    branches: [main]\n    paths:\n      - 'docs/**'\n", "workbench", [3]),
    ("on:\n  push:\n    branches: ['v1.0']\n", "v1x0", [3]),
    ('name: Python application\n\non:\n  push:\n    branches: [ "main" ]\n  pull_request:\n    branches: [ "main" ]\n\n'
     "permissions:\n  contents: read\n\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n"
     "    - uses: actions/checkout@v4\n    - name: Install dependencies\n      run: |\n"
     "        python -m pip install --upgrade pip\n"
     "        if [ -f requirements.txt ]; then pip install -r requirements.txt; fi\n", "workbench", [5, 7]),
    ("on:\n  push:\n    branches: ['*/trunk']\n", "org/team/trunk", [3]),
    ("on:\n  push:\n    branches: ['work*x']\n", "workbench", [3]),
    ("on:\n  push:\n    branches: [work, bench, 'ork*']\n", "workbench", [3]),
], ids=["one-line-list-on-both-events", "one-line-list-bare", "block-list", "block-list-at-the-keys-indent",
        "single-name", "quoted-on", "comments-crlf-bom", "glob-that-misses", "star-stops-at-a-slash",
        "beside-a-branches-ignore", "comment-lines-with-an-apostrophe", "comment-at-the-margin-with-an-apostrophe",
        "trailing-comments-with-quotes", "quoted-keys", "trailing-comma", "beside-a-paths-list",
        "dot-is-not-a-wildcard", "script-bodies-after-the-on-block", "star-before-a-name-stops-at-a-slash",
        "name-after-a-star-has-to-end-it", "names-that-are-only-part-of-the-trunk"])
def test_migrate_flags_a_branch_filter_that_leaves_the_trunk_out(
        tmp_path: Path, workflow: str, trunk: str, lines: list[int]) -> None:
    actions = workflow_actions(tmp_path, workflow, trunk)

    assert [action.split("：")[0] for action in actions] == [f".github/workflows/ci.yml:{line}" for line in lines]
    assert all(f"主干是 {trunk}" in action for action in actions)


@pytest.mark.parametrize("workflow, trunk", [
    ('on:\n  push:\n    branches: [ "main", "workbench" ]\n', "workbench"),
    ("on:\n  push:\n    branches:\n      - main\n      - workbench\n", "workbench"),
    ("on:\n  push:\n    branches: ['work*']\n", "workbench"),
    ("on:\n  push:\n    branches: ['**']\n", "workbench"),
    ("on:\n  push:\n    branches: ['**']\n", "team/trunk"),
    ("on:\n  push:\n    branches: ['team/*']\n", "team/trunk"),
    ("on:\n  push:\n    branches: ['*/trunk']\n", "team/trunk"),
    ("on:\n  push:\n    branches: ['**/trunk']\n", "org/team/trunk"),
    ("on:\n  push:\n    branches: ['w*k*h']\n", "workbench"),
    ("on:\n  push:\n    branches: ['workbench*']\n", "workbench"),
    ("on:\n  push:\n    branches: ['***']\n", "team/trunk"),
    ("on: push\njobs: {}\n", "workbench"),
    ("on: [push, pull_request]\njobs: {}\n", "workbench"),
    ("on:\n  - push\n  - pull_request\njobs: {}\n", "workbench"),
    ("on:\n  push:\n    tags: ['v*']\n    paths: ['docs/**']\n  schedule:\n    - cron: '0 3 * * *'\n", "workbench"),
    ("on:\n  push:\n    branches: [workbench]\n  pull_request:\n  workflow_dispatch:\n", "workbench"),
    ("on:\n  workflow_run:\n    workflows: [Build]\n    branches: [main]\n", "workbench"),
    ("jobs: {}\n", "workbench"),
], ids=["named-among-others", "named-in-a-block-list", "glob", "double-star", "double-star-crosses-a-slash",
        "star-within-a-segment", "star-before-a-name", "double-star-before-a-name", "stars-inside-a-name",
        "star-for-nothing", "more-stars-than-two", "on-push", "on-list", "on-block-list", "tags-and-paths-only",
        "pull-request-unfiltered", "another-events-branches", "no-on"])
def test_migrate_accepts_a_workflow_that_runs_on_the_trunk(tmp_path: Path, workflow: str, trunk: str) -> None:
    """No `branches:` on an event means every branch; a filter counts when a name or a glob lets the trunk through."""
    assert workflow_actions(tmp_path, workflow, trunk) == []


@pytest.mark.parametrize("workflow", [
    "on:\n  push:\n    branches-ignore: [main]\n",
    "on:\n  push:\n    branches: ['main', '!main/old']\n",
    "on:\n  push:\n    branches:\n      - main\n      - '!main/old'\n",
    "on: {push: {branches: [main]}}\n",
    "on:\n  push: {branches: [main]}\n",
    "on:\n  push:\n    branches: [\n      main\n    ]\n",
    "on:\n  push:\n    branches: [main,\n      workbench]\n",
    "on:\n  push:\n    branches:\n      - main\n      -\n        workbench\n",
    "on:\n  push:\n    branches: &trunks [main]\n  pull_request:\n    branches: *trunks\n",
    "on:\n  push:\n    branches: *trunks\n",
    "on:\n\tpush:\n\t\tbranches: [main]\n",
    "on:\n  push:\n  \tbranches: [main]\n",
    "on:\n  push:\n    branches: ['v[0-9]+']\n",
    "on:\n  push:\n    branches: ['workbenchx?']\n",
    "on:\n  push:\n    branches: ['']\n",
    "on:\n  push:\n    branches:\n  pull_request:\n",
    "on:\n  push:\n    branches: [main]\n  pull_request:\n    branches: ['main', '!main/old']\n",
], ids=["branches-ignore", "negation", "negation-in-a-block-list", "flow-mapping", "flow-mapping-on-the-event",
        "list-over-several-lines", "list-broken-after-its-first-entry", "entry-on-the-line-after-its-dash",
        "anchor-and-alias", "alias",
        "tab-indentation", "tab-after-spaces", "character-class", "optional-character", "empty-name", "empty-filter",
        "one-unread-part-drops-the-file"])
def test_migrate_says_nothing_about_a_workflow_it_cannot_read(tmp_path: Path, workflow: str) -> None:
    """A text scan, not a YAML parser: where it is not sure what a filter means, it lists nothing rather than guess."""
    assert workflow_actions(tmp_path, workflow) == []


@pytest.mark.parametrize("pattern, trunk, listed", [
    ("*" * 60 + "!", "workbench", False),  # `!` is not read, so nothing is said about this one
    ("*" * 60 + "x", "release/2026.10-stable", True),
    ("*a" * 20 + "b", "a" * 60, True),
], ids=["stars-and-a-negation", "stars-before-a-letter", "stars-between-letters"])
def test_migrate_is_not_stalled_by_a_filter_full_of_stars(tmp_path: Path, pattern: str, trunk: str, listed: bool) -> None:
    """Reading a pattern and matching it both backtracked: each further `*` multiplied the time, and a few dozen stalled the command."""
    write(tmp_path, "AGENTS.md", f"# 项目\n\n- 主干：`{trunk}`\n")
    write(tmp_path, ".github/workflows/ci.yml", f"on:\n  push:\n    branches: ['{pattern}']\n")
    env = {**os.environ, "PYTHONPATH": str(Path(cli.__file__).resolve().parents[1])}

    done = subprocess.run([sys.executable, "-B", "-m", "devcircuit.cli", "migrate", "--check", "--project", str(tmp_path)],
                          env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert "审核模型" in done.stdout, done.stderr  # the check ran to its end and listed the rest
    assert (".github/workflows/ci.yml:3：push 只在" in done.stdout) == listed


def test_migrate_does_not_take_a_folder_for_a_workflow(tmp_path: Path) -> None:
    (tmp_path / ".github" / "workflows" / "composite.yml").mkdir(parents=True)

    assert len(workflow_actions(tmp_path, "on:\n  push:\n    branches: [main]\n")) == 1


def test_migrate_reads_only_the_workflows_github_loads(tmp_path: Path) -> None:
    """GitHub runs the files right under .github/workflows; one in a folder below it is not a workflow."""
    write(tmp_path, ".github/workflows/shared/build.yml", "on:\n  push:\n    branches: [main]\n")

    actions = workflow_actions(tmp_path, "on:\n  push:\n    branches: [main]\n")
    assert [action.split("：")[0] for action in actions] == [".github/workflows/ci.yml:3"]


def test_migrate_names_a_workflow_with_a_non_ascii_name(tmp_path: Path) -> None:
    [action] = workflow_actions(tmp_path, "on:\n  push:\n    branches: [main]\n", name="检查.yaml")

    assert action.startswith(".github/workflows/检查.yaml:3：push 只在 main 上触发")


def test_migrate_skips_a_workflow_listed_in_dcuignore(tmp_path: Path) -> None:
    """A workflow meant for another branch only, a release one say, is the project's call."""
    write(tmp_path, ".dcuignore", "# 发布流程只在 release 上跑\n.github/workflows/release.yml\n")
    release_only = "on:\n  push:\n    branches: [release]\n"

    assert workflow_actions(tmp_path, release_only, name="release.yml") == []
    assert len(workflow_actions(tmp_path, release_only, name="ci.yml")) == 1


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def repo_on(root: Path, branch: str) -> Path:
    write(root, "README.md", "# r\n")
    for args in (("init", "-q", "-b", branch), ("add", "-A"), ("commit", "-q", "-m", "init")):
        git(root, *args)
    return root


ONLY_ON_MAIN = 'on:\n  push:\n    branches: [ "main" ]\n'


def test_migrate_does_not_guess_a_trunk_to_hold_the_workflows_against(tmp_path: Path) -> None:
    """AGENTS.md names no trunk and there is no origin/HEAD: a local branch name is not enough to call a workflow wrong."""
    repo = repo_on(tmp_path / "repo", "main")

    assert workflow_actions(repo, 'on:\n  push:\n    branches: [ "develop" ]\n', trunk=None) == []


def test_migrate_leaves_the_workflows_until_a_broken_trunk_line_is_fixed(tmp_path: Path) -> None:
    write(tmp_path, ".github/workflows/ci.yml", ONLY_ON_MAIN)
    write(tmp_path, "AGENTS.md", "# 项目\n\n- 主干：\n")

    actions = migrate.check(tmp_path)
    assert any("主干一行没写分支名" in action for action in actions)
    assert [action for action in actions if ".github/workflows/" in action] == []


def test_migrate_holds_the_workflows_against_the_remote_default_when_agents_names_no_trunk(tmp_path: Path) -> None:
    remote = repo_on(tmp_path / "remote", "workbench")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)

    [action] = workflow_actions(clone, ONLY_ON_MAIN, trunk=None)
    assert action.startswith(".github/workflows/ci.yml:3：push 只在 main 上触发，远端默认分支是 workbench")

    # A local main next to a remote default of workbench: which one is the trunk is the open question,
    # and migrate asks that first instead of calling the workflow wrong on a guess.
    git(clone, "branch", "main")
    assert workflow_actions(clone, ONLY_ON_MAIN, trunk=None) == []
    assert any("确认哪个是主干" in action for action in migrate.check(clone))


def test_migrate_holds_the_workflows_against_the_agents_trunk_not_the_remote_default(tmp_path: Path) -> None:
    """A remote often keeps main as its default after the team moved to another trunk; AGENTS.md is where the project says which."""
    remote = repo_on(tmp_path / "remote", "main")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)

    [action] = workflow_actions(clone, ONLY_ON_MAIN, trunk="workbench")
    assert action.startswith(".github/workflows/ci.yml:3：push 只在 main 上触发，AGENTS.md 的主干是 workbench")
    assert workflow_actions(clone, 'on:\n  push:\n    branches: [ "workbench" ]\n', trunk="workbench") == []


def test_migrate_has_nothing_to_say_about_the_workflow_adopt_writes(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "workbench")
    assert cli.main(["init", "--path", str(repo), "--adopt"]) == 0

    assert [action for action in migrate.check(repo) if ".github/workflows/" in action] == []


def test_migrate_asks_for_a_trunk_line_when_the_remote_default_differs(tmp_path: Path, capsys) -> None:
    """Without a trunk line the base is main / master first; a different remote default needs a decision."""
    remote = tmp_path / "remote"
    write(remote, "README.md", "# r\n")
    for args in (("init", "-q", "-b", "workbench"), ("add", "-A"), ("commit", "-q", "-m", "init")):
        subprocess.run(["git", "-C", str(remote), *args], check=True, capture_output=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(clone), "branch", "main"], check=True, capture_output=True)

    cli.main(["migrate", "--check", "--project", str(clone)])
    assert any("主干" in line and "workbench" in line for line in capsys.readouterr().out.splitlines())
