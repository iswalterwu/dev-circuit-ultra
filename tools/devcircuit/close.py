"""`devcircuit close <feature>`: the closing bookkeeping as one command.

Order: full checks -> ledger check -> delete the card and commit `close <feature>` -> close record
-> ledger check again -> a delivery-report skeleton with the mechanical parts filled in.
Nothing changes when a check before the commit fails. Ledger gaps of other features are reported,
not blocking; only this feature and this branch must be consistent.
"""

import os
import subprocess
from pathlib import Path

from . import context, ledger
from ._loader import load_script


class CloseError(RuntimeError):
    """A precondition failed; the message is meant for the user."""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _preconditions(project: Path, feature: str, summary: str) -> None:
    if not ledger.valid_feature(feature):
        raise CloseError(f"功能名不合规：{feature}（{ledger.FEATURE_RULE}）")
    if not summary.strip():
        raise CloseError("--summary 不能为空：一句话说明交付了什么")
    specs = project / "specs"
    names = set(os.listdir(specs)) if specs.is_dir() else set()
    if feature not in names or not (specs / feature / "spec.md").is_file():
        raise CloseError(f"找不到卡：specs/{feature}/spec.md（目录名的大小写也要一致）")
    status = _git(project, "status", "--porcelain", "--untracked-files=all")
    if status.returncode != 0:
        raise CloseError("close 要在项目的 git 仓库里跑")
    dirty = [line[3:] for line in status.stdout.splitlines() if line.strip()]
    if dirty:
        listed = "、".join(dirty[:5]) + ("…" if len(dirty) > 5 else "")
        raise CloseError(f"先提交或处理这些改动，再收尾：{listed}")


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


def run(project: Path, feature: str, summary: str, review: str | None, base: str | None, out) -> int:
    _preconditions(project, feature, summary)

    print("== doc_guard / spec_check ==", file=out)
    if any(int(load_script(name).main(["--root", str(project)])) for name in ("doc_guard", "spec_check")):
        print("检查没过，没有收尾：按上面的输出修好、提交后再跑 devcircuit close。", file=out)
        return 1

    human = ledger.configured(project) and ledger.human_side(project)
    has_ledger = ledger.configured(project) and not human
    if has_ledger:
        blocking = [finding for finding in _check(project, base) if finding.feature in (feature, None)]
        if blocking:
            for finding in blocking:
                print(finding.text, file=out)
            print("账本和本功能不一致，没有收尾：原因清楚的用 devcircuit ledger add --kind correction 补记，"
                  "不清楚的问用户。", file=out)
            return 1
    elif human:
        print("账本在 human 一侧：跳过账本核对和收尾记录。", file=out)
    else:
        print("提醒：没有配置账本，跳过账本核对和收尾记录。", file=out)

    try:
        compared = context.merge_base(project, base)
    except context.ContextError as error:
        raise CloseError(str(error)) from error
    added, rewritten, removed = context.requirement_changes(project, compared[1]) if compared else ([], [], [])

    checks = "doc_guard、spec_check" + ("、ledger check" if has_ledger else "")
    head = _commit_close(project, feature, summary, review, checks)
    card_dir = project / "specs" / feature
    leftovers = sorted(path.relative_to(project).as_posix() for path in card_dir.rglob("*")
                       if path.is_file()) if card_dir.is_dir() else []

    exit_code = 0
    if has_ledger:
        _, recorded = ledger.add(project, feature, "close", summary, review=review, commit=head)
        findings = _check(project, base)
        ledger_line = ("账本核对：通过" if not findings
                       else "账本核对：" + "；".join(finding.text for finding in findings))
        if not recorded:
            ledger_line += "；收尾记录已写入，但账本仓库没有提交成功，请人工检查"
        if not recorded or any(finding.feature in (feature, None) for finding in findings):
            exit_code = 1
    elif human:
        ledger_line = "账本核对：账本在 human 一侧，由 human 补记和核对"
        print(f"账本在 human 一侧：请在账本一侧运行 devcircuit ledger add --feature {feature} --kind close "
              f"--commit {head} --decision \"{summary}\"，再运行 devcircuit ledger check。", file=out)
    else:
        ledger_line = "账本核对：没有配置账本"

    changes = "；".join(f"{label}：{'、'.join(items)}" for label, items in
                       (("新增", added), ("改写", rewritten), ("删除", removed)) if items)
    potential = []
    uncovered = _uncovered(project, [*added, *rewritten])
    if uncovered:
        potential.append("未覆盖的要求：" + "、".join(uncovered))
    potential.append(ledger_line)
    backlog = project / "specs" / "backlog.md"
    pending = sum(1 for line in backlog.read_text(encoding="utf-8-sig").splitlines()
                  if line.startswith("- ")) if backlog.is_file() else 0

    print(f"已收尾：{feature}（提交 {head[:7]}）。按 AGENTS.md 的分支约定合并 feat/{feature}。", file=out)
    if leftovers:
        print(f"specs/{feature}/ 里还留着没被 git 跟踪的文件，没有删：{'、'.join(leftovers)}", file=out)
    print("交付报告骨架（补全“怎么验收”“潜在问题”“下一步建议”后回复用户）：", file=out)
    print(f"交付：{feature}", file=out)
    print(f"做了什么：{summary}" + (f"（{changes}）" if changes else ""), file=out)
    print("怎么验收：…", file=out)
    print(f"审核：{review or '…'}", file=out)
    print("潜在问题：" + "；".join(potential), file=out)
    print(f"下一步建议：…（specs/backlog.md 现有 {pending} 条）", file=out)
    return exit_code
