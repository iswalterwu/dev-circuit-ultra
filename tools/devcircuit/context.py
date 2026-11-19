"""`devcircuit context`: read the parts of the current design a task needs, and say what was left out.

Modes:
  --map            capabilities, the cards in this worktree, where the framework summary is, other docs, backlog size
  --capability C   one line per requirement of capability C
  --ids A,B        the full text of these requirements
  --feature F      card, requirements the checked-out branch added or rewrote, requirements its code cites, tests
  --review F       --feature plus the merge base and a diff summary, for the reviewer

What it cannot read (a slice line, the card's 能力 line) or had to leave out (a truncated list) it says,
with the text or the command to go on from; it does not answer from the part it could read.
"""

import re
import shlex
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
BULLET = r"(?:[-*+]|\d+[.)])"
FENCE = re.compile(r"^\s*(`{3,}(?!.*`)|~{3,})")  # (?!.*`): "```make``` 之后…" is inline code, not an opening fence
# "## 切片", "## 切片计划", "## 切片 3 个"; not "## 切片 1：建表", which is a slice written as a heading
SLICE_SECTION = re.compile(r"^(#{1,6})\s*切片(?!\s*[Ss]?\d+\s*[：:])")
# A slice line is a top-level list item "S<n>：<title>". The shape is read loosely (any bullet, a task box,
# bold, a small s, either colon, a space before it); the state is not: a ✓ in the title or a ticked box
# means done, （当前） after the title means in progress, and no other word is a state.
# A small s with a Latin name run straight on from a half-width colon is not read: "- s3:GetObject" is as
# likely a permission as a slice, so it falls to SLICE_LIKE and is reported. "- s3://bucket" is an address.
SLICE = re.compile(r"^" + BULLET + r"\s+(?:\[(?P<box>[ xX])\]\s+)?(?P<bold>\*\*)?(?:S|s(?!\d+:[A-Za-z*]))"
                   r"(?P<number>\d+)(?:\*\*)?\s*(?:\*\*)?(?P<colon>[：:])(?!//)(?P<title>.*)$")
CURRENT_MARK = re.compile(r"\s*[（(]当前[）)]")
# A state written where ✓ or （当前） goes, in a mark or a word that is not read: another tick anywhere in
# the title, one of these words in brackets at its end (before closing marks and a full stop). The line is
# reported, not read without its state: read so, a slice marked （进行中） was one not started, and --map
# named an earlier open slice instead.
OTHER_TICK = re.compile(r"[✔✅☑√]")
OTHER_STATE = re.compile(r"[（(【\[]\s*(?:当前|在做|进行中|下一个|待做|完成|已完成|做完)\s*[）)】\]][\s*_`~。.；;，,]*$")
# What a reader takes for a slice line: a list item, a heading below the card's title or a table row that,
# past task boxes, bracketed words and marks such as ** ` ~~ ✓ in any order, starts with S<n> or 切片 <n>.
# One of these that SLICE cannot read is reported with its text: skipping it made --map name the wrong slice.
SLICE_LIKE = re.compile(r"^(?:" + BULLET + r"|#{2,6}|\|)\s*(?:(?:[（(【\[][^）)】\]]{0,8}[）)】\]]|[^\w\s]|_)\s*){0,6}"
                        r"(?:[Ss]\d(?!\d*://)|切片\s*[Ss]?\d)")
SLICE_FORM = "写成 `- S<n>：<标题>`，在做的加（当前），做完的加 ✓"


def _labelled_line(label: str) -> re.Pattern:
    """A "<label>：<value>" line: "- 主干：`main`", "1. **主干**: main", "**主干：** main", or "| 主干 | main |"."""
    # [^\S\n] is any whitespace but a newline: full-width and no-break spaces count, as they do in Chinese text.
    name = r"(?:\*\*)?" + label + r"(?:\*\*)?[^\S\n]*"
    return re.compile(
        r"^[^\S\n]*(?:" + BULLET + r"[^\S\n]+)?" + name + r"[：:][^\S\n]*(?:\*\*)?(?P<value>[^\n]*)$"
        r"|^[^\S\n]*\|[^\S\n]*" + name + r"\|(?P<cell>[^|\n]*)\|",
        re.MULTILINE)


CAPABILITY_LINE = _labelled_line("能力")  # on a card: "能力：<代号>（已有 / 新建）· 框架：…"
TRUNK_LINE = _labelled_line("主干")       # in AGENTS.md: "- 主干：`main`"
TRUNK_NAME = re.compile(r"\s*(?:\*\*)?`?([^\s`（(，,。；;|*]+)")
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


@dataclass(frozen=True)
class Slice:
    """One slice line of a card."""
    id: str        # "S3"
    title: str     # what follows the colon, up to the （当前） mark; a ✓ stays where it was written
    done: bool     # a ✓ in the title, or a ticked task box: the one rule for done
    current: bool  # （当前） after the title
    line: int      # 1-based line on the card
    label: str     # "S3：<title>" with the colon and the spacing as written, the way --map shows it


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
        # core.quotepath=false: by default git prints non-ASCII paths quoted and octal-escaped, and a
        # capability spec named 订单.md then matched nothing.
        result = subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(root), *args],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def _git_lines(root: Path, *args: str) -> list[str]:
    output = _git(root, *args)
    return [line for line in (output or "").splitlines() if line.strip()]


def named_trunk(root: Path) -> str | None:
    """The trunk AGENTS.md names on its 主干 line, if it has one.

    A 主干 line without a branch name is an error: quietly ignoring it would compare against
    another branch while the user believes the trunk is set.
    """
    try:
        text = (root / "AGENTS.md").read_text(encoding="utf-8-sig", errors="replace")
    except OSError:  # no AGENTS.md, or one that cannot be read: the same as no 主干 line
        return None
    match = TRUNK_LINE.search(text)
    if not match:
        return None
    name = TRUNK_NAME.match(match.group("value") if match.group("value") is not None else match.group("cell"))
    if not name:
        raise ContextError("AGENTS.md 的主干一行没写分支名：写成 `- 主干：`<分支>``，或者删掉这一行")
    return name.group(1)


def remote_trunk(root: Path) -> str | None:
    """The remote's default branch (origin/HEAD), without the origin/ prefix."""
    ref = (_git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD") or "").strip()
    return ref.split("/", 1)[1] if ref.startswith("origin/") else None


def current_branch(root: Path) -> str | None:
    """The checked-out branch (also before its first commit); None on a detached HEAD or outside git."""
    return (_git(root, "symbolic-ref", "--quiet", "--short", "HEAD") or "").strip() or None


def _detached(root: Path) -> str:
    return f"游离 HEAD {(_git(root, 'rev-parse', '--short=7', 'HEAD') or '').strip()}"


def merge_base(root: Path, base: str | None) -> tuple[str, str] | None:
    """Return (base name, merge-base sha), or None when there is nothing to compare against.

    Without --base: the trunk AGENTS.md names (local branch, then origin's); without one, main and
    master as in 0.6, and the remote's default branch only when neither exists, so a stale origin/HEAD
    cannot move an old project's base. An explicit base or a named trunk that cannot be compared is
    an error: falling back silently would hand the reviewer the wrong change set, or an empty one.
    """
    if _git(root, "rev-parse", "--is-inside-work-tree") is None:
        if base:
            raise ContextError(f"不是 git 仓库，没法和基线 {base} 比较")
        return None
    named = None if base else named_trunk(root)
    if base:
        candidates = [base]
    elif named:
        candidates = [named, f"origin/{named}"]
    else:
        remote = remote_trunk(root)
        candidates = ["main", "master", *([remote, f"origin/{remote}"] if remote else [])]
    for candidate in dict.fromkeys(candidates):
        sha = (_git(root, "merge-base", candidate, "HEAD") or "").strip()
        if sha:
            return candidate, sha
    if base:
        raise ContextError(f"找不到基线分支：{base}（或它和 HEAD 没有共同祖先）")
    if named and _git(root, "rev-parse", "--verify", "--quiet", "HEAD") is not None:
        raise ContextError(f"AGENTS.md 写的主干 {named} 找不到（本地和 origin 都没有），或它和 HEAD 没有共同祖先："
                           "改成实际的主干分支，或用 --base 指定")
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


def _slice_lines(lines: list[str]) -> tuple[list[tuple[int, str]], bool]:
    """The (number, line) pairs slices are read from, and whether the card has a 切片 section.

    Every section whose heading starts with 切片 is read, to the next heading of its level or above;
    a card without one is read whole. A line inside a fenced block is not a heading, and a heading written
    like a slice does not end the section: each of them, taken for the end, hid the slices after it.
    """
    inside: list[tuple[int, str]] = []
    level = fence = None
    found = False
    for number, line in enumerate(lines, 1):
        text = line.strip()
        if fence:  # closed by its own character, at least as many of them, and nothing else on the line
            if text.startswith(fence) and not text.strip(fence[0]):
                fence = None
        elif opening := FENCE.match(line):
            fence = opening.group(1)
        elif (section := SLICE_SECTION.match(line)) and (level is None or len(section.group(1)) <= level):
            level, found = len(section.group(1)), True
            continue
        elif (level is not None and (heading := HEADING.match(line)) and len(heading.group(1)) <= level
              and not SLICE_LIKE.match(line)):
            level = None
        if level is not None:
            inside.append((number, line))
    return (inside, True) if found else (list(enumerate(lines, 1)), False)


def read_slices(card_text: str) -> tuple[list[Slice], list[tuple[int, str]]]:
    """The slices on a card, and the lines (number, text) that look like slices but cannot be read.

    Only top-level lines of the 切片 sections count; indented lines are steps.
    """
    slices: list[Slice] = []
    unreadable: list[tuple[int, str]] = []
    for number, line in _slice_lines(card_text.splitlines())[0]:
        match = SLICE.match(line)
        if not match:
            if SLICE_LIKE.match(line):
                unreadable.append((number, line.rstrip()))
            continue
        written = match.group("title")
        if match.group("bold"):  # "- **S3：读回**": the closing marks are not part of the title
            written = written.replace("**", "")
        current = CURRENT_MARK.search(written)
        shown = (written[:current.start()] if current else written).rstrip()
        if OTHER_TICK.search(written) or OTHER_STATE.search(shown):
            unreadable.append((number, line.rstrip()))
            continue
        identifier = f"S{match.group('number')}"
        done = "✓" in written or match.group("box") in ("x", "X")
        slices.append(Slice(identifier, shown.strip(), done, current is not None, number,
                            f"{identifier}{match.group('colon')}{shown}"))
    return slices, unreadable


def slice_status(card_text: str) -> str:
    """What --map says about a card: the slice in progress, else the first one not done.

    A line that cannot be read is quoted instead, with no state at all: a state built from the lines
    that did parse is what pointed at the wrong slice.
    """
    slices, unreadable = read_slices(card_text)
    if unreadable:
        number, raw = unreadable[0]
        raw = raw if len(raw) <= MAX_TITLE else raw[:MAX_TITLE] + "…"
        more = f"，另有 {len(unreadable) - 1} 行" if len(unreadable) > 1 else ""
        return f"切片行读不懂（第 {number} 行{more}）：{raw}  ← {SLICE_FORM}"
    for found in slices:
        if found.current:
            return f"当前：{found.label}"
    for found in slices:
        if not found.done:
            return f"下一个：{found.label}"
    if slices:
        return "切片都已完成"
    inside, section = _slice_lines(card_text.splitlines())
    return f"没读到切片行：{SLICE_FORM}" if section and any(line.strip() for _, line in inside) else "还没有切片"


def _slice_status(card: Path) -> str:
    return slice_status(card.read_text(encoding="utf-8-sig"))


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


def _fit(blocks: list[tuple[str, str]], budget: int) -> tuple[list[str], list[tuple[str, str]]]:
    """Keep whole blocks while they fit the budget; return kept texts and the blocks left out."""
    kept: list[str] = []
    used = 0
    for position, (identifier, text) in enumerate(blocks):
        if kept and used + len(text) + 2 > budget:
            return kept, blocks[position:]
        kept.append(text)
        used += len(text) + 2
    return kept, []


def _quoted(text: str) -> str:
    """Double quotes pass through bash, cmd and PowerShell alike; single ones where " $ ` or \\ would be read."""
    return shlex.quote(text) if re.search(r'["$`\\]', text) else f'"{text}"'


def carried_flags(root: str, base: str | None) -> str:
    """The --base and --root this call was given, to append to the commands its output tells the reader to run.

    Without them a command printed for a project elsewhere would run against the current directory.
    """
    flags = f" --base {_quoted(base)}" if base else ""
    if root != ".":  # forward slashes: a backslash before the closing quote would escape it
        flags += f" --root {_quoted(Path(root).as_posix())}"
    return flags


def _truncation_note(dropped: list[tuple[str, str]], flags: str = "") -> str:
    """Name every requirement left out, in commands that run as printed, one per line.

    The batches are packed the way --ids packs at its default limit, so none of them is cut again.
    The first 10 IDs followed by `…` could not be run, and named nothing after the tenth.
    """
    commands: list[str] = []
    rest = dropped
    while rest:
        kept, later = _fit(rest, DEFAULT_MAX_CHARS)
        batch = ",".join(identifier for identifier, _ in rest[:len(kept)])
        commands.append(f"devcircuit context --ids {batch}{flags}")
        rest = later
    return "\n".join([f"（截断：还有 {len(dropped)} 条没列出，补读用下面的命令，每行一条，原样运行）", *commands])


def _card_codes(card_text: str) -> list[str]:
    match = CAPABILITY_LINE.search(card_text)
    if not match:
        return []
    value = match.group("value") if match.group("value") is not None else match.group("cell")
    return CODE_WORD.findall(value.split("·", 1)[0])


def _card_capabilities(card_text: str, capabilities: list[Capability], flags: str = "") -> list[str]:
    """The requirement lists of the capabilities the card names.

    A card that names no capability spec gets a line saying so: with nothing printed, an unread or
    misspelt 能力 line looked the same as a capability without requirements.
    """
    codes = _card_codes(card_text)
    lines: list[str] = []
    for capability in capabilities:
        if capability.code in codes:
            lines += _capability_lines(capability, flags)
    if not lines:
        read = (f"卡的“能力：”一行写的是 {'、'.join(codes)}，docs/requirements/ 里没有对应的能力规格" if codes
                else "没从卡里读到“能力：”一行的代号")
        lines.append(f"{read}，所以没有清单可列。规范写法：`能力：<代号>（已有 / 新建）`；代号见 devcircuit context --map")
    return lines


# ---------------------------------------------------------------- modes

def render_map(root: Path) -> str:
    capabilities = load_capabilities(root)
    out = ["能力（docs/requirements/；要求清单：devcircuit context --capability <代号>）"]
    out += [f"- {item.code}  {Path(item.path).name}  {item.title}  {len(item.entries)} 条" for item in capabilities]
    if not capabilities:
        out.append("- （还没有能力规格）")
    in_git = _git(root, "rev-parse", "--is-inside-work-tree") is not None
    scope = "specs/"
    if in_git:  # cards on other branches and in other worktrees are not here: say whose list this is
        branch = current_branch(root)
        scope = "只列本工作树的 specs/，" + (f"当前分支 {branch}" if branch else f"当前不在分支上：{_detached(root)}")
    out.append(f"在研功能（{scope}；上下文：devcircuit context --feature <名>）")
    cards = sorted((root / "specs").glob("*/spec.md")) if (root / "specs").is_dir() else []
    for card in cards:
        relative = f"specs/{card.parent.name}/spec.md"
        # From 0.7 the card is written before the user settles the design; only a committed card is settled.
        draft = in_git and _git(root, "cat-file", "-e", f"HEAD:./{relative}") is None
        mark = "  草稿（没提交：用户还没说定了）" if draft else ""
        out.append(f"- {card.parent.name}  {relative}  {_slice_status(card)}{mark}")
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


def _capability_lines(capability: Capability, flags: str = "") -> list[str]:
    out = [f"{capability.code}  {capability.title}（{capability.path}，{len(capability.entries)} 条）"]
    out += [entry.title for entry in capability.entries]
    ids = [entry.id for entry in capability.entries]
    if ids:
        listed = ",".join(ids) if len(ids) <= MAX_LISTED_IDS else "<编号>,<编号>"
        out.append(f"要原文和例子：devcircuit context --ids {listed}{flags}")
    return out


def render_capability(root: Path, code: str, flags: str = "") -> tuple[int, str]:
    for capability in load_capabilities(root):
        if capability.code == code:
            return 0, "\n".join(_capability_lines(capability, flags))
    return 1, f"找不到代号：{code}（能力清单：devcircuit context --map）"


def render_ids(root: Path, ids: list[str], max_chars: int = DEFAULT_MAX_CHARS, flags: str = "") -> tuple[int, str]:
    index = {entry.id: entry for capability in load_capabilities(root) for entry in capability.entries}
    blocks = [(identifier, f"{index[identifier].path}:{index[identifier].line}\n{index[identifier].text}")
              for identifier in ids if identifier in index]
    missing = [identifier for identifier in ids if identifier not in index]
    kept, dropped = _fit(blocks, max_chars)
    out = ["\n\n".join(kept)] if kept else []
    if dropped:
        out.append(_truncation_note(dropped, flags))
    if missing:
        out.append("找不到：" + "、".join(missing))
    return (1 if missing else 0), "\n".join(out)


def _branch_line(root: Path, feature: str, compared: tuple[str, str] | None) -> str | None:
    """Which branch is compared with which base, and whether that branch is this feature's; None outside git.

    --feature shows what the checked-out branch changed, whichever feature it was asked about.
    """
    if _git(root, "rev-parse", "--is-inside-work-tree") is None:
        return None
    branch, expected = current_branch(root), f"feat/{feature}"
    if branch == expected:
        who = branch
    else:
        who = f"{branch}，不是 {expected}" if branch else f"没有（{_detached(root)}）"
    if not compared:
        return f"分支：{who}；基线：没有可比的"
    line = f"分支：{who}；基线：{compared[0]}（分叉点 {compared[1][:7]}）"
    if branch == expected:
        return line
    if branch == compared[0]:
        return line + "。下面是当前分支相对基线的全部改动：当前分支就是基线，所以只有还没提交的部分。"
    return line + f"。下面是当前{'分支' if branch else '提交'}相对基线的全部改动，不一定都属于 {feature}。"


def render_feature(root: Path, feature: str, base: str | None = None, review: bool = False,
                   max_chars: int = DEFAULT_MAX_CHARS, flags: str = "") -> str:
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
            out.append(_truncation_note(dropped, flags))

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
            out += _card_capabilities(card_text, capabilities, flags)

        if review:
            out.append(f"== 基线 ==\n{base_sha}（{base_name} 与 HEAD 的分叉点）")
            stat = _git_lines(root, "diff", "--stat", "--relative", base_sha)
            if len(stat) > MAX_STAT_LINES:
                stat = stat[:MAX_STAT_LINES - 1] + [f"…（另有 {len(stat) - MAX_STAT_LINES + 1} 行）", stat[-1]]
            out.append("== 改动统计（git diff --stat 基线，不含未跟踪文件）==")
            out += stat or ["（没有已跟踪文件的改动）"]
    else:
        out.append("== 要求 ==")
        out.append("没有可比的基线（不是 git 仓库、还没有提交，或找不到 main / master / 远端默认分支；"
                   "可以用 --base 指定，或在 AGENTS.md 写一行主干）。"
                   "下面按卡里的“能力：”列出要求清单。")
        out += _card_capabilities(card_text, capabilities, flags)

    omitted = []
    for capability in capabilities:
        touched = [entry.id for entry in capability.entries if entry.id in set(shown)]
        if touched and len(touched) < len(capability.entries):
            omitted.append(f"{capability.code} 另有 {len(capability.entries) - len(touched)} 条没列出："
                           f"devcircuit context --capability {capability.code}{flags}")
    if omitted:
        out.append("== 省略 ==")
        out += omitted
    where = _branch_line(root, feature, compared)  # put first only now: it is not part of what --max-chars limits
    return "\n".join([where, *out] if where else out)
