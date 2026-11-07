"""Turn one or more `run_open_ab.py` result directories into a table.

    python bench/summarize.py bench/out/open-20260101-120000
    python bench/summarize.py bench/out/open-*        # pool several sessions

The point of pooling is n>1: report the median and the spread per side, and say
which side won each paired run instead of pretending one number is the truth.
A run's score is the median of every judgment of its artifacts (the run's own
judges and any re-judges), with and without the closeout dimension.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import statistics
import sys
from pathlib import Path

FIELDS = (
    ("seconds", "墙钟时间（秒）"),
    ("cost", "模型成本（$，含子 agent）"),
    ("subagent_cost", "其中子 agent（$）"),
    ("input", "输入 tokens"),
    ("output", "输出 tokens"),
    ("cache_read", "缓存读取 tokens"),
    ("turns", "assistant 轮次"),
    ("tests", "项目测试通过数"),
    ("probes", "错误路径探针通过数（9 项）"),
    ("commits", "提交数"),
    ("uncommitted", "未提交文件数"),
    ("docs_lines", "留存文档行数"),
)
SIDES = ("dev", "openspec")
FORMAL_RUNS = 5

PASSED = re.compile(r"(\d+) passed")


def side_metrics(record: dict | None) -> dict | None:
    if not record:
        return None
    tests = record.get("tests") or {}
    summary = tests.get("summary") or ""
    if not isinstance(summary, str):  # older harness versions could store a list here
        summary = " ".join(map(str, summary))
    match = PASSED.search(summary + " " + (tests.get("stdout") or ""))
    diff = record.get("diff") or {}
    docs = record.get("docs") or {}
    return {
        "seconds": record.get("seconds"),
        "cost": record.get("cost"),
        "subagent_cost": (record.get("subagents") or {}).get("cost"),
        "input": record.get("input"),
        "output": record.get("output"),
        "cache_read": record.get("cache_read"),
        "turns": record.get("turns"),
        "tests": int(match.group(1)) if match else None,
        "probes": (record.get("probes") or {}).get("passed"),
        "commits": len(diff.get("commits") or []),
        "uncommitted": len(diff.get("status") or []),
        "docs_lines": (docs.get("requirements_lines") or 0) + (docs.get("openspec_spec_lines") or 0),
    }


def load(directories: list[Path]) -> list[dict]:
    runs = []
    for directory in directories:
        payload = json.loads((directory / "runs.json").read_text(encoding="utf-8"))
        for run in payload.get("runs") or []:
            run["_source"] = str(directory)
            run["_meta"] = {key: payload.get(key) for key in ("model", "thinking", "judge_model", "seed",
                                                              "stale_skill_copies")}
            run_dir = directory / f"run-{run['index'] + 1:02d}"
            run["_rejudges"] = [json.loads(path.read_text(encoding="utf-8"))
                                for path in sorted(run_dir.glob("rejudge-*.json"))]
            runs.append(run)
    return runs


DIMENSIONS = (("product", "产品用途"), ("correctness", "正确性"), ("tests", "测试"),
              ("docs", "设计与文档"), ("code", "代码质量"), ("closeout", "收尾"))


def own_judges(run: dict) -> list[dict]:
    return [item for item in [run.get("judge"), *(run.get("judge_repeats") or [])] if item]


def judgments(run: dict) -> list[dict]:
    """Every parsed judgment of the run's artifacts: its own judges and later re-judges."""
    return [item for item in own_judges(run) + run.get("_rejudges", []) if item.get("parsed")]


def score(item: dict, side: str, quality: bool = False) -> int:
    card = item["result"][side]
    return card["total"] - card["closeout"] if quality else card["total"]


def run_score(run: dict, side: str, quality: bool = False) -> float:
    return statistics.median(score(item, side, quality) for item in judgments(run))


def mean(values: list[float]) -> str:
    return f"{statistics.mean(values):+.2f}" if values else "—"


def span(values: list[int]) -> str:
    low, high = min(values), max(values)
    return str(low) if low == high else f"{low}–{high}"


def caveats(runs: list[dict]) -> list[str]:
    """What the reader has to know before trusting the scores."""
    notes = []
    if len(runs) < FORMAL_RUNS:
        notes.append(f"只有 {len(runs)} 轮：只描述这几轮的分布，不下结论；正式结论至少 {FORMAL_RUNS} 轮。")
    items = [item for run in runs for item in judgments(run)]
    same = [item for run in runs for item in judgments(run)
            if item.get("model") and item.get("model") == (run.get("_meta") or {}).get("model")]
    if same:
        notes.append(f"{len(items)} 次评审里有 {len(same)} 次的评委与被测是同一个模型，可能偏向自己写法；"
                     "换评委用 `--judge-provider` / `--judge-model`，或重评时换模型。")
    versions = {item.get("rubric") for item in items}
    if len(versions) > 1:
        notes.append(f"这些评审用了 {len(versions)} 个版本的 rubric 与评审说明（未记录版本的算一个），"
                     "总分不完全可比；看各维度和探针。")
    stale = sorted({path for run in runs for path in (run.get("_meta") or {}).get("stale_skill_copies") or []})
    if stale:
        notes.append(f"跑的时候本机装着和被测版本不同的技能（{'；'.join(stale)}），子 agent 可能读到旧规则。")
    single = [run for run in runs if len(judgments(run)) == 1]
    if single:
        notes.append(f"{len(single)} 轮只有 1 次评审：单次评审分辨不了 ±3 分，只作定性参考。")
    return notes


def reliability(runs: list[dict]) -> list[str]:
    """How much the score moves when only the judgment changes."""
    lines: list[str] = []
    repeated = [run for run in runs if len(judgments(run)) >= 2]
    if not repeated:
        return lines
    lines += ["", "### 评委信度：同一份产物的多次评审", "",
              "| 轮 | 评审次数 | dev 各次总分 | OpenSpec 各次总分 | 差值（dev−OpenSpec） |",
              "|---|---:|---|---|---|"]
    for run in repeated:
        items = judgments(run)
        dev = [score(item, "dev") for item in items]
        other = [score(item, "openspec") for item in items]
        deltas = [left - right for left, right in zip(dev, other)]
        lines.append(f"| {Path(run['_source']).name} 第 {run['index'] + 1} 轮 | {len(items)} | "
                     f"{', '.join(map(str, dev))} | {', '.join(map(str, other))} | "
                     f"{min(deltas):+d} 到 {max(deltas):+d} |")

    for run in repeated:
        items = judgments(run)
        if len(items) < 4:
            continue
        lines += ["", f"#### 第 {run['index'] + 1} 轮的 {len(items)} 次评审", "",
                  "| 评审 | 评委 | A 是 | EVIDENCE | dev | OpenSpec | 差值（dev−OpenSpec） |",
                  "|---|---|---|---|---:|---:|---:|"]
        deltas, by_position, by_evidence = [], {"dev": [], "openspec": []}, {True: [], False: []}
        for item in items:
            dev, other = score(item, "dev"), score(item, "openspec")
            delta = dev - other
            deltas.append(delta)
            by_position[item["mapping"]["A"]].append(delta)
            by_evidence[bool(item.get("evidence"))].append(delta)
            lines.append(f"| {item.get('tag', 'judge')} | {item.get('model') or '—'} | {item['mapping']['A']} | "
                         f"{'有' if item.get('evidence') else '无'} | {dev} | {other} | {delta:+d} |")
        lines += ["",
                  f"- 总分：dev {describe([score(item, 'dev') for item in items])}，"
                  f"OpenSpec {describe([score(item, 'openspec') for item in items])}；"
                  f"差值 {min(deltas):+d} 到 {max(deltas):+d}，均值 {mean(deltas)}。",
                  f"- 位置：dev 在 A 时差值均值 {mean(by_position['dev'])}（{len(by_position['dev'])} 次），"
                  f"在 B 时 {mean(by_position['openspec'])}（{len(by_position['openspec'])} 次）。",
                  f"- EVIDENCE：有时差值均值 {mean(by_evidence[True])}（{len(by_evidence[True])} 次），"
                  f"无时 {mean(by_evidence[False])}（{len(by_evidence[False])} 次）。"]
        spread = []
        for key, name in DIMENSIONS:
            dev_values = [item["result"]["dev"][key] for item in items]
            other_values = [item["result"]["openspec"][key] for item in items]
            spread.append(f"{name} dev {span(dev_values)} / OpenSpec {span(other_values)}")
        lines.append("- 各维度范围：" + "；".join(spread) + "。")
    return lines


def describe(values: list[float]) -> str:
    numbers = [value for value in values if isinstance(value, (int, float))]
    if not numbers:
        return "—"
    if len(numbers) == 1:
        return f"{numbers[0]:,.6g}" if isinstance(numbers[0], float) else f"{numbers[0]:,}"
    median = statistics.median(numbers)
    low, high = min(numbers), max(numbers)
    if any(isinstance(value, float) for value in (median, low, high)):
        digits = 4 if max(abs(low), abs(high)) < 1 else 1
        render = lambda value: f"{value:,.{digits}f}"  # noqa: E731
    else:
        render = lambda value: f"{value:,}"  # noqa: E731
    return f"{render(median)}（{render(low)}–{render(high)}）"


def build(runs: list[dict]) -> tuple[str, dict]:
    per_side = {side: [side_metrics(run.get(side)) for run in runs] for side in SIDES}
    lines: list[str] = []
    meta = runs[0].get("_meta") if runs else {}
    lines.append("# 开放 A/B 汇总\n")
    lines.append(f"- 轮数：{len(runs)}")
    if meta:
        lines.append(f"- 模型：{meta.get('model')}（thinking {meta.get('thinking')}）")
        lines.append(f"- 盲评模型：{meta.get('judge_model') or '未启用'}")
    lines.append(f"- 来源：{', '.join(sorted({run['_source'] for run in runs}))}")
    lines.append("")
    lines.append("每轮的 A/B 映射与先后顺序都是随机的；中位数和区间描述分布，不是显著性检验。")
    notes = caveats(runs)
    if notes:
        lines.append("")
        lines += [f"> {note}" for note in notes]
    lines.append("")

    lines.append("| 指标 | dev-circuit-ultra | OpenSpec | 配对差值中位数 |")
    lines.append("|---|---:|---:|---:|")
    summary: dict = {"runs": len(runs), "sides": {}, "paired": {}, "caveats": notes}
    for key, label in FIELDS:
        values = {side: [m[key] for m in per_side[side] if m and m.get(key) is not None] for side in SIDES}
        if key == "probes" and not any(values.values()):
            continue
        summary["sides"][key] = {side: values[side] for side in SIDES}
        deltas = []
        for left, right in zip(per_side["dev"], per_side["openspec"]):
            if left and right and left.get(key) is not None and right.get(key) is not None:
                deltas.append(left[key] - right[key])
        summary["paired"][key] = deltas
        lines.append(f"| {label} | {describe(values['dev'])} | {describe(values['openspec'])} | {describe(deltas)} |")

    scored = [run for run in runs if judgments(run)]
    if scored:
        counts = sorted({len(judgments(run)) for run in scored})
        count = str(counts[0]) if len(counts) == 1 else f"{counts[0]}–{counts[-1]}"
        totals = {side: [run_score(run, side) for run in scored] for side in SIDES}
        quality = {side: [run_score(run, side, quality=True) for run in scored] for side in SIDES}
        pairs = list(zip(totals["dev"], totals["openspec"]))
        wins = sum(1 for d, o in pairs if d > o)
        ties = sum(1 for d, o in pairs if d == o)
        losses = len(pairs) - wins - ties
        lines += ["",
                  f"| 盲评（每轮取 {count} 次评审的中位数） | dev-circuit-ultra | OpenSpec |",
                  "|---|---:|---:|",
                  f"| 总分（30） | {describe(totals['dev'])} | {describe(totals['openspec'])} |",
                  f"| 不计收尾（25） | {describe(quality['dev'])} | {describe(quality['openspec'])} |",
                  "",
                  f"逐轮胜负（按总分中位数）：dev 胜 {wins}、平 {ties}、OpenSpec 胜 {losses}（共 {len(scored)} 轮）。"]
        summary["judge"] = {"dev": totals["dev"], "openspec": totals["openspec"], "quality": quality,
                            "judgments": [len(judgments(run)) for run in scored],
                            "wins": wins, "ties": ties, "losses": losses}
    else:
        lines.append("")
        lines.append("这一批没有可用的盲评分数（`--no-judge` 或解析失败），只有运行指标。")

    if any(own_judges(run) for run in runs):
        judge_cost = sum((item.get("usage") or {}).get("cost") or 0
                         for run in runs for item in own_judges(run))
        session_cost = sum((run.get(side) or {}).get("cost") or 0 for run in runs for side in SIDES)
        rejudge_cost = sum((item.get("usage") or {}).get("cost") or 0
                           for run in runs for item in run.get("_rejudges", []))
        lines.append("")
        lines.append(f"盲评成本（$）：{judge_cost:,.4f}（不按侧分摊）；"
                     f"两侧会话合计 {session_cost:,.4f}；本轮总计 {session_cost + judge_cost:,.4f}。")
        if rejudge_cost:
            lines.append(f"重评另花 {rejudge_cost:,.4f}。")
        summary["cost"] = {"sessions": session_cost, "judge": judge_cost,
                           "rejudge": rejudge_cost, "total": session_cost + judge_cost}

    lines += reliability(runs)

    failures = [run["index"] for run in runs
                if (run.get("dev") or {}).get("timeout") or (run.get("openspec") or {}).get("timeout")]
    if failures:
        lines.append("")
        lines.append(f"注意：第 {', '.join(str(index + 1) for index in failures)} 轮有会话超时，指标不完整。")

    return "\n".join(lines) + "\n", summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise open A/B runs")
    parser.add_argument("directories", nargs="+", help="run_open_ab.py 的输出目录（可多个）")
    parser.add_argument("--out", default=None, help="同时把 summary.md 写到哪里")
    args = parser.parse_args(argv)

    directories = []
    for item in args.directories:
        # PowerShell and cmd hand the pattern over unexpanded; matches without runs.json are skipped.
        matches = sorted(glob.glob(item)) if not Path(item).exists() and any(c in item for c in "*?[") else []
        directories += [Path(match) for match in matches if (Path(match) / "runs.json").is_file()] or [Path(item)]
    missing = [str(item) for item in directories if not (item / "runs.json").is_file()]
    if missing:
        print(f"找不到 runs.json：{', '.join(missing)}", file=sys.stderr)
        return 2

    runs = load(directories)
    if not runs:
        print("这些目录里没有任何一轮。", file=sys.stderr)
        return 1

    text, summary = build(runs)
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)
    destination = Path(args.out) if args.out else directories[0] / "summary.md"
    destination.write_text(text, encoding="utf-8")
    destination.with_suffix(".json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"写到 {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
