"""Run the open-ended A/B: one problem, one prompt, no prescribed workflow.

Both repos start from the same fixture + skeleton and a neutral AGENTS.md.
Each skill gets one end-to-end session. There is no review budget, no slice
count, no hidden acceptance suite and no required command shape.

Usage:
    python bench/open/run_open_ab.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))

from run_ab import (  # noqa: E402
    BASE_TAG,
    changed,
    fill,
    git,
    pi_command,
    pytest_summary,
    read_usage,
    reset,
    run_process,
)

ROOT = Path("C:/Users/iswal/open-ab")
OUT = BENCH / "out" / "open"
SKILLS = BENCH.parent / "skills" / "dev-circuit-ultra"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


HARNESS_PREFIXES = (".bench/", "__pycache__/", ".pytest_cache/", ".dev-circuit/")


def without_harness(lines: list[str]) -> list[str]:
    return [line for line in lines if not any(part in line for part in HARNESS_PREFIXES)]


def copy_eval_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(".git", ".bench", "__pycache__", ".pytest_cache", ".pi", ".dev-circuit"),
    )


def run_one(label: str, repo: Path, workflow: str, skills: list[Path], problem: str, timeout: int = 3600) -> dict:
    pi = pi_command()
    reset(repo)
    base = git(repo, "rev-parse", BASE_TAG).strip()
    OUT.mkdir(parents=True, exist_ok=True)
    prompt = fill(
        (BENCH / "open" / "prompt.md").read_text(encoding="utf-8"),
        DIR=repo.as_posix(),
        WORKFLOW=workflow,
        PROBLEM=problem,
    )
    session_dir = repo / ".bench" / "sessions" / "open"
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
    for skill in skills:
        command += ["--skill", str(skill)]

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
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
            timeout=timeout,
            env={**os.environ, "NO_COLOR": "1", "PI_SKIP_VERSION_CHECK": "1"},
        )
        stdout, stderr, code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    elapsed = round(time.monotonic() - started, 1)

    (OUT / f"{label}.stdout.txt").write_text(stdout, encoding="utf-8")
    (OUT / f"{label}.stderr.txt").write_text(stderr, encoding="utf-8")

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

    help_result = run_process(repo, sys.executable, "records.py", "--help")
    requirements = sorted((repo / "docs" / "requirements").glob("*.md"))
    requirements = [p for p in requirements if p.name != "README.md"]
    specs = sorted((repo / "openspec" / "specs").rglob("*.md")) if (repo / "openspec" / "specs").exists() else []
    archive = sorted((repo / "openspec" / "changes" / "archive").rglob("*.md")) if (repo / "openspec").exists() else []
    cards = sorted((repo / "specs").glob("*/spec.md"))

    result = {
        "label": label,
        "workflow": workflow,
        "started": started_at,
        "base": base,
        "exit": code,
        "timeout": timed_out,
        "seconds": elapsed,
        **usage,
        "stdout_tail": stdout.strip().splitlines()[-20:],
        "stderr_tail": stderr.strip().splitlines()[-10:],
        "diff": state,
        "tests": tests,
        "export": export,
        "help": {
            "exit": help_result["exit"],
            "stdout": help_result["stdout"],
            "stderr": help_result["stderr"],
        },
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
    write_json(OUT / f"{label}.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    problem = (BENCH / "open" / "problem.md").read_text(encoding="utf-8").strip()
    dev_repo = root / "dev-circuit"
    os_repo = root / "openspec"
    out: dict[str, dict] = {}

    out["dev"] = run_one(
        "dev",
        dev_repo,
        "dev-circuit-ultra",
        [SKILLS],
        problem,
    )
    out["openspec"] = run_one(
        "openspec",
        os_repo,
        "OpenSpec",
        sorted((os_repo / ".pi" / "skills").glob("openspec-*")),
        problem,
    )

    # Blind evaluator copies: A/B, no .git or .bench.
    copy_eval_tree(dev_repo, OUT / "eval" / "A")
    copy_eval_tree(os_repo, OUT / "eval" / "B")

    summary = {
        "problem": problem,
        "model": "deepseek/deepseek-flash",
        "thinking": "high",
        "caveat": "n=1 per skill; one open prompt; no hidden acceptance; judge artifact quality with bench/open/rubric.md.",
        "dev": {k: out["dev"][k] for k in ("exit", "timeout", "seconds", "input", "output", "cache_read", "cost", "turns", "tests", "export", "docs", "diff")},
        "openspec": {k: out["openspec"][k] for k in ("exit", "timeout", "seconds", "input", "output", "cache_read", "cost", "turns", "tests", "export", "docs", "diff")},
    }
    write_json(OUT / "summary.json", summary)
    print(json.dumps({
        "dev": {k: summary["dev"][k] for k in ("seconds", "cost", "turns", "tests")},
        "openspec": {k: summary["openspec"][k] for k in ("seconds", "cost", "turns", "tests")},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
