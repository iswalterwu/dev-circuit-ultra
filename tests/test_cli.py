"""The guards are also a CLI; these tests cover the wrapper, not the rules."""

import contextlib
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
    assert "已安装 hook" in out and "已写入配置" in out
    assert str(ledger.resolve()) not in out  # where the ledger is stays in guard.json, which the hook guards

    assert cli.main(["hooks", "status", "--project", str(project)]) == 0
    status = capsys.readouterr().out
    assert str(ledger.resolve()) not in status
    assert "账本：已配置（目录存在）" in status
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


def hooked_project(tmp_path: Path, capsys, harness: str = "pi") -> tuple[Path, Path]:
    """A git project on main with the hook installed and committed, and its ledger folder outside it."""
    project, ledger = _repo_on(tmp_path / "app", "main"), tmp_path / "ledgers" / "app"
    ledger.mkdir(parents=True)
    assert cli.main(["hooks", "install", "--harness", harness, "--project", str(project), "--ledger", str(ledger)]) == 0
    capsys.readouterr()
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "hooks")
    return project, ledger


def linked_worktree(project: Path, tree: Path) -> Path:
    _git(project, "worktree", "add", "-q", "-b", "feat/x", str(tree))
    return tree


def hook_status(capsys, project: Path) -> tuple[int, str, str]:
    code = cli.main(["hooks", "status", "--project", str(project)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_locate_names_the_guard_file_the_ledger_commands_use(tmp_path: Path, capsys) -> None:
    """`hooks status` and `hooks install` ask the ledger module, so they cannot disagree with `ledger add` / `check`."""
    project, _ = hooked_project(tmp_path, capsys)
    tree = linked_worktree(project, tmp_path / "wt")
    guard = project / ".dev-circuit" / "guard.json"
    locate = cli.ledger_module.locate

    assert locate(project) == (guard, project, "本工作树")
    found, root, source = locate(tree)
    assert (found.samefile(guard), root.samefile(project), source) == (True, True, "主工作树")
    assert locate(tree / ".pi") == (None, tree / ".pi", "无")  # a folder inside a working tree is not the project
    own = write(tree, ".dev-circuit/guard.json", "{}")
    assert locate(tree) == (own, tree, "本工作树")
    guard.unlink()
    (tree / ".dev-circuit" / "guard.json").unlink()
    assert locate(tree) == (None, tree, "无")


def test_hooks_status_in_a_linked_worktree_finds_the_main_trees_config(tmp_path: Path, capsys) -> None:
    # guard.json is gitignored, so a worktree has none. Status said 未找到 and to run `hooks install`, which
    # there wrote a second config holding only the ledger path, while `ledger check` in the same worktree passed.
    project, _ = hooked_project(tmp_path, capsys)
    tree = linked_worktree(project, tmp_path / "wt")

    code, out, _ = hook_status(capsys, tree)

    assert code == 0
    assert "未找到" not in out
    [config] = [line for line in out.splitlines() if line.startswith("配置：")]
    assert "主工作树" in config and str(project.resolve() / ".dev-circuit" / "guard.json") in config
    # the script came with git (as CRLF where git converts line ends): still the one this devcircuit ships
    assert f"pi: 已安装（{tree.resolve() / '.pi' / 'extensions' / 'ledger-guard.js'}），与本机 devcircuit 带的相同" in out
    assert str(project.resolve() / ".dev-circuit" / "guard.json.selftest") in out  # the probe names the config in use
    assert "账本：已配置（目录存在）" in out and "ledgers" not in out  # the main tree's ledger, and not where it is

    # a relative path in the main tree's file counts from the main tree, wherever the worktree lies
    (project / ".dev-circuit" / "guard.json").write_text(json.dumps({"ledger": "../ledgers/app"}), encoding="utf-8")
    deep = tmp_path / "deep" / "wt"
    _git(project, "worktree", "add", "-q", "-b", "feat/deep", str(deep))
    assert "账本：已配置（目录存在）" in hook_status(capsys, deep)[1]


@pytest.mark.parametrize("data", [b'{"ledger": ', b"[]", b'{"ledger": 7}', b'{"ledger": " "}', b'{"ledger": null}',
                                  b"\xef\xbb\xbf{", b"\xff\xfe{}",
                                  # python's json takes these; JSON.parse in the pi hook does not, and it then blocks every call
                                  b'{"ledger": "x", "deny": [NaN]}', b'{"ledger": "x", "since": -Infinity}',
                                  b"[" * 100_000],
                         ids=["cut-short", "not-an-object", "ledger-not-text", "ledger-blank", "ledger-null",
                              "bom-then-cut-short", "not-utf8", "nan", "infinity", "nested-too-deep"])
def test_hooks_status_reports_a_guard_file_it_cannot_use(tmp_path: Path, capsys, data: bytes) -> None:
    # It exited 0 showing 账本：（未配置） and borrowed install's warning that the file 将被覆盖.
    project = tmp_path / "app"
    write(project, ".dev-circuit/guard.json", "").write_bytes(data)

    code, out, err = hook_status(capsys, project)

    assert code == 2
    [config] = [line for line in out.splitlines() if line.startswith("配置：")]
    assert "无法解析" in config and "human" in config
    assert "将被覆盖" not in out + err and "（未配置）" not in out + err
    assert "账本：" not in out  # nothing is said about a ledger that could not be read
    # scripts from before 0.2.0 let every call through on such a file: 文件不存在 from the probe then proves nothing
    [probe] = [line for line in out.splitlines() if line.startswith("会话内探针")]
    assert "先修好配置再探" in probe and "旧脚本" in probe


def test_hooks_status_reads_the_guard_file_as_the_hooks_do(tmp_path: Path, capsys, monkeypatch) -> None:
    """A BOM, no ledger at all (the ledger is on the human side), a deny list written wrongly: none is a broken config."""
    project = tmp_path / "app"
    guard = write(project, ".dev-circuit/guard.json", "")
    guard.write_bytes(b"\xef\xbb\xbf" + json.dumps({"ledger": "../ledgers/app"}).encode("utf-8"))
    (tmp_path / "ledgers" / "app").mkdir(parents=True)

    code, out, _ = hook_status(capsys, project)
    assert code == 0 and "账本：已配置（目录存在）" in out and "额外拒绝" not in out and "提醒" not in out

    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(tmp_path))
    guard.write_text(json.dumps({"ledger": "~/ledgers/app"}), encoding="utf-8")  # the hooks expand ~ as well
    assert "账本：已配置（目录存在）" in hook_status(capsys, project)[1]

    guard.write_text(json.dumps({"ledger_side": "human"}), encoding="utf-8")
    code, out, _ = hook_status(capsys, project)
    assert code == 0 and "账本：未配置" in out

    guard.write_text(json.dumps({"ledger": "../ledgers/gone", "deny": ["../notes", 7, ""]}), encoding="utf-8")
    code, out, _ = hook_status(capsys, project)
    assert code == 0  # only the field is pointed out
    assert "账本：已配置（目录不存在" in out and "提醒：账本路径当前不存在" in out
    [deny] = [line for line in out.splitlines() if line.startswith("额外拒绝")]
    assert "额外拒绝 1 项" in deny and "字符串数组" in deny

    guard.write_text(json.dumps({"ledger": "../ledgers/app", "deny": "../notes"}), encoding="utf-8")
    code, out, _ = hook_status(capsys, project)
    [deny] = [line for line in out.splitlines() if line.startswith("额外拒绝")]
    assert code == 0 and "额外拒绝 0 项" in deny and "字符串数组" in deny


def test_hooks_status_tells_a_hook_without_config_from_no_hook_at_all(tmp_path: Path, capsys) -> None:
    # The script travels with git and guard.json does not: a clone, or a worktree whose main tree lost its config.
    project, _ = hooked_project(tmp_path, capsys)
    tree = linked_worktree(project, tmp_path / "wt")
    (project / ".dev-circuit" / "guard.json").unlink()

    for where in (project, tree):
        code, out, _ = hook_status(capsys, where)
        assert code == 2, where
        [config] = [line for line in out.splitlines() if line.startswith("配置：")]
        assert "找不到 guard.json" in config and "human" in config
        assert f"主工作树（{project.resolve()}）" in config  # the worktree is sent to the main tree, not told to install here
        assert "跑 devcircuit hooks install 生成" not in out

    plain = tmp_path / "plain"  # neither script nor config: not set up at all, as before
    plain.mkdir()
    code, out, _ = hook_status(capsys, plain)
    assert code == 1 and "未找到" in out


def test_hooks_status_in_a_linked_worktree_with_nothing_set_up_points_at_the_main_tree(tmp_path: Path, capsys) -> None:
    """跑 devcircuit hooks install 生成 is the advice for a project of its own; run in a worktree it wrote a second config."""
    project = _repo_on(tmp_path / "app", "main")
    tree = linked_worktree(project, tmp_path / "wt")

    code, out, _ = hook_status(capsys, tree)

    assert code == 1
    [config] = [line for line in out.splitlines() if line.startswith("配置：")]
    assert "未找到" in config and f"主工作树（{project.resolve()}）" in config and "human" in config
    assert "跑 devcircuit hooks install 生成" not in out
    [probe] = [line for line in out.splitlines() if line.startswith("会话内探针")]
    assert str(project.resolve() / ".dev-circuit" / "guard.json.selftest") in probe  # where the config will be
    assert str(tree.resolve()) not in probe


def test_hooks_status_and_install_in_a_folder_below_the_config_point_at_the_folder_to_give(tmp_path: Path, capsys) -> None:
    # --project is the current folder unless given. Run from src/, status said 未找到 and to run `hooks install`;
    # that wrote a second guard.json in src/ with the ledger path alone, in the main tree and in a worktree alike.
    project, ledger = hooked_project(tmp_path, capsys)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger), "ledger_side": "human", "deny": ["../notes"]}), encoding="utf-8")
    tree = linked_worktree(project, tmp_path / "wt")

    for top in (project, tree):
        inner = top / "src" / "deep"
        inner.mkdir(parents=True)
        code, out, _ = hook_status(capsys, inner)
        [config] = [line for line in out.splitlines() if line.startswith("配置：")]
        assert code == 1 and "未找到" in config and f"--project 给 {top.resolve()}" in config
        assert "跑 devcircuit hooks install 生成" not in out and "主工作树（" not in config
        [probe] = [line for line in out.splitlines() if line.startswith("会话内探针")]
        assert f"先用 --project {top.resolve()} 重跑" in probe  # a session here meets the config above: not 没有配置

        for more in ([], ["--ledger", str(tmp_path / "ledgers" / "other")]):
            assert cli.main(["hooks", "install", "--harness", "pi", "--project", str(inner), *more]) == 2
            captured = capsys.readouterr()
            assert f"--project 给 {top.resolve()}" in captured.err and "ledgers" not in captured.out + captured.err
        assert not (inner / ".dev-circuit").exists() and not (inner / ".pi").exists()
        assert cli.main(["ledger", "check", "--project", str(top)]) == 2
        assert "human 一侧" in capsys.readouterr().err

        write(inner, ".pi/extensions/ledger-guard.js", "// left by an install made here earlier\n")
        code, out, _ = hook_status(capsys, inner)
        [config] = [line for line in out.splitlines() if line.startswith("配置：")]
        assert code == 2 and f"--project 给 {top.resolve()}" in config and "主工作树（" not in config

    # A project kept in a folder of a larger repository is set up in that folder, as before: nothing above it is
    # configured. Once it is, a folder below it is sent to it, not to the top of the repository.
    part = _repo_on(tmp_path / "mono", "main") / "packages" / "app"
    part.mkdir(parents=True)
    code, out, _ = hook_status(capsys, part)
    assert code == 1 and "跑 devcircuit hooks install 生成" in out
    assert cli.main(["hooks", "install", "--harness", "pi", "--project", str(part), "--ledger", str(ledger)]) == 0
    capsys.readouterr()
    assert (part / ".dev-circuit" / "guard.json").is_file() and hook_status(capsys, part)[0] == 0
    (part / "src").mkdir()
    [config] = [line for line in hook_status(capsys, part / "src")[1].splitlines() if line.startswith("配置：")]
    assert f"--project 给 {part.resolve()}" in config
    # a folder that already carries a guard.json of its own keeps using it, whatever is configured above
    write(part / "src", ".dev-circuit/guard.json", json.dumps({"ledger": str(ledger)}))
    assert cli.main(["hooks", "install", "--harness", "pi", "--project", str(part / "src")]) == 0
    assert "沿用现有配置" in capsys.readouterr().out
    code, out, _ = hook_status(capsys, part / "src")
    assert code == 0 and "--project" not in out

    # The look upward ends at the top of the working tree: another repository checked out inside a configured
    # project is a project of its own, and is not sent to the one around it.
    nested = _repo_on(project / "vendor" / "tool", "main")
    (nested / "src").mkdir()
    for where in (nested, nested / "src"):
        code, out, _ = hook_status(capsys, where)
        assert code == 1 and "跑 devcircuit hooks install 生成" in out and "--project 给" not in out, where
    assert cli.main(["hooks", "install", "--harness", "pi", "--project", str(nested), "--ledger", str(ledger)]) == 0
    assert "已写入配置" in capsys.readouterr().out


def test_hooks_status_and_install_do_not_print_where_the_ledger_is(tmp_path: Path, capsys) -> None:
    # The hook blocks reads of guard.json because it holds the ledger path; these two commands printed that path.
    project, ledger, notes = tmp_path / "app", tmp_path / "ledgers" / "app", tmp_path / "private notes"
    ledger.mkdir(parents=True)
    write(project, ".dev-circuit/guard.json", json.dumps({"deny": ["../private notes", str(notes)]}))
    printed = []
    for args in (["hooks", "install", "--harness", "claude", "--project", str(project), "--ledger", str(ledger)],
                 ["hooks", "install", "--harness", "pi", "--project", str(project), "--force"],
                 ["hooks", "status", "--project", str(project)]):
        assert cli.main(args) == 0, args
        captured = capsys.readouterr()
        printed.append(captured.out + captured.err)

    assert "账本：已配置（目录存在）" in printed[-1] and "额外拒绝 2 项" in printed[-1]
    for secret in (str(ledger), ledger.as_posix(), "ledgers", "private notes"):
        assert secret not in "".join(printed), secret


@contextlib.contextmanager
def out_of_sight(folder: Path):
    """Take this user's access to a folder and all below it away, as when the ledger belongs to another OS user."""
    everyone = "*S-1-1-0"  # the well-known SID: the group's name differs with the language of Windows
    if os.name == "nt":
        # Listing, traversing and reading attributes, not (RX) as a whole: that takes READ_CONTROL too, and under
        # the temp folder pytest makes with mode 0o700 not even the owner could then give the access back.
        subprocess.run(["icacls", str(folder), "/deny", f"{everyone}:(OI)(CI)(RD,X,RA,REA)", "/Q"],
                       check=True, capture_output=True)
    else:
        folder.chmod(0)
    try:
        yield
    finally:
        if os.name == "nt":
            subprocess.run(["icacls", str(folder), "/remove:d", everyone, "/T", "/Q"], check=True, capture_output=True)
        else:
            folder.chmod(0o700)


def test_hooks_status_does_not_fail_on_a_ledger_folder_this_user_may_not_look_into(tmp_path: Path, capsys) -> None:
    # Before Python 3.14 Path.is_dir() raised PermissionError here: status ended in a traceback that named the ledger.
    # From 3.14 on it answered 目录不存在 for a folder that is there.
    project, ledger = tmp_path / "app", tmp_path / "locked" / "ledgers" / "app"
    ledger.mkdir(parents=True)
    write(project, ".dev-circuit/guard.json", json.dumps({"ledger": str(ledger), "deny": [str(ledger.parent / "notes")]}))

    with out_of_sight(tmp_path / "locked"):
        try:
            os.stat(ledger)
        except OSError:
            code, out, err = hook_status(capsys, project)
        else:
            pytest.skip("这个用户照样看得到（比如 root）")

    assert code == 0
    assert "账本：已配置（目录看不到：当前用户没有访问权限）" in out and "额外拒绝 1 项" in out
    assert "目录不存在" not in out and "当前不存在" not in out
    assert "locked" not in out + err and "ledgers" not in out + err


def test_hooks_status_says_whether_this_worktree_registers_the_claude_hook(tmp_path: Path, capsys) -> None:
    # "claude: 已安装" only meant the script file was there; Claude Code runs it only once settings name it.
    project, _, _ = install_claude_hook(tmp_path, capsys)

    def registration() -> str:
        code, out, _ = hook_status(capsys, project)
        assert code == 0  # not registered here is reported, not an error: user-level settings are out of sight
        [line] = [line for line in out.splitlines() if line.startswith("登记 claude")]
        return line

    assert "本工作树的 settings 里没有登记（用户级设置 CLI 看不到）" in registration()

    snippet = cli.claude_snippet(project / ".dev-circuit/hooks/ledger_guard.py")
    write(project, ".claude/settings.local.json", snippet)
    line = registration()
    assert ".claude/settings.local.json" in line and "没有登记" not in line
    # saved with a BOM, as Windows PowerShell's `Set-Content -Encoding utf8` does
    (project / ".claude" / "settings.local.json").write_bytes(b"\xef\xbb\xbf" + snippet.encode("utf-8"))
    assert "没有登记" not in registration()

    other = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python lint.py"}]}]}}
    write(project, ".claude/settings.local.json", json.dumps(other))
    assert "没有登记" in registration()
    for broken in ("{", "[" * 100_000):  # not JSON, or nested past what python parses: no registration, no traceback
        write(project, ".claude/settings.local.json", broken)
        assert "没有登记" in registration()
    write(project, ".claude/settings.json", cli.claude_snippet(project / ".dev-circuit/hooks/ledger_guard.py"))
    assert ".claude/settings.json" in registration()  # the file beside the broken one is still read


def test_hooks_status_says_whether_pi_would_find_the_script(tmp_path: Path, capsys) -> None:
    project, _, _ = install_claude_hook(tmp_path, capsys)

    def registration() -> str:
        [line] = [line for line in hook_status(capsys, project)[1].splitlines() if line.startswith("登记 pi")]
        return line

    assert "没有" in registration()
    write(project, ".pi/extensions/ledger-guard.js", "// hook\n")
    assert "没有" not in registration() and ".pi/extensions/" in registration()


@pytest.mark.parametrize("guard", [None, "{", json.dumps({"ledger": "../ledgers/app"})],
                         ids=["no-config", "broken-config", "configured"])
def test_hooks_status_never_claims_the_host_loaded_the_hook(tmp_path: Path, capsys, guard: str | None) -> None:
    """Files and settings are all a command line can see; whether the harness runs the hook takes a probe in a session."""
    project = tmp_path / "app"
    write(project, ".pi/extensions/ledger-guard.js", "// hook\n")
    write(project, ".claude/settings.local.json", cli.claude_snippet(project / ".dev-circuit/hooks/ledger_guard.py"))
    if guard is not None:
        write(project, ".dev-circuit/guard.json", guard)

    lines = hook_status(capsys, project)[1].splitlines()

    assert "宿主是否已加载：CLI 证明不了" in lines
    [probe] = [line for line in lines if line.startswith("会话内探针")]
    assert str(project.resolve() / ".dev-circuit" / "guard.json.selftest") in probe
    assert "账本边界" in probe and "文件不存在" in probe
    # 已加载 appears as the question and as what the probe would show, never as something status found
    assert [line for line in lines if "已加载" in line and line not in ("宿主是否已加载：CLI 证明不了", probe)] == []


def hook_text(name: str, version: str | None, body: str = "rules") -> str:
    """A stand-in hook script with the version line the real ones carry from 0.2.0 on (None: an older one, without)."""
    if name.endswith(".js"):
        return "// ledger-guard\n" + (f'const VERSION = "{version}";\n' if version else "") + f"// {body}\n"
    return "# ledger-guard\n" + (f'VERSION = "{version}"\n' if version else "") + f"# {body}\n"


def ship_hooks(tmp_path: Path, monkeypatch, version: str | None) -> None:
    """Have this devcircuit ship stand-in hook scripts of the given version, whatever the real ones say today."""
    def shipped(*parts: str) -> Path:
        return write(tmp_path / "shipped", parts[-1], hook_text(parts[-1], version))

    monkeypatch.setattr(cli, "asset_path", shipped)
    monkeypatch.setattr(cli.migrate_module, "asset_path", shipped)


@pytest.mark.parametrize("name, harness", [("ledger-guard.js", "pi"), ("ledger_guard.py", "claude")])
def test_hooks_status_compares_each_script_with_the_one_this_devcircuit_ships(tmp_path: Path, capsys, monkeypatch,
                                                                              name: str, harness: str) -> None:
    # "不是当前版本" could not tell a script that needs updating from one that is ahead of the installed devcircuit.
    project = tmp_path / "app"
    script = write(project, cli.HOOKS[harness][1].as_posix(), "")

    def compared(text: str) -> str:
        script.write_bytes(text.encode("utf-8"))
        [line] = [line for line in hook_status(capsys, project)[1].splitlines() if line.startswith(f"{harness}: ")]
        assert line.startswith(f"{harness}: 已安装（{script.resolve()}），")
        return line

    ship_hooks(tmp_path, monkeypatch, "0.2.0")
    assert "与本机 devcircuit 带的相同" in compared(hook_text(name, "0.2.0").replace("\n", "\r\n"))
    assert "比本机 devcircuit 带的旧" in compared(hook_text(name, "0.1.9"))
    assert "比本机 devcircuit 带的旧" in compared(hook_text(name, None))  # no version line: older than any that has one
    assert "比本机 devcircuit 带的新" in compared(hook_text(name, "0.10.0"))  # compared as numbers, not as text
    assert "与本机 devcircuit 带的不同" in compared(hook_text(name, "0.2.0", "edited here"))
    if name.endswith(".js"):  # exported, the constant states the version just the same
        assert "比本机 devcircuit 带的新" in compared(hook_text(name, "0.10.0").replace("const VERSION", "export const VERSION"))

    ship_hooks(tmp_path, monkeypatch, None)  # the shipped script has no version either: only same or not
    assert "与本机 devcircuit 带的相同" in compared(hook_text(name, None))
    assert "与本机 devcircuit 带的不同" in compared(hook_text(name, "0.2.0"))


@pytest.mark.parametrize("harness", sorted(cli.HOOKS))
def test_a_version_the_shipped_hook_script_states_is_one_the_cli_reads(harness: str) -> None:
    """The hook scripts are edited apart from the CLI. A version written another way than `VERSION = "x.y.z"` reads
    as none: status then calls every difference 不同, and --force puts an older script over a newer one again.

    Holds trivially for a script that says nothing about a version.
    """
    shipped = cli.asset_path(*cli.HOOKS[harness][0])
    mentions = [line for line in shipped.read_text(encoding="utf-8").splitlines() if "version" in line.lower()]
    assert not mentions or cli.migrate_module.hook_version(shipped) is not None, mentions


def old_scripts_then_upgrade(tmp_path: Path, capsys, monkeypatch) -> tuple[Path, Path, Path]:
    """A project whose trunk and branches carry both hook scripts from before the version line, then a newer devcircuit.

    Returns the main tree, a linked worktree beside it and one inside it (Claude Code makes its own inside the
    project, under .claude/worktrees/; a short name here keeps the paths within what Windows takes).
    """
    ship_hooks(tmp_path, monkeypatch, None)
    project, _ = hooked_project(tmp_path, capsys)
    assert cli.main(["hooks", "install", "--harness", "claude", "--project", str(project)]) == 0
    capsys.readouterr()
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "claude hook")
    beside, inside = linked_worktree(project, tmp_path / "wt"), project / "in"
    _git(project, "worktree", "add", "-q", "-b", "feat/in", str(inside))
    ship_hooks(tmp_path, monkeypatch, "0.2.0")
    return project, beside, inside


def status_lines(capsys, project: Path, start: str) -> tuple[int, list[str]]:
    code, out, _ = hook_status(capsys, project)
    return code, [line for line in out.splitlines() if line.startswith(start)]


def test_hooks_status_says_when_a_worktrees_old_script_cannot_find_the_main_trees_config(tmp_path: Path, capsys,
                                                                                          monkeypatch) -> None:
    # After the upgrade a branch cut earlier still carries the old scripts. Those only walk up from the session's
    # folder: beside the main tree they find no guard.json and block nothing. Status said 来自主工作树，可解析, exit 0.
    project, beside, inside = old_scripts_then_upgrade(tmp_path, capsys, monkeypatch)

    code, stale = status_lines(capsys, beside, "这里不拦：")
    assert code == 2
    [stale] = stale
    assert "pi、claude hook 脚本" in stale and "把主干合并进这个 worktree 的分支" in stale
    assert "--harness <pi|claude> --force" in stale
    assert "用户级" in stale  # Claude Code registered at user level with the main tree's script is not affected
    assert "已加载" not in stale
    _, [config] = status_lines(capsys, beside, "配置：")
    assert "主工作树" in config and "可解析" in config  # the config itself is fine and still named
    for harness in sorted(cli.HOOKS):
        _, [script] = status_lines(capsys, beside, f"{harness}: ")
        assert "比本机 devcircuit 带的旧" in script and "把主干合并进这个 worktree 的分支" in script
        assert "在主干上 hooks install --force 更新后提交" not in script  # that is done in the main tree, not here
    _, [probe] = status_lines(capsys, beside, "会话内探针")
    assert "旧脚本" in probe and "换上新脚本再探" in probe  # loaded or not, the old script answers 文件不存在

    # walking up from a worktree inside the main tree reaches the main tree's guard.json: the old script blocks there
    code, stale = status_lines(capsys, inside, "这里不拦：")
    assert (code, stale) == (0, [])
    _, [probe] = status_lines(capsys, inside, "会话内探针")
    assert "旧脚本" not in probe
    # so does the old script in the main tree itself; there the advice is to update on the trunk
    code, [script] = status_lines(capsys, project, "pi: ")
    assert code == 0 and "在主干上 hooks install --force 更新后提交" in script and "合并" not in script
    assert status_lines(capsys, project, "这里不拦：") == (0, [])
    # below a folder that holds another project's guard.json the old script walks up to that file, not the main tree's
    write(tmp_path / "outer", ".dev-circuit/guard.json", json.dumps({"ledger": str(tmp_path / "ledgers" / "outer")}))
    _git(project, "worktree", "add", "-q", "-b", "feat/below", str(tmp_path / "outer" / "wt"))
    code, [stale] = status_lines(capsys, tmp_path / "outer" / "wt", "这里不拦：")
    assert code == 2 and "pi、claude hook 脚本" in stale

    # one script brought up to date: the other is still named, alone
    assert cli.main(["hooks", "install", "--harness", "pi", "--project", str(beside), "--force"]) == 0
    capsys.readouterr()
    code, [stale] = status_lines(capsys, beside, "这里不拦：")
    assert code == 2 and "claude hook 脚本" in stale and "pi、" not in stale and "--harness claude " in stale
    assert cli.main(["hooks", "install", "--harness", "claude", "--project", str(beside), "--force"]) == 0
    capsys.readouterr()
    assert status_lines(capsys, beside, "这里不拦：") == (0, [])

    # older than what this devcircuit ships, yet from 0.2.0 on: such a script does fall back to the main tree
    ship_hooks(tmp_path, monkeypatch, "0.3.0")
    code, [script] = status_lines(capsys, beside, "pi: ")
    assert code == 0 and "比本机 devcircuit 带的旧" in script
    assert status_lines(capsys, beside, "这里不拦：") == (0, [])

    # no config anywhere is the 找不到 guard.json case, old script or not: there is no config for it to miss
    (project / ".dev-circuit" / "guard.json").unlink()
    assert status_lines(capsys, inside, "这里不拦：") == (2, [])


def test_hooks_status_does_not_judge_a_worktree_by_a_script_its_settings_do_not_run(tmp_path: Path, capsys,
                                                                                     monkeypatch) -> None:
    # A worktree's settings may have Claude Code run the main tree's script, which is up to date. Status went by
    # the old copy on the worktree's branch all the same: 这里不拦 and exit 2, beside a line saying it is registered.
    project, beside, _ = old_scripts_then_upgrade(tmp_path, capsys, monkeypatch)
    force = ["hooks", "install", "--force", "--harness"]
    assert cli.main([*force, "claude", "--project", str(project)]) == 0  # the trunk's script is brought up to date
    capsys.readouterr()
    own, trunk = (tree / ".dev-circuit" / "hooks" / "ledger_guard.py" for tree in (beside, project))

    def registered_with(settings: str) -> tuple[int, list[str], str]:
        write(beside, ".claude/settings.local.json", settings)
        code, stale = status_lines(capsys, beside, "这里不拦：")
        _, [registration] = status_lines(capsys, beside, "登记 claude")
        return code, stale, registration

    code, [stale], registration = registered_with(cli.claude_snippet(own))  # its own old copy is the one that runs
    assert code == 2 and "这个 worktree 的 pi、claude hook 脚本" in stale and "不是本工作树这份" not in registration
    code, [stale], registration = registered_with(cli.claude_snippet(trunk))
    assert "命令指向的不是本工作树这份脚本" in registration
    assert code == 2 and "这个 worktree 的 pi hook 脚本" in stale  # pi still loads this worktree's old script
    assert cli.main([*force, "pi", "--project", str(beside)]) == 0
    capsys.readouterr()
    assert status_lines(capsys, beside, "这里不拦：") == (0, [])
    _, [probe] = status_lines(capsys, beside, "会话内探针")
    assert "旧脚本" not in probe
    # relative to the session's folder, or through Claude Code's own variable, the command runs this worktree's copy
    for command in ("python .dev-circuit/hooks/ledger_guard.py",
                    'python "$CLAUDE_PROJECT_DIR/.dev-circuit/hooks/ledger_guard.py"'):
        settings = {"hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": command}]}]}}
        code, [stale], registration = registered_with(json.dumps(settings))
        assert code == 2 and "这个 worktree 的 claude hook 脚本" in stale and "不是本工作树这份" not in registration, command


def test_hooks_install_says_when_the_old_script_it_leaves_in_a_worktree_cannot_find_the_config(tmp_path: Path, capsys,
                                                                                                monkeypatch) -> None:
    """Without --force the script stays; said plainly, 已存在，未覆盖 and 沿用现有配置 read as if the worktree were guarded."""
    project, beside, inside = old_scripts_then_upgrade(tmp_path, capsys, monkeypatch)
    old = hook_text("ledger-guard.js", None)

    def install(where: Path, *more: str) -> str:
        assert cli.main(["hooks", "install", "--harness", "pi", "--project", str(where), *more]) == 0
        return capsys.readouterr().out

    out = install(beside)
    assert "已存在，未覆盖" in out and "沿用现有配置" in out
    [warning] = [line for line in out.splitlines() if line.startswith("提醒：") and "不拦" in line]
    assert "把主干合并进这个 worktree 的分支" in warning and "--force" in warning
    assert (beside / ".pi" / "extensions" / "ledger-guard.js").read_text(encoding="utf-8") == old

    for where in (inside, project):  # there the old script finds the config by walking up
        assert "不拦" not in install(where)
    out = install(beside, "--force")
    assert "已安装 hook" in out and "不拦" not in out


def test_hooks_status_says_when_a_worktrees_own_config_differs_from_the_main_trees(tmp_path: Path, capsys) -> None:
    # A copy made by hand, as the README used to tell, keeps winning over the main tree's file and drifts from it.
    project, ledger = hooked_project(tmp_path, capsys)
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": "../ledgers/app", "deny": ["../notes"], "ledger_side": "human"}), encoding="utf-8")
    tree = linked_worktree(project, tmp_path / "deep" / "wt")

    # the same settings with the paths made absolute, as those instructions said: nothing to report
    same = {"ledger": str(ledger), "deny": [str(tmp_path / "notes")], "ledger_side": "human", "project": "app"}
    write(tree, ".dev-circuit/guard.json", json.dumps(same))
    code, out, _ = hook_status(capsys, tree)
    assert code == 0 and "与主工作树的不同" not in out
    [config] = [line for line in out.splitlines() if line.startswith("配置：")]
    assert "本工作树" in config and str(tree.resolve() / ".dev-circuit" / "guard.json") in config

    for drifted in ({"ledger": str(ledger)},  # what `hooks install --ledger` wrote in a worktree
                    {**same, "ledger": str(tmp_path / "ledgers" / "old")},
                    # copied without making the paths absolute: from deep/wt they lead somewhere else
                    {**same, "ledger": "../ledgers/app"}, {**same, "deny": ["../notes"]},
                    {**same, "ledger_side": "dev"}, {**same, "project": "wt"}):
        write(tree, ".dev-circuit/guard.json", json.dumps(drifted))
        code, out, _ = hook_status(capsys, tree)
        assert code == 0 and "与主工作树的不同" in out, drifted
        assert "notes" not in out and "ledgers" not in out  # that they differ, not what they say


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


def test_hooks_install_in_a_linked_worktree_does_not_fork_the_config(tmp_path: Path, capsys) -> None:
    # Run there with --ledger, as status used to suggest, it wrote a second guard.json holding the ledger path
    # alone: the main tree's ledger_side, deny and project were gone, and a human-side ledger became writable.
    project, ledger = hooked_project(tmp_path, capsys, "claude")
    (project / ".dev-circuit" / "guard.json").write_text(
        json.dumps({"ledger": str(ledger), "ledger_side": "human", "deny": ["../notes"]}), encoding="utf-8")
    tree = linked_worktree(project, tmp_path / "wt")
    install = ["hooks", "install", "--harness", "claude", "--project", str(tree)]

    assert cli.main(install) == 0  # no --ledger needed: the main tree's config is the one in use
    out = capsys.readouterr().out
    assert "沿用现有配置" in out and "主工作树" in out and "已写入配置" not in out
    # registering Claude Code is what is left to do in a worktree, in its own settings: they are not in git either
    assert "合并进这个 worktree 的 .claude/settings.local.json" in out
    snippet = json.loads((tree / ".dev-circuit" / "claude-settings.hook.json").read_text(encoding="utf-8"))
    command = snippet["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert (tree.resolve() / ".dev-circuit" / "hooks" / "ledger_guard.py").as_posix() in command  # this worktree's script
    assert not (tree / ".dev-circuit" / "guard.json").exists()

    assert cli.main([*install, "--ledger", str(ledger)]) == 0  # naming the ledger already configured is no conflict
    capsys.readouterr()
    assert cli.main([*install, "--ledger", str(tmp_path / "ledgers" / "other")]) == 2
    captured = capsys.readouterr()
    assert f"主工作树（{project.resolve()}）" in captured.err
    assert "--ledger 和主工作树的 guard.json 里的账本配置不一样" in captured.err
    assert "删掉" not in captured.err  # this worktree carries no guard.json of its own to delete
    assert "ledgers" not in captured.out + captured.err  # neither the configured path nor the one just given
    assert not (tree / ".dev-circuit" / "guard.json").exists()

    assert cli.main(["ledger", "check", "--project", str(tree)]) == 2  # still the main tree's settings
    assert "human 一侧" in capsys.readouterr().err

    # the dev side of a human-side ledger may not know where the ledger is at all: naming one here is a change too
    (project / ".dev-circuit" / "guard.json").write_text(json.dumps({"ledger_side": "human"}), encoding="utf-8")
    assert cli.main(install) == 0
    capsys.readouterr()
    assert cli.main([*install, "--ledger", str(ledger)]) == 2
    assert "ledgers" not in capsys.readouterr().err and not (tree / ".dev-circuit" / "guard.json").exists()


def test_hooks_install_in_a_linked_worktree_sends_the_human_to_the_main_tree_for_a_config(tmp_path: Path, capsys) -> None:
    project = _repo_on(tmp_path / "app", "main")
    tree = linked_worktree(project, tmp_path / "wt")
    install = ["hooks", "install", "--harness", "pi", "--project", str(tree)]

    for args in (install, [*install, "--ledger", str(tmp_path / "ledgers" / "app")]):
        assert cli.main(args) == 2
        err = capsys.readouterr().err
        assert f"主工作树（{project.resolve()}）" in err and "human" in err
        assert not (tree / ".dev-circuit").exists() and not (tree / ".pi").exists()

    # a config the hooks cannot read is the human's to mend, in the main tree; a second one here would hide it
    broken = write(project, ".dev-circuit/guard.json", '{"ledger": ')
    assert cli.main([*install, "--ledger", str(tmp_path / "ledgers" / "app")]) == 2
    captured = capsys.readouterr()
    assert "无法解析" in captured.err and str(broken.resolve()) in captured.err
    assert "将被覆盖" not in captured.out + captured.err
    assert broken.read_text(encoding="utf-8") == '{"ledger": ' and not (tree / ".dev-circuit").exists()


def test_hooks_install_refuses_a_ledger_that_a_worktrees_own_config_does_not_name(tmp_path: Path, capsys) -> None:
    """A worktree that carries its own guard.json, copied in by hand, keeps it: install does not rewrite or override it."""
    project, ledger = hooked_project(tmp_path, capsys)
    tree = linked_worktree(project, tmp_path / "wt")
    own = write(tree, ".dev-circuit/guard.json", json.dumps({"ledger": str(tmp_path / "ledgers" / "old")}))
    install = ["hooks", "install", "--harness", "pi", "--project", str(tree)]

    assert cli.main(install) == 0
    out = capsys.readouterr().out
    assert "沿用现有配置" in out and "本工作树自带的那份" in out and "主工作树的那份" not in out
    # one differs from this worktree's file, one from the main tree's: the refusal says which, not 这个 worktree 已有的
    # for both (given the very ledger this worktree's file names, that read as if the file said something else)
    for given, other in ((ledger, "本工作树自带的那份 guard.json"), (tmp_path / "ledgers" / "old", "主工作树的 guard.json")):
        assert cli.main([*install, "--ledger", str(given)]) == 2
        err = capsys.readouterr().err
        assert "ledgers" not in err
        assert f"--ledger 和{other} 里的账本配置不一样" in err and f"主工作树（{project.resolve()}）" in err
        assert "想跟主工作树一致就删掉它" in err
    assert json.loads(own.read_text(encoding="utf-8")) == {"ledger": str(tmp_path / "ledgers" / "old")}


def test_hooks_install_in_a_linked_worktree_knows_the_configured_ledger_however_it_is_written(tmp_path: Path, capsys,
                                                                                               monkeypatch) -> None:
    """guard.json may give the ledger relative to the main tree, through `..` or from `~`; --ledger arrives absolute."""
    project, ledger = hooked_project(tmp_path, capsys)
    tree = linked_worktree(project, tmp_path / "deep" / "wt")  # not beside the main tree: `..` leads elsewhere from here
    install = ["hooks", "install", "--harness", "pi", "--project", str(tree), "--ledger"]
    guard = project / ".dev-circuit" / "guard.json"
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(tmp_path))

    for written in ("../ledgers/app", str(ledger.parent / "elsewhere" / ".." / "app"), "~/ledgers/app"):
        guard.write_text(json.dumps({"ledger": written}), encoding="utf-8")
        assert cli.main([*install, str(ledger)]) == 0, written
        assert "沿用现有配置" in capsys.readouterr().out
        assert cli.main([*install, str(ledger.parent / "other")]) == 2, written

    # a folder that is not there yet cannot be looked up on disk: Windows still takes either case for the same place
    guard.write_text(json.dumps({"ledger": str(ledger.parent / "Later")}), encoding="utf-8")
    assert cli.main([*install, str(ledger.parent / "later")]) == (0 if os.name == "nt" else 2)
    capsys.readouterr()
    assert not (tree / ".dev-circuit").exists()


def test_hooks_install_in_a_linked_worktree_knows_a_ledger_configured_through_a_symlink(tmp_path: Path, capsys) -> None:
    """--ledger arrives with links followed, and guard.json may name the same folder through one."""
    project, ledger = hooked_project(tmp_path, capsys)
    tree = linked_worktree(project, tmp_path / "wt")
    link = tmp_path / "shortcut"
    try:
        link.symlink_to(ledger.parent, target_is_directory=True)
    except OSError:
        pytest.skip("这台机器不让当前用户建符号链接")
    (project / ".dev-circuit" / "guard.json").write_text(json.dumps({"ledger": str(link / "app")}), encoding="utf-8")
    install = ["hooks", "install", "--harness", "pi", "--project", str(tree), "--ledger"]

    for given in (ledger, link / "app"):
        assert cli.main([*install, str(given)]) == 0, given
        assert "沿用现有配置" in capsys.readouterr().out
    assert cli.main([*install, str(ledger.parent / "other")]) == 2
    assert not (tree / ".dev-circuit").exists()


def test_hooks_install_and_status_agree_when_only_the_main_trees_unused_config_is_broken(tmp_path: Path, capsys) -> None:
    # A worktree with a guard.json of its own does not use the main tree's. Status exited 0 there while install
    # refused because the main tree's file would not parse.
    project, ledger = hooked_project(tmp_path, capsys)
    tree = linked_worktree(project, tmp_path / "wt")
    write(tree, ".dev-circuit/guard.json", json.dumps({"ledger": str(ledger)}))
    broken = write(project, ".dev-circuit/guard.json", '{"ledger": ')
    install = ["hooks", "install", "--harness", "pi", "--project", str(tree)]

    code, out, _ = hook_status(capsys, tree)
    assert code == 0
    [reminder] = [line for line in out.splitlines() if line.startswith("提醒：")]
    assert "主工作树的 guard.json 无法解析" in reminder and "与主工作树的不同" not in out  # it cannot tell that much

    assert cli.main(install) == 0
    assert "沿用现有配置" in capsys.readouterr().out
    # --ledger is held against the main tree's file as well, and for that the file has to be readable
    assert cli.main([*install, "--ledger", str(ledger)]) == 2
    captured = capsys.readouterr()
    assert "无法解析" in captured.err and str(broken.resolve()) in captured.err and "ledgers" not in captured.err


def test_hooks_install_still_writes_the_config_in_a_worktree_of_a_bare_repository(tmp_path: Path, capsys) -> None:
    """No main working tree there to hold a shared guard.json, so such a worktree carries its own, as before."""
    bare, tree, ledger = tmp_path / "app.git", tmp_path / "wt", tmp_path / "ledgers" / "app"
    subprocess.run(["git", "clone", "-q", "--bare", str(_repo_on(tmp_path / "src", "main")), str(bare)],
                   check=True, capture_output=True)
    _git(bare, "worktree", "add", "-q", str(tree), "main")
    ledger.mkdir(parents=True)

    code, out, _ = hook_status(capsys, tree)  # nothing set up yet, and no main tree to send the human to
    assert code == 1 and "未找到" in out and "不回退" in out and "主工作树（" not in out

    assert cli.main(["hooks", "install", "--harness", "pi", "--project", str(tree), "--ledger", str(ledger)]) == 0
    capsys.readouterr()
    own = json.loads((tree / ".dev-circuit" / "guard.json").read_text(encoding="utf-8"))
    assert own["ledger"] == str(ledger.resolve())
    assert hook_status(capsys, tree)[0] == 0


@pytest.mark.parametrize("git_dir", [".bare", ".git"], ids=["a-git-file-pointing-at-it", "cloned-as-dot-git"])
def test_the_folder_holding_a_bare_repository_and_its_worktrees_is_no_main_working_tree(tmp_path: Path, capsys,
                                                                                         git_dir: str) -> None:
    # proj/.bare with a proj/.git file pointing at it, or the bare repository cloned as proj/.git; the worktrees are
    # proj/main, proj/feat. proj has a .git, so it passed for the main working tree: install in proj/main was refused
    # and sent the human to run `hooks install` in proj, where nothing can be committed.
    holder, ledger = tmp_path / "proj", tmp_path / "ledgers" / "app"
    holder.mkdir()
    ledger.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(_repo_on(tmp_path / "src", "main")), str(holder / git_dir)],
                   check=True, capture_output=True)
    if git_dir != ".git":
        (holder / ".git").write_text(f"gitdir: ./{git_dir}\n", encoding="utf-8")
    tree = holder / "main"
    _git(holder, "worktree", "add", "-q", str(tree), "main")

    code, out, _ = hook_status(capsys, tree)
    assert code == 1 and "未找到" in out and "不回退" in out and "主工作树（" not in out

    assert cli.main(["hooks", "install", "--harness", "pi", "--project", str(tree), "--ledger", str(ledger)]) == 0
    out = capsys.readouterr().out
    assert "已写入配置" in out and "不回退" in out
    assert json.loads((tree / ".dev-circuit" / "guard.json").read_text(encoding="utf-8"))["ledger"] == str(ledger.resolve())
    assert not (holder / ".dev-circuit").exists() and not (holder / ".pi").exists()
    assert hook_status(capsys, tree)[0] == 0


def test_hooks_status_and_install_go_by_the_guard_file_the_ledger_commands_fall_back_to(tmp_path: Path, capsys) -> None:
    """The folder a bare repository lies in is no working tree, yet a guard.json there is the one `ledger add` /
    `check` read from its worktrees. Status and install go by that file too, rather than write a second one."""
    bare, tree, ledger = tmp_path / "app.git", tmp_path / "wt", tmp_path / "ledgers" / "app"
    subprocess.run(["git", "clone", "-q", "--bare", str(_repo_on(tmp_path / "src", "main")), str(bare)],
                   check=True, capture_output=True)
    _git(bare, "worktree", "add", "-q", str(tree), "main")
    ledger.mkdir(parents=True)
    beside = write(tmp_path, ".dev-circuit/guard.json", json.dumps({"ledger": str(ledger), "ledger_side": "human"}))

    assert cli.main(["ledger", "check", "--project", str(tree)]) == 2
    assert "human 一侧" in capsys.readouterr().err
    code, out, _ = hook_status(capsys, tree)
    [config] = [line for line in out.splitlines() if line.startswith("配置：")]
    assert code == 0 and str(beside.resolve()) in config and "不回退" not in out
    assert cli.main(["hooks", "install", "--harness", "pi", "--project", str(tree)]) == 0
    assert "沿用现有配置" in capsys.readouterr().out and not (tree / ".dev-circuit").exists()


@pytest.mark.parametrize("kept_in", ["gitdirs", "store/gitdirs"], ids=["a-plain-folder", "a-folder-of-another-repository"])
def test_a_worktree_with_no_main_tree_to_fall_back_to_is_told_to_carry_the_whole_config(tmp_path: Path, capsys,
                                                                                         kept_in: str) -> None:
    # A linked worktree of a --separate-git-dir repository does not fall back to the other working tree's guard.json.
    # Status called the worktree itself 主工作树 and said to run `hooks install --ledger` there; that wrote the ledger
    # path alone, so a ledger kept on the human side became one the dev side writes and checks.
    main, tree, ledger = tmp_path / "app", tmp_path / "wt", tmp_path / "ledgers" / "app"
    ledger.mkdir(parents=True)
    _repo_on(tmp_path / "store", "main")  # the folder the git dir is kept in may lie in a working tree of its own
    (tmp_path / kept_in).mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", "--separate-git-dir", str(tmp_path / kept_in / "app.git"),
                    str(main)], check=True, capture_output=True)
    write(main, "README.md", "# r\n")
    install = ["hooks", "install", "--harness", "pi", "--project"]
    assert cli.main([*install, str(main), "--ledger", str(ledger)]) == 0
    assert "不回退" not in capsys.readouterr().out  # the main working tree is a project like any other
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "hooks")
    (main / ".dev-circuit" / "guard.json").write_text(json.dumps({"ledger": str(ledger), "ledger_side": "human"}),
                                                      encoding="utf-8")
    linked_worktree(main, tree)

    code, out, _ = hook_status(capsys, tree)  # the script came with git, the config did not
    assert code == 2
    [config] = [line for line in out.splitlines() if line.startswith("配置：")]
    assert "找不到 guard.json" in config and "human" in config and "不回退" in config
    assert "主工作树（" not in config and f"这个 worktree（{tree.resolve()}）" in config
    assert "照那份抄" in config and "ledger_side" in config and "绝对路径" in config

    assert cli.main([*install, str(tree)]) == 2
    err = capsys.readouterr().err
    assert "缺少 --ledger" in err and "不回退" in err and "ledger_side" in err

    assert cli.main([*install, str(tree), "--ledger", str(ledger)]) == 0  # still how the first config gets there
    out = capsys.readouterr().out
    [reminder] = [line for line in out.splitlines() if line.startswith("提醒：") and "不回退" in line]
    assert "已写入配置" in out and "ledger_side" in reminder and "绝对路径" in reminder and "ledgers" not in out
    assert cli.main([*install, str(tree), "--force"]) == 0  # nothing written this time: nothing to remind of
    assert "不回退" not in capsys.readouterr().out


def test_a_worktree_of_a_submodule_has_no_main_tree_to_fall_back_to_either(tmp_path: Path, capsys) -> None:
    """Its git dir sits under the superproject's .git/modules: the fallback finds no working tree beside that.

    The message named bare and --separate-git-dir repositories only, so here it described another layout.
    """
    library, parent = _repo_on(tmp_path / "lib", "main"), _repo_on(tmp_path / "super", "main")
    _git(parent, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(library), "sub")

    code, out, _ = hook_status(capsys, parent / "sub")  # the submodule itself is a project like any other
    assert code == 1 and "跑 devcircuit hooks install 生成" in out and "不回退" not in out

    tree = linked_worktree(parent / "sub", tmp_path / "wt")
    code, out, _ = hook_status(capsys, tree)
    [config] = [line for line in out.splitlines() if line.startswith("配置：")]
    assert code == 1 and "未找到" in config and "主工作树（" not in config
    assert "不回退" in config and "子模块" in config and "--separate-git-dir" in config and "bare" in config


def test_hooks_install_replaces_the_guard_file_in_one_step_and_only_when_it_changes(tmp_path: Path, capsys) -> None:
    # The hooks block every call while they cannot read guard.json, so a session must never find half of it.
    project, ledger = tmp_path / "app", tmp_path / "ledgers" / "app"
    project.mkdir()
    install = ["hooks", "install", "--harness", "pi", "--project", str(project)]
    guard = project / ".dev-circuit" / "guard.json"

    def identity() -> tuple[int, int]:
        status = guard.stat()
        return status.st_ino, status.st_mtime_ns

    assert cli.main([*install, "--ledger", str(ledger)]) == 0
    assert "已写入配置" in capsys.readouterr().out
    guard.write_text(json.dumps(json.loads(guard.read_text(encoding="utf-8"))), encoding="utf-8")  # laid out by hand
    first, text = identity(), guard.read_bytes()

    for args in ([*install, "--force"], [*install, "--ledger", str(ledger)]):  # nothing to change
        assert cli.main(args) == 0
        out = capsys.readouterr().out
        assert "沿用现有配置" in out and "已写入配置" not in out
        assert (identity(), guard.read_bytes()) == (first, text)

    assert cli.main([*install, "--ledger", str(tmp_path / "ledgers" / "other")]) == 0
    assert "已写入配置" in capsys.readouterr().out
    assert json.loads(guard.read_text(encoding="utf-8"))["ledger"] == str((tmp_path / "ledgers" / "other").resolve())
    assert identity()[0] != first[0]  # another file took its place whole; the old one was not written over
    assert [path.name for path in guard.parent.iterdir()] == ["guard.json"]  # and the temporary file is gone


def test_hooks_install_waits_for_a_reader_and_says_when_it_cannot_replace_the_guard_file(tmp_path: Path, capsys,
                                                                                          monkeypatch) -> None:
    # Windows does not replace a file while a hook has it open. A few tries later the PermissionError went up as a
    # traceback; writing the file in place, as before, got through.
    project, ledgers = tmp_path / "app", tmp_path / "ledgers"
    project.mkdir()
    install = ["hooks", "install", "--harness", "pi", "--project", str(project), "--ledger"]
    guard = project / ".dev-circuit" / "guard.json"
    assert cli.main([*install, str(ledgers / "app")]) == 0
    capsys.readouterr()
    real, held, tries = os.replace, [2], []

    def replace(source, target):
        tries.append(target)
        if len(tries) <= held[0]:
            raise PermissionError(13, "in use")  # what Windows answers while a reader holds the old file
        real(source, target)

    monkeypatch.setattr(cli.os, "replace", replace)
    assert cli.main([*install, str(ledgers / "second")]) == 0  # the reader let go after two tries
    capsys.readouterr()
    assert json.loads(guard.read_text(encoding="utf-8"))["ledger"] == str((ledgers / "second").resolve())
    assert len(tries) == 3

    held[0], before = 99, guard.read_bytes()
    script = project / ".pi" / "extensions" / "ledger-guard.js"
    script.unlink()
    assert cli.main([*install, str(ledgers / "third")]) == 2  # said, not raised
    captured = capsys.readouterr()
    assert "原文件没有动" in captured.err and str(guard) in captured.err
    assert "ledgers" not in captured.out + captured.err
    assert guard.read_bytes() == before
    assert [path.name for path in guard.parent.iterdir()] == ["guard.json"]  # the temporary file is not left behind
    assert not script.exists()  # nothing else was done once the config could not be written


def test_hooks_install_writes_through_a_guard_file_that_is_a_symlink(tmp_path: Path, capsys) -> None:
    """Replacing the link itself would leave the file it points at, kept elsewhere on this machine, with the old ledger."""
    project, ledger = tmp_path / "app", tmp_path / "ledgers" / "app"
    kept = write(tmp_path / "machine", "guard.json", json.dumps({"ledger": "../ledgers/old", "deny": ["../notes"]}))
    link = project / ".dev-circuit" / "guard.json"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(kept)
    except OSError:
        pytest.skip("这台机器不让当前用户建符号链接")

    assert cli.main(["hooks", "install", "--harness", "pi", "--project", str(project), "--ledger", str(ledger)]) == 0
    assert "已写入配置" in capsys.readouterr().out
    assert link.is_symlink()
    assert json.loads(kept.read_text(encoding="utf-8")) == {"ledger": str(ledger.resolve()), "deny": ["../notes"]}
    assert [path.name for path in kept.parent.iterdir()] == ["guard.json"]


@pytest.mark.skipif(os.name == "nt", reason="Windows 没有这些权限位")
def test_hooks_install_keeps_the_permissions_of_the_guard_file(tmp_path: Path, capsys) -> None:
    """The file that takes guard.json's place is a new one: without this it came out with the default permissions."""
    project, ledgers = tmp_path / "app", tmp_path / "ledgers"
    project.mkdir()
    install = ["hooks", "install", "--harness", "pi", "--project", str(project), "--ledger"]
    guard = project / ".dev-circuit" / "guard.json"
    assert cli.main([*install, str(ledgers / "app")]) == 0
    guard.chmod(0o600)

    assert cli.main([*install, str(ledgers / "other")]) == 0
    assert json.loads(guard.read_text(encoding="utf-8"))["ledger"] == str((ledgers / "other").resolve())
    assert guard.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("unusable", [7, " "], ids=["a-number", "blank"])
def test_hooks_install_does_not_keep_a_ledger_entry_the_hooks_cannot_read(tmp_path: Path, capsys, unusable) -> None:
    project, ledger = tmp_path / "app", tmp_path / "ledgers" / "app"
    guard = write(project, ".dev-circuit/guard.json", json.dumps({"ledger": unusable, "deny": ["../notes"]}))
    install = ["hooks", "install", "--harness", "pi", "--project", str(project)]

    assert cli.main(install) == 2  # it passed, and status then showed the 7 as the ledger
    assert "缺少 --ledger" in capsys.readouterr().err
    assert cli.main([*install, "--ledger", str(ledger)]) == 0
    assert json.loads(guard.read_text(encoding="utf-8")) == {"ledger": str(ledger.resolve()), "deny": ["../notes"]}


def test_hooks_install_does_not_ask_for_the_ledger_a_human_side_config_leaves_out(tmp_path: Path, capsys) -> None:
    # With the ledger on the human side the dev side's guard.json says so and names no ledger (docker/README).
    # Refreshing the hook script in such a project stopped at 缺少 --ledger, and giving one wrote the ledger path
    # back into the file; in a linked worktree of the same project the command went through.
    project = tmp_path / "app"
    guard = write(project, ".dev-circuit/guard.json", json.dumps({"ledger_side": "human", "deny": ["../notes"]}))
    install, before = ["hooks", "install", "--harness", "pi", "--project", str(project)], guard.read_bytes()

    for args in (install, [*install, "--force"]):
        assert cli.main(args) == 0
        assert "沿用现有配置" in capsys.readouterr().out and guard.read_bytes() == before
    assert (project / ".pi" / "extensions" / "ledger-guard.js").is_file()

    # only that setup: a ledger the dev side writes still has to be named, and one the hooks cannot read is not kept
    for unfinished in ({"deny": ["../notes"]}, {"ledger_side": "dev"}, {"ledger_side": "human", "ledger": 7}):
        guard.write_text(json.dumps(unfinished), encoding="utf-8")
        assert cli.main(install) == 2, unfinished
        assert "缺少 --ledger" in capsys.readouterr().err


@pytest.mark.parametrize("harness", sorted(cli.HOOKS))
def test_hooks_install_force_does_not_put_an_older_script_over_a_newer_one(tmp_path: Path, capsys, monkeypatch,
                                                                             harness: str) -> None:
    # A devcircuit not yet upgraded on one machine would put its old hook back over the one the trunk carries.
    project, ledger = tmp_path / "app", tmp_path / "ledgers" / "app"
    project.mkdir()
    install = ["hooks", "install", "--harness", harness, "--project", str(project), "--ledger", str(ledger)]
    script = project / cli.HOOKS[harness][1]
    ship_hooks(tmp_path, monkeypatch, "0.2.0")
    assert cli.main(install) == 0
    capsys.readouterr()
    shipped = hook_text(script.name, "0.2.0")
    assert script.read_text(encoding="utf-8") == shipped

    newer = hook_text(script.name, "0.10.0")
    script.write_text(newer, encoding="utf-8")
    for args in (install, [*install, "--force"]):
        assert cli.main(args) == 0
        out = capsys.readouterr().out
        assert "项目里的更新，未覆盖：先升级本机 devcircuit" in out and "已安装 hook" not in out
        assert script.read_text(encoding="utf-8") == newer

    # older, without a version line at all, or edited in place: --force replaces them, as it always did
    for stale in (hook_text(script.name, "0.1.9"), hook_text(script.name, None),
                  hook_text(script.name, "0.2.0", "edited")):
        script.write_text(stale, encoding="utf-8")
        assert cli.main(install) == 0
        assert "用 --force 覆盖" in capsys.readouterr().out and script.read_text(encoding="utf-8") == stale
        assert cli.main([*install, "--force"]) == 0
        assert "已安装 hook" in capsys.readouterr().out and script.read_text(encoding="utf-8") == shipped

    ship_hooks(tmp_path, monkeypatch, None)  # this devcircuit's script has no version line: nothing says which is newer
    script.write_text(newer, encoding="utf-8")
    assert cli.main([*install, "--force"]) == 0
    assert "已安装 hook" in capsys.readouterr().out and script.read_text(encoding="utf-8") == hook_text(script.name, None)


def test_migrate_does_not_send_a_newer_hook_script_to_force(tmp_path: Path, capsys, monkeypatch) -> None:
    """`migrate --check` called any difference 不是当前版本 and said to run `hooks install --force`."""
    project = tmp_path / "app"
    script = write(project, ".pi/extensions/ledger-guard.js", hook_text("ledger-guard.js", "0.1.9"))
    ship_hooks(tmp_path, monkeypatch, "0.2.0")

    def advice() -> str:
        assert cli.main(["migrate", "--check", "--project", str(project)]) == 1
        [line] = [line for line in capsys.readouterr().out.splitlines() if "ledger-guard.js" in line]
        return line

    assert "不是当前版本" in advice() and "--force" in advice()
    script.write_text(hook_text("ledger-guard.js", "0.3.0"), encoding="utf-8")
    assert "先升级本机 devcircuit" in advice() and "--force" not in advice()
    ship_hooks(tmp_path, monkeypatch, None)  # no version line to tell by: a script that differs is still listed
    assert "不是当前版本" in advice() and "--force" in advice()


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


def _declare_version(checker: Path, version: str) -> str:
    """Give a vendored checker another VERSION, as a copy from an older or a later devcircuit has; returns its text."""
    lines = checker.read_text(encoding="utf-8").splitlines(keepends=True)
    [index] = [index for index, line in enumerate(lines) if line.startswith("VERSION = ")]
    lines[index] = f'VERSION = "{version}"\n'
    checker.write_text("".join(lines), encoding="utf-8", newline="\n")
    return "".join(lines)


def test_vendor_does_not_downgrade_a_newer_checker(tmp_path: Path, capsys) -> None:
    """Vendored from a later devcircuit than this machine has: writing the packaged copy over it takes the checks back."""
    project = tmp_path / "app"
    project.mkdir()
    assert cli.main(["vendor", "--project", str(project)]) == 0
    checker = project / "scripts" / "spec_check.py"
    newer = _declare_version(checker, "99.0.0")
    capsys.readouterr()

    assert cli.main(["vendor", "--project", str(project)]) == 0
    out = capsys.readouterr().out
    assert checker.read_text(encoding="utf-8") == newer
    [line] = [line for line in out.splitlines() if str(checker) in line]
    assert line.startswith("项目里的更新，未覆盖：先升级本机 devcircuit")
    assert "未变" in out and "更新：" not in out  # doc_guard.py is the packaged one and stays


@pytest.mark.parametrize("version", ["0.0.1", None], ids=["older", "same-version-edited"])
def test_vendor_still_replaces_a_copy_that_is_not_newer(tmp_path: Path, capsys, version: str | None) -> None:
    project = tmp_path / "app"
    project.mkdir()
    assert cli.main(["vendor", "--project", str(project)]) == 0
    checker = project / "scripts" / "doc_guard.py"
    packaged = checker.read_text(encoding="utf-8")
    if version:
        _declare_version(checker, version)
    else:
        checker.write_text(packaged + "\n# a local edit\n", encoding="utf-8", newline="\n")
    capsys.readouterr()

    assert cli.main(["vendor", "--project", str(project)]) == 0
    assert "更新：" in capsys.readouterr().out
    assert checker.read_text(encoding="utf-8") == packaged


def test_vendor_is_stable_after_init(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"

    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    capsys.readouterr()

    # init writes LF; vendor must not "update" the same bytes back over CRLF.
    assert cli.main(["vendor", "--project", str(project)]) == 0
    out = capsys.readouterr().out
    assert "未变" in out and "更新" not in out


def test_init_gives_the_project_a_gitignore_for_the_guard_config_and_caches(tmp_path: Path, capsys) -> None:
    """The template is stored as `gitignore` (npm drops files named .gitignore); the project still gets the dot."""
    project = tmp_path / "app"

    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    lines = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".dev-circuit/guard.json" in lines and "__pycache__/" in lines
    assert not (project / "gitignore").exists()


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
    out = capsys.readouterr().out
    assert ".claude/settings.local.json" in out and "worktree" not in out  # a project of its own is not called one


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


WORKFLOW = ".github/workflows/doc-guard.yml"
WORKFLOW_KEPT_MAIN = "CI 工作流的触发分支按 main 写的，主干定了以后改 .github/workflows/doc-guard.yml"


def _workflow_branches(root: Path) -> list[str]:
    """The `branches:` lines of the scaffolded CI workflow."""
    return [line.strip() for line in (root / WORKFLOW).read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("branches:")]


@pytest.mark.parametrize("trunk", ["workbench", "team/release-2.x"])
def test_adopt_points_the_ci_workflow_at_the_repos_trunk(tmp_path: Path, capsys, trunk: str) -> None:
    """The workflow template says main; in a repo adopted on workbench the checks never ran on the trunk."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", trunk, str(repo)], check=True)

    assert cli.main(["init", "--path", str(repo), "--adopt"]) == 0
    assert _workflow_branches(repo) == [f'branches: [ "{trunk}" ]'] * 2
    assert "CI 工作流" not in capsys.readouterr().out


def test_adopt_takes_the_workflow_trunk_from_an_existing_agents_file(tmp_path: Path, capsys) -> None:
    """AGENTS.md is where the trunk is written down; the branch the repo is on is only a guess."""
    repo = tmp_path / "repo"
    write(repo, "AGENTS.md", "# 已有入口\n\n- 主干：`release/2.x`\n")
    _git(repo, "init", "-q", "-b", "develop")

    assert cli.main(["init", "--path", str(repo), "--adopt"]) == 0
    assert _workflow_branches(repo) == ['branches: [ "release/2.x" ]'] * 2
    assert "CI 工作流" not in capsys.readouterr().out


@pytest.mark.parametrize("branch, agents", [
    ("feat/first", None),
    ("develop", "# 已有入口\n"),
    ("develop", "# 已有入口\n\n- 主干：\n"),
    ("develop", '# 已有入口\n\n- 主干：`we"ird`\n'),
    ("主线", None),
], ids=["no-safe-guess", "agents-names-no-trunk", "trunk-line-without-a-branch", "quote-in-the-name",
        "name-outside-plain-ascii"])
def test_adopt_keeps_main_in_the_workflow_and_says_so_when_it_cannot_tell(
        tmp_path: Path, capsys, branch: str, agents: str | None) -> None:
    """No trunk to read, or a name that cannot go into the quoted YAML string as it is: main stays, and adopt says so."""
    repo = tmp_path / "repo"
    repo.mkdir()
    if agents is not None:
        write(repo, "AGENTS.md", agents)
    _git(repo, "init", "-q", "-b", branch)

    assert cli.main(["init", "--path", str(repo), "--adopt"]) == 0
    assert _workflow_branches(repo) == ['branches: [ "main" ]'] * 2
    assert WORKFLOW_KEPT_MAIN in capsys.readouterr().out


def test_adopt_leaves_an_existing_ci_workflow_alone(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    write(repo, WORKFLOW, "name: Existing CI\n")
    _git(repo, "init", "-q", "-b", "feat/first")

    assert cli.main(["init", "--path", str(repo), "--adopt"]) == 0
    assert (repo / WORKFLOW).read_text(encoding="utf-8") == "name: Existing CI\n"
    assert "CI 工作流" not in capsys.readouterr().out  # nothing was written, so there is nothing to say about it


def test_init_writes_main_into_the_workflow_of_a_new_project(tmp_path: Path, capsys) -> None:
    project = tmp_path / "app"

    assert cli.main(["init", "--path", str(project), "--name", "App"]) == 0
    assert _workflow_branches(project) == ['branches: [ "main" ]'] * 2
    assert "CI 工作流" not in capsys.readouterr().out


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
