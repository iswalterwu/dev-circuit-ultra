"""Small shared helpers for the open A/B runner.

Only what the open run needs: git reset, pi invocation, usage totals, process
output and changed-file state. The historical controlled runner is gone.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

PI_FALLBACK = Path.home() / ".pi" / "agent" / "bin" / "pi.cmd"
BASE_TAG = "bench-base"


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
