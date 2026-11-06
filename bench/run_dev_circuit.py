"""Run only the dev-circuit-ultra side of the controlled A/B.

The OpenSpec side is run by run_openspec_capped.py. Both repos start from the
same fixture and tag; this script resets the dev repo to bench-base, runs
implement / review / close, and writes bench/out/dev_circuit.json.

Usage:
    python bench/run_dev_circuit.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))

from run_ab import (  # noqa: E402
    BASE_TAG,
    Step,
    changed,
    fill,
    git,
    hidden_tests,
    pi_command,
    pytest_summary,
    repo_docs,
    reset,
    run_process,
    run_step,
)

ROOT = Path("C:/Users/iswal/dev-circuit-ab")
REPO = ROOT / "dev-circuit"
SKILLS = BENCH.parent / "skills" / "dev-circuit-ultra"
OUT = BENCH / "out"


def template(name: str) -> str:
    return (BENCH / "prompts" / name).read_text(encoding="utf-8")


def main() -> int:
    feature = (BENCH / "feature.md").read_text(encoding="utf-8").strip()
    pi = pi_command()
    reset(REPO)
    base = git(REPO, "rev-parse", BASE_TAG).strip()
    OUT.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    steps: list[dict] = []

    implement = fill(
        template("dev-circuit-implement.md"),
        DIR=REPO.as_posix(),
        SKILL=SKILLS.as_posix(),
        FEATURE=feature,
    )
    steps.append(run_step(pi, REPO, Step("dev_circuit_implement", SKILLS, implement, timeout=1800), OUT))

    review = fill(
        template("dev-circuit-review.md"),
        DIR=REPO.as_posix(),
        SKILL=SKILLS.as_posix(),
        BASE=base,
    )
    review_result = run_step(pi, REPO, Step("dev_circuit_review", None, review, timeout=1200), OUT)
    steps.append(review_result)
    review_file = REPO / ".bench" / "review.md"
    review_file.parent.mkdir(parents=True, exist_ok=True)
    review_file.write_text(
        (OUT / "dev_circuit_review.stdout.txt").read_text(encoding="utf-8").strip()
        or "(审核没有输出)",
        encoding="utf-8",
    )

    close = fill(
        template("dev-circuit-close.md"),
        DIR=REPO.as_posix(),
        REVIEW=review_file.as_posix(),
    )
    steps.append(run_step(pi, REPO, Step("dev_circuit_close", SKILLS, close, timeout=1200), OUT))

    state = changed(REPO, base)
    docs = repo_docs(REPO, "dev-circuit")
    tests = run_process(REPO, sys.executable, "-m", "pytest", "tests", "-q")
    tests["summary"] = pytest_summary(tests["stdout"] + "\n" + tests["stderr"])
    hidden = hidden_tests(REPO)

    totals = {
        "input": sum(step["input"] for step in steps),
        "output": sum(step["output"] for step in steps),
        "cache_read": sum(step["cache_read"] for step in steps),
        "cost": round(sum(step["cost"] for step in steps), 6),
        "seconds": round(sum(step["seconds"] for step in steps), 1),
    }
    results = {
        "started": started_at,
        "model": "deepseek/deepseek-flash",
        "thinking": "high",
        "feature": feature,
        "base": base,
        "steps": steps,
        "diff": state,
        "docs": docs,
        "tests": tests,
        "hidden": hidden,
        "totals": totals,
    }
    (OUT / "dev_circuit.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(totals, ensure_ascii=False, indent=2))
    print("hidden:", hidden["summary"])
    print("own tests:", tests["summary"])
    print("docs:", docs)
    print("commits:", state["commits"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
