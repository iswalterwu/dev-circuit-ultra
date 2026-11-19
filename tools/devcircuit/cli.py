"""devcircuit command line interface."""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from . import close as close_module
from . import context as context_module
from . import ledger as ledger_module
from . import migrate as migrate_module
from ._loader import asset_path, load_script, script_path
from .scaffold import ScaffoldError, init_ledger, init_project
from .sync import sync as sync_skills

CONFIG_DIR = ".dev-circuit"
CONFIG_NAME = "guard.json"
GUARD_IGNORE = f"{CONFIG_DIR}/{CONFIG_NAME}"
SNIPPET_IGNORE = f"{CONFIG_DIR}/claude-settings.hook.json"
IS_WINDOWS = os.name == "nt"
COMMIT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")  # a full SHA-1 or SHA-256 object name, as pip records it
HOOKS = {
    "pi": (("pi", "ledger-guard.js"), Path(".pi") / "extensions" / "ledger-guard.js"),
    "claude": (("claude", "ledger_guard.py"), Path(CONFIG_DIR) / "hooks" / "ledger_guard.py"),
}
HOOK_COPY_NOTES = {
    migrate_module.SAME: "与本机 devcircuit 带的相同",
    migrate_module.OLDER: "比本机 devcircuit 带的旧（在主干上 hooks install --force 更新后提交）",
    migrate_module.NEWER: "比本机 devcircuit 带的新（先升级本机 devcircuit）",
    migrate_module.DIFFERENT: "与本机 devcircuit 带的不同（读不出谁新谁旧）",
}
# In a linked worktree the script comes with the branch: there it is brought up to date by a merge.
OLDER_IN_A_WORKTREE = "比本机 devcircuit 带的旧（主干换上新脚本后，把主干合并进这个 worktree 的分支）"
MAIN_TREE_FALLBACK = (0, 2, 0)  # hook scripts look for guard.json in the main working tree from this version on
# The script a Claude Code hook command runs; quoted, the path may hold spaces.
GUARD_SCRIPT = re.compile(r'"([^"]*ledger_guard\.py)"|\'([^\']*ledger_guard\.py)\'|(\S*ledger_guard\.py)')
# Claude Code reads exit 2 as "block this call", and that is also how python exits when it cannot
# open a script. Run the hook only if it is there (an older branch may not have it), so a missing
# script lets calls through instead of blocking every one. -I keeps the project's own modules
# (a json.py at the root, say) out of the interpreter's path. No $, backticks or double quotes
# inside, so bash, cmd and PowerShell all pass it through unchanged.
HOOK_LAUNCHER = ("import os,runpy,sys; sys.argv=sys.argv[1:]; "
                 "os.path.isfile(sys.argv[0]) and runpy.run_path(sys.argv[0], run_name='__main__')")


def installed_commit() -> str | None:
    """The commit pip recorded when this copy was installed from a git URL (PEP 610), else None.

    `pipx install git+…` installs whatever the branch holds, so two builds can carry one version.
    The metadata has to belong to the code that is running: another install of devcircuit on the
    path, or a dist-info an upgrade left behind in the same folder, must not lend its commit.
    """
    from importlib import metadata  # costs more to import than the lookup itself; only --version needs it

    own = Path(__file__).with_name("__init__.py")
    for distribution in metadata.distributions(name="devcircuit"):
        try:
            if distribution.version != __version__ or not os.path.samefile(
                    distribution.locate_file("devcircuit/__init__.py"), own):
                continue
            recorded = json.loads(distribution.read_text("direct_url.json") or "null")["vcs_info"]
            commit = recorded["commit_id"] if recorded["vcs"] == "git" else None
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            continue
        return commit if isinstance(commit, str) and COMMIT_ID.fullmatch(commit) else None
    return None


def version_line() -> str:
    commit = installed_commit()
    return f"devcircuit {__version__}" + (f" (git {commit[:7]})" if commit else "")


class _Version(argparse.Action):
    """`--version`, with the metadata import and lookup left until asked for: every command builds the parser."""

    def __call__(self, parser, namespace, values, option_string=None):
        print(version_line())
        parser.exit()


def python_command() -> str:
    """Name the interpreter the way this machine spells it.

    On Windows `python3` is usually the WindowsApps store alias, so `python` comes first there.
    """
    candidates = ("python", "python3") if IS_WINDOWS else ("python3", "python")
    for candidate in candidates:
        if shutil.which(candidate):
            return candidate
    return candidates[0]


def shell_expands(hook: Path) -> str:
    """The characters of the script path a shell rewrites inside the double quotes of the Claude command, or "".

    sh, bash and PowerShell expand $NAME and backticks there, cmd expands %NAME%. The path then names nothing,
    the launcher takes the script for missing, and every call is let through: installed, and not guarding.
    """
    return "".join(character for character in "$%`\"" if character in Path(hook).as_posix())


def _expands_note(hook: Path, characters: str) -> str:
    return (f"{hook} 的路径里有 shell 会展开的字符（{characters}）：Claude 的 hook 命令把这个路径放在双引号里，"
            "sh / bash / PowerShell 展开 $NAME 和反引号，cmd 展开 %NAME%；展开后路径对不上，命令当成脚本不在而放行，"
            "账本边界在这里不拦。把项目放到不含这些字符的路径下。")


def claude_snippet(hook: Path) -> str:
    """Build the .claude/settings.json fragment with proper JSON escaping."""
    command = f'{python_command()} -I -c "{HOOK_LAUNCHER}" "{Path(hook).as_posix()}"'
    payload = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": command},
                    ],
                },
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _ignore(project: Path, entry: str, why: str) -> bool:
    """Have git ignore a machine-local file under .dev-circuit/; True when this call added the line.

    The command does it rather than the agent: once the hook is on, any tool call that names
    guard.json, an edit of .gitignore included, is blocked.
    """
    try:
        probe = subprocess.run(["git", "-C", str(project), "check-ignore", "-q", "--no-index", entry],
                               capture_output=True)
        if probe.returncode == 0:  # already covered, maybe by a wider rule such as .dev-circuit/*.json
            return False
    except OSError:
        pass
    gitignore = project / ".gitignore"
    data = gitignore.read_bytes() if gitignore.is_file() else b""
    lines = data.decode("utf-8-sig", errors="replace").splitlines()
    if any(line.strip().lstrip("/") == entry for line in lines):
        return False
    eol = "\r\n" if b"\r\n" in data else "\n"
    lead = eol if data and not data.endswith(b"\n") else ""
    with gitignore.open("a", encoding="utf-8", newline="") as handle:
        handle.write(f"{lead}# 本机路径，不要提交：{why}{eol}{entry}{eol}")
    return True


def _out(stream=None, errors=None):
    stream = stream or sys.stdout
    try:
        stream.reconfigure(encoding="utf-8", **({"errors": errors} if errors else {}))
    except (AttributeError, OSError):
        pass
    return stream


def _passthrough(name: str, rest: list[str]) -> int:
    try:
        module = load_script(name)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 2
    return int(module.main(rest))


COMMON_FLAGS = {"--root", "--json", "--ignore", "--ignore-file", "--no-ignore-file"}
EXTRA_FLAGS = {
    "doc_guard": set(),
    "spec_check": {"--report"},
}


def _split_for(name: str, rest: list[str], rules) -> list[str]:
    """Keep only the flags the given guard understands, so `check` can share argv."""
    kept: list[str] = []
    index = 0
    while index < len(rest):
        token = rest[index]
        if token == "--ignore-rule":
            value = rest[index + 1] if index + 1 < len(rest) else None
            if value in rules:
                kept.extend([token, value])
            index += 2 if value is not None else 1
            continue
        if token.startswith("--ignore-rule="):
            value = token.split("=", 1)[1]
            if value in rules:
                kept.append(token)
            index += 1
            continue
        if token == "--list-rules" or (token == "--report" and token not in EXTRA_FLAGS[name]):
            index += 1
            continue
        kept.append(token)
        index += 1
    return kept


def _check(rest: list[str]) -> int:
    codes = []
    for name in ("doc_guard", "spec_check"):
        print(f"== {name} ==", file=_out())
        try:
            rules = load_script(name).RULES
        except RuntimeError as error:
            print(error, file=sys.stderr)
            return 2
        codes.append(_passthrough(name, _split_for(name, rest, rules)))
    if 2 in codes:
        return 2
    return 1 if 1 in codes else 0


def _rules() -> int:
    out = _out()
    for name, label in (("doc_guard", "doc_guard"), ("spec_check", "spec_check")):
        try:
            module = load_script(name)
        except RuntimeError as error:
            print(error, file=sys.stderr)
            return 2
        print(f"{label}:", file=out)
        for rule in module.RULES:
            print(f"  {rule:<20}{module.RULE_HELP[rule]}", file=out)
    return 0


def _read_guard(path: Path) -> dict:
    """The config `hooks install` starts from in a project of its own: whatever it cannot read is written anew."""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        print(f"警告：{path} 无法解析（{error}），将被覆盖。", file=sys.stderr)
        return {}
    return raw if isinstance(raw, dict) else {}


def _not_json(constant: str):
    """NaN and Infinity: python's json reads them, JSON.parse in the pi hook does not."""
    raise ValueError(constant)


def _load_guard(path: Path) -> tuple[dict | None, str]:
    """guard.json read by the rule the hooks follow: (config, ""), or (None, why it cannot be used).

    UTF-8 with or without a BOM; JSON as both hooks parse it; a JSON object; `ledger`, when it is there, a
    path that is not blank. The reason is one of a few fixed sentences: a parser's own message can quote the
    file, which names the ledger.
    """
    try:
        loaded = json.loads(path.read_bytes().decode("utf-8-sig"), parse_constant=_not_json)
    except OSError:
        return None, "读不出这个文件"
    except (ValueError, RecursionError):
        return None, "不是合法的 UTF-8 JSON"
    if not isinstance(loaded, dict):
        return None, "内容不是一个 JSON 对象"
    if "ledger" in loaded and not (isinstance(loaded["ledger"], str) and loaded["ledger"].strip()):
        return None, "ledger 应该是非空的路径字符串"
    return loaded, ""


def _guard_site(project: Path) -> tuple[Path | None, Path, str, Path | None, bool]:
    """ledger.locate(), the main working tree whose guard.json a linked worktree shares (None: no such tree),
    and whether this is a linked worktree left without one.

    A worktree of a bare repository, of one made with --separate-git-dir, or of a submodule has no main
    working tree where the fallback looks. It carries its own guard.json and is handled like any project,
    except that the human is told so: another working tree's config, ledger_side and deny included, does
    not reach it.
    """
    found, root, source = ledger_module.locate(project)
    if source == ledger_module.MAIN_TREE:
        return found, root, source, root, False
    main = ledger_module._main_tree(project)
    shared = main if main and (main / ".git").exists() and _is_working_tree(main) else None
    return found, root, source, shared, main is not None and shared is None


def _is_working_tree(folder: Path) -> bool:
    """Whether git has a working tree in the folder a repository lies in.

    A bare repository kept as proj/.bare behind a proj/.git file, or cloned as proj/.git, with its worktrees
    in proj/main and proj/feat: proj has a .git and is no working tree. Taken for the main one, it made
    `hooks install` in proj/main refuse and send the human to install in proj.
    """
    try:
        inside = ledger_module._git(folder, "rev-parse", "--is-inside-work-tree")
    except OSError:
        return False
    return inside.stdout.strip() == "true"  # nothing on stdout when git finds no repository there


def _project_above(project: Path) -> Path | None:
    """The folder to give as --project when `project` lies inside a working tree and the config is kept above it.

    --project is the current folder unless given. From src/, `hooks status` found nothing and said to run
    `hooks install`, and that wrote a second guard.json in src/ holding the ledger path alone. A project kept
    in a folder of a larger repository has nothing configured above it and is left as it was.
    """
    try:
        prefix = ledger_module._git(project, "rev-parse", "--show-prefix")
    except OSError:
        return None
    depth = len([part for part in prefix.stdout.strip().split("/") if part]) if prefix.returncode == 0 else 0
    for folder in list(project.parents)[:depth]:  # nearest first, no further than the top of the working tree
        if ledger_module.locate(folder)[0]:
            return folder
    return None


NO_FALLBACK = "这个 worktree 属于 bare 仓库、--separate-git-dir 建的仓库或子模块，这种布局不回退到别的工作区的配置"
CARRY_OVER = "保留 project / deny / ledger_side，相对路径改成绝对路径"


def _place(root: Path, entry: str) -> str:
    """A path from guard.json as one comparable string; a relative one counts from the folder holding .dev-circuit."""
    path = os.path.join(root, os.path.expanduser(entry))
    try:
        path = os.path.realpath(path)
    except (OSError, ValueError):
        path = os.path.abspath(path)
    return os.path.normcase(path)


def _deny_entries(config: dict) -> tuple[list[str], bool]:
    """The `deny` entries the hooks can use, and whether the field is written as they expect: a list of paths."""
    deny = config.get("deny")
    if deny is None:
        return [], True
    usable = [entry for entry in deny if isinstance(entry, str) and entry.strip()] if isinstance(deny, list) else []
    return usable, isinstance(deny, list) and len(usable) == len(deny)


def _effect(config: dict | None, root: Path, main: Path) -> tuple | None:
    """What a guard.json comes to once its paths are resolved, so two of them compare without showing either."""
    if config is None:
        return None
    ledger = config.get("ledger")
    return (_place(root, ledger) if ledger else None,
            sorted(_place(root, entry) for entry in _deny_entries(config)[0]),
            config.get("project") or main.name,  # the name records are filed under: the main tree's, unless given
            config.get("ledger_side"))


def _cannot_see(script: Path, shipped: Path, project: Path, found: Path) -> bool:
    """Whether a worktree's hook script misses the main tree's guard.json that the CLI found for it.

    A script from before 0.2.0 only walks up from the session's folder. In a worktree beside the main tree
    that walk meets no guard.json and the script blocks nothing, while the config itself reads fine.
    """
    if migrate_module.hook_copy(script, shipped) != migrate_module.OLDER:
        return False  # not older, or the script this devcircuit ships has no version line to tell by
    version = migrate_module.hook_version(script)
    if version is not None and version >= MAIN_TREE_FALLBACK:
        return False
    for folder in (project, *project.parents):
        candidate = folder / CONFIG_DIR / CONFIG_NAME
        if candidate.is_file():
            return not candidate.samefile(found)
    return True


def _replace_file(path: Path, text: str) -> None:
    """Put the new content in place in one step.

    The hooks block every tool call while they cannot read guard.json, so a session running beside
    `hooks install` must find the old file or the new one, never the first half of a write.
    """
    path = path.resolve()  # a symlink stays one: the file it points at is the one replaced
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        if not IS_WINDOWS and path.exists():  # Windows has the read-only bit alone, and a read-only file is not replaced
            shutil.copymode(path, temporary)
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:  # Windows refuses while a reader holds the old file open
                if attempt == 4:
                    raise
                time.sleep(0.05)
    finally:
        temporary.unlink(missing_ok=True)


def _worktree_refusal(harness: str, found: Path | None, root: Path, main: Path, wanted: Path | None) -> str | None:
    """Why `hooks install` stops in a linked worktree, or None when the config in use there can stay as it is.

    --ledger is held against the main tree's guard.json and against one the worktree carries itself. Another
    ledger is the human's change to make in the main tree; the configured path is not echoed back. Without
    --ledger only the file in use is read: a worktree with its own config is not stopped by a main tree's
    file it does not use, as `hooks status` does not fail on it either.
    """
    shared = main / CONFIG_DIR / CONFIG_NAME
    if found is None:
        return (f"这是 linked worktree，主工作树（{main}）还没有账本配置。这里不另写 guard.json：由 human 先在主工作树跑 "
                f"devcircuit hooks install --harness {harness} --ledger <账本>，再回到这个 worktree。")
    for path, base in dict.fromkeys([(found, root), (shared, main)]):
        if not path.is_file() or (path != found and wanted is None):
            continue
        config, problem = _load_guard(path)
        if config is None:
            return f"{path} 无法解析：{problem}。由 human 修好它，再回到这个 worktree。"
        ledger = config.get("ledger")
        if wanted is not None and (not ledger or _place(base, ledger) != _place(base, str(wanted))):
            which = "主工作树的" if path == shared else "本工作树自带的那份"
            own = "" if found == shared else "；本工作树自带的那份 guard.json 优先，想跟主工作树一致就删掉它"
            return (f"--ledger 和{which} guard.json 里的账本配置不一样。linked worktree 里不另写 guard.json：要换账本，"
                    f"由 human 在主工作树（{main}）改{own}。")
    return None


def _install_hooks(args) -> int:
    out = _out()
    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"项目目录不存在：{project}", file=sys.stderr)
        return 2
    wanted = Path(args.ledger).resolve() if args.ledger else None
    if wanted is not None and (wanted == project or project in wanted.parents):
        print(f"账本不能放在项目里：{wanted}", file=sys.stderr)
        print("账本是项目之外的私有仓库；开发 agent 只读写项目。", file=sys.stderr)
        return 2

    found, root, source, main, alone = _guard_site(project)
    above = _project_above(project) if found is None else None
    if above is not None:
        print(f"这里是 {above} 里面的目录，账本配置在那一层。这里不另写 guard.json：--project 给 {above}。", file=sys.stderr)
        return 2
    if main is not None:
        # A linked worktree uses the main tree's guard.json. Writing one here made a second config with the
        # ledger path alone: the main tree's ledger_side, deny and project no longer applied in this worktree.
        refusal = _worktree_refusal(args.harness, found, root, main, wanted)
        if refusal:
            print(refusal, file=sys.stderr)
            return 2
        config_path = found
        kept = "本工作树自带的那份" if source == ledger_module.HERE else "主工作树的那份，linked worktree 里不另写"
    else:
        config_path = project / CONFIG_DIR / CONFIG_NAME
        config = _read_guard(config_path)
        stored = dict(config)
        if wanted is not None:
            config["ledger"] = str(wanted)
        # With the ledger on the human side the dev side's file may leave the path out: there is none to ask for.
        human_side = "ledger" not in config and config.get("ledger_side") == ledger_module.HUMAN_SIDE
        if not human_side and not (isinstance(config.get("ledger"), str) and config["ledger"].strip()):
            print("缺少 --ledger：账本在项目之外，需要给它一个绝对路径。", file=sys.stderr)
            if alone:
                print(f"{NO_FALLBACK}：别的工作区已有一份 guard.json 的，由 human 照那份抄进这个 worktree，{CARRY_OVER}。",
                      file=sys.stderr)
            return 2
        kept = "没有改动，未重写" if config == stored else None
        if kept is None:
            try:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                _replace_file(config_path, json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            except OSError:  # the error's own message is left out: nothing here repeats what the file holds
                print(f"写不进 {config_path}：文件正被占用，或没有写权限。原文件没有动，稍后重试。", file=sys.stderr)
                return 2
    ignored_now = [entry for entry, why in ((GUARD_IGNORE, "账本位置只对这台机器有意义"),
                                            (SNIPPET_IGNORE, "hook 片段里是这台机器的路径"))
                   if (entry == GUARD_IGNORE or args.harness == "claude") and _ignore(project, entry, why)]

    asset, relative = HOOKS[args.harness]
    destination = project / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and migrate_module.hook_copy(destination, asset_path(*asset)) == migrate_module.NEWER:
        print(f"项目里的更新，未覆盖：先升级本机 devcircuit（{destination}）", file=out)
    elif destination.exists() and not args.force:
        print(f"已存在，未覆盖：{destination}（用 --force 覆盖）", file=out)
        if source == ledger_module.MAIN_TREE and _cannot_see(destination, asset_path(*asset), project, found):
            print("提醒：这份脚本还不会回退到主工作树的配置，在这个 worktree 里不拦：把主干合并进这个 worktree 的分支"
                  "（主干要已换上新脚本），或带 --force 重跑后提交。", file=out)
    else:
        shutil.copyfile(asset_path(*asset), destination)
        if destination.suffix == ".py":
            destination.chmod(destination.stat().st_mode | 0o111)
        print(f"已安装 hook：{destination}", file=out)

    # Where the ledger is stays out of the output: guard.json holds it, and the hook keeps the agent out of that file.
    if kept:
        print(f"沿用现有配置：{config_path}（{kept}）", file=out)
    else:
        print(f"已写入配置：{config_path}（账本配置已写入，账本路径不在这里显示）", file=out)
        if alone:
            print(f"提醒：{NO_FALLBACK}，这里用的是刚写的这一份。别的工作区那份 guard.json 里还有 project / deny / "
                  "ledger_side 的，由 human 照抄进这一份，相对路径改成绝对路径。", file=out)
    if ignored_now:
        print(f"已把 {'、'.join(ignored_now)} 加进 .gitignore：它们记录的是本机路径。", file=out)
    leftover = "、".join(([".gitignore"] if ignored_now else []) + [Path(relative).as_posix()])
    print(f"下一步：{leftover} 还没提交的话，在主干上提交；留着不提交，devcircuit close 会因为工作区不干净而拒绝收尾。",
          file=out)
    print("", file=out)
    if args.harness == "pi":
        print("pi 会在可信项目里自动加载 .pi/extensions/*.js；/reload 生效。", file=out)
        print("如果已把 hook 装到 ~/.pi/agent/extensions/，删掉项目这份即可。", file=out)
    else:
        expanded = shell_expands(destination)
        if expanded:
            print(f"警告：{_expands_note(destination, expanded)}", file=sys.stderr)
        snippet = claude_snippet(destination)
        snippet_path = project / CONFIG_DIR / "claude-settings.hook.json"
        snippet_path.write_text(snippet + "\n", encoding="utf-8")
        where = "这个 worktree 的" if main is not None else ""
        print(f"把下面的 hooks 段合并进{where} .claude/settings.local.json（片段里是本机路径，这个文件不提交）：", file=out)
        print(snippet, file=out)
        print("", file=out)
        print(f"同样的内容也写到了 {snippet_path}", file=out)
        print("hook 脚本不在时（比如切到还没装 hook 的旧分支），这条命令放行，不会拦下所有调用。", file=out)
    return 0


def _scaffold(action) -> int:
    try:
        return action()
    except ScaffoldError as error:
        print(str(error), file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2


def _vendor(args) -> int:
    """Copy or refresh the guard scripts inside the project."""
    out = _out()
    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"项目目录不存在：{project}", file=sys.stderr)
        return 2
    target_dir = project / "scripts"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in ("doc_guard", "spec_check"):
        source = script_path(name)
        destination = target_dir / f"{name}.py"
        # Compare and write normalised text: the packaged copy may carry CRLF
        # depending on how the wheel was built, the project copy is always LF.
        text = source.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        if not destination.exists():
            destination.write_text(text, encoding="utf-8", newline="\n")
            print(f"新增：{destination}", file=out)
            continue
        existing = destination.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        if existing == text:
            print(f"未变：{destination}", file=out)
        elif migrate_module.checker_version(existing) > migrate_module.checker_version(text):
            # Vendored from a later devcircuit than the one installed here: the packaged copy
            # written over it would quietly take the project's checks back a version.
            print(f"项目里的更新，未覆盖：先升级本机 devcircuit（{destination}）", file=out)
        else:
            destination.write_text(text, encoding="utf-8", newline="\n")
            print(f"更新：{destination}", file=out)
    print("", file=out)
    print("提交前检查仍然跑 python scripts/doc_guard.py 和 python scripts/spec_check.py；"
          "下次升级再跑一次 devcircuit vendor。", file=out)
    return 0


def _claude_registration(project: Path) -> tuple[str | None, bool]:
    """The settings file of this working tree that has Claude Code run ledger_guard.py before tool calls, if any,
    and whether every such command names another script than this tree's own copy.

    A worktree's settings may point at the main tree's script. A path that is not absolute counts as the own
    copy: it is read from the session's folder, or starts with a variable such as $CLAUDE_PROJECT_DIR.
    """
    own = _place(project, str(HOOKS["claude"][1]))
    for name in ("settings.local.json", "settings.json"):
        try:
            settings = json.loads((project / ".claude" / name).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, RecursionError):
            continue
        named = [next(filter(None, match.groups())) for command in migrate_module._hook_commands(settings)
                 for match in GUARD_SCRIPT.finditer(command)]
        if named:
            return f".claude/{name}", all(os.path.isabs(os.path.expanduser(script)) and _place(project, script) != own
                                          for script in named)
    return None, False


def _folder_there(path: str) -> bool | None:
    """Whether a folder is there; None when this user may not look.

    The ledger of the stronger tiers belongs to another OS user. Path.is_dir() raised PermissionError on
    it before Python 3.14, the traceback named the ledger, and from 3.14 on the folder counted as missing.
    """
    try:
        return stat.S_ISDIR(os.stat(path).st_mode)
    except PermissionError:
        return None
    except (OSError, ValueError):
        return False


def _config_lines(config: dict, root: Path, main: Path | None) -> list[str]:
    """What status says about a readable guard.json, leaving out the paths in it.

    `main` is the main working tree when the file belongs to a linked worktree: a copy made there by hand
    keeps winning over the main tree's file, and nothing said so once the two had drifted apart.
    """
    ledger = config.get("ledger")
    there = _folder_there(os.path.join(root, os.path.expanduser(ledger))) if ledger else False
    folder = {True: "目录存在", False: "目录不存在", None: "目录看不到：当前用户没有访问权限"}[there]
    lines = ["账本：" + (f"已配置（{folder}）" if ledger else "未配置")]
    if ledger and there is False:
        lines.append("提醒：账本路径当前不存在，hook 仍会拦截对这个路径的访问。")
    usable, well_formed = _deny_entries(config)
    if usable or not well_formed:
        lines.append(f"额外拒绝 {len(usable)} 项"
                     + ("" if well_formed else "（deny 应该是路径字符串数组，写法不对的部分 hook 不拦）"))
    shared = main / CONFIG_DIR / CONFIG_NAME if main else None
    theirs = _load_guard(shared)[0] if shared and shared.is_file() else None
    if shared and shared.is_file() and theirs is None:
        lines.append("提醒：主工作树的 guard.json 无法解析，由 human 修好；本工作树自带的这份优先，在这里不受影响。")
    elif theirs is not None and _effect(theirs, main, main) != _effect(config, root, main):
        lines.append("提醒：本工作树自带的 guard.json 与主工作树的不同，本工作树这份优先；想跟主工作树一致，"
                     "由 human 删掉本工作树这份。")
    return lines


def _hook_status(args) -> int:
    """Report the script files, the config and the registration apart, one layer a line.

    A single 已安装 used to stand for all three, and only meant that a script file was there. Whether the
    harness then loads the hook is beyond a command line: the last lines say so and give a probe for a session.
    Where the ledger and the deny entries are is never printed: guard.json holds that, and the hook keeps
    the agent out of that file.
    """
    out = _out()
    project = Path(args.project).resolve()
    found, root, source, main, alone = _guard_site(project)
    code = 0

    present = [harness for harness, (_, relative) in HOOKS.items() if (project / relative).is_file()]
    for harness, (asset, relative) in HOOKS.items():
        script = project / relative
        if harness in present:
            state = migrate_module.hook_copy(script, asset_path(*asset))
            compared = OLDER_IN_A_WORKTREE if state == migrate_module.OLDER and main else HOOK_COPY_NOTES[state]
            print(f"{harness}: 已安装（{script}），{compared}", file=out)
        else:
            print(f"{harness}: 未安装（{script}）", file=out)
    claude_script = project / HOOKS["claude"][1]
    if "claude" in present and shell_expands(claude_script):
        print(f"提醒：{_expands_note(claude_script, shell_expands(claude_script))}", file=out)

    # A config found through the main tree is no use to a script that never looks there. The worktree's own copy
    # of the Claude script is not the one to judge by when its settings have Claude Code run another.
    registered, elsewhere = _claude_registration(project)
    blind = [harness for harness in present if source == ledger_module.MAIN_TREE
             and not (harness == "claude" and elsewhere)
             and _cannot_see(project / HOOKS[harness][1], asset_path(*HOOKS[harness][0]), project, found)]
    readable = True
    # Said in a worktree that has no main working tree to share a config with: `hooks install --ledger` run
    # there writes the ledger path alone, without the ledger_side / deny / project another working tree has.
    carry = (f"{NO_FALLBACK}：由 human 在这个 worktree（{project}）里自带一份 guard.json。别的工作区已有一份的照那份抄，"
             f"{CARRY_OVER}；都没有，就在这里跑 devcircuit hooks install --harness <pi|claude> --ledger <账本>。")
    above = _project_above(project) if found is None else None
    below = f"这里是 {above} 里面的目录，账本配置在那一层：--project 给 {above}，不要在这里跑 hooks install。" if above else ""
    if found is None and present:
        code = 2
        print("配置：找不到 guard.json，而这里有 hook 脚本" + (f"。{carry}" if alone else f"。{below}" if above else (
            f"：账本在哪由 human 在主工作树（{main or project}）配置"
            "（在那里跑 devcircuit hooks install --harness <pi|claude> --ledger <账本>）。")), file=out)
    elif found is None:
        code = 1
        print(f"配置：未找到 {project / CONFIG_DIR / CONFIG_NAME}；" + (
            f"这是 linked worktree，主工作树（{main}）也没有，要用账本边界由 human 在主工作树配置。" if main
            else carry if alone else below or "跑 devcircuit hooks install 生成。"), file=out)
    else:
        config, problem = _load_guard(found)
        origin = "本工作树" if source == ledger_module.HERE else "来自主工作树"
        if config is None:
            code, readable = 2, False
            print(f"配置：{found}（{origin}）无法解析：{problem}。由 human 修好这个文件；修好之前账本边界不可靠"
                  "（当前版本的 hook 拦下全部工具调用，旧脚本全部放行）。", file=out)
        else:
            print(f"配置：{found}（{origin}，可解析）", file=out)
            for line in _config_lines(config, root, main if source == ledger_module.HERE else None):
                print(line, file=out)
    if blind:
        code = 2
        print(f"这里不拦：这个 worktree 的 {'、'.join(blind)} hook 脚本还不会回退到主工作树的配置（它只从会话目录往上找 "
              "guard.json），读不到上面这份。把主干合并进这个 worktree 的分支（主干要已换上新脚本），或在这里跑 devcircuit "
              f"hooks install --harness {blind[0] if len(blind) == 1 else '<' + '|'.join(blind) + '>'} --force 并提交。"
              "Claude Code 在用户级设置里登记、命令指向主工作树新脚本的，不受这一条影响。", file=out)

    if registered:
        print(f"登记 claude：{registered} 里有运行 ledger_guard.py 的 PreToolUse 命令" + (
            "，命令指向的不是本工作树这份脚本（上面 claude 一行比的是本工作树这份）" if elsewhere else ""), file=out)
    else:
        print("登记 claude：本工作树的 settings 里没有登记（用户级设置 CLI 看不到）" + (
            "；在这里跑 devcircuit hooks install --harness claude，把它给的 hooks 段合并进 .claude/settings.local.json"
            if "claude" in present else ""), file=out)
    print("登记 pi：" + ("脚本在 .pi/extensions/ 下，pi 在可信项目的根目录启动时从那里找扩展" if "pi" in present
                       else ".pi/extensions/ 下没有脚本（装在全局目录的那份 CLI 看不到）"), file=out)

    print("宿主是否已加载：CLI 证明不了", file=out)
    probe = (root if found else main or project) / CONFIG_DIR / f"{CONFIG_NAME}.selftest"
    if above:
        caveat = f"；先用 --project {above} 重跑，照那一次给的路径探。"
    elif found is None:
        caveat = "；要先有 guard.json，没有配置时 hook 不拦，探针一律回“文件不存在”。"
    elif not readable:
        caveat = "；先修好配置再探：配置无法解析时旧脚本全部放行，已加载也回“文件不存在”。"
    elif blind:
        caveat = "；换上新脚本再探：这个 worktree 的旧脚本读不到这份配置，已加载也回“文件不存在”。"
    else:
        caveat = "。"
    print(f"会话内探针：让 agent 读 {probe}（一个不存在的文件）：回“账本边界”说明已加载，回“文件不存在”说明没加载{caveat}",
          file=out)
    return code


def _context(args) -> int:
    out = _out()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"项目目录不存在：{root}", file=sys.stderr)
        return 2
    # The commands an answer prints must reach this project too, from wherever this call was made.
    flags = context_module.carried_flags(args.root, args.base)
    try:
        if args.map:
            code, text = 0, context_module.render_map(root)
        elif args.capability:
            code, text = context_module.render_capability(root, args.capability, flags)
        elif args.ids:
            ids = [item for item in ledger_module.ID_SEPARATORS.split(args.ids) if item]
            code, text = context_module.render_ids(root, ids, args.max_chars, flags)
        else:
            feature = args.feature or args.review
            code, text = 0, context_module.render_feature(root, feature, args.base, bool(args.review),
                                                          args.max_chars, flags)
    except context_module.ContextError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(text, file=out)
    return code


def _ledger(args) -> int:
    out = _out()
    command = args.ledger_command or ("init" if args.path else None)
    if command is None:
        print("用法：devcircuit ledger init --path <目录> | ledger add … | ledger check", file=sys.stderr)
        return 2
    if command == "init":
        return _scaffold(lambda: init_ledger(Path(args.path), not args.no_commit))
    project = Path(args.project).resolve()
    try:
        if command == "add":
            record_id, committed = ledger_module.add(
                project, args.feature, args.kind, args.decision, args.rejected, args.reason,
                args.ids, args.removed_ids, args.review, args.commit)
            print(f"已记录：{record_id}", file=out)
            if not committed:
                print("提醒：记录已写入，但账本仓库没有提交成功；请人工检查账本仓库的 git 身份和状态。", file=out)
            return 0
        findings, records, features, notes = ledger_module.check(project, args.base)
    except ledger_module.LedgerError as error:
        print(str(error), file=sys.stderr)
        return 2
    except OSError as error:
        # Only the reason: the message of an OSError names the file it failed on, and that may be the ledger's.
        print(f"账本命令没做成：{ledger_module.why_failed(error)}（不显示出错的文件，免得带出账本路径；"
              "请人工检查账本目录和权限）", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding.text, file=out)
    for note in notes:  # what was not checked: said, but not counted, so the exit code stays what it was
        print(f"说明：{note}", file=out)
    if findings:
        print(f"ledger check：{len(findings)} 处不一致", file=out)
        return 1
    print(f"ledger check：通过（{records} 条记录，{features} 个功能）", file=out)
    return 0


def _close(args) -> int:
    out = _out()
    project = Path(args.project).resolve()
    try:
        return close_module.run(project, args.feature, args.summary, args.review, args.base, out)
    except (close_module.CloseError, ledger_module.LedgerError) as error:
        print(str(error), file=sys.stderr)
        return 2


def _migrate(args) -> int:
    out = _out()
    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"项目目录不存在：{project}", file=sys.stderr)
        return 2
    actions = migrate_module.check(project)
    if not actions:
        print("迁移检查：没有要改的", file=out)
        return 0
    print(f"迁移检查：{len(actions)} 项要处理（只列出，没有改任何文件）", file=out)
    for number, action in enumerate(actions, 1):
        print(f"{number}. {action}", file=out)
    return 1


def main(argv: list[str] | None = None) -> int:
    _out()
    # Errors go here; piped on Chinese Windows it would otherwise be GBK. Keep stderr's usual
    # backslashreplace so a path that cannot be encoded still gives a readable error, not a traceback.
    _out(sys.stderr, errors="backslashreplace")
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="devcircuit",
        description="dev-circuit-ultra guards: document hygiene, requirement IDs, ledger boundary.",
    )
    parser.add_argument("--version", action=_Version, nargs=0, help="显示版本；从 git 地址安装的另带提交号")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doc-guard", add_help=False,
                   help="文档卫生检查（禁止的历史内容、禁止路径、断链）")
    sub.add_parser("spec-check", add_help=False,
                   help="要求编号检查（重复、悬空引用、在研卡冲突）")
    sub.add_parser("check", add_help=False,
                   help="依次跑 doc-guard 和 spec-check（共用的忽略参数自动分发；要看 JSON 用子命令）")
    sub.add_parser("rules", add_help=False, help="列出两个检查器的规则和各自查什么")
    vendor = sub.add_parser("vendor", help="把两个检查器拷进项目的 scripts/，已有则升级")
    vendor.add_argument("--project", default=".", help="项目目录（默认当前目录）")

    context = sub.add_parser("context", help="按需取现行设计：能力清单、要求原文、某个功能的上下文")
    mode = context.add_mutually_exclusive_group(required=True)
    mode.add_argument("--map", action="store_true", help="能力清单、本工作树里的在研功能、框架摘要位置、其他文档、待做数")
    mode.add_argument("--capability", metavar="CODE", help="某个能力的要求清单（每条一行）")
    mode.add_argument("--ids", metavar="ID[,ID...]", help="这些要求的原文和例子")
    mode.add_argument("--feature", metavar="NAME", help="功能的卡、当前分支相对基线改到或引用到的要求、相关测试")
    mode.add_argument("--review", metavar="NAME", help="同 --feature，另加基线和改动统计，交给审核")
    context.add_argument("--base", default=None, help="对比的基线分支（默认取 AGENTS.md 写的主干，没写就用远端默认分支，再没有就 main / master）")
    context.add_argument("--root", default=".", help="项目目录（默认当前目录）")
    context.add_argument("--max-chars", type=int, default=context_module.DEFAULT_MAX_CHARS,
                         help="要求原文部分的字数上限，超出时截断，并给出补读其余编号的命令（命令不计入上限）")

    close = sub.add_parser("close", help="收尾一个功能：检查、账本核对、删卡并提交、写收尾记录、给出交付报告骨架")
    close.add_argument("feature", help="功能名，和 specs/<feature>/ 一致")
    close.add_argument("--summary", required=True, help="一句话说明交付了什么")
    close.add_argument("--review", default=None, help="审核结果，一句话")
    close.add_argument("--base", default=None, help="对比的基线分支（默认取 AGENTS.md 写的主干，没写就用远端默认分支，再没有就 main / master）")
    close.add_argument("--project", default=".", help="项目目录（默认当前目录）")

    migrate = sub.add_parser("migrate", help="升级前检查：列出旧项目要改的地方，不改任何文件")
    migrate.add_argument("--check", action="store_true", required=True, help="只检查并列出（目前唯一的模式）")
    migrate.add_argument("--project", default=".", help="项目目录（默认当前目录）")

    init = sub.add_parser("init", help="新建项目骨架，或给已有仓库补齐文件")
    init.add_argument("--path", required=True, help="目标目录")
    init.add_argument("--name", default=None, help="项目名（默认取目录名）")
    init.add_argument("--adopt", action="store_true", help="接入已有 Git 仓库：只补缺失文件，不提交")

    ledger = sub.add_parser("ledger", help="项目外的私有账本：init 建库，add 只追加，check 核对")
    ledger.add_argument("--path", help=argparse.SUPPRESS)
    ledger.add_argument("--no-commit", action="store_true", help=argparse.SUPPRESS)
    ledger_sub = ledger.add_subparsers(dest="ledger_command")
    ledger_init = ledger_sub.add_parser("init", help="在项目之外创建私有账本仓库")
    ledger_init.add_argument("--path", required=True, help="账本目录（必须在项目之外）")
    ledger_init.add_argument("--no-commit", action="store_true", help="不创建第一次提交")
    ledger_add = ledger_sub.add_parser("add", help="追加一条记录；只回执编号，不显示账本内容")
    ledger_add.add_argument("--project", default=".", help="项目目录（默认当前目录）")
    ledger_add.add_argument("--feature", required=True, help="功能名，和 specs/<feature>/ 一致")
    ledger_add.add_argument("--kind", required=True, choices=ledger_module.KINDS)
    ledger_add.add_argument("--decision", required=True, help="选定的决定，一句话")
    ledger_add.add_argument("--rejected", action="append", default=[], metavar="方案：原因",
                            help="被否的方案和原因（可重复）")
    ledger_add.add_argument("--reason", default=None, help="为什么这样定")
    ledger_add.add_argument("--ids", default=None, help="涉及的要求编号，逗号分隔")
    ledger_add.add_argument("--removed-ids", default=None, help="删掉的要求编号，逗号分隔")
    ledger_add.add_argument("--review", default=None, help="审核结果，一句话")
    ledger_add.add_argument("--commit", default=None, help="对应的提交（默认 HEAD）")
    ledger_check = ledger_sub.add_parser("check", help="核对账本和项目；只报不一致的功能、编号和提交")
    ledger_check.add_argument("--project", default=".", help="项目目录（默认当前目录）")
    ledger_check.add_argument("--base", default=None, help="对比的基线分支（默认取 AGENTS.md 写的主干，没写就用远端默认分支，再没有就 main / master）")

    sync = sub.add_parser("sync", help="把技能同步到 Claude Code / agents / DSH 目录，并移除已退役的技能")
    sync.add_argument("--target", action="append", default=[], metavar="DIR",
                      help="额外或替代的目标目录（可重复；不给就用默认三处）")

    hooks = sub.add_parser("hooks", help="安装或检查账本边界 hook")
    hooks_sub = hooks.add_subparsers(dest="hooks_command", required=True)
    install = hooks_sub.add_parser("install", help="安装 pi / claude 的账本边界 hook")
    install.add_argument("--harness", choices=sorted(HOOKS), required=True)
    install.add_argument("--project", default=".", help="项目目录（默认当前目录）")
    install.add_argument("--ledger", default=None, help="项目之外的账本绝对路径")
    install.add_argument("--force", action="store_true", help="覆盖已存在的 hook 文件（项目里的比本机带的新时不覆盖）")
    status = hooks_sub.add_parser("status", help="分层看 hook 状态：脚本、配置、登记；宿主是否加载要在会话里探")
    status.add_argument("--project", default=".", help="项目目录（默认当前目录）")

    try:
        args, rest = parser.parse_known_args(argv)
    except SystemExit as error:
        return int(error.code or 0)
    if rest and args.command not in ("doc-guard", "spec-check", "check"):
        print(f"不认识的参数：{' '.join(rest)}（用 devcircuit {args.command} --help 查看）", file=sys.stderr)
        return 2

    if args.command == "doc-guard":
        return _passthrough("doc_guard", rest)
    if args.command == "spec-check":
        return _passthrough("spec_check", rest)
    if args.command == "check":
        return _check(rest)
    if args.command == "rules":
        return _rules()
    if args.command == "vendor":
        return _vendor(args)
    if args.command == "context":
        return _context(args)
    if args.command == "close":
        return _close(args)
    if args.command == "migrate":
        return _migrate(args)
    if args.command == "init":
        return _scaffold(lambda: init_project(Path(args.path), args.name, args.adopt))
    if args.command == "ledger":
        return _ledger(args)
    if args.command == "sync":
        targets = [Path(item) for item in args.target] or None
        return _scaffold(lambda: sync_skills(targets))
    if args.command == "hooks":
        return _install_hooks(args) if args.hooks_command == "install" else _hook_status(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
