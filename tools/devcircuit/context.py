"""`devcircuit context`: read the parts of the current design a task needs, and say what was left out.

Modes:
  --map            capabilities, features in progress, where the framework summary is, other docs, backlog size
  --capability C   one line per requirement of capability C
  --ids A,B        the full text of these requirements
  --feature F      card, requirements the branch added or rewrote, requirements its code cites, related tests
  --review F       --feature plus the merge base and a diff summary, for the reviewer
"""

import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ._loader import load_script

DEFAULT_MAX_CHARS = 12000
ARCHITECTURE = "docs/architecture.md"
SUMMARY_ANCHOR = re.compile(r"<a\s+id=[\"']summary[\"']")
HEADING = re.compile(r"^(#{1,6})\s")
READ_ME = re.compile(r"^>\s*\*\*读我\*\*\s*[：:]\s*(.*)$")
CURRENT_SLICE = re.compile(r"^-\s+(S\d+[：:].*?)\s*[（(]当前[）)]")
SLICE = re.compile(r"^-\s+(S\d+[：:].*)$")
CAPABILITY_LINE = re.compile(r"^能力[：:]\s*(.*)$")
CODE_WORD = re.compile(r"(?<![A-Za-z])[A-Z]{2,8}(?![A-Za-z])")
MAX_TITLE = 160
MAX_LISTED_IDS = 10
MAX_DOCS = 30
MAX_STAT_LINES = 40


class ContextError(RuntimeError):
    """A usage problem; the message is meant for the user."""


@dataclass(frozen=True)
class Entry:
    id: str
    path: str
    line: int
    text: str

    @property
    def title(self) -> str:
        first = self.text.splitlines()[0]
        return first if len(first) <= MAX_TITLE else first[:MAX_TITLE] + "…"


@dataclass(frozen=True)
class Capability:
    code: str
    path: str
    title: str
    entries: tuple[Entry, ...]


@lru_cache(maxsize=1)
def _spec():
    return load_script("spec_check")


def _natural(identifier: str):
    head, _, tail = identifier.rpartition("-")
    return (head, int(tail)) if tail.isdigit() else (identifier, 0)


def parse_capability(relative: str, text: str) -> Capability:
    """Split a capability spec into entries: a definition line plus the indented lines under it."""
    spec = _spec()
    lines = text.splitlines()
    code = next((match.group(1) for line in lines if (match := spec.HEADER.fullmatch(line))), "")
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), Path(relative).stem)
    entries: list[Entry] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = spec.DEFINITION.match(line) or spec.TABLE_DEFINITION.match(line)
        if not match:
            index += 1
            continue
        end = index + 1
        if spec.DEFINITION.match(line):
            while end < len(lines):
                if lines[end][:1].isspace() and lines[end].strip():
                    end += 1
                    continue
                if not lines[end].strip():
                    following = end
                    while following < len(lines) and not lines[following].strip():
                        following += 1
                    if following < len(lines) and lines[following][:1].isspace():
                        end = following
                        continue
                break
        identifier = match.group(1)
        if identifier.startswith("AC-") and code:
            identifier = f"{code}:{identifier}"
        entries.append(Entry(identifier, relative, index + 1, "\n".join(lines[index:end]).rstrip()))
        index = end
    return Capability(code or "?", relative, title, tuple(entries))


def _patterns(root: Path) -> list[str]:
    return _spec()._ignores(root, [], None, True)


def load_capabilities(root: Path) -> list[Capability]:
    capabilities = []
    for path in _spec()._capability_files(root, _patterns(root)):
        relative = path.relative_to(root).as_posix()
        capabilities.append(parse_capability(relative, path.read_text(encoding="utf-8-sig")))
    return capabilities


# ---------------------------------------------------------------- git helpers

def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def _git_lines(root: Path, *args: str) -> list[str]:
    output = _git(root, *args)
    return [line for line in (output or "").splitlines() if line.strip()]


def merge_base(root: Path, base: str | None) -> tuple[str, str] | None:
    """Return (base name, merge-base sha), or None when there is nothing to compare against.

    Without --base, main and then master are tried. An explicit base that cannot be compared is an
    error: falling back silently would hand the reviewer an empty change set.
    """
    if _git(root, "rev-parse", "--is-inside-work-tree") is None:
        if base:
            raise ContextError(f"不是 git 仓库，没法和基线 {base} 比较")
        return None
    for candidate in ([base] if base else ["main", "master"]):
        sha = (_git(root, "merge-base", candidate, "HEAD") or "").strip()
        if sha:
            return candidate, sha
    if base:
        raise ContextError(f"找不到基线分支：{base}（或它和 HEAD 没有共同祖先）")
    return None


def changed_files(root: Path, base_sha: str, *paths: str) -> set[str]:
    """Files that differ from the merge base: committed on the branch, uncommitted, or untracked.

    Renames count as a deletion plus an addition, so requirements in a renamed spec are compared
    under both paths instead of looking brand new.
    """
    scope = ["--", *paths] if paths else []
    files = set(_git_lines(root, "diff", "--name-only", "--no-renames", "--relative", base_sha, *scope))
    files |= set(_git_lines(root, "ls-files", "--others", "--exclude-standard", *scope))
    return files


def requirement_changes(root: Path, base_sha: str):
    """Compare requirement entries at the merge base with the working tree."""
    old: dict[str, Entry] = {}
    new: dict[str, Entry] = {}
    for relative in changed_files(root, base_sha, "docs/requirements"):
        if not relative.endswith(".md") or Path(relative).name == "README.md":
            continue
        before = _git(root, "show", f"{base_sha}:./{relative}") or ""
        path = root / relative
        after = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
        for text, bucket in ((before, old), (after, new)):
            if text:
                for entry in parse_capability(relative, text).entries:
                    bucket[entry.id] = entry
    added = sorted(set(new) - set(old), key=_natural)
    removed = sorted(set(old) - set(new), key=_natural)
    rewritten = sorted((key for key in set(new) & set(old) if new[key].text != old[key].text), key=_natural)
    return added, rewritten, removed


# ---------------------------------------------------------------- rendering helpers

def _summary_bounds(lines: list[str]) -> tuple[int, int, int] | None:
    """(anchor index, first body line, end) of the framework summary, or None without an anchor."""
    anchor = next((index for index, line in enumerate(lines) if SUMMARY_ANCHOR.search(line)), None)
    if anchor is None:
        return None
    level, start = 2, anchor + 1
    heading = HEADING.match(lines[anchor])
    if not heading:
        following = next((index for index in range(anchor + 1, len(lines)) if lines[index].strip()), None)
        if following is not None and (heading := HEADING.match(lines[following])):
            start = following + 1
    if heading:
        level = len(heading.group(1))
    end = next((index for index in range(start, len(lines))
                if (match := HEADING.match(lines[index])) and len(match.group(1)) <= level), len(lines))
    return anchor, start, end


def _summary_line(root: Path) -> str:
    path = root / ARCHITECTURE
    if not path.is_file():
        return f"框架：还没有 {ARCHITECTURE}（新项目的第一个功能先做框架设计）"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    bounds = _summary_bounds(lines)
    if bounds is None:
        return f"框架：{ARCHITECTURE} 没有用 <a id=\"summary\"></a> 标出的框架摘要（doc_guard 会报）"
    _, start, end = bounds
    count = sum(1 for line in lines[start:end] if line.strip())
    return f"框架摘要：{ARCHITECTURE}#summary（{count} 行）"


def _summary_text(root: Path) -> str:
    path = root / ARCHITECTURE
    if not path.is_file():
        return f"还没有 {ARCHITECTURE}"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    bounds = _summary_bounds(lines)
    if bounds is None:
        return f"{ARCHITECTURE} 没有框架摘要"
    _, start, end = bounds
    return "\n".join(line for line in lines[start:end]).strip()


def _slice_status(card: Path) -> str:
    lines = card.read_text(encoding="utf-8-sig").splitlines()
    for line in lines:
        if match := CURRENT_SLICE.match(line):
            return f"当前：{match.group(1)}"
    slices = [match.group(1) for line in lines if (match := SLICE.match(line))]
    pending = [title for title in slices if "✓" not in title]
    if pending:
        return f"下一个：{pending[0]}"
    return "切片都已完成" if slices else "还没有切片"


def _read_me(path: Path) -> str:
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[:30]:
        if match := READ_ME.match(line.strip()):
            return re.split(r"[；;。]", match.group(1), maxsplit=1)[0].strip()
    heading = next((line[2:].strip() for line in path.read_text(encoding="utf-8-sig", errors="replace")
                    .splitlines() if line.startswith("# ")), "")
    return heading or "（没有读我块）"


def _other_docs(root: Path) -> list[str]:
    docs = root / "docs"
    if not docs.is_dir():
        return []
    skipped = {"docs/README.md", ARCHITECTURE}
    found = [path for path in sorted(docs.rglob("*.md"))
             if path.relative_to(root).as_posix() not in skipped
             and path.relative_to(root).parts[:2] != ("docs", "requirements")]
    lines = [f"- {path.relative_to(root).as_posix()}：{_read_me(path)}" for path in found[:MAX_DOCS]]
    if len(found) > MAX_DOCS:
        lines.append(f"- 另有 {len(found) - MAX_DOCS} 份没列出")
    return lines


def _fit(blocks: list[tuple[str, str]], budget: int) -> tuple[list[str], list[str]]:
    """Keep whole blocks while they fit the budget; return kept texts and the IDs left out."""
    kept: list[str] = []
    used = 0
    for position, (identifier, text) in enumerate(blocks):
        if kept and used + len(text) + 2 > budget:
            return kept, [item for item, _ in blocks[position:]]
        kept.append(text)
        used += len(text) + 2
    return kept, []


def _truncation_note(dropped: list[str]) -> str:
    listed = ",".join(dropped[:MAX_LISTED_IDS]) + ("…" if len(dropped) > MAX_LISTED_IDS else "")
    return f"（截断：还有 {len(dropped)} 条没列出，用 devcircuit context --ids {listed} 补读）"


def _card_codes(card_text: str) -> list[str]:
    for line in card_text.splitlines():
        if match := CAPABILITY_LINE.match(line.strip()):
            return CODE_WORD.findall(match.group(1).split("·", 1)[0])
    return []


# ---------------------------------------------------------------- modes

def render_map(root: Path) -> str:
    capabilities = load_capabilities(root)
    out = ["能力（docs/requirements/；要求清单：devcircuit context --capability <代号>）"]
    out += [f"- {item.code}  {Path(item.path).name}  {item.title}  {len(item.entries)} 条" for item in capabilities]
    if not capabilities:
        out.append("- （还没有能力规格）")
    out.append("在研功能（specs/；上下文：devcircuit context --feature <名>）")
    cards = sorted((root / "specs").glob("*/spec.md")) if (root / "specs").is_dir() else []
    out += [f"- {card.parent.name}  specs/{card.parent.name}/spec.md  {_slice_status(card)}" for card in cards]
    if not cards:
        out.append("- （没有）")
    out.append(_summary_line(root))
    docs = _other_docs(root)
    if docs:
        out.append("其他文档")
        out += docs
    backlog = root / "specs" / "backlog.md"
    if backlog.is_file():
        count = sum(1 for line in backlog.read_text(encoding="utf-8-sig").splitlines() if line.startswith("- "))
        out.append(f"待做：specs/backlog.md {count} 条")
    return "\n".join(out)


def _capability_lines(capability: Capability) -> list[str]:
    out = [f"{capability.code}  {capability.title}（{capability.path}，{len(capability.entries)} 条）"]
    out += [entry.title for entry in capability.entries]
    ids = [entry.id for entry in capability.entries]
    if ids:
        listed = ",".join(ids) if len(ids) <= MAX_LISTED_IDS else "<编号>,<编号>"
        out.append(f"要原文和例子：devcircuit context --ids {listed}")
    return out


def render_capability(root: Path, code: str) -> tuple[int, str]:
    for capability in load_capabilities(root):
        if capability.code == code:
            return 0, "\n".join(_capability_lines(capability))
    return 1, f"找不到代号：{code}（能力清单：devcircuit context --map）"


def render_ids(root: Path, ids: list[str], max_chars: int = DEFAULT_MAX_CHARS) -> tuple[int, str]:
    index = {entry.id: entry for capability in load_capabilities(root) for entry in capability.entries}
    blocks = [(identifier, f"{index[identifier].path}:{index[identifier].line}\n{index[identifier].text}")
              for identifier in ids if identifier in index]
    missing = [identifier for identifier in ids if identifier not in index]
    kept, dropped = _fit(blocks, max_chars)
    out = ["\n\n".join(kept)] if kept else []
    if dropped:
        out.append(_truncation_note(dropped))
    if missing:
        out.append("找不到：" + "、".join(missing))
    return (1 if missing else 0), "\n".join(out)


def render_feature(root: Path, feature: str, base: str | None = None, review: bool = False,
                   max_chars: int = DEFAULT_MAX_CHARS) -> str:
    card = root / "specs" / feature / "spec.md"
    if not card.is_file():
        raise ContextError(f"找不到卡：specs/{feature}/spec.md（在研功能：devcircuit context --map）")
    card_text = card.read_text(encoding="utf-8-sig").strip()
    capabilities = load_capabilities(root)
    index = {entry.id: entry for capability in capabilities for entry in capability.entries}
    out = [f"== 卡：specs/{feature}/spec.md ==", card_text]

    compared = merge_base(root, base)
    shown: list[str] = []
    blocks: list[tuple[str, str]] = []
    if compared:
        base_name, base_sha = compared
        added, rewritten, removed = requirement_changes(root, base_sha)
        changed = changed_files(root, base_sha)
        spec = _spec()
        codes = {capability.code: capability.path for capability in capabilities if capability.code != "?"}
        references = list(spec._references(root, codes, _patterns(root)))
        cited = sorted({identifier for path, _, identifier in references
                        if path.as_posix() in changed and identifier in index}
                       - set(added) - set(rewritten), key=_natural)

        out.append(f"== 本功能改到的要求（相对 {base_name} 的分叉点 {base_sha[:7]}）==")
        summary = [f"{label}：{'、'.join(items)}" for label, items in
                   (("新增", added), ("改写", rewritten), ("删除", removed)) if items]
        out.append(" / ".join(summary) if summary else "这个分支相对基线还没有改要求")
        for identifier in [*added, *rewritten]:
            if identifier in index:
                blocks.append((identifier, f"{index[identifier].path}:{index[identifier].line}\n"
                                           f"{index[identifier].text}"))
        cited_blocks = [(identifier, f"{index[identifier].path}:{index[identifier].line}\n"
                                     f"{index[identifier].text}") for identifier in cited]
        shown = [*added, *rewritten, *cited]

        budget = max(max_chars - sum(len(part) + 1 for part in out), 0)
        kept, dropped = _fit(blocks + cited_blocks, budget)
        changed_count = len(blocks)
        if kept[:changed_count]:
            out.append("\n\n".join(kept[:changed_count]))
        if cited:
            out.append("== 本功能的代码和测试引用到的其他要求 ==")
            if kept[changed_count:]:
                out.append("\n\n".join(kept[changed_count:]))
        if dropped:
            out.append(_truncation_note(dropped))

        wanted = set(shown)
        tests: dict[str, list[str]] = {}
        for path, _, identifier in references:
            if identifier in wanted and spec._is_test(path):
                tests.setdefault(path.as_posix(), [])
                if identifier not in tests[path.as_posix()]:
                    tests[path.as_posix()].append(identifier)
        out.append("== 相关测试 ==")
        out += [f"{path}（{'、'.join(sorted(ids, key=_natural))}）" for path, ids in sorted(tests.items())] \
            or ["（还没有测试引用这些要求）"]

        out.append("== 框架 ==")
        if ARCHITECTURE in changed:
            out.append(f"本分支改了 {ARCHITECTURE}，框架摘要：")
            out.append(_summary_text(root))
        else:
            out.append(f"框架摘要没改；要用时读 {ARCHITECTURE}#summary")

        if not shown:
            codes_on_card = _card_codes(card_text)
            for capability in capabilities:
                if capability.code in codes_on_card:
                    out += _capability_lines(capability)

        if review:
            out.append(f"== 基线 ==\n{base_sha}（{base_name} 与 HEAD 的分叉点）")
            stat = _git_lines(root, "diff", "--stat", "--relative", base_sha)
            if len(stat) > MAX_STAT_LINES:
                stat = stat[:MAX_STAT_LINES - 1] + [f"…（另有 {len(stat) - MAX_STAT_LINES + 1} 行）", stat[-1]]
            out.append("== 改动统计（git diff --stat 基线，不含未跟踪文件）==")
            out += stat or ["（没有已跟踪文件的改动）"]
    else:
        out.append("== 要求 ==")
        out.append("没有可比的基线（不是 git 仓库，或找不到 main / master；可以用 --base 指定）。"
                   "下面按卡里的“能力：”列出要求清单。")
        codes_on_card = _card_codes(card_text)
        for capability in capabilities:
            if capability.code in codes_on_card:
                out += _capability_lines(capability)
                shown += [entry.id for entry in capability.entries]

    omitted = []
    for capability in capabilities:
        touched = [entry.id for entry in capability.entries if entry.id in set(shown)]
        if touched and len(touched) < len(capability.entries):
            omitted.append(f"{capability.code} 另有 {len(capability.entries) - len(touched)} 条没列出："
                           f"devcircuit context --capability {capability.code}")
    if omitted:
        out.append("== 省略 ==")
        out += omitted
    return "\n".join(out)
