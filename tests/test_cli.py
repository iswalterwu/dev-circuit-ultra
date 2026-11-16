"""The guards are also a CLI; these tests cover the wrapper, not the rules."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import devcircuit.cli as cli


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_version(capsys) -> None:
    assert cli.main(["--version"]) == 0
    assert "devcircuit" in capsys.readouterr().out


COMMIT = "61a639c34b08e5c9668ca5854a1a0b795f496b4b"
CHECKOUT = str(Path(cli.__file__).resolve().parents[1])


def _git_install(commit: str = COMMIT, vcs: str = "git") -> str:
    """What pip writes into direct_url.json for `pip install git+…` (PEP 610)."""
    return json.dumps({"url": "https://example.invalid/dev-circuit-ultra.git",
                       "vcs_info": {"vcs": vcs, "requested_revision": "main", "commit_id": commit}})


def _dist_info(site: Path, direct_url: str | None, version: str = cli.__version__) -> None:
    """The metadata pip leaves beside an installed package; direct_url.json is what it adds for a URL install."""
    info = site / f"devcircuit-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: devcircuit\nVersion: {version}\n",
                                   encoding="utf-8")
    if direct_url is not None:
        (info / "direct_url.json").write_text(direct_url, encoding="utf-8")


def _installed_copy(site: Path, direct_url: str | None) -> str:
    """A copy of the package with pip's metadata beside it, the way site-packages holds an install."""
    shutil.copytree(Path(cli.__file__).resolve().parent, site / "devcircuit",
                    ignore=shutil.ignore_patterns("__pycache__"))
    _dist_info(site, direct_url)
    return str(site)


def _version_line(python_path: str, cwd: Path) -> str:
    result = subprocess.run([sys.executable, "-m", "devcircuit.cli", "--version"], capture_output=True,
                            cwd=cwd, env={**os.environ, "PYTHONPATH": python_path})
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return result.stdout.decode("utf-8").strip()


@pytest.mark.parametrize("commit", [COMMIT, "a1b2c3d" + "0" * 57], ids=["sha1", "sha256"])
def test_version_names_the_commit_of_a_git_install(tmp_path: Path, commit: str) -> None:
    """`pipx install git+…` installs whatever main holds, so the version alone cannot tell two builds apart."""
    site = _installed_copy(tmp_path / "site", _git_install(commit))

    assert _version_line(site, tmp_path) == f"devcircuit {cli.__version__} (git {commit[:7]})"


@pytest.mark.parametrize("direct_url", [
    None,
    json.dumps({"url": "file:///src/dev-circuit-ultra", "dir_info": {}}),
    "{",
    "[]",
    "[" * 100_000,
    json.dumps({"vcs_info": "git"}),
    json.dumps({"vcs_info": {"vcs": "git", "commit_id": 61}}),
    _git_install("main && echo"),
    _git_install(COMMIT[:7]),
    _git_install(COMMIT[:-1]),
    _git_install(COMMIT + "0"),
    _git_install(vcs="hg"),
], ids=["wheel-or-index", "from-a-folder", "cut-short", "not-an-object", "nested-too-deep", "vcs-info-not-an-object",
        "commit-not-text", "commit-not-a-hash", "short-hash", "one-digit-short", "one-digit-long", "not-git"])
def test_version_is_plain_when_pip_recorded_no_commit(tmp_path: Path, direct_url: str | None) -> None:
    """Only a git install has a commit, a full one; anything else, readable or not, prints the bare version and exits 0."""
    site = _installed_copy(tmp_path / "site", direct_url)

    assert _version_line(site, tmp_path) == f"devcircuit {cli.__version__}"


def test_version_of_a_checkout_does_not_borrow_the_commit_of_an_install(tmp_path: Path) -> None:
    """Run from a checkout while a git install of the same version is also on the path: its commit is not this code's."""
    installed = _installed_copy(tmp_path / "site", _git_install())

    assert _version_line(os.pathsep.join([CHECKOUT, installed]), tmp_path) == f"devcircuit {cli.__version__}"


def test_version_ignores_metadata_whose_package_is_gone(tmp_path: Path) -> None:
    """A dist-info with no package beside it (a half-removed install) describes nothing that is running."""
    _dist_info(tmp_path / "other", _git_install())

    assert _version_line(os.pathsep.join([str(tmp_path / "other"), CHECKOUT]), tmp_path) == f"devcircuit {cli.__version__}"


def test_version_skips_metadata_left_behind_by_another_version(tmp_path: Path) -> None:
    """`pip install --target --upgrade` leaves the old dist-info next to the new one; only the new one is this code's."""
    site = _installed_copy(tmp_path / "site", _git_install())
    _dist_info(Path(site), _git_install("b" * 40), version="0.0.1")
    _dist_info(Path(site), _git_install("c" * 40), version="99.0.0")

    assert _version_line(site, tmp_path) == f"devcircuit {cli.__version__} (git 61a639c)"


def test_other_commands_do_not_load_the_metadata_machinery(tmp_path: Path) -> None:
    """importlib.metadata costs more to import than the lookup itself; only `--version` pays for either."""
    script = ("import sys; before = 'importlib.metadata' in sys.modules; from devcircuit import cli; "
              "code = cli.main(['context', '--map', '--root', sys.argv[1]]); "
              "print(); print(code, before, 'importlib.metadata' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, cwd=tmp_path,
                            env={**os.environ, "PYTHONPATH": CHECKOUT})
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    code, before, after = result.stdout.decode("utf-8", errors="replace").split()[-3:]

    assert (code, after) == ("0", before)


def test_doc_guard_passthrough(tmp_path: Path, capsys) -> None:
    write(tmp_path, "docs/a.md", "见 D-036\n")

    assert cli.main(["doc-guard", "--root", str(tmp_path)]) == 1
    assert "[decision-id]" in capsys.readouterr().out
    assert cli.main(["doc-guard", "--root", str(tmp_path), "--ignore-rule", "decision-id"]) == 0
    assert capsys.readouterr().out.startswith("doc_guard：通过")
    assert cli.main(["doc-guard", "--root", str(tmp_path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)[0]["rule"] == "decision-id"


def test_spec_check_passthrough(tmp_path: Path, capsys) -> None:
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "src/app.py", "# DEMO-9\n")

    assert cli.main(["spec-check", "--root", str(tmp_path)]) == 1
    assert "[dangling-ref]" in capsys.readouterr().out
    assert cli.main(["spec-check", "--root", str(tmp_path), "--ignore", "src"]) == 0


def test_check_runs_both(tmp_path: Path, capsys) -> None:
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")

    assert cli.main(["check", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "== doc_guard ==" in out and "== spec_check ==" in out

    write(tmp_path, "docs/b.md", "见 D-036\n")
    assert cli.main(["check", "--root", str(tmp_path)]) == 1


def test_missing_root_is_a_usage_error(tmp_path: Path, capsys) -> None:
    assert cli.main(["doc-guard", "--root", str(tmp_path / "absent")]) == 2
    assert cli.main(["check", "--root", str(tmp_path / "absent")]) == 2


def test_rules(capsys) -> None:
    assert cli.main(["rules"]) == 0
    out = capsys.readouterr().out
    assert "forbidden-path" in out and "dangling-ref" in out
    assert "D-036" in out  # each rule comes with what it checks


def test_hooks_install_pi(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"
    ledger = tmp_path / "ledgers" / "app"
    project.mkdir()
    ledger.mkdir(parents=True)

    args = ["hooks", "install", "--harness", "pi",
            "--project", str(project), "--ledger", str(ledger)]
    assert cli.main(args) == 0
    out = capsys.readouterr().out

    hook = project / ".pi" / "extensions" / "ledger-guard.js"
    config = project / ".dev-circuit" / "guard.json"
    assert hook.is_file()
    assert json.loads(config.read_text(encoding="utf-8"))["ledger"] == str(ledger.resolve())
    assert "已安装 hook" in out

    assert cli.main(["hooks", "status", "--project", str(project)]) == 0
    status = capsys.readouterr().out
    assert str(ledger.resolve()) in status
    assert "pi: 已安装" in status

    assert cli.main(args) == 0
    assert "未覆盖" in capsys.readouterr().out
    assert cli.main([*args, "--force"]) == 0
    assert "已安装 hook" in capsys.readouterr().out


def test_hooks_install_claude_writes_snippet(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"
    ledger = tmp_path / "ledgers" / "app"
    project.mkdir()
    ledger.mkdir(parents=True)

    assert cli.main(["hooks", "install", "--harness", "claude",
                     "--project", str(project), "--ledger", str(ledger)]) == 0
    capsys.readouterr()

    hook = project / ".dev-circuit" / "hooks" / "ledger_guard.py"
    snippet = project / ".dev-circuit" / "claude-settings.hook.json"
    assert hook.is_file()
    payload = json.loads(snippet.read_text(encoding="utf-8"))
    command = payload["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "ledger_guard.py" in command
    assert "PreToolUse" in snippet.read_text(encoding="utf-8")


def test_hooks_install_needs_a_ledger(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"
    project.mkdir()

    assert cli.main(["hooks", "install", "--harness", "pi", "--project", str(project)]) == 2
    assert "缺少 --ledger" in capsys.readouterr().err


def test_hooks_status_without_config(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"
    project.mkdir()

    assert cli.main(["hooks", "status", "--project", str(project)]) == 1
    assert "未找到" in capsys.readouterr().out


def test_check_shares_flags_between_guards(tmp_path: Path, capsys) -> None:
    write(tmp_path, "docs/requirements/demo.md", "代号：DEMO\n- DEMO-1：one\n")
    write(tmp_path, "docs/a.md", "见 D-036\n")
    write(tmp_path, "src/app.py", "# DEMO-9\n")

    # dangling-ref is a spec_check rule: doc_guard must not choke on it.
    assert cli.main(["check", "--root", str(tmp_path), "--ignore-rule", "dangling-ref"]) == 1
    out = capsys.readouterr().out
    assert "[decision-id]" in out
    assert "[dangling-ref]" not in out

    assert cli.main(["check", "--root", str(tmp_path),
                     "--ignore-rule", "decision-id",
                     "--ignore-rule", "dangling-ref"]) == 0
    # --report belongs to spec_check; check() drops it for doc_guard instead of erroring.
    assert cli.main(["check", "--root", str(tmp_path), "--report"]) == 1
    assert "[decision-id]" in capsys.readouterr().out


def test_hooks_install_refuses_a_ledger_inside_the_project(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"
    (project / "ledger").mkdir(parents=True)

    assert cli.main(["hooks", "install", "--harness", "pi",
                     "--project", str(project), "--ledger", str(project / "ledger")]) == 2
    assert "账本不能放在项目里" in capsys.readouterr().err
    assert not (project / ".dev-circuit").exists()


def test_claude_snippet_uses_the_available_interpreter(tmp_path: Path) -> None:
    snippet = cli.claude_snippet(tmp_path / "hook.py")

    assert cli.python_command() in snippet
    assert "hook.py" in snippet
    assert json.loads(snippet)["hooks"]["PreToolUse"][0]["matcher"] == "*"


def test_python_command_avoids_the_windows_store_alias(monkeypatch) -> None:
    # On Windows `python3` is usually the WindowsApps stub even when a real `python` is installed.
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(cli, "IS_WINDOWS", True)
    assert cli.python_command() == "python"
    monkeypatch.setattr(cli, "IS_WINDOWS", False)
    assert cli.python_command() == "python3"


def install_claude_hook(tmp_path: Path, capsys) -> tuple[Path, Path, str]:
    project, ledger = tmp_path / "app", tmp_path / "ledgers" / "app"
    project.mkdir()
    ledger.mkdir(parents=True)
    assert cli.main(["hooks", "install", "--harness", "claude",
                     "--project", str(project), "--ledger", str(ledger)]) == 0
    capsys.readouterr()
    snippet = json.loads((project / ".dev-circuit" / "claude-settings.hook.json").read_text(encoding="utf-8"))
    return project, ledger, snippet["hooks"]["PreToolUse"][0]["hooks"][0]["command"]


def run_hook_command(command: str, payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    # Claude Code hands the command to a shell; exit 2 means "block this tool call".
    return subprocess.run(command, shell=True, cwd=cwd, input=json.dumps(payload), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def test_claude_hook_command_steps_aside_when_its_script_is_gone(tmp_path: Path, capsys) -> None:
    project, ledger, command = install_claude_hook(tmp_path, capsys)
    payload = {"cwd": str(project), "tool_name": "Read", "tool_input": {"file_path": str(ledger / "x.md")}}

    blocked = run_hook_command(command, payload, project)
    assert blocked.returncode == 2, blocked.stderr
    assert "账本边界" in blocked.stderr

    # e.g. checking out an older branch that has no .dev-circuit/hooks yet
    (project / ".dev-circuit" / "hooks" / "ledger_guard.py").unlink()
    gone = run_hook_command(command, payload, project)
    assert gone.returncode == 0, gone.stderr


def test_hooks_install_adds_the_guard_config_to_gitignore(tmp_path: Path, capsys) -> None:
    project, ledger = tmp_path / "app", tmp_path / "ledgers" / "app"
    project.mkdir()
    ledger.mkdir(parents=True)
    (project / ".gitignore").write_bytes(b"node_modules/\r\ndist/")  # CRLF, no final newline
    args = ["hooks", "install", "--harness", "claude", "--project", str(project), "--ledger", str(ledger)]

    assert cli.main(args) == 0
    out = capsys.readouterr().out
    data = (project / ".gitignore").read_bytes()
    assert data.startswith(b"node_modules/\r\ndist/\r\n")
    assert b"\r\n.dev-circuit/guard.json\r\n" in data
    assert data.endswith(b"\r\n.dev-circuit/claude-settings.hook.json\r\n")
    # done by the command: under the hook, an agent that edits .gitignore naming guard.json is blocked
    assert "已把 .dev-circuit/guard.json、.dev-circuit/claude-settings.hook.json 加进 .gitignore" in out

    assert cli.main([*args, "--force"]) == 0
    assert "已把" not in capsys.readouterr().out
    assert (project / ".gitignore").read_bytes() == data


def test_hooks_install_creates_gitignore_when_missing(tmp_path: Path, capsys) -> None:
    project, _, _ = install_claude_hook(tmp_path, capsys)

    lines = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".dev-circuit/guard.json" in lines


def test_hooks_install_respects_a_wider_ignore_rule(tmp_path: Path, capsys) -> None:
    project, ledger = tmp_path / "app", tmp_path / "ledgers" / "app"
    project.mkdir()
    ledger.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / ".gitignore").write_text(".dev-circuit/*.json\n", encoding="utf-8")

    assert cli.main(["hooks", "install", "--harness", "pi",
                     "--project", str(project), "--ledger", str(ledger)]) == 0
    assert (project / ".gitignore").read_text(encoding="utf-8") == ".dev-circuit/*.json\n"


def test_vendor_copies_and_refreshes_guards(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"
    project.mkdir()

    assert cli.main(["vendor", "--project", str(project)]) == 0
    first = capsys.readouterr().out
    assert "新增" in first
    guard = project / "scripts" / "doc_guard.py"
    assert guard.is_file() and (project / "scripts" / "spec_check.py").is_file()

    assert cli.main(["vendor", "--project", str(project)]) == 0
    assert "未变" in capsys.readouterr().out

    guard.write_text("outdated\n", encoding="utf-8")
    assert cli.main(["vendor", "--project", str(project)]) == 0
    assert "更新" in capsys.readouterr().out
    assert "outdated" not in guard.read_text(encoding="utf-8")


def test_vendor_is_stable_after_init(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"

    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    capsys.readouterr()

    # init writes LF; vendor must not "update" the same bytes back over CRLF.
    assert cli.main(["vendor", "--project", str(project)]) == 0
    out = capsys.readouterr().out
    assert "未变" in out and "更新" not in out


def test_init_then_adopt_keeps_existing_files(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    capsys.readouterr()

    agents = project / "AGENTS.md"
    agents.write_text("hand written\n", encoding="utf-8")
    assert cli.main(["init", "--path", str(project), "--adopt"]) == 0
    out = capsys.readouterr().out
    assert "已存在、未覆盖" in out
    assert agents.read_text(encoding="utf-8") == "hand written\n"
    assert (project / "specs" / "backlog.md").read_text(encoding="utf-8").strip()


def test_init_rejects_an_empty_name_less_new_dir(tmp_path: Path, capsys) -> None:
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "file.txt").write_text("x", encoding="utf-8")

    assert cli.main(["init", "--path", str(busy)]) == 2
    assert "不是空的" in capsys.readouterr().err


def test_adopt_requires_a_git_repository(tmp_path: Path, capsys) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    assert cli.main(["init", "--path", str(plain), "--adopt"]) == 2
    assert "Git 仓库" in capsys.readouterr().err


def test_ledger_and_sync(tmp_path: Path, capsys) -> None:
    ledger = tmp_path / "ledgers" / "app"
    assert cli.main(["ledger", "--path", str(ledger), "--no-commit"]) == 0
    assert (ledger / "schema.md").is_file()
    assert (ledger / "entries").is_dir()
    capsys.readouterr()

    skills = tmp_path / "skills"
    retired = skills / "dev-circuit-archivist"
    retired.mkdir(parents=True)
    (retired / "SKILL.md").write_text("old\n", encoding="utf-8")
    assert cli.main(["sync", "--target", str(skills)]) == 0
    for name in ("dev-circuit-ultra", "dev-circuit-ledger"):
        assert (skills / name / "SKILL.md").is_file()
    assert not retired.exists()  # the dev agent now writes the ledger itself through `ledger add`
    assert not list(skills.rglob("__pycache__"))
    assert "skills synced" in capsys.readouterr().out


def test_init_reports_a_missing_git_identity(tmp_path: Path, monkeypatch, capsys) -> None:
    project = tmp_path / "app"
    for variable in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME",
                     "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-such-config"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(tmp_path / "no-such-config"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))

    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 2
    err = capsys.readouterr().err
    assert "git user.name" in err
    assert (project / "AGENTS.md").is_file()


def test_pre_commit_hook_is_executable_and_clean(tmp_path: Path) -> None:
    import os
    import subprocess

    project = tmp_path / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    if os.name != "nt":
        assert os.access(project / ".githooks" / "pre-commit", os.X_OK)
    status = subprocess.run(["git", "-C", str(project), "status", "--short"],
                            capture_output=True, text=True, encoding="utf-8")
    assert status.stdout.strip() == ""


@pytest.mark.skipif(shutil.which("sh") is None, reason="需要 POSIX sh")
@pytest.mark.parametrize("broken, working", [("python3", "python"), ("python", "python3")])
def test_pre_commit_skips_a_python_that_does_not_run(tmp_path: Path, broken: str, working: str) -> None:
    # On Windows `python3` is often the WindowsApps store stub: found on PATH, but it only prints
    # "Python was not found" and fails. The hook must move on to an interpreter that runs, whichever
    # name it tries first on this platform.
    project = tmp_path / "app"
    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    fake = tmp_path / "bin"
    stub = write(fake, broken, "#!/bin/sh\necho 'Python was not found' >&2\nexit 49\n")
    real = write(fake, working, f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n')
    for path in (stub, real):
        path.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}

    result = subprocess.run(["sh", ".githooks/pre-commit"], cwd=project, env=env, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stdout + result.stderr


def test_unknown_arguments_are_rejected(tmp_path: Path, capsys) -> None:
    # Only the checker passthroughs forward extra flags; elsewhere a typo must not be dropped silently.
    assert cli.main(["context", "--map", "--root", str(tmp_path), "--bogus"]) == 2
    assert "--bogus" in capsys.readouterr().err


def test_errors_reach_a_pipe_as_utf8_with_legacy_stdio_encoding(tmp_path: Path) -> None:
    """Piped on Chinese Windows, stderr is GBK; `devcircuit ledger check 2>&1 | head` must still read as UTF-8."""
    env = {**os.environ, "PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0",
           "PYTHONPATH": str(Path(cli.__file__).resolve().parents[1])}
    for name in ("DEVCIRCUIT_LEDGER", "DEVCIRCUIT_PROJECT"):
        env.pop(name, None)
    result = subprocess.run([sys.executable, "-m", "devcircuit.cli", "ledger", "check", "--project", str(tmp_path)],
                            capture_output=True, env=env)
    assert result.returncode == 2
    assert "没有配置账本" in result.stderr.decode("utf-8", errors="replace")


def test_hooks_install_points_the_claude_snippet_at_local_settings(tmp_path: Path, capsys) -> None:
    """The snippet holds this machine's absolute paths, so it goes into the settings file nobody commits."""
    project = tmp_path / "app"
    ledger = tmp_path / "ledgers" / "app"
    project.mkdir()
    ledger.mkdir(parents=True)

    assert cli.main(["hooks", "install", "--harness", "claude",
                     "--project", str(project), "--ledger", str(ledger)]) == 0
    assert ".claude/settings.local.json" in capsys.readouterr().out


def test_adopt_writes_the_repos_trunk_into_agents(tmp_path: Path, capsys) -> None:
    """The template says main; a repo adopted on develop must not get main as its default base."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "develop", str(repo)], check=True)

    assert cli.main(["init", "--path", str(repo), "--adopt"]) == 0
    capsys.readouterr()
    assert "主干：`develop`" in (repo / "AGENTS.md").read_text(encoding="utf-8")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo_on(root: Path, branch: str) -> Path:
    write(root, "README.md", "# r\n")
    _git(root, "init", "-q", "-b", branch)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def test_adopt_takes_the_remotes_default_branch(tmp_path: Path, capsys) -> None:
    remote = _repo_on(tmp_path / "remote", "workbench")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
    _git(clone, "switch", "-q", "-c", "feat/x")

    assert cli.main(["init", "--path", str(clone), "--adopt"]) == 0
    out = capsys.readouterr().out
    assert "主干：`workbench`" in (clone / "AGENTS.md").read_text(encoding="utf-8")
    assert "workbench" in out  # says which trunk it wrote, so a wrong guess gets noticed


def test_adopt_on_a_feature_branch_takes_the_local_trunk(tmp_path: Path, capsys) -> None:
    repo = _repo_on(tmp_path / "repo", "master")
    _git(repo, "switch", "-q", "-c", "feat/adopt")

    assert cli.main(["init", "--path", str(repo), "--adopt"]) == 0
    capsys.readouterr()
    assert "主干：`master`" in (repo / "AGENTS.md").read_text(encoding="utf-8")


def test_adopt_leaves_the_trunk_out_when_it_cannot_tell(tmp_path: Path, capsys) -> None:
    repo = _repo_on(tmp_path / "repo", "feat/first")

    assert cli.main(["init", "--path", str(repo), "--adopt"]) == 0
    capsys.readouterr()
    assert "主干：" not in (repo / "AGENTS.md").read_text(encoding="utf-8")


def test_adopt_reminds_an_existing_agents_file_about_the_trunk(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    write(repo, "AGENTS.md", "# 已有入口\n")
    _git(repo, "init", "-q", "-b", "develop")

    assert cli.main(["init", "--path", str(repo), "--adopt"]) == 0
    assert "主干" in capsys.readouterr().out


def test_errors_about_unencodable_paths_do_not_crash(tmp_path: Path) -> None:
    """A lone surrogate (a non-UTF-8 byte in a Linux path) must not turn a readable error into a traceback."""
    env = {**os.environ, "PYTHONPATH": str(Path(cli.__file__).resolve().parents[1])}
    result = subprocess.run([sys.executable, "-m", "devcircuit.cli", "context", "--map",
                             "--root", str(tmp_path / "x\udcff")], capture_output=True, env=env)
    assert result.returncode == 2
    assert b"Traceback" not in result.stderr


def test_hooks_install_keeps_the_claude_snippet_out_of_git(tmp_path: Path, capsys) -> None:
    project, _, _ = install_claude_hook(tmp_path, capsys)

    lines = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".dev-circuit/claude-settings.hook.json" in lines


def test_hooks_install_says_to_commit_what_it_left_in_the_project(tmp_path: Path, capsys) -> None:
    # The hook script and the .gitignore edit stayed uncommitted and nothing said so: the first framework
    # draft could not be committed on the feature branch, and `devcircuit close` refused the dirty tree.
    project = tmp_path / "app"
    ledger = tmp_path / "ledgers" / "app"
    project.mkdir()
    ledger.mkdir(parents=True)

    assert cli.main(["hooks", "install", "--harness", "pi", "--project", str(project), "--ledger", str(ledger)]) == 0

    [line] = [line for line in capsys.readouterr().out.splitlines() if "在主干上提交" in line]
    assert ".pi/extensions/ledger-guard.js" in line and ".gitignore" in line


def test_adopt_does_not_take_a_fix_branch_for_the_trunk(tmp_path: Path, capsys) -> None:
    # Bugs are fixed on fix/<name>, which goes away after the merge just as feat/<name> does.
    repo = _repo_on(tmp_path / "repo", "fix/first")

    assert cli.main(["init", "--path", str(repo), "--adopt"]) == 0
    capsys.readouterr()
    assert "主干：" not in (repo / "AGENTS.md").read_text(encoding="utf-8")
