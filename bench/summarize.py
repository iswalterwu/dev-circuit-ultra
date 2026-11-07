"""Turn one or more `run_open_ab.py` result directories into a table.

    python bench/summarize.py bench/out/open-20260101-120000
    python bench/summarize.py bench/out/open-*        # pool several sessions

The point of pooling is n>1: report the median and the spread per side, and say
which side won each paired run instead of pretending one number is the truth.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

FIELDS = (
    ("seconds", "墙钟时间（秒）"),
    ("cost", "模型成本（$）"),
    ("input", "输入 tokens"),
    ("output", "输出 tokens"),
    ("cache_read", "缓存读取 tokens"),
    ("turns", "assistant 轮次"),
    ("tests", "项目测试通过数"),
    ("commits", "提交数"),
    ("uncommitted", "未提交文件数"),
    ("docs_lines", "留存文档行数"),
)

PASSED = re.compile(r"(\d+) passed")


def side_metrics(record: dict | None) -> dict | None:
    if not record:
        return None
    tests = record.get("tests") or {}
    match = PASSED.search((tests.get("summary") or "") + " " + (tests.get("stdout") or ""))
    diff = record.get("diff") or {}
    docs = record.get("docs") or {}
    return {
        "seconds": record.get("seconds"),
        "cost": record.get("cost"),
        "input": record.get("input"),
        "output": record.get("output"),
        "cache_read": record.get("cache_read"),
        "turns": record.get("turns"),
        "tests": int(match.group(1)) if match else None,
        "commits": len(diff.get("commits") or []),
        "uncommitted": len(diff.get("status") or []),
        "docs_lines": (docs.get("requirements_lines") or 0) + (docs.get("openspec_spec_lines") or 0),
    }


def judge_total(run: dict, side: str) -> int | None:
    judge = run.get("judge") or {}
    if not judge.get("parsed"):
        return None
    card = (judge.get("result") or {}).get(side)
    return card.get("total") if isinstance(card, dict) else None


def load(directories: list[Path]) -> list[dict]:
    runs = []
    for directory in directories:
        payload = json.loads((directory / "runs.json").read_text(encoding="utf-8"))
        for run in payload.get("runs") or []:
            run["_source"] = str(directory)
            run["_meta"] = {key: payload.get(key) for key in ("model", "thinking", "judge_model", "seed")}
            runs.append(run)
    return runs


def describe(values: list[float]) -> str:
    numbers = [value for value in values if isinstance(value, (int, float))]
    if not numbers:
        return "—"
    if len(numbers) == 1:
        return f"{numbers[0]:,.6g}" if isinstance(numbers[0], float) else f"{numbers[0]:,}"
    median = statistics.median(numbers)
    low, high = min(numbers), max(numbers)
    render = (lambda value: f"{value:,.2f}") if isinstance(median, float) else (lambda value: f"{value:,}")
    return f"{render(median)}（{render(low)}–{render(high)}）"


def build(runs: list[dict]) -> tuple[str, dict]:
    sides = ("dev", "openspec")
    per_side = {side: [side_metrics(run.get(side)) for run in runs] for side in sides}
    lines: list[str] = []
    meta = runs[0].get("_meta") if runs else {}
    lines.append("# 开放 A/B 汇总\n")
    lines.append(f"- 轮数：{len(runs)}")
    if meta:
        lines.append(f"- 模型：{meta.get('model')}（thinking {meta.get('thinking')}）")
        lines.append(f"- 盲评模型：{meta.get('judge_model') or '未启用'}")
    lines.append(f"- 来源：{', '.join(sorted({run['_source'] for run in runs}))}")
    lines.append("")
    lines.append("n>1 只说明这几轮的分布，不构成统计结论；每轮的 A/B 映射与顺序都是随机的。\n")

    lines.append("| 指标 | dev-circuit-ultra | OpenSpec | 配对差值中位数 |")
    lines.append("|---|---:|---:|---:|")
    summary: dict = {"runs": len(runs), "sides": {}, "paired": {}}
    for key, label in FIELDS:
        values = {side: [m[key] for m in per_side[side] if m and m.get(key) is not None] for side in sides}
        summary["sides"][key] = {side: values[side] for side in sides}
        deltas = []
        for left, right in zip(per_side["dev"], per_side["openspec"]):
            if left and right and left.get(key) is not None and right.get(key) is not None:
                deltas.append(left[key] - right[key])
        summary["paired"][key] = deltas
        lines.append(f"| {label} | {describe(values['dev'])} | {describe(values['openspec'])} | {describe(deltas)} |")

    judge_rows = [(judge_total(run, "dev"), judge_total(run, "openspec")) for run in runs]
    scored = [row for row in judge_rows if row[0] is not None and row[1] is not None]
    if scored:
        dev_scores = [row[0] for row in scored]
        os_scores = [row[1] for row in scored]
        wins = sum(1 for d, o in scored if d > o)
        ties = sum(1 for d, o in scored if d == o)
        losses = len(scored) - wins - ties
        lines.append("")
        lines.append("| 盲评 | dev-circuit-ultra | OpenSpec |")
        lines.append("|---|---:|---:|")
        lines.append(f"| 总分（30） | {describe(dev_scores)} | {describe(os_scores)} |")
        lines.append("")
        lines.append(f"逐轮胜负：dev 胜 {wins}、平 {ties}、OpenSpec 胜 {losses}（共 {len(scored)} 轮）。")
        summary["judge"] = {"dev": dev_scores, "openspec": os_scores,
                            "wins": wins, "ties": ties, "losses": losses}
    else:
        lines.append("")
        lines.append("这一批没有可用的盲评分数（`--no-judge` 或解析失败），只有运行指标。")

    judge_usage = [run["judge"]["usage"] for run in runs
                   if (run.get("judge") or {}).get("usage")]
    if judge_usage:
        judge_cost = sum(item.get("cost") or 0 for item in judge_usage)
        session_cost = sum((run.get(side) or {}).get("cost") or 0
                           for run in runs for side in sides)
        lines.append("")
        lines.append(f"盲评成本（$）：{judge_cost:,.4f}（每轮一次，不按侧分摊）；"
                     f"两侧会话合计 {session_cost:,.4f}；本轮总计 {session_cost + judge_cost:,.4f}。")
        summary["cost"] = {"sessions": session_cost, "judge": judge_cost,
                           "total": session_cost + judge_cost}

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

    directories = [Path(item) for item in args.directories]
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
    (destination.parent / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"写到 {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
