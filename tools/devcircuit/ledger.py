"""The private ledger outside the project.

The dev agent appends with `add` and never reads; `add` answers with a receipt only.
`check` compares the ledger with the repo and reports features, IDs and commits that disagree,
never the content of a record.
"""

import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import context

GUARD = Path(".dev-circuit") / "guard.json"
KINDS = ("framework", "design", "design-change", "close", "correction")
FEATURE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FEATURE_RULE = "功能名只用字母、数字、点、下划线和连字符，一段，不含斜杠"
REQUIREMENT_ID = re.compile(r"^(?:[A-Z]{2,8}-\d+|[A-Z]{2,8}:AC-\d{3}-\d+)$")
ID_SEPARATORS = re.compile(r"[,，、；;\s]+")
CLOSE_SUBJECT = re.compile(r"^close\s+([A-Za-z0-9][A-Za-z0-9._-]*)")
# "框架：已改", in bold too, as the capability line it sits on is read: **框架**：已改, **框架：** 已改, 框架：**已改**
FRAMEWORK_CHANGED = re.compile(r"框架(?:\*\*)?[^\S\n]*[：:]\s*(?:\*\*)?\s*已改")
HUMAN_SIDE = "human"
NOT_CONFIGURED = ("没有配置账本：先 devcircuit ledger init --path <项目外的私有目录>，"
                  "再 devcircuit hooks install --harness <pi|claude> --project <项目> --ledger <账本>")


class LedgerError(RuntimeError):
    """A usage or configuration problem; the message is meant for the user."""


@dataclass(frozen=True)
class Finding:
    rule: str
    feature: str | None  # None: about the current branch as a whole
    text: str


def valid_feature(name: str) -> bool:
    return bool(FEATURE.match(name))


def _git(root: Path, *args: str, stdin: str | None = None,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    # core.quotepath=false, as in context and close: git would quote and octal-escape non-ASCII paths.
    return subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(root), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", input=stdin, env=env)


# What `git rev-parse --local-env-vars` lists (git 2.52): the variables that tie git to one repository, whatever
# -C says. git sets them for its hooks, and an agent a hook starts inherits them; `git -C <ledger> commit` then
# committed the record into the project. GIT_CONFIG_KEY_<n> / GIT_CONFIG_VALUE_<n> carry `git -c` down to the
# commands git starts, as GIT_CONFIG_PARAMETERS does.
LOCAL_GIT_ENV = frozenset({
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE", "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX", "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
})
PASSED_CONFIG = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")


def ledger_environment() -> dict[str, str]:
    """The environment for git run on the ledger repository: this process's, less what points git elsewhere.

    git run on the project keeps them: whoever set GIT_DIR there meant the project.
    """
    return {name: value for name, value in os.environ.items()
            if name not in LOCAL_GIT_ENV and not name.startswith(PASSED_CONFIG)}


def _ledger_git(ledger: Path, *args: str) -> subprocess.CompletedProcess:
    return _git(ledger, *args, env=ledger_environment())


def _home(project: Path) -> Path:
    """Where guard.json lives: the project, or its main working tree when the project is a linked git worktree.

    guard.json is machine-local and gitignored, so a worktree never has its own copy. Without this the
    ledger looked unconfigured there: `ledger add` failed and `devcircuit close` skipped the records.
    """
    if (project / GUARD).is_file():
        return project
    main = _main_tree(project)
    return main if main and (main / GUARD).is_file() else project


def _main_tree(project: Path) -> Path | None:
    """The main working tree when `project` is the top level of a linked git worktree, else None.

    A folder inside a working tree is not the project: the card and the capability specs are looked up
    under the folder given, so falling back from src/ would check the ledger against nothing.
    """
    try:
        found = _git(project, "rev-parse", "--show-prefix", "--git-dir", "--git-common-dir")
    except OSError:
        return None
    lines = found.stdout.split("\n")
    if found.returncode != 0 or len(lines) < 3 or lines[0]:
        return None
    git_dir, common = ((project / line.strip()).resolve() for line in lines[1:3])
    return common.parent if git_dir != common else None


HERE, MAIN_TREE, NOWHERE = "本工作树", "主工作树", "无"


def locate(project: Path) -> tuple[Path | None, Path, str]:
    """guard.json as the ledger commands find it: the file or None, the folder it is read from, and which one that is.

    `hooks status` and `hooks install` ask here. They used to look in the project only, so in a linked
    worktree they found no config where `ledger add` / `check` and `close` did.
    """
    home = _home(project)
    guard = home / GUARD
    if not guard.is_file():
        return None, home, NOWHERE
    return guard, home, HERE if home == project else MAIN_TREE


MAX_NESTING = 64
LEDGER_NOT_A_PATH = "ledger 应该是非空的路径字符串"
UNREADABLE = "{guard} 无法解析：{problem}。两个 hook 读不出这样的配置，会拦下全部工具调用：由 human 修好这个文件{hint}"


def _too_deep(text: str) -> bool:
    """Whether brackets outside strings nest deeper than MAX_NESTING anywhere.

    Counted before parsing, so the answer does not hang on an interpreter's recursion limit: python 3.10 and
    3.14, and node in the pi hook, all come to the same one.
    """
    depth, in_string, escaped = 0, False, False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_NESTING:
                return True
        elif character in "]}":
            depth -= 1
    return False


def _not_json(constant: str):
    """NaN and Infinity: python's json takes them, JSON.parse in the pi hook does not."""
    raise ValueError(constant)


INT_DIGITS = 4300  # what python's int() takes from a string by default since 3.10.7


def _integer(text: str) -> int | float:
    """A JSON integer as JSON.parse in the pi hook takes it: never an error, a float past what int() reads.

    Past INT_DIGITS digits int() raises, and the file was unreadable here while the pi hook read it; below
    that, PYTHONINTMAXSTRDIGITS may set the limit lower. A float that long is infinity, as in node.
    """
    if len(text.lstrip("-")) <= INT_DIGITS:
        try:
            return int(text)
        except ValueError:
            pass
    return float(text)


def read_guard(path: Path) -> tuple[dict | None, str]:
    """guard.json by the rule both hooks follow: (config, ""), or (None, why it cannot be used).

    Bytes decoded as strict UTF-8 with a leading BOM dropped; nesting no deeper than MAX_NESTING; JSON without
    NaN or Infinity; an object; `ledger`, when it is there, a string that is not blank to str.strip(), the set
    both hooks strip from an entry before they turn it into a path. A `deny` the hooks skip does not make the
    file unreadable. The reason is one of a few fixed
    sentences: a parser's own message can quote the file, and the file names the ledger.
    """
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except OSError:
        return None, "读不出这个文件"
    except ValueError:
        return None, "不是合法的 UTF-8 JSON"
    if _too_deep(text):
        return None, f"嵌套超过 {MAX_NESTING} 层"
    try:
        loaded = json.loads(text, parse_constant=_not_json, parse_int=_integer)
    except ValueError:
        return None, "不是合法的 UTF-8 JSON"
    if not isinstance(loaded, dict):
        return None, "内容不是一个 JSON 对象"
    if "ledger" in loaded and not (isinstance(loaded["ledger"], str) and loaded["ledger"].strip()):
        return None, LEDGER_NOT_A_PATH
    return loaded, ""


def _guard(project: Path) -> dict:
    guard = _home(project) / GUARD
    if not guard.is_file():
        return {}
    loaded, problem = read_guard(guard)
    if loaded is None:
        # "No ledger configured" here would send the human to set up one they already have.
        hint = "（ledger 写账本的路径；这里不放账本的，删掉这一项）" if problem == LEDGER_NOT_A_PATH else ""
        raise LedgerError(UNREADABLE.format(guard=GUARD.as_posix(), problem=problem, hint=hint))
    return loaded


def configured(project: Path) -> bool:
    return bool(os.environ.get("DEVCIRCUIT_LEDGER")) or (_home(project) / GUARD).is_file()


def human_side(project: Path) -> bool:
    """guard.json says the ledger is kept on the human side: the dev side neither writes nor checks it."""
    return not os.environ.get("DEVCIRCUIT_LEDGER") and _guard(project).get("ledger_side") == HUMAN_SIDE


def resolve(project: Path) -> tuple[Path, str]:
    """Ledger directory and project name.

    DEVCIRCUIT_LEDGER / DEVCIRCUIT_PROJECT win when set: the ledger side of a container setup
    mounts the ledger at its own path. Otherwise <project>/.dev-circuit/guard.json decides, and a
    relative path there is resolved from the project root, as the hook does. In a linked git worktree
    the main working tree's guard.json and name are used, so every worktree files under one project.
    """
    home = _home(project)
    raw = _guard(project)
    environment = os.environ.get("DEVCIRCUIT_LEDGER")
    if not environment and raw.get("ledger_side") == HUMAN_SIDE:
        raise LedgerError("这个项目的账本在 human 一侧（guard.json 的 ledger_side 是 human）：开发侧不写也不核对，"
                          "由 human 在账本一侧运行 devcircuit ledger add / check；devcircuit close 会跳过账本步骤")
    location = environment or raw.get("ledger")
    if not location:
        raise LedgerError(NOT_CONFIGURED)
    ledger = Path(os.path.expanduser(location))
    if not ledger.is_absolute():
        ledger = ledger.resolve() if environment else home.resolve() / ledger
    try:
        usable = (ledger / "entries").is_dir()
    except OSError as error:  # Python before 3.14 raises for a folder this user may not look into, and names it
        raise LedgerError(f"账本目录查不了（{why_failed(error)}）；请人工检查 guard.json 或 DEVCIRCUIT_LEDGER，"
                          "以及账本目录的权限") from error
    if not usable:
        raise LedgerError("配置的账本目录不存在或不是账本；请人工检查 guard.json 或 DEVCIRCUIT_LEDGER")
    # A worktree may carry its own guard.json (copied in, or written by hooks install there): the records
    # still belong to the project, not to the worktree's folder name.
    name = (os.environ.get("DEVCIRCUIT_PROJECT") or raw.get("project")
            or (_main_tree(project) or home).resolve().name)
    return ledger, str(name)


def _split_ids(value: str | None) -> list[str]:
    out: list[str] = []
    for item in ID_SEPARATORS.split(value or ""):
        if item and item not in out:
            out.append(item)
    return out


def _discarded(items) -> list[dict]:
    """'方案：原因' becomes {"idea": 方案, "why": 原因}; without a colon the reason stays empty."""
    out = []
    for item in items:
        parts = re.split(r"[：:]", item, maxsplit=1)
        out.append({"idea": parts[0].strip(), "why": parts[1].strip() if len(parts) > 1 else ""})
    return out


def _full_commit(project: Path, commit: str | None) -> str | None:
    target = commit or "HEAD"
    result = _git(project, "rev-parse", "--verify", "--quiet", f"{target}^{{commit}}")
    if result.returncode == 0:
        return result.stdout.strip()
    if commit:
        raise LedgerError(f"提交不存在：{commit}")
    return None


def _checked_ids(project: Path, ids: str | None, removed_ids: str | None) -> tuple[list[str], list[str]]:
    """The agent cannot read a record back, so a wrong ID has to be refused now."""
    current, removed = _split_ids(ids), _split_ids(removed_ids)
    malformed = [item for item in current + removed if not REQUIREMENT_ID.match(item)]
    if malformed:
        raise LedgerError("这些不是要求编号：" + "、".join(malformed)
                          + "（写成 <代号>-<数字>，多个用逗号或顿号隔开）")
    if current:
        defined = {entry.id for capability in context.load_capabilities(project) for entry in capability.entries}
        missing = [item for item in current if item not in defined]
        if missing:
            raise LedgerError("这些编号在能力规格里不存在：" + "、".join(missing) + "（删掉的编号用 --removed-ids）")
    return current, removed


def add(project: Path, feature: str, kind: str, decision: str, rejected=(), reason: str | None = None,
        ids: str | None = None, removed_ids: str | None = None, review: str | None = None,
        commit: str | None = None) -> tuple[str, bool]:
    """Append one record; return its id and whether the ledger commit succeeded."""
    if kind not in KINDS:
        raise LedgerError(f"--kind 只能是：{'、'.join(KINDS)}")
    if not valid_feature(feature):
        raise LedgerError(f"--feature 不合规：{FEATURE_RULE}")
    if not decision.strip():
        raise LedgerError("--decision 不能为空")
    current, removed = _checked_ids(project, ids, removed_ids)
    ledger, name = resolve(project)
    sha = _full_commit(project, commit)

    now = datetime.now(timezone.utc)
    record = {
        "id": f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}",
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": name,
        "feature": feature,
        "kind": kind,
        "commit": sha,
        "decision": decision.strip(),
    }
    if rejected:
        record["discarded"] = _discarded(rejected)
    if reason:
        record["reason"] = reason.strip()
    if review:
        record["review"] = review.strip()
    if current:
        record["ids"] = current
    if removed:
        record["ids_removed"] = removed
    record.update({"source": "dev-agent", "human_only": True})

    path = ledger / "entries" / name / f"{feature}.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as error:
        raise LedgerError(f"账本记录写不进去（{why_failed(error)}）；请人工检查账本目录的权限和磁盘空间") from error
    relative = path.relative_to(ledger).as_posix()
    return record["id"], _commit(ledger, relative, f"{name}/{feature} {kind} {record['id']}")


def why_failed(error: OSError) -> str:
    """Why a file operation failed, without the path: the error names the file, and that may be the ledger's."""
    return error.strerror or type(error).__name__


def _commit(ledger: Path, relative: str, message: str) -> bool:
    return (_ledger_git(ledger, "add", relative).returncode == 0
            and _ledger_git(ledger, "commit", "-q", "-m", message, "--", relative).returncode == 0)


def close_recorded(project: Path, feature: str, commit: str) -> bool:
    """Whether the ledger has a close record of `feature` for the close that `commit` made. Yes or no only.

    A rerun of `devcircuit close` asks this before it writes. A close record counts when it points at
    `commit` or at a commit made on top of it, and when it was written after `commit` was made: a human who
    saw close-missing may have recorded the close by hand since, from the trunk or from another clone, and
    `ledger add` takes whatever HEAD is there. A record written before `commit` was made, pointing
    elsewhere, does not count: it belongs to an earlier feature that used the name.
    """
    ledger, name = resolve(project)
    closes = [record for record in _records(ledger, name)
              if record.get("feature") == feature and record.get("kind") == "close"]
    made = _git(project, "show", "-s", "--format=%ct", commit).stdout.strip()
    if made.isdigit() and any(_written(record) > int(made) for record in closes):
        return True
    recorded = {record["commit"] for record in closes if isinstance(record.get("commit"), str)}
    return any(_git(project, "merge-base", "--is-ancestor", commit, sha).returncode == 0
               for sha in set(_resolve_commits(project, recorded).values()))


def _written(record: dict) -> float:
    """When a record was written, in seconds since the epoch; 0 when its `ts` is not the UTC time `add` writes."""
    try:
        return datetime.strptime(record.get("ts"), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0


def settle(project: Path, feature: str) -> bool:
    """Commit `feature`'s records when an earlier `add` wrote one that the ledger repository did not commit.

    True when nothing is left uncommitted.
    """
    ledger, name = resolve(project)
    relative = f"entries/{name}/{feature}.jsonl"
    status = _ledger_git(ledger, "status", "--porcelain", "--", relative)
    if status.returncode != 0:
        return False
    return not status.stdout.strip() or _commit(ledger, relative, f"{name}/{feature} close（补提交）")


def _records(ledger: Path, name: str) -> list[dict]:
    records = []
    try:
        # Listed, not globbed: Path.glob() takes a folder it may not list for an empty one, and check then said
        # every feature in progress had no design record.
        try:
            paths = sorted(path for path in (ledger / "entries" / name).iterdir() if path.suffix == ".jsonl")
        except FileNotFoundError:
            paths = []  # nothing filed under this project yet
        for path in paths:
            for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                if line.strip():
                    try:
                        item = json.loads(line)
                    except (ValueError, RecursionError):  # a line nested too deep is as malformed as any other
                        continue
                    if isinstance(item, dict):
                        item.setdefault("feature", path.stem)
                        # Compared and used as keys from here on: a hand edit may have left a list there.
                        for key in ("feature", "kind"):
                            if not isinstance(item.get(key), (str, type(None))):
                                item[key] = OMITTED
                        records.append(item)
    except OSError as error:
        raise LedgerError(f"账本记录读不出来（{why_failed(error)}）；请人工检查账本目录的权限") from error
    return records


# The shapes of what `check` prints from a record besides requirement IDs and feature names.
# <UTC time>-<6 hex digits>, as `add` writes it; ASCII, so \d takes no other script's digits
RECORD_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{6}$", re.ASCII)
COMMIT_ID = re.compile(r"^[0-9A-Fa-f]{4,64}$")
OMITTED = "（格式不对，已略）"


def _shown(value, shape: re.Pattern) -> str:
    """A record field as `check` may print it: itself when it has the shape of what it claims to be.

    `add` validates what it writes, but a record edited by hand, or an old one, can hold a sentence where an
    ID belongs, and printing that would hand ledger content to the dev side.
    """
    return value if isinstance(value, str) and shape.fullmatch(value) else OMITTED


def _listed(value) -> list:
    """A record's `ids` or `ids_removed` as a list, whatever a hand edit left there; None for what is not text."""
    entries = value if isinstance(value, list) else [value] if value else []
    return [entry if isinstance(entry, str) else None for entry in entries]


def uncomparable(project: Path, compared: tuple[str, str] | None) -> str | None:
    """Why the requirements this branch changed cannot be told from `compared` (context.merge_base), or None.

    Without a base nothing is compared. With HEAD as the fork point the comparison runs and comes back
    empty, which reads as "nothing changed" when it only means there is no branch to look at.
    """
    if not compared:
        return "找不到可比的基线（用 --base 指定，或在 AGENTS.md 写一行主干）"
    if compared[1] == _git(project, "rev-parse", "--verify", "--quiet", "HEAD").stdout.strip():
        return (f"当前提交就是和基线 {compared[0]} 的分叉点（就在基线上，或者已经合并进去），"
                "看不出这个分支改过哪些要求")
    return None


def _history(project: Path) -> list[tuple[str, str]]:
    """(sha, subject) for commits reachable from HEAD, newest first."""
    result = _git(project, "log", "--format=%H%x09%s", "HEAD")
    if result.returncode != 0:
        return []
    return [tuple(line.split("\t", 1)) if "\t" in line else (line, "")
            for line in result.stdout.splitlines() if line.strip()]


def _resolve_commits(project: Path, shas: set[str]) -> dict[str, str]:
    """Map each recorded commit, short or full, to the full SHA of a commit the repo has."""
    ordered = sorted(sha for sha in shas if sha and not any(char.isspace() for char in sha))
    if not ordered:
        return {}
    result = _git(project, "cat-file", "--batch-check=%(objectname) %(objecttype)",
                  stdin="".join(f"{sha}\n" for sha in ordered))
    resolved = {}
    for sha, line in zip(ordered, result.stdout.splitlines()):
        parts = line.split()
        if len(parts) == 2 and parts[1] == "commit":
            resolved[sha] = parts[0]
    return resolved


def check(project: Path, base: str | None = None) -> tuple[list[Finding], int, int, list[str]]:
    """Return (findings, record count, feature count, notes). Findings name features, IDs and commits only.

    A note says what could not be checked and why. It is not a finding: the verdict stays what it is.
    """
    ledger, name = resolve(project)
    records = _records(ledger, name)
    history = _history(project)
    order = {sha: position for position, (sha, _) in enumerate(history)}
    commits = _resolve_commits(project, {record["commit"] for record in records
                                         if isinstance(record.get("commit"), str)})

    def full(record: dict) -> str | None:
        sha = record.get("commit")
        return commits.get(sha) if isinstance(sha, str) else None

    corrected_at: dict[str, int] = {}
    for position, record in enumerate(records):
        if record.get("kind") == "correction":
            corrected_at[record["feature"]] = position

    def kinds(feature: str) -> set[str]:
        return {record.get("kind") for record in records if record.get("feature") == feature}

    findings: list[Finding] = []

    # Cards in progress need their design record, and a framework record when the card says the framework changed.
    in_progress: set[str] = set()
    specs = project / "specs"
    for card in sorted(specs.glob("*/spec.md")) if specs.is_dir() else []:
        feature = card.parent.name
        if not valid_feature(feature):
            findings.append(Finding("bad-feature-name", feature,
                                    f"[bad-feature-name] {feature}：{FEATURE_RULE}；改了卡的目录名再记账本"))
            continue
        in_progress.add(feature)
        present = kinds(feature)
        if not present & {"design", "design-change", "correction"}:
            findings.append(Finding("design-missing", feature, f"[design-missing] {feature}：在研功能没有设计记录"))
        if FRAMEWORK_CHANGED.search(card.read_text(encoding="utf-8-sig")) \
                and not present & {"framework", "correction"}:
            findings.append(Finding("framework-missing", feature,
                                    f"[framework-missing] {feature}：卡上写着框架已改，账本没有框架记录"))

    # Close commits after the first recorded commit need a close record.
    recorded = [order[full(record)] for record in records if full(record) in order]
    if recorded:
        for sha, subject in history[:max(recorded)]:
            match = CLOSE_SUBJECT.match(subject)
            if match and not kinds(match.group(1)) & {"close", "correction"}:
                findings.append(Finding("close-missing", match.group(1),
                                        f"[close-missing] {match.group(1)}：提交 {sha[:7]} 没有对应的收尾记录"))

    # Records of features in progress must point at commits the repo has, unless a later correction
    # acknowledged them. Closed features are skipped: squash and rebase merges drop branch commits.
    for position, record in enumerate(records):
        feature = record.get("feature")
        sha = record.get("commit")
        if sha and feature in in_progress and full(record) is None \
                and corrected_at.get(feature, -1) <= position:
            number = _shown(record["id"], RECORD_ID) if "id" in record else "?"
            commit = _shown(sha, COMMIT_ID)
            findings.append(Finding("commit-missing", feature,
                                    f"[commit-missing] {feature}：记录 {number} "
                                    f"指向的提交 {commit if commit == OMITTED else commit[:7]} 不在仓库里"))

    removed = {identifier for record in records for identifier in _listed(record.get("ids_removed")) if identifier}

    # Requirements this branch deleted need a record of the deletion.
    try:
        compared = context.merge_base(project, base)
    except context.ContextError as error:
        raise LedgerError(str(error)) from error
    if compared:
        _, _, deleted = context.requirement_changes(project, compared[1])
        for identifier in deleted:
            if identifier not in removed:
                findings.append(Finding("removal-unrecorded", None,
                                        f"[removal-unrecorded] {identifier}：本分支删掉了这条要求，账本里没有删除记录"))
    unknown = uncomparable(project, compared)
    notes = [f"removal-unrecorded 没查这个分支删掉的要求：{unknown}"] if unknown else []

    # IDs recorded as current must still exist, for records on the history you are on.
    defined = {entry.id for capability in context.load_capabilities(project) for entry in capability.entries}
    for position, record in enumerate(records):
        if full(record) not in order or corrected_at.get(record["feature"], -1) > position:
            continue
        for identifier in _listed(record.get("ids")):
            if identifier not in defined and identifier not in removed:
                feature = _shown(record["feature"], FEATURE)
                findings.append(Finding("id-stale", feature,
                                        f"[id-stale] {_shown(identifier, REQUIREMENT_ID)}：{feature} 的记录里的这条要求"
                                        "已经不在能力规格里，也没有删除记录"))

    unique = {finding.text: finding for finding in findings}
    features = {record.get("feature") for record in records}
    return [unique[text] for text in sorted(unique)], len(records), len(features), notes
