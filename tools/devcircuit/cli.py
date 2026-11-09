"""devcircuit command line interface."""

import argparse
import json
import os
import shutil
import subprocess
import sys
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
IS_WINDOWS = os.name == "nt"
HOOKS = {
    "pi": (("pi", "ledger-guard.js"), Path(".pi") / "extensions" / "ledger-guard.js"),
    "claude": (("claude", "ledger_guard.py"), Path(CONFIG_DIR) / "hooks" / "ledger_guard.py"),
}
# Claude Code reads exit 2 as "block this call", and that is also how python exits when it cannot
# open a script. Run the hook only if it is there (an older branch may not have it), so a missing
# script lets calls through instead of blocking every one. -I keeps the project's own modules
# (a json.py at the root, say) out of the interpreter's path. No $, backticks or double quotes
# inside, so bash, cmd and PowerShell all pass it through unchanged.
HOOK_LAUNCHER = ("import os,runpy,sys; sys.argv=sys.argv[1:]; "
                 "os.path.isfile(sys.argv[0]) and runpy.run_path(sys.argv[0], run_name='__main__')")


def python_command() -> str:
    """Name the interpreter the way this machine spells it.

    On Windows `python3` is usually the WindowsApps store alias, so `python` comes first there.
    """
    candidates = ("python", "python3") if IS_WINDOWS else ("python3", "python")
    for candidate in candidates:
        if shutil.which(candidate):
            return candidate
    return candidates[0]


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


def _ignore_guard(project: Path) -> bool:
    """Have git ignore guard.json; True when this call added the line.

    The command does it rather than the agent: once the hook is on, any tool call that names
    guard.json, an edit of .gitignore included, is blocked.
    """
    try:
        probe = subprocess.run(["git", "-C", str(project), "check-ignore", "-q", "--no-index", GUARD_IGNORE],
                               capture_output=True)
        if probe.returncode == 0:  # already covered, maybe by a wider rule such as .dev-circuit/*.json
            return False
    except OSError:
        pass
    gitignore = project / ".gitignore"
    data = gitignore.read_bytes() if gitignore.is_file() else b""
    lines = data.decode("utf-8-sig", errors="replace").splitlines()
    if any(line.strip().lstrip("/") == GUARD_IGNORE for line in lines):
        return False
    eol = "\r\n" if b"\r\n" in data else "\n"
    lead = eol if data and not data.endswith(b"\n") else ""
    with gitignore.open("a", encoding="utf-8", newline="") as handle:
        handle.write(f"{lead}# 本机路径，不要提交：账本位置只对这台机器有意义{eol}{GUARD_IGNORE}{eol}")
    return True


def _out(stream=None):
    stream = stream or sys.stdout
    try:
        stream.reconfigure(encoding="utf-8")
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
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        print(f"警告：{path} 无法解析（{error}），将被覆盖。", file=sys.stderr)
        return {}
    return raw if isinstance(raw, dict) else {}


def _install_hooks(args) -> int:
    out = _out()
    project = Path(args.project).resolve()
    if not project.is_dir():
        print(f"项目目录不存在：{project}", file=sys.stderr)
        return 2

    config_path = project / CONFIG_DIR / CONFIG_NAME
    config = _read_guard(config_path)
    if args.ledger:
        ledger = Path(args.ledger).resolve()
        if ledger == project or project in ledger.parents:
            print(f"账本不能放在项目里：{ledger}", file=sys.stderr)
            print("账本是项目之外的私有仓库；开发 agent 只读写项目。", file=sys.stderr)
            return 2
        config["ledger"] = str(ledger)
    if not config.get("ledger"):
        print("缺少 --ledger：账本在项目之外，需要给它一个绝对路径。", file=sys.stderr)
        return 2

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    ignored_now = _ignore_guard(project)

    source, relative = HOOKS[args.harness]
    destination = project / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not args.force:
        print(f"已存在，未覆盖：{destination}（用 --force 覆盖）", file=out)
    else:
        shutil.copyfile(asset_path(*source), destination)
        if destination.suffix == ".py":
            destination.chmod(destination.stat().st_mode | 0o111)
        print(f"已安装 hook：{destination}", file=out)

    print(f"已写入配置：{config_path}", file=out)
    if ignored_now:
        print(f"已把 {GUARD_IGNORE} 加进 .gitignore：它记录的是本机账本路径。", file=out)
    print(f"账本：{config['ledger']}", file=out)
    print("", file=out)
    if args.harness == "pi":
        print("pi 会在可信项目里自动加载 .pi/extensions/*.js；/reload 生效。", file=out)
        print("如果已把 hook 装到 ~/.pi/agent/extensions/，删掉项目这份即可。", file=out)
    else:
        snippet = claude_snippet(destination)
        snippet_path = project / CONFIG_DIR / "claude-settings.hook.json"
        snippet_path.write_text(snippet + "\n", encoding="utf-8")
        print("把下面的 hooks 段合并进 .claude/settings.json：", file=out)
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
        elif destination.read_text(encoding="utf-8-sig").replace("\r\n", "\n") == text:
            print(f"未变：{destination}", file=out)
        else:
            destination.write_text(text, encoding="utf-8", newline="\n")
            print(f"更新：{destination}", file=out)
    print("", file=out)
    print("提交前检查仍然跑 python scripts/doc_guard.py 和 python scripts/spec_check.py；"
          "下次升级再跑一次 devcircuit vendor。", file=out)
    return 0


def _hook_status(args) -> int:
    out = _out()
    project = Path(args.project).resolve()
    config_path = project / CONFIG_DIR / CONFIG_NAME
    if not config_path.is_file():
        print(f"未找到 {config_path}；跑 devcircuit hooks install 生成。", file=out)
        return 1
    config = _read_guard(config_path)
    ledger = config.get("ledger")
    print(f"配置：{config_path}", file=out)
    print(f"账本：{ledger or '（未配置）'}", file=out)
    for extra in config.get("deny") or []:
        print(f"额外拒绝：{extra}", file=out)
    for harness, (_, relative) in HOOKS.items():
        installed = "已安装" if (project / relative).is_file() else "未安装"
        print(f"{harness}: {installed}（{project / relative}）", file=out)
    if ledger and not Path(ledger).exists():
        print("提醒：账本路径当前不存在，hook 仍会拦截对这个路径的访问。", file=out)
    return 0


def _context(args) -> int:
    out = _out()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"项目目录不存在：{root}", file=sys.stderr)
        return 2
    try:
        if args.map:
            code, text = 0, context_module.render_map(root)
        elif args.capability:
            code, text = context_module.render_capability(root, args.capability)
        elif args.ids:
            ids = [item for item in ledger_module.ID_SEPARATORS.split(args.ids) if item]
            code, text = context_module.render_ids(root, ids, args.max_chars)
        else:
            feature = args.feature or args.review
            code, text = 0, context_module.render_feature(root, feature, args.base, bool(args.review),
                                                          args.max_chars)
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
        findings, records, features = ledger_module.check(project, args.base)
    except ledger_module.LedgerError as error:
        print(str(error), file=sys.stderr)
        return 2
    for finding in findings:
        print(finding.text, file=out)
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
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="devcircuit",
        description="dev-circuit-ultra guards: document hygiene, requirement IDs, ledger boundary.",
    )
    parser.add_argument("--version", action="version", version=f"devcircuit {__version__}")
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
    mode.add_argument("--map", action="store_true", help="能力清单、在研功能、框架摘要位置、其他文档、待做数")
    mode.add_argument("--capability", metavar="CODE", help="某个能力的要求清单（每条一行）")
    mode.add_argument("--ids", metavar="ID[,ID...]", help="这些要求的原文和例子")
    mode.add_argument("--feature", metavar="NAME", help="功能的卡、分支改到或引用到的要求、相关测试")
    mode.add_argument("--review", metavar="NAME", help="同 --feature，另加基线和改动统计，交给审核")
    context.add_argument("--base", default=None, help="对比的基线分支（默认 main，没有就 master）")
    context.add_argument("--root", default=".", help="项目目录（默认当前目录）")
    context.add_argument("--max-chars", type=int, default=context_module.DEFAULT_MAX_CHARS,
                         help="要求原文部分的字数上限，超出时截断并列出没给的编号")

    close = sub.add_parser("close", help="收尾一个功能：检查、账本核对、删卡并提交、写收尾记录、给出交付报告骨架")
    close.add_argument("feature", help="功能名，和 specs/<feature>/ 一致")
    close.add_argument("--summary", required=True, help="一句话说明交付了什么")
    close.add_argument("--review", default=None, help="审核结果，一句话")
    close.add_argument("--base", default=None, help="对比的基线分支（默认 main，没有就 master）")
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
    ledger_check.add_argument("--base", default=None, help="对比的基线分支（默认 main，没有就 master）")

    sync = sub.add_parser("sync", help="把技能同步到 Claude Code / agents / DSH 目录，并移除已退役的技能")
    sync.add_argument("--target", action="append", default=[], metavar="DIR",
                      help="额外或替代的目标目录（可重复；不给就用默认三处）")

    hooks = sub.add_parser("hooks", help="安装或检查账本边界 hook")
    hooks_sub = hooks.add_subparsers(dest="hooks_command", required=True)
    install = hooks_sub.add_parser("install", help="安装 pi / claude 的账本边界 hook")
    install.add_argument("--harness", choices=sorted(HOOKS), required=True)
    install.add_argument("--project", default=".", help="项目目录（默认当前目录）")
    install.add_argument("--ledger", default=None, help="项目之外的账本绝对路径")
    install.add_argument("--force", action="store_true", help="覆盖已存在的 hook 文件")
    status = hooks_sub.add_parser("status", help="查看当前项目的 hook 状态")
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
