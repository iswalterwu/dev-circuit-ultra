"""Run the open-ended A/B: one problem, one prompt, no prescribed workflow.

Both repos start from the same fixture + skeleton and a neutral AGENTS.md.
Each skill gets one end-to-end session per run. There is no review budget, no
slice count, no hidden acceptance suite and no required command shape.

    python bench/open/run_open_ab.py --runs 3            # three paired runs
    python bench/open/run_open_ab.py --dry-run           # print the plan only
    python bench/open/run_open_ab.py --no-judge          # metrics only

Every run is recorded under --out (default: bench/out/open-<timestamp>/):
`run-01/dev.json`, `run-01/openspec.json`, `run-01/judge/` and an aggregate
`runs.json`. Feed the directory to `bench/summarize.py` for the median table.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent

from _harness import (  # noqa: E402
    BASE_TAG,
    anonymize,
    changed,
    copy_eval_tree,
    fill,
    git,
    judge_prompt,
    parse_scores,
    pi_command,
    pytest_summary,
    read_usage,
    reset,
    run_process,
    setup_pair,
    stage_judge,
    without_harness,
)

SKILLS = BENCH.parent / "skills" / "dev-circuit-ultra"
BENCH_OPEN = BENCH / "open"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def session_command(pi: str, session_dir: Path, skills: list[Path],
                    provider: str, model: str, thinking: str) -> list[str]:
    command = [
        pi,
        "-p",
        "--provider", provider,
        "--model", model,
        "--thinking", thinking,
        "--approve",
        "--no-mcp",
        "--no-skills",
        "--no-prompt-templates",
        "--session-dir", str(session_dir),
    ]
    for skill in skills:
        command += ["--skill", str(skill)]
    return command


def run_one(label: str, repo: Path, workflow: str, skills: list[Path], prompt: str,
            run_dir: Path, pi: str, provider: str, model: str, thinking: str,
            fixture: Path, timeout: int) -> dict:
    reset(repo)
    base = git(repo, "rev-parse", BASE_TAG).strip()
    session_dir = repo / ".bench" / "sessions" / "open"
    command = session_command(pi, session_dir, skills, provider, model, thinking)

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    started = time.monotonic()
    timed_out = False
    stdout = stderr = ""
    code = -1
    try:
        result = subprocess.run(
            command,
            cwd=repo,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env={**os.environ, "NO_COLOR": "1", "PI_SKIP_VERSION_CHECK": "1"},
        )
        stdout, stderr, code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", "replace")
        stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", "replace")
    elapsed = round(time.monotonic() - started, 1)

    (run_dir / f"{label}.stdout.txt").write_text(stdout, encoding="utf-8")
    (run_dir / f"{label}.stderr.txt").write_text(stderr, encoding="utf-8")

    usage = read_usage(session_dir)
    state = changed(repo, base)
    state["status"] = without_harness(state["status"])
    state["untracked"] = without_harness(state["untracked"])
    tests = run_process(repo, sys.executable, "-m", "pytest", "-q")
    tests["summary"] = pytest_summary(tests["stdout"] + "\n" + tests["stderr"])

    export = run_process(repo, sys.executable, "records.py", "export", "--id", "1")
    export["json_ok"] = False
    try:
        parsed = json.loads(export["stdout"])
        export["json_ok"] = isinstance(parsed, dict) and {"id", "name", "amount"} <= set(parsed)
    except json.JSONDecodeError:
        pass

    requirements = sorted(p for p in (repo / "docs" / "requirements").glob("*.md") if p.name != "README.md")
    specs = sorted((repo / "openspec" / "specs").rglob("*.md")) if (repo / "openspec" / "specs").exists() else []
    archive = sorted((repo / "openspec" / "changes" / "archive").rglob("*.md")) if (repo / "openspec").exists() else []
    cards = sorted((repo / "specs").glob("*/spec.md"))

    record = {
        "label": label,
        "workflow": workflow,
        "started": started_at,
        "base": base,
        "fixture": str(fixture),
        "exit": code,
        "timeout": timed_out,
        "seconds": elapsed,
        **usage,
        "stdout_tail": stdout.strip().splitlines()[-20:],
        "stderr_tail": stderr.strip().splitlines()[-10:],
        "diff": state,
        "tests": tests,
        "export": export,
        "docs": {
            "requirements_files": [p.relative_to(repo).as_posix() for p in requirements],
            "requirements_lines": sum(len(p.read_text(encoding="utf-8").splitlines()) for p in requirements),
            "openspec_spec_files": [p.relative_to(repo).as_posix() for p in specs],
            "openspec_spec_lines": sum(len(p.read_text(encoding="utf-8").splitlines()) for p in specs),
            "openspec_archive_files": [p.relative_to(repo).as_posix() for p in archive],
            "openspec_archive_lines": sum(len(p.read_text(encoding="utf-8").splitlines()) for p in archive),
            "cards_left": [p.relative_to(repo).as_posix() for p in cards],
        },
    }
    write_json(run_dir / f"{label}.json", record)
    return record


def judge_run(run_dir: Path, copies: dict[str, Path], mapping: dict[str, str],
              pi: str, model: str, provider: str, thinking: str, seed: int) -> dict:
    """Blind judge: the prompt never says which side is which."""
    stage_judge(run_dir / "judge", copies, BENCH_OPEN)
    result = run_process(
        run_dir / "judge",
        pi, "-p",
        "--provider", provider,
        "--model", model,
        "--thinking", thinking,
        "--approve",
        "--no-mcp",
        "--no-skills",
        "--no-prompt-templates",
        "--session-dir", str(run_dir / "judge-sessions"),
        timeout=3600,
        stdin=judge_prompt(BENCH_OPEN),
    )
    text = result["stdout"] + "\n" + result["stderr"]
    (run_dir / "judge.log").write_text(result["stdout"] + "\n--- stderr ---\n" + result["stderr"],
                                       encoding="utf-8")
    usage = read_usage(run_dir / "judge-sessions")
    scores = parse_scores(result["stdout"])
    record = {
        "seed": seed,
        "mapping": mapping,
        "exit": result["exit"],
        "seconds": result["seconds"],
        "usage": usage,
        "parsed": scores is not None,
    }
    if scores:
        record["result"] = {side: scores[label] for label, side in mapping.items()}
        record["verdict"] = scores.get("verdict", "")
        record["uncertainty"] = scores.get("uncertainty", "")
    else:
        record["raw_tail"] = text.strip().splitlines()[-20:]
    write_json(run_dir / "judge.json", record)
    return record


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=None,
                        help="两侧仓库所在目录（默认：临时目录；--keep 时保留）")
    parser.add_argument("--out", default=None, help="结果目录（默认 bench/out/open-<时间戳>）")
    parser.add_argument("--runs", type=int, default=1, help="成对运行多少次（默认 1）")
    parser.add_argument("--fixture", default=str(BENCH / "fixture"), help="两侧共用的起始 fixture")
    parser.add_argument("--problem", default=str(BENCH_OPEN / "problem.md"), help="开放问题描述")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--thinking", default="high")
    parser.add_argument("--pi", default=None, help="pi 可执行文件（默认找 PATH 或 PI_BIN）")
    parser.add_argument("--openspec-cmd", default="openspec", help="openspec 可执行文件")
    parser.add_argument("--reviewer", default="reviewer-fast", help="dev 侧预置的 reviewer agent")
    parser.add_argument("--judge", dest="judge", action="store_true", default=True)
    parser.add_argument("--no-judge", dest="judge", action="store_false")
    parser.add_argument("--judge-model", default=None, help="盲评用的模型（默认与 --model 相同）")
    parser.add_argument("--judge-pi", default=None, help="盲评用的 pi（默认与 --pi 相同）")
    parser.add_argument("--seed", type=int, default=0, help="A/B 映射与顺序的随机种子")
    parser.add_argument("--timeout", type=int, default=3600, help="单侧会话超时（秒）")
    parser.add_argument("--overwrite", action="store_true", help="--root 非空时重新生成")
    parser.add_argument("--keep", action="store_true", help="保留 --root（默认临时目录会删除）")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不创建任何东西")
    args = parser.parse_args(argv)

    problem = Path(args.problem).read_text(encoding="utf-8").strip()
    pi = args.pi or ("pi" if args.dry_run else pi_command(None))
    judge_pi = args.judge_pi or pi
    judge_model = args.judge_model or args.model

    temporary = args.root is None
    root = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="dcu-ab-"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else BENCH / "out" / f"open-{stamp}"

    sides = {"dev": (root / "dev-circuit", "dev-circuit-ultra",
                     [SKILLS]),
             "openspec": (root / "openspec", "OpenSpec",
                          None)}

    if args.dry_run:
        print(f"root:   {root}{'（临时）' if temporary else ''}")
        print(f"out:    {out}")
        print(f"runs:   {args.runs}")
        print(f"model:  {args.provider}/{args.model}  thinking={args.thinking}")
        print(f"fixture:{args.fixture}")
        print(f"judge:  {'on' if args.judge else 'off'}  ({judge_model})")
        print("")
        print("setup:")
        print(f"  devcircuit init --path {root / 'dev-circuit'} --name records")
        print(f"  devcircuit init --path {root / 'openspec'} --name records")
        print(f"  openspec init --tools pi --language zh-CN --no-animation --no-copilot-cloud  (in {root / 'openspec'})")
        for index in range(args.runs):
            order = ["dev", "openspec"] if index % 2 == 0 else ["openspec", "dev"]
            print(f"run {index + 1}: {' -> '.join(order)}  (A/B mapping seeded by {args.seed + index})")
        return 0

    if not Path(args.fixture).is_dir():
        print(f"fixture 目录不存在：{args.fixture}", file=sys.stderr)
        return 2
    if not shutil.which(pi) and not Path(pi).exists():
        print(f"找不到 pi：{pi}", file=sys.stderr)
        return 2

    repos = setup_pair(root, Path(args.fixture), BENCH_OPEN,
                       openspec_cmd=args.openspec_cmd, reviewer=args.reviewer,
                       overwrite=args.overwrite)
    out.mkdir(parents=True, exist_ok=True)
    openspec_skills = sorted((repos["openspec"] / ".pi" / "skills").glob("openspec-*"))
    template = (BENCH_OPEN / "prompt.md").read_text(encoding="utf-8")

    runs = []
    for index in range(args.runs):
        run_dir = out / f"run-{index + 1:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        order = ["dev", "openspec"] if index % 2 == 0 else ["openspec", "dev"]
        print(f"run {index + 1}/{args.runs}: {' -> '.join(order)}", flush=True)
        records = {}
        for side in order:
            repo, workflow, skills = sides[side]
            if skills is None:
                skills = openspec_skills
            side_prompt = fill(template, DIR=repo.as_posix(), WORKFLOW=workflow, PROBLEM=problem)
            records[side] = run_one(side, repo, workflow, skills, side_prompt, run_dir,
                                    pi, args.provider, args.model, args.thinking,
                                    Path(args.fixture), args.timeout)
            print(f"  {side}: {records[side]['seconds']}s, "
                  f"{records[side]['turns']} turns, ${records[side]['cost']}", flush=True)

        mapping = anonymize(args.seed + index)
        copies = {label: repos[side] for label, side in mapping.items()}
        judge_record = None
        if args.judge:
            judge_record = judge_run(run_dir, copies, mapping, judge_pi, judge_model,
                                     args.provider, args.thinking, args.seed + index)
            if judge_record["parsed"]:
                totals = {side: card["total"] for side, card in judge_record["result"].items()}
                print(f"  judge: {json.dumps(totals)}", flush=True)
            else:
                print("  judge: 无法解析分数，原文见 judge.log", flush=True)

        runs.append({
            "index": index,
            "order": order,
            "mapping": mapping,
            "dev": records.get("dev"),
            "openspec": records.get("openspec"),
            "judge": judge_record,
        })
        write_json(out / "runs.json", {
            "problem": problem,
            "fixture": str(args.fixture),
            "provider": args.provider,
            "model": args.model,
            "thinking": args.thinking,
            "judge_model": judge_model if args.judge else None,
            "seed": args.seed,
            "runs": runs,
        })
        print(f"  wrote {out / 'runs.json'}", flush=True)

    if temporary and not args.keep:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n完成 {len(runs)} 轮：{out}")
    print(f"汇总：python bench/summarize.py {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
