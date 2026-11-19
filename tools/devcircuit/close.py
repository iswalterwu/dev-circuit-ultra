"""`devcircuit close <feature>`: the closing bookkeeping as one command.

Order: full checks -> ledger check -> delete the card and commit `close <feature>` -> close record
-> ledger check again -> a delivery-report skeleton with the mechanical parts filled in.
Nothing changes when a check before the commit fails. Ledger gaps of other features are reported,
not blocking; only this feature and this branch must be consistent.

The command can be run again. Once the close commit exists the project is closed whatever happens to the
ledger afterwards, so a rerun finds that commit, leaves the project alone and only fills in the record.
It finds the commit by the feature's name alone, so it says which one it took and when that was made.
"""

import os
import subprocess
from pathlib import Path

from . import context, ledger
from ._loader import load_script


class CloseError(RuntimeError):
    """A precondition failed; the message is meant for the user."""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    # core.quotepath=false: by default git prints non-ASCII paths quoted and octal-escaped, and the dirty
    # files this command lists were unreadable.
    return subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(root), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def _has_card(project: Path, feature: str) -> bool:
    specs = project / "specs"
    names = set(os.listdir(specs)) if specs.is_dir() else set()
    return feature in names and (specs / feature / "spec.md").is_file()


def _clean_tree(project: Path) -> None:
    status = _git(project, "status", "--porcelain", "--untracked-files=all")
    if status.returncode != 0:
        raise CloseError("close 要在项目的 git 仓库里跑")
    dirty = [line[3:] for line in status.stdout.splitlines() if line.strip()]
    if dirty:
        listed = "、".join(dirty[:5]) + ("…" if len(dirty) > 5 else "")
        raise CloseError(f"先提交或处理这些改动，再收尾：{listed}")


def _closed_commit(project: Path, feature: str) -> str | None:
    """The newest commit on this history that is `close <feature>` and deleted the card, else None.

    The subject alone can be anybody's; only a commit that took the card away closed the feature. Every
    commit is looked at, not the ones a path-limited `git log` keeps: that drops the branch side of a merge.
    """
    for line in _git(project, "log", "--format=%H%x09%s", "HEAD").stdout.splitlines():
        sha, _, subject = line.partition("\t")
        match = ledger.CLOSE_SUBJECT.match(subject)
        if match and match.group(1) == feature and _git(
                project, "diff-tree", "-r", "--no-commit-id", "--name-only", "--diff-filter=D", sha,
                "--", f"specs/{feature}/spec.md").stdout.strip():
            return sha
    return None


def _already_closed(project: Path, feature: str) -> str:
    """The close commit a rerun picks up from when the card is gone; CloseError when there is none."""
    card_dir = f"specs/{feature}"
    missing = f"找不到卡：{card_dir}/spec.md（目录名的大小写也要一致）"
    if _git(project, "cat-file", "-e", f"HEAD:./{card_dir}/spec.md").returncode == 0:
        # HEAD still has the card, so this feature is not closed, whatever an older `close <feature>` of the
        # same name says: a close died between `git rm` and `git commit`, or the card was deleted by hand.
        # `./`: the path is the project's, and the project may be a folder of a larger repository.
        raise CloseError(f"{missing}。HEAD 里还有这张卡，它的删除没有提交（上一次收尾可能中断了）：运行 "
                         f"git reset -q HEAD -- {card_dir} 和 git checkout HEAD -- {card_dir} 恢复，再重跑")
    closed = _closed_commit(project, feature)
    if not closed:
        raise CloseError(f"{missing}；当前历史里也没有删掉这张卡的 close {feature} 提交")
    return closed


def _uncovered(project: Path, identifiers: list[str]) -> list[str]:
    spec = load_script("spec_check")
    coverage = spec._coverage(project, spec._ignores(project, [], None, True))
    return [identifier for identifier in identifiers
            if identifier not in coverage.tested and identifier not in coverage.demonstrations]


def _check(project: Path, base: str | None):
    try:
        return ledger.check(project, base)[0]
    except ledger.LedgerError as error:
        raise CloseError(str(error)) from error
    except OSError as error:
        # Only the reason: the message of an OSError names the file it failed on, and that may be the ledger's.
        raise CloseError(f"账本核对没做成：{ledger.why_failed(error)}（不显示出错的文件，免得带出账本路径；"
                         "请人工检查账本目录和权限）。没有收尾") from error


def _ledger_side(project: Path) -> str | None:
    """Who keeps the ledger: "dev" (this side writes and checks it), "human", or None when none is configured."""
    if not ledger.configured(project):
        return None
    return "human" if ledger.human_side(project) else "dev"


def _baseline(project: Path, base: str | None) -> tuple[tuple[str, str] | None, str | None]:
    """(base name and fork point if there is a base, why the feature's requirement changes cannot be told)."""
    try:
        compared = context.merge_base(project, base)
    except context.ContextError as error:
        raise CloseError(str(error)) from error
    return compared, ledger.uncomparable(project, compared)


def _commit_close(project: Path, feature: str, summary: str, review: str | None, checks: str) -> str:
    card_dir = f"specs/{feature}"
    removed = _git(project, "rm", "-r", "-q", "--", card_dir)
    if removed.returncode != 0:
        raise CloseError(f"git rm 失败，没有收尾：{(removed.stderr or removed.stdout).strip()}")
    message = ["-m", f"close {feature}", "-m", f"为什么：{summary}"]
    if review:
        message += ["-m", f"审核：{review}"]
    message += ["-m", f"验证：devcircuit close（{checks} 通过）"]
    committed = _git(project, "commit", "-q", *message)
    if committed.returncode != 0:
        detail = (committed.stderr or committed.stdout).strip()
        reset = _git(project, "reset", "-q", "HEAD", "--", card_dir)
        restored = _git(project, "checkout", "-q", "HEAD", "--", card_dir)
        if reset.returncode == 0 and restored.returncode == 0:
            raise CloseError(f"提交失败，卡已恢复：{detail}")
        raise CloseError(f"提交失败，卡没能自动恢复：运行 git reset -q HEAD -- {card_dir} 和 "
                         f"git checkout HEAD -- {card_dir} 恢复。原因：{detail}")
    return _git(project, "rev-parse", "HEAD").stdout.strip()


def _where_next(project: Path, compared: tuple[str, str] | None) -> str:
    """What to do with the close commit, by the branch it is really on."""
    branch = _git(project, "symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
    if not branch:
        return "当前是游离的 HEAD，不在任何分支上：按 AGENTS.md 的分支约定处理这个提交。"
    if compared and compared[0] == branch:
        return f"当前就在 {branch} 上，没有要合并的分支。"
    return f"按 AGENTS.md 的分支约定合并 {branch}。"


def _record(project: Path, feature: str, summary: str, review: str | None, base: str | None, head: str,
            rerun: bool) -> tuple[str, str | None, int]:
    """Write the close record and check again: (the 账本核对 line, what a rerun did, exit code).

    The close commit exists by now, so nothing here may end the command: the report has to come out, and say
    that the project is closed. On a rerun the record is written only if the ledger does not have it.
    """
    did, written = None, False
    try:
        if rerun and ledger.close_recorded(project, feature, head):
            committed, did = ledger.settle(project, feature), "账本里已经有这个提交的收尾记录，没有重复写。"
        else:
            _, committed = ledger.add(project, feature, "close", summary, review=review, commit=head)
            did = "补写了账本的收尾记录。"
        written = True
        findings = ledger.check(project, base)[0]
    except (OSError, ledger.LedgerError) as error:
        # Only the reason: an OSError carries the path of the file it failed on, and that is the ledger's.
        why = ledger.why_failed(error) if isinstance(error, OSError) else str(error)
        what = "收尾记录已写入，但再核对没做成" if written else "收尾记录没写成"
        return (f"账本核对：{what}：{why}。项目已收尾，不用回退；账本修好后重跑同一条 devcircuit close 命令，"
                "它只补记录"), None, 1
    line = "账本核对：通过" if not findings else "账本核对：" + "；".join(finding.text for finding in findings)
    if not committed:
        line += ("；收尾记录已写入，但账本仓库没有提交成功，请人工检查，修好后重跑同一条 devcircuit close 命令，"
                 "它只补提交")
    return line, did, int(not committed or any(finding.feature in (feature, None) for finding in findings))


def _deliver(project: Path, feature: str, summary: str, review: str | None, base: str | None, head: str,
             side: str | None, uncompared: str | None, changes, lead: list[str], rerun: bool, out) -> int:
    """Everything after the close commit: the ledger step and the report. Shared by the first run and a rerun."""
    added, rewritten, removed = changes
    exit_code = 0
    if side == "dev":
        ledger_line, did, exit_code = _record(project, feature, summary, review, base, head, rerun)
        if rerun and did:
            lead.append(did)
    elif side == "human":
        ledger_line = "账本核对：账本在 human 一侧，由 human 补记和核对"
        print(f"账本在 human 一侧：请在账本一侧运行 devcircuit ledger add --feature {feature} --kind close "
              f"--commit {head} --decision \"{summary}\"" + (f" --review \"{review}\"" if review else "")
              + "，再运行 devcircuit ledger check。", file=out)
    else:
        ledger_line = "账本核对：没有配置账本"

    listed = "；".join(f"{label}：{'、'.join(items)}" for label, items in
                      (("新增", added), ("改写", rewritten), ("删除", removed)) if items)
    potential = []
    if uncompared:
        # Not the same as "nothing changed, nothing uncovered": say that it was not looked at, and why.
        potential.append("要求变化和未覆盖的要求没比" + ("，账本的 removal-unrecorded 也没查" if side == "dev" else "")
                         + f"：{uncompared}")
    uncovered = _uncovered(project, [*added, *rewritten])
    if uncovered:
        potential.append("未覆盖的要求：" + "、".join(uncovered))
    potential.append(ledger_line)
    backlog = project / "specs" / "backlog.md"
    pending = sum(1 for line in backlog.read_text(encoding="utf-8-sig").splitlines()
                  if line.startswith("- ")) if backlog.is_file() else 0

    for line in lead:
        print(line, file=out)
    print("交付报告骨架（补全“怎么验收”“潜在问题”“下一步建议”后回复用户）：", file=out)
    print(f"交付：{feature}", file=out)
    print(f"做了什么：{summary}" + (f"（{listed}）" if listed else ""), file=out)
    print("怎么验收：…", file=out)
    print(f"审核：{review or '…'}", file=out)
    print("潜在问题：" + "；".join(potential), file=out)
    print(f"下一步建议：…（specs/backlog.md 现有 {pending} 条）", file=out)
    return exit_code


def run(project: Path, feature: str, summary: str, review: str | None, base: str | None, out) -> int:
    if not ledger.valid_feature(feature):
        raise CloseError(f"功能名不合规：{feature}（{ledger.FEATURE_RULE}）")
    if not summary.strip():
        raise CloseError("--summary 不能为空：一句话说明交付了什么")

    if not _has_card(project, feature):
        # The card is gone. If a close commit took it, this is a rerun: the project stays as it is.
        head = _already_closed(project, feature)
        side = _ledger_side(project)
        compared, uncompared = _baseline(project, base)
        changes = ([], [], []) if uncompared else context.requirement_changes(project, compared[1])
        # Only the name ties this run to that commit, and the name may have been closed before: the card of
        # this round is on another branch, or its close commit was squashed away. The commit's date is what
        # shows that; the committer's, so a rebased close counts from when it came onto this history.
        made = _git(project, "show", "-s", "--date=short", "--format=%cd", head).stdout.strip()
        lead = [f"已经收尾过：{feature}（提交 {head[:7]}" + (f"，{made}" if made else "")
                + "）。卡已经删了，这次不动项目，只做账本这一步。",
                f"认的是当前历史里最新的 close {feature} 提交；日期对不上，就是同名功能以前那次的收尾，这一次的没有处理。"]
        return _deliver(project, feature, summary, review, base, head, side, uncompared, changes, lead, True, out)

    _clean_tree(project)

    print("== doc_guard / spec_check ==", file=out)
    # A list, not a generator handed to any(): both run, so one round shows everything there is to fix.
    failed = [name for name in ("doc_guard", "spec_check")
              if int(load_script(name).main(["--root", str(project)]))]
    if failed:
        print("检查没过，没有收尾：按上面的输出修好、提交后再跑 devcircuit close。", file=out)
        return 1

    side = _ledger_side(project)
    if side == "dev":
        blocking = [finding for finding in _check(project, base) if finding.feature in (feature, None)]
        if blocking:
            for finding in blocking:
                print(finding.text, file=out)
            print("账本和本功能不一致，没有收尾：原因清楚的用 devcircuit ledger add --kind correction 补记，"
                  "不清楚的问用户。", file=out)
            return 1
    elif side == "human":
        print("账本在 human 一侧：跳过账本核对和收尾记录。", file=out)
    else:
        print("提醒：没有配置账本，跳过账本核对和收尾记录。", file=out)

    compared, uncompared = _baseline(project, base)
    changes = ([], [], []) if uncompared else context.requirement_changes(project, compared[1])
    where_next = _where_next(project, compared)

    checks = "doc_guard、spec_check" + ("、ledger check" if side == "dev" else "")
    head = _commit_close(project, feature, summary, review, checks)
    card_dir = project / "specs" / feature
    leftovers = sorted(path.relative_to(project).as_posix() for path in card_dir.rglob("*")
                       if path.is_file()) if card_dir.is_dir() else []

    lead = [f"已收尾：{feature}（提交 {head[:7]}）。{where_next}"]
    if leftovers:
        lead.append(f"specs/{feature}/ 里还留着没被 git 跟踪的文件，没有删：{'、'.join(leftovers)}")
    return _deliver(project, feature, summary, review, base, head, side, uncompared, changes, lead, False, out)
