"""Run the spec-loop vs OpenSpec A/B on the records fixture.

One run, same model, same feature, same starting repo. The script resets both
repos to `bench-base`, runs each workflow's sessions, then measures tokens,
cost, artifacts and the shared hidden acceptance tests.

Usage:
    python bench/run_ab.py --root C:/path/to/ab --skills C:/path/to/skills/dev-circuit-ultra
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path(__file__).resolve().parent
PI_FALLBACK = Path.home() / ".pi" / "agent" / "bin" / "pi.cmd"
BASE_TAG = "bench-base"


@dataclass
class Step:
    name: str
    skill: Path | None
    prompt: str
    timeout: int = 900
    result: dict = field(default_factory=dict)


def pi_command() -> str:
    if os.name == "nt":
        candidate = Path(os.environ.get("PI_BIN", PI_FALLBACK))
        if candidate.exists():
            return str(candidate)
    found = shutil.which("pi")
    if not found:
        raise SystemExit("pi not found; pass --pi or set PI_BIN")
    return found


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def reset(repo: Path) -> None:
    git(repo, "reset", "--hard", BASE_TAG)
    git(repo, "clean", "-fdx")


def fill(prompt: str, **values: str) -> str:
    for key, value in values.items():
        prompt = prompt.replace("{{" + key + "}}", value)
    return prompt


def run_step(
    pi: str,
    repo: Path,
    step: Step,
    out_dir: Path,
    extra_prompt: str = "",
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    session_dir = repo / ".bench" / "sessions" / step.name
    command = [
        pi,
        "-p",
        "--provider",
        "deepseek",
        "--model",
        "deepseek-flash",
        "--thinking",
        "high",
        "--approve",
        "--no-mcp",
        "--no-skills",
        "--no-prompt-templates",
        "--session-dir",
        str(session_dir),
    ]
    if step.skill:
        command += ["--skill", str(step.skill)]

    prompt = step.prompt + extra_prompt
    started = time.monotonic()
    timed_out = False
    stdout = ""
    stderr = ""
    code = -1
    try:
        result = subprocess.run(
            command,
            cwd=repo,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=step.timeout,
            env={**os.environ, "NO_COLOR": "1", "PI_SKIP_VERSION_CHECK": "1"},
        )
        stdout, stderr, code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    elapsed = round(time.monotonic() - started, 1)

    (out_dir / f"{step.name}.stdout.txt").write_text(stdout, encoding="utf-8")
    (out_dir / f"{step.name}.stderr.txt").write_text(stderr, encoding="utf-8")

    usage = read_usage(session_dir)
    step.result = {
        "step": step.name,
        "exit": code,
        "timeout": timed_out,
        "seconds": elapsed,
        **usage,
        "stdout_tail": stdout.strip().splitlines()[-12:],
    }
    (out_dir / f"{step.name}.json").write_text(
        json.dumps(step.result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return step.result


def read_usage(session_dir: Path) -> dict:
    totals = {"input": 0, "output": 0, "cache_read": 0, "reasoning": 0, "cost": 0.0, "turns": 0}
    for path in session_dir.rglob("*.jsonl") if session_dir.exists() else []:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = (record.get("message") or {}).get("usage") or {}
            if not usage:
                continue
            totals["input"] += usage.get("input", 0)
            totals["output"] += usage.get("output", 0)
            totals["cache_read"] += usage.get("cacheRead", 0)
            totals["reasoning"] += usage.get("reasoning", 0)
            totals["cost"] += (usage.get("cost") or {}).get("total", 0)
            totals["turns"] += 1
    totals["cost"] = round(totals["cost"], 6)
    return totals


def run_process(repo: Path, *command: str, timeout: int = 300) -> dict:
    started = time.monotonic()
    try:
        result = subprocess.run(
            list(command),
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env={**os.environ, "NO_COLOR": "1"},
        )
        return {
            "command": " ".join(command),
            "exit": result.returncode,
            "seconds": round(time.monotonic() - started, 1),
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {
            "command": " ".join(command),
            "exit": -1,
            "timeout": True,
            "seconds": round(time.monotonic() - started, 1),
            "stdout": "",
            "stderr": "",
        }


def pytest_summary(output: str) -> str:
    lines = [line for line in output.splitlines() if re.search(r"\bpassed\b|\bfailed\b|\berror", line)]
    return lines[-1].strip() if lines else output.strip().splitlines()[-1:] or ""


def changed(repo: Path, base: str) -> dict:
    status = git(repo, "status", "--porcelain")
    committed = git(repo, "log", "--oneline", f"{base}..HEAD")
    diff = git(repo, "diff", "--stat", base)
    untracked = [line[3:] for line in status.splitlines() if line.startswith("??")]
    return {
        "status": status.strip().splitlines(),
        "commits": committed.strip().splitlines(),
        "diff_stat": diff.strip().splitlines(),
        "untracked": untracked,
    }


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def repo_docs(repo: Path, kind: str) -> dict:
    if kind in {"spec-loop", "dev-circuit"}:
        reqs = [p for p in (repo / "docs" / "requirements").glob("*.md") if p.name != "README.md"]
        cards = list((repo / "specs").glob("*/spec.md"))
        return {
            "requirements_files": [p.relative_to(repo).as_posix() for p in reqs],
            "requirements_lines": sum(line_count(p) for p in reqs),
            "requirements_ids": sum(
                len(re.findall(r"^- [A-Z]{2,8}-\d+[：:]", p.read_text(encoding="utf-8"), re.M)) for p in reqs
            ),
            "cards_left": [c.relative_to(repo).as_posix() for c in cards],
        }
    archived = list((repo / "openspec" / "changes" / "archive").glob("*/**/*.md"))
    specs = list((repo / "openspec" / "specs").rglob("*.md"))
    return {
        "archive_files": [p.relative_to(repo).as_posix() for p in archived],
        "archive_lines": sum(line_count(p) for p in archived),
        "spec_files": [p.relative_to(repo).as_posix() for p in specs],
        "spec_lines": sum(line_count(p) for p in specs),
    }


def hidden_tests(repo: Path) -> dict:
    target = repo / "hidden_tests"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(BENCH / "hidden", target)
    result = run_process(repo, sys.executable, "-m", "pytest", "hidden_tests", "-q")
    shutil.rmtree(target)
    result["summary"] = pytest_summary(result["stdout"] + "\n" + result["stderr"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="C:/Users/iswal/spec-loop-ab")
    parser.add_argument("--skills", default=str(BENCH.parent / "skills" / "design-loop"))
    parser.add_argument("--pi", default=pi_command())
    args = parser.parse_args()

    root = Path(args.root).resolve()
    skills = Path(args.skills).resolve()
    spec_repo = root / "spec-loop"
    os_repo = root / "openspec"
    out_dir = BENCH / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    feature = (BENCH / "feature.md").read_text(encoding="utf-8").strip()

    def template(name: str) -> str:
        return (BENCH / "prompts" / name).read_text(encoding="utf-8")

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    all_steps: list[dict] = []

    # --- spec-loop ---
    reset(spec_repo)
    base = git(spec_repo, "rev-parse", BASE_TAG).strip()

    implement = fill(
        template("spec-loop-implement.md"),
        DIR=spec_repo.as_posix(),
        SKILL=skills.as_posix(),
        FEATURE=feature,
    )
    all_steps.append(run_step(args.pi, spec_repo, Step("spec_loop_implement", skills, implement, timeout=1800), out_dir))

    review = fill(
        template("spec-loop-review.md"),
        DIR=spec_repo.as_posix(),
        SKILL=skills.as_posix(),
        BASE=base,
    )
    review_result = run_step(args.pi, spec_repo, Step("spec_loop_review", None, review, timeout=1200), out_dir)
    all_steps.append(review_result)
    review_file = spec_repo / ".bench" / "review.md"
    review_file.parent.mkdir(parents=True, exist_ok=True)
    review_file.write_text(
        (out_dir / "spec_loop_review.stdout.txt").read_text(encoding="utf-8").strip()
        or "(审核没有输出)",
        encoding="utf-8",
    )

    close = fill(
        template("spec-loop-close.md"),
        DIR=spec_repo.as_posix(),
        REVIEW=review_file.as_posix(),
    )
    all_steps.append(run_step(args.pi, spec_repo, Step("spec_loop_close", skills, close, timeout=1200), out_dir))

    spec_state = changed(spec_repo, base)
    spec_docs = repo_docs(spec_repo, "spec-loop")
    spec_tests = run_process(spec_repo, sys.executable, "-m", "pytest", "tests", "-q")
    spec_tests["summary"] = pytest_summary(spec_tests["stdout"] + "\n" + spec_tests["stderr"])
    spec_hidden = hidden_tests(spec_repo)

    # --- OpenSpec ---
    reset(os_repo)
    base_os = git(os_repo, "rev-parse", BASE_TAG).strip()

    propose = fill(
        template("openspec-propose.md"),
        DIR=os_repo.as_posix(),
        SKILL=(os_repo / ".pi" / "skills" / "openspec-propose").as_posix(),
        FEATURE=feature,
    )
    all_steps.append(
        run_step(args.pi, os_repo, Step("openspec_propose", os_repo / ".pi" / "skills" / "openspec-propose", propose, timeout=1200), out_dir)
    )

    apply_prompt = fill(
        template("openspec-apply.md"),
        DIR=os_repo.as_posix(),
        SKILL=(os_repo / ".pi" / "skills" / "openspec-apply-change").as_posix(),
    )
    all_steps.append(
        run_step(
            args.pi,
            os_repo,
            Step("openspec_apply", os_repo / ".pi" / "skills" / "openspec-apply-change", apply_prompt, timeout=2400),
            out_dir,
        )
    )
    openspec = shutil.which("openspec") or "openspec"
    archive = run_process(os_repo, openspec, "archive", "add-report", "-y", timeout=120)
    (out_dir / "openspec_archive.json").write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")

    os_state = changed(os_repo, base_os)
    os_docs = repo_docs(os_repo, "openspec")
    os_tests = run_process(os_repo, sys.executable, "-m", "pytest", "tests", "-q")
    os_tests["summary"] = pytest_summary(os_tests["stdout"] + "\n" + os_tests["stderr"])
    os_hidden = hidden_tests(os_repo)

    results = {
        "started": started_at,
        "model": "deepseek/deepseek-flash",
        "thinking": "high",
        "feature": feature,
        "spec_loop": {
            "steps": [s for s in all_steps if s["step"].startswith("spec_loop")],
            "diff": spec_state,
            "docs": spec_docs,
            "tests": spec_tests,
            "hidden": spec_hidden,
        },
        "openspec": {
            "steps": [s for s in all_steps if s["step"].startswith("openspec")],
            "archive": archive,
            "diff": os_state,
            "docs": os_docs,
            "tests": os_tests,
            "hidden": os_hidden,
        },
    }

    def total_tokens(steps):
        return {
            "input": sum(s["input"] for s in steps),
            "output": sum(s["output"] for s in steps),
            "cache_read": sum(s["cache_read"] for s in steps),
            "cost": round(sum(s["cost"] for s in steps), 6),
            "seconds": round(sum(s["seconds"] for s in steps), 1),
        }

    spec_total = total_tokens(results["spec_loop"]["steps"])
    os_total = total_tokens(results["openspec"]["steps"]) 
    os_total["seconds"] = round(os_total["seconds"] + archive["seconds"], 1)
    results["totals"] = {"spec_loop": spec_total, "openspec": os_total}

    (out_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"spec_loop": spec_total, "openspec": os_total}, ensure_ascii=False, indent=2))
    print("spec hidden:", spec_hidden["summary"])
    print("openspec hidden:", os_hidden["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
