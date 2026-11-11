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
FRAMEWORK_CHANGED = re.compile(r"框架[：:]\s*已改")
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


def _git(root: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", input=stdin)


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


def _guard(project: Path) -> dict:
    guard = _home(project) / GUARD
    if not guard.is_file():
        return {}
    try:
        loaded = json.loads(guard.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise LedgerError(f"{GUARD.as_posix()} 无法解析：{error}") from error
    if not isinstance(loaded, dict):
        raise LedgerError(f"{GUARD.as_posix()} 应该是一个 JSON 对象")
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
    if not isinstance(location, str):
        raise LedgerError(f"{GUARD.as_posix()} 里的 ledger 必须是路径字符串")
    ledger = Path(os.path.expanduser(location))
    if not ledger.is_absolute():
        ledger = ledger.resolve() if environment else home.resolve() / ledger
    if not (ledger / "entries").is_dir():
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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    relative = path.relative_to(ledger).as_posix()
    committed = (_git(ledger, "add", relative).returncode == 0
                 and _git(ledger, "commit", "-q", "-m", f"{name}/{feature} {kind} {record['id']}",
                          "--", relative).returncode == 0)
    return record["id"], committed


def _records(ledger: Path, name: str) -> list[dict]:
    records = []
    for path in sorted((ledger / "entries" / name).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if line.strip():
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict):
                    item.setdefault("feature", path.stem)
                    records.append(item)
    return records


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


def check(project: Path, base: str | None = None) -> tuple[list[Finding], int, int]:
    """Return (findings, record count, feature count). Findings name features, IDs and commits only."""
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
            findings.append(Finding("commit-missing", feature,
                                    f"[commit-missing] {feature}：记录 {record.get('id', '?')} "
                                    f"指向的提交 {str(sha)[:7]} 不在仓库里"))

    removed = {identifier for record in records for identifier in record.get("ids_removed") or []}

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

    # IDs recorded as current must still exist, for records on the history you are on.
    defined = {entry.id for capability in context.load_capabilities(project) for entry in capability.entries}
    for position, record in enumerate(records):
        if full(record) not in order or corrected_at.get(record["feature"], -1) > position:
            continue
        for identifier in record.get("ids") or []:
            if identifier not in defined and identifier not in removed:
                findings.append(Finding("id-stale", record["feature"],
                                        f"[id-stale] {identifier}：{record['feature']} 的记录里的这条要求已经不在"
                                        "能力规格里，也没有删除记录"))

    unique = {finding.text: finding for finding in findings}
    features = {record.get("feature") for record in records}
    return [unique[text] for text in sorted(unique)], len(records), len(features)
