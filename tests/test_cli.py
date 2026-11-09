"""The guards are also a CLI; these tests cover the wrapper, not the rules."""

import json
from pathlib import Path

import devcircuit.cli as cli


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_version(capsys) -> None:
    assert cli.main(["--version"]) == 0
    assert "devcircuit" in capsys.readouterr().out


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


def test_unknown_arguments_are_rejected(tmp_path: Path, capsys) -> None:
    # Only the checker passthroughs forward extra flags; elsewhere a typo must not be dropped silently.
    assert cli.main(["context", "--map", "--root", str(tmp_path), "--bogus"]) == 2
    assert "--bogus" in capsys.readouterr().err
