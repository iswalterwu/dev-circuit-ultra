"""`devcircuit migrate --check`: list what an older project must change before it runs the current flow.

Read-only: it names files and steps and changes nothing. Work in progress is the user's call,
so uncommitted changes under specs/ are reported, never touched.
"""

import json
import re
import subprocess
from pathlib import Path

from . import context, ledger
from ._loader import asset_path, load_script, script_path

OLD_CARD_SECTIONS = ("规格变化", "设计", "验收例子", "结构影响", "风险", "待定", "失败行为")
HOOK_FILES = {
    Path(".pi") / "extensions" / "ledger-guard.js": ("pi", "ledger-guard.js"),
    Path(".dev-circuit") / "hooks" / "ledger_guard.py": ("claude", "ledger_guard.py"),
}
# The retired per-feature file: a bare `design.md` (old templates said 同目录的 `design.md`) or one
# under specs/. A design.md in any other directory, docs/design.md say, is the project's own document.
OLD_DESIGN_ROUTE = re.compile(r"(?<![\w./\\-])design\.md|\bspecs[/\\][^\s`'\"|)]*design\.md")
TABLE_RULE = re.compile(r"^\|\s*:?-{3,}", re.MULTILINE)
SECTION = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")


def _cards(project: Path) -> list[str]:
    actions = []
    specs = project / "specs"
    if not specs.is_dir():
        return actions
    for design in sorted(specs.glob("*/design.md")):
        actions.append(f"{design.relative_to(project).as_posix()}：把仍然有效的结构和关键决定并入 "
                       "docs/architecture.md（开头写框架摘要），然后删掉它")
    for card in sorted(specs.glob("*/spec.md")):
        relative = card.relative_to(project).as_posix()
        text = _text(card)
        headings = {match.group(1) for match in SECTION.finditer(text)}
        for section in OLD_CARD_SECTIONS:
            if section in headings:
                actions.append(f"{relative}：卡里还有旧的“{section}”一节：要求写进能力规格，结构写进 "
                               "docs/architecture.md，卡只留目标、范围、切片")
        if not re.search(r"^能力[：:]", text, re.MULTILINE):
            actions.append(f"{relative}：卡缺“能力：<代号>（已有 / 新建）· 框架：不变 / 已改”一行")
    return actions


def _sizes(project: Path) -> list[str]:
    """Files that doc_guard will reject after the upgrade, using its own limits."""
    guard = load_script("doc_guard")
    actions = []
    specs = project / "specs"
    for card in sorted(specs.glob("*/spec.md")) if specs.is_dir() else []:
        count = len(_text(card).splitlines())
        if count > guard.CARD_MAX_LINES:
            actions.append(f"{card.relative_to(project).as_posix()}：卡 {count} 行，"
                           f"超过 {guard.CARD_MAX_LINES} 行：把做完的切片收成一行")
    requirements = project / "docs" / "requirements"
    for spec in sorted(requirements.glob("*.md")) if requirements.is_dir() else []:
        count = len(_text(spec).splitlines())
        if spec.name != "README.md" and count > guard.SPEC_MAX_LINES:
            actions.append(f"{spec.relative_to(project).as_posix()}：能力规格 {count} 行，"
                           f"超过 {guard.SPEC_MAX_LINES} 行：按子能力拆成几份")
    return actions


def _agents(project: Path) -> list[str]:
    agents = project / "AGENTS.md"
    if not agents.is_file():
        return ["没有 AGENTS.md：devcircuit init --adopt --path <项目> 补齐，再填项目事实"]
    text = _text(agents)
    actions = []
    if OLD_DESIGN_ROUTE.search(text):
        actions.append("AGENTS.md 的路由还提到 design.md：改成 devcircuit context --feature <feature>")
    if "devcircuit context" not in text:
        actions.append("AGENTS.md 没有用 devcircuit context 取上下文：照新模板更新第 2、3、7 节")
    if "审核模型" not in text:
        actions.append("AGENTS.md 缺“审核模型”一行：写同模型，或指定审核用的 agent / 模型")
    return actions


def _trunk(project: Path) -> list[str]:
    """Without a 主干 line the base is main / master first; a different remote default needs a decision."""
    try:
        if context.named_trunk(project):
            return []
    except context.ContextError as error:
        return [str(error)]
    remote = context.remote_trunk(project)
    chosen = context.merge_base(project, None) if remote else None
    if chosen and chosen[0] not in (remote, f"origin/{remote}"):
        return [f"AGENTS.md 没写主干：默认基线取 {chosen[0]}，远端默认分支却是 {remote}。确认哪个是主干，"
                "在 AGENTS.md 第 5 节加一行 `- 主干：`<分支>``"]
    return []


def _hook_commands(settings) -> list[str]:
    """PreToolUse command strings, skipping anything not shaped like Claude Code settings."""
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    groups = hooks.get("PreToolUse") if isinstance(hooks, dict) else None
    commands = []
    for group in groups if isinstance(groups, list) else []:
        entries = group.get("hooks") if isinstance(group, dict) else None
        for hook in entries if isinstance(entries, list) else []:
            command = hook.get("command") if isinstance(hook, dict) else None
            if isinstance(command, str):
                commands.append(command)
    return commands


def _claude_settings(project: Path) -> list[str]:
    """Hook commands from older installs block every tool call once the script is missing."""
    from .cli import HOOK_LAUNCHER  # cli imports this module; import late to avoid the cycle

    actions = []
    for name in ("settings.json", "settings.local.json"):
        path = project / ".claude" / name
        if not path.is_file():
            continue
        try:
            settings = json.loads(_text(path))
        except ValueError:
            continue
        if any("ledger_guard.py" in command and HOOK_LAUNCHER not in command
               for command in _hook_commands(settings)):
            actions.append(f".claude/{name} 里的 ledger_guard 命令在脚本不在时会拦下所有工具调用："
                           "devcircuit hooks install --harness claude --project <项目>，再用新生成的片段替换这一段")
    return actions


def _tooling(project: Path) -> list[str]:
    actions = []
    for name in ("doc_guard", "spec_check"):
        vendored = project / "scripts" / f"{name}.py"
        if vendored.is_file() and _text(vendored) != _text(script_path(name)):
            actions.append(f"scripts/{name}.py 不是当前版本：devcircuit vendor --project <项目>")
    for relative, source in HOOK_FILES.items():
        installed = project / relative
        if installed.is_file() and _text(installed) != _text(asset_path(*source)):
            actions.append(f"{relative.as_posix()} 不是当前版本："
                           f"devcircuit hooks install --harness {source[0]} --project <项目> --force")
    actions += _claude_settings(project)
    try:
        if not ledger.human_side(project):  # a human-side ledger is a setup, not a to-do
            ledger.resolve(project)
    except ledger.LedgerError as error:
        actions.append(str(error))
    return actions


def check(project: Path) -> list[str]:
    actions = [*_cards(project), *_sizes(project), *_agents(project), *_trunk(project)]
    if (project / ".dev-circuit" / "reviewer.json").is_file():
        actions.append(".dev-circuit/reviewer.json：可以删掉；审核改为每个功能一次，模型写在 AGENTS.md 的“审核模型”")
    architecture = project / "docs" / "architecture.md"
    if architecture.is_file() and not context.SUMMARY_ANCHOR.search(_text(architecture)):
        actions.append('docs/architecture.md 缺框架摘要：开头加 <a id="summary"></a> 和不超过 60 行的摘要')
    for relative in ("docs/README.md", "docs/requirements/README.md"):
        path = project / relative
        if path.is_file() and TABLE_RULE.search(_text(path)):
            actions.append(f"{relative} 还有手写的登记表：可以删掉，devcircuit context --map 现场生成")
    actions += _tooling(project)
    status = subprocess.run(["git", "-C", str(project), "status", "--porcelain", "--untracked-files=all",
                             "--", "specs"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    dirty = [line[3:] for line in status.stdout.splitlines() if line.strip()] if status.returncode == 0 else []
    if dirty:
        listed = "、".join(dirty[:3]) + ("…" if len(dirty) > 3 else "")
        actions.append(f"specs/ 下有未提交的改动（{listed}）：迁移前先和用户确认")
    return actions
