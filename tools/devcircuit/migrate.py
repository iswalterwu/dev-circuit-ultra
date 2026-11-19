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
CHECKER_VERSION = re.compile(r"""^VERSION\s*=\s*["'](\d+(?:\.\d+)*)""", re.MULTILINE)
# What the workflow scan reads of YAML: block keys, `- item` lines, one-line lists, trailing comments.
CI_EVENTS = ("push", "pull_request")
ON_KEY = re.compile(r"""^(?:on|"on"|'on')\s*:(?:\s|$)""")
YAML_KEY = re.compile(r"""^(?P<indent> *)(?P<key>[A-Za-z_"'][\w"'-]*)\s*:(?:\s+(?P<rest>.*))?$""")
YAML_ITEM = re.compile(r"^(?P<indent> *)-\s+(?P<value>.+)$")
YAML_COMMENT = re.compile(r"(?:^|\s)#.*$")
# A name, with * and ** at most: all the scan compares. One character class and no nesting, so a
# pattern that does not fit is turned down in one pass however long it is.
BRANCH_GLOB = re.compile(r"[\w./*-]+")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")


def checker_version(text: str) -> tuple[int, ...]:
    """The VERSION a checker script declares, as numbers to compare; () when it declares none.

    () sorts below every version: a copy whose version cannot be read counts as older, so it is
    refreshed the way it always was. Only a copy that says it is newer is left alone.
    """
    match = CHECKER_VERSION.search(text)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


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


class _Unread(Exception):
    """The workflow's `on:` block uses YAML the scan does not read; it lists nothing rather than guess."""


def _yaml_line(raw: str) -> str:
    """A workflow line without its comment: from a `#` that starts the line or follows a space.

    Quotes are not looked at: an apostrophe in a comment is far more common than a ` #` inside a quoted
    string. Where there is one, the string is cut short; no branch name has a space in it, and an entry
    left with half its quotes is no pattern, so that file ends up unread.
    """
    return YAML_COMMENT.sub("", raw).rstrip()


def _pattern(value: str) -> str:
    """One entry of a `branches:` filter without its quotes: a branch name, or a glob of * and **."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    elif value.startswith("*"):  # unquoted, that is a YAML alias and not a glob
        raise _Unread
    if not BRANCH_GLOB.fullmatch(value):  # nothing at all, `!` negation, ?, +, [] and the rest of YAML
        raise _Unread
    return value


def _branch_filters(text: str) -> list[tuple[str, int, list[str]]]:
    """(event, line of its `branches:`, patterns) for the push and pull_request filters of a workflow.

    A text scan of the top-level `on:` block, not a YAML parser: the CLI has no dependencies. Only
    `branches:` is read. An event without it runs on every branch and is left out, and so is whatever
    is written on one line (`on: push`, `push: {…}`) or filtered with branches-ignore. Raises _Unread
    where the block cannot be followed: a line that is neither a key nor a list item, a list that runs
    over several lines, an alias, a pattern with more in it than * and **.
    """
    lines = [_yaml_line(raw) for raw in text.split("\n")]
    start = next((index for index, line in enumerate(lines) if ON_KEY.match(line)), None)
    if start is None:
        return []
    block = []
    for number, line in enumerate(lines[start + 1:], start + 2):
        if not line.strip():
            continue
        if not line.startswith(" "):
            break  # the next top-level key
        block.append((number, line))
    found: list[tuple[str, int, list[str]]] = []
    event, event_indent, position = None, None, 0
    while position < len(block):
        number, line = block[position]
        position += 1
        key = YAML_KEY.match(line)
        if not key:
            if YAML_ITEM.match(line):
                continue  # `- push` under on:, or the items of a key that is not read
            raise _Unread
        indent, name, rest = len(key["indent"]), key["key"].strip("\"'"), (key["rest"] or "").strip()
        if event_indent is None or indent <= event_indent:
            event, event_indent = name, indent
        elif event in CI_EVENTS and name == "branches":
            if one_line_list := re.fullmatch(r"\[(.*)\]", rest):
                values = [part for part in one_line_list[1].split(",") if part.strip()]
            elif rest:  # a single name; a list left open for the next lines is no pattern and ends up unread
                values = [rest]
            else:
                values = []
                while (position < len(block) and (item := YAML_ITEM.match(block[position][1]))
                       and len(item["indent"]) >= indent):
                    values.append(item["value"])
                    position += 1
            if not values:
                raise _Unread
            found.append((event, number, [_pattern(value) for value in values]))
    return found


def _matches(pattern: str, name: str) -> bool:
    """Whether a `branches:` pattern takes a branch name: * stops at a slash, ** does not.

    Not a regex made from the pattern: that backtracks, and a few dozen stars in front of a letter
    stalled the command. This follows how far into the name the pattern can have got, so the work is
    bounded by the two lengths whatever the filter says.
    """
    reached = {0}
    for part in re.findall(r"\*+|[^*]+", pattern):
        if part.startswith("*"):  # one star stays inside a segment; two take anything, and more say no more than two
            reached = {end for start in reached for end in range(start, len(name) + 1)
                       if len(part) > 1 or "/" not in name[start:end]}
        else:
            reached = {start + len(part) for start in reached if name.startswith(part, start)}
    return len(name) in reached


def _runs_on(patterns: list[str], trunk: str) -> bool:
    """A `branches:` filter lets the trunk through when one of its patterns matches it, by name or by glob."""
    return any(_matches(pattern, trunk) for pattern in patterns)


def _workflows(project: Path) -> list[str]:
    """CI workflows whose push or pull_request filter leaves the trunk out: the checks never run on it.

    The trunk is the one AGENTS.md names, else the remote's default branch. With neither there is nothing
    reliable to hold a workflow against, and a local branch name is not taken for one. A workflow that
    is meant for another branch goes into .dcuignore.
    """
    folder = project / ".github" / "workflows"
    if not folder.is_dir():
        return []
    named = context.named_trunk(project)
    trunk = named or context.remote_trunk(project)
    if not trunk:
        return []
    stated = "AGENTS.md 的主干" if named else "远端默认分支"
    guard = load_script("spec_check")
    ignore_file = project / guard.IGNORE_FILE
    ignored = guard.load_ignore_file(ignore_file) if ignore_file.is_file() else []
    actions = []
    for path in sorted(folder.iterdir()):
        relative = path.relative_to(project).as_posix()
        if path.suffix not in (".yml", ".yaml") or not path.is_file() or guard.path_is_ignored(relative, ignored):
            continue
        try:
            filters = _branch_filters(_text(path))
        except _Unread:
            continue
        actions += [f"{relative}:{line}：{event} 只在 {'、'.join(patterns)} 上触发，{stated}是 {trunk}："
                    f"把 {trunk} 写进这里的 branches；有意不在主干上跑的工作流，把这个文件写进 .dcuignore"
                    for event, line, patterns in filters if not _runs_on(patterns, trunk)]
    return actions


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
        if not vendored.is_file():
            continue
        copy, packaged = _text(vendored), _text(script_path(name))
        if checker_version(copy) > checker_version(packaged):  # vendor would refuse; it is the tool that is behind
            actions.append(f"scripts/{name}.py 比本机 devcircuit 带的新：先升级本机 devcircuit，不要跑 vendor")
        elif copy != packaged:
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
    trunk_first = _trunk(project)
    actions = [*_cards(project), *_sizes(project), *_agents(project), *trunk_first]
    if not trunk_first:  # a broken trunk line or an undecided base is settled first; the workflows wait for it
        actions += _workflows(project)
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
    # core.quotepath=false: by default git prints a non-ASCII path quoted and octal-escaped.
    status = subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(project), "status", "--porcelain",
                             "--untracked-files=all", "--", "specs"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    dirty = [line[3:] for line in status.stdout.splitlines() if line.strip()] if status.returncode == 0 else []
    if dirty:
        listed = "、".join(dirty[:3]) + ("…" if len(dirty) > 3 else "")
        actions.append(f"specs/ 下有未提交的改动（{listed}）：迁移前先和用户确认")
    return actions
