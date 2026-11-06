"""Run the full OpenSpec side with a capped review budget (8 assistant turns / ~10k output).

The spec-loop side is the existing full run in bench/out/results.json.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))
from run_ab import (  # noqa: E402
    BASE_TAG,
    BENCH as RUN_BENCH,
    Step,
    changed,
    fill,
    git,
    hidden_tests,
    pi_command,
    pytest_summary,
    read_usage,
    repo_docs,
    reset,
    run_process,
    run_step,
)

OUT = BENCH / "out"
SPEC_LOOP_RESULTS = OUT / "results.json"


def main() -> int:
    root = Path("C:/Users/iswal/dev-circuit-ab")
    repo = root / "openspec"
    skills = repo / ".pi" / "skills"
    reviewer = Path("C:/Users/iswal/spec-loop-draft/skills/dev-circuit-ultra/reviewer.md")
    pi = pi_command()
    feature = (BENCH / "feature.md").read_text(encoding="utf-8").strip()

    def template(name: str) -> str:
        return (BENCH / "prompts" / name).read_text(encoding="utf-8")

    reset(repo)
    base = git(repo, "rev-parse", BASE_TAG).strip()
    OUT.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    steps: list[dict] = []

    propose = fill(
        template("openspec-propose.md"),
        DIR=repo.as_posix(),
        SKILL=(skills / "openspec-propose").as_posix(),
        FEATURE=feature,
    )
    steps.append(
        run_step(pi, repo, Step("openspec_propose", skills / "openspec-propose", propose, timeout=1200), OUT)
    )

    apply_prompt = fill(
        template("openspec-apply.md"),
        DIR=repo.as_posix(),
        SKILL=(skills / "openspec-apply-change").as_posix(),
    )
    steps.append(
        run_step(
            pi,
            repo,
            Step("openspec_apply", skills / "openspec-apply-change", apply_prompt, timeout=2400),
            OUT,
        )
    )

    review_prompt = fill(
        template("openspec-review-capped.md"),
        DIR=repo.as_posix(),
        REVIEWER=reviewer.as_posix(),
        BASE=base,
    )
    review = run_step(pi, repo, Step("openspec_review", None, review_prompt, timeout=1200), OUT)
    steps.append(review)
    review_file = repo / ".bench" / "review.md"
    review_file.parent.mkdir(parents=True, exist_ok=True)
    review_file.write_text(
        (OUT / "openspec_review.stdout.txt").read_text(encoding="utf-8").strip() or "(审核没有输出)",
        encoding="utf-8",
    )

    fix_prompt = fill(
        template("openspec-fix.md"),
        DIR=repo.as_posix(),
        REVIEW=review_file.as_posix(),
    )
    steps.append(run_step(pi, repo, Step("openspec_fix", None, fix_prompt, timeout=1200), OUT))

    archive_prompt = fill(
        template("openspec-archive.md"),
        DIR=repo.as_posix(),
        SKILL=(skills / "openspec-archive-change").as_posix(),
    )
    steps.append(
        run_step(
            pi,
            repo,
            Step("openspec_archive", skills / "openspec-archive-change", archive_prompt, timeout=1800),
            OUT,
        )
    )

    state = changed(repo, base)
    docs = repo_docs(repo, "openspec")
    tests = run_process(repo, sys.executable, "-m", "pytest", "tests", "-q")
    tests["summary"] = pytest_summary(tests["stdout"] + "\n" + tests["stderr"])
    hidden = hidden_tests(repo)

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
    }
    (OUT / "openspec_capped_dev.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    total = {
        "input": sum(s["input"] for s in steps),
        "output": sum(s["output"] for s in steps),
        "cache_read": sum(s["cache_read"] for s in steps),
        "cost": round(sum(s["cost"] for s in steps), 6),
        "seconds": round(sum(s["seconds"] for s in steps), 1),
    }
    results["totals"] = total
    (OUT / "openspec_capped_dev.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(total, ensure_ascii=False, indent=2))
    print("hidden:", hidden["summary"])
    print("own tests:", tests["summary"])
    print("docs:", docs)
    print("commits:", state["commits"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
