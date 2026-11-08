"""devcircuit command line interface."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from ._loader import asset_path, load_script, script_path
from .scaffold import ScaffoldError, init_ledger, init_project
from .sync import sync as sync_skills

CONFIG_DIR = ".dev-circuit"
CONFIG_NAME = "guard.json"
HOOKS = {
    "pi": (("pi", "ledger-guard.js"), Path(".pi") / "extensions" / "ledger-guard.js"),
    "claude": (("claude", "ledger_guard.py"), Path(CONFIG_DIR) / "hooks" / "ledger_guard.py"),
}
def python_command() -> str:
    """Name the interpreter the way this machine spells it."""
    for candidate in ("python3", "python"):
        if shutil.which(candidate):
            return candidate
    return "python3"


def claude_snippet(hook: Path) -> str:
    """Build the .claude/settings.json fragment with proper JSON escaping."""
    payload = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command",
                         "command": f'{python_command()} "{hook}"'},
                    ],
                },
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


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
    print("", file=out)
    print("把 .dev-circuit/guard.json 加进 .gitignore：它记录的是本机账本路径。", file=out)
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

    init = sub.add_parser("init", help="新建项目骨架，或给已有仓库补齐文件")
    init.add_argument("--path", required=True, help="目标目录")
    init.add_argument("--name", default=None, help="项目名（默认取目录名）")
    init.add_argument("--adopt", action="store_true", help="接入已有 Git 仓库：只补缺失文件，不提交")

    ledger = sub.add_parser("ledger", help="在项目之外创建私有账本仓库")
    ledger.add_argument("--path", required=True, help="账本目录（必须在项目之外）")
    ledger.add_argument("--no-commit", action="store_true", help="不创建第一次提交")

    sync = sub.add_parser("sync", help="把三个技能同步到 Claude Code / agents / DSH 目录")
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
    if args.command == "init":
        return _scaffold(lambda: init_project(Path(args.path), args.name, args.adopt))
    if args.command == "ledger":
        return _scaffold(lambda: init_ledger(Path(args.path), not args.no_commit))
    if args.command == "sync":
        targets = [Path(item) for item in args.target] or None
        return _scaffold(lambda: sync_skills(targets))
    if args.command == "hooks":
        return _install_hooks(args) if args.hooks_command == "install" else _hook_status(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
