"""Small shared helpers for the open A/B runner.

Only what the open run needs: setup, git reset, pi invocation, usage totals,
process output, changed-file state and the blind-judge plumbing.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

PI_FALLBACK = Path.home() / ".pi" / "agent" / "bin" / "pi.cmd"
BASE_TAG = "bench-base"
REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_IGNORES = (".git", ".bench", "__pycache__", ".pytest_cache", ".pi", ".dev-circuit")


def pi_command(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    if os.name == "nt":
        candidate = Path(os.environ.get("PI_BIN", PI_FALLBACK))
        if candidate.exists():
            return str(candidate)
    found = shutil.which(os.environ.get("PI_BIN", "pi"))
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


def remove_tree(path: Path) -> None:
    """rmtree that also removes read-only files (git objects on Windows)."""
    def retry(function, target, _info):
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if not Path(path).exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def fill(prompt: str, **values: str) -> str:
    for key, value in values.items():
        prompt = prompt.replace("{{" + key + "}}", value)
    return prompt


def devcircuit(*args: str, python: str | None = None) -> dict:
    """Run the CLI from this checkout, so the bench does not need it installed."""
    environment = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT / "tools"),
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(
        [python or sys.executable, "-m", "devcircuit.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"devcircuit {' '.join(args)} failed ({result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}")
    return {"stdout": result.stdout, "stderr": result.stderr}


def read_usage(session_dir: Path) -> dict:
    """Main-session usage plus the subagents it dispatched.

    The subagent extension runs children with --no-session, so their usage only
    exists in the parent's toolResult details. Top-level token and cost totals
    include it; `turns` stays the parent's assistant turns.
    """
    totals = {"input": 0, "output": 0, "cache_read": 0, "reasoning": 0, "cost": 0.0, "turns": 0}
    children = {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cost": 0.0, "turns": 0}
    for path in session_dir.rglob("*.jsonl") if session_dir.exists() else []:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = record.get("message") or {}
            if message.get("role") == "toolResult" and message.get("toolName") == "subagent":
                for child in (message.get("details") or {}).get("results") or []:
                    used = child.get("usage") or {}
                    children["calls"] += 1
                    children["input"] += used.get("input", 0)
                    children["output"] += used.get("output", 0)
                    children["cache_read"] += used.get("cacheRead", 0)
                    children["cost"] += used.get("cost", 0) or 0
                    children["turns"] += used.get("turns", 0)
                continue
            usage = message.get("usage") or {}
            if not usage:
                continue
            totals["input"] += usage.get("input", 0)
            totals["output"] += usage.get("output", 0)
            totals["cache_read"] += usage.get("cacheRead", 0)
            totals["reasoning"] += usage.get("reasoning", 0)
            totals["cost"] += (usage.get("cost") or {}).get("total", 0)
            totals["turns"] += 1
    for key in ("input", "output", "cache_read", "cost"):
        totals[key] += children[key]
    totals["cost"] = round(totals["cost"], 6)
    children["cost"] = round(children["cost"], 6)
    totals["subagents"] = children
    return totals


def run_process(repo: Path, *command: str, timeout: int = 300, stdin: str | None = None,
                extra_env: dict | None = None) -> dict:
    started = time.monotonic()
    try:
        result = subprocess.run(
            list(command),
            cwd=repo,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            env={**os.environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8", **(extra_env or {})},
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


def without_harness(lines: list[str]) -> list[str]:
    return [line for line in lines
            if not any(part in line for part in (".bench/", "__pycache__/", ".pytest_cache/", ".dev-circuit/"))]


def setup_pair(root: Path, fixture: Path, bench_open: Path,
               openspec_cmd: str = "openspec", reviewer: str = "reviewer-fast",
               overwrite: bool = False) -> dict[str, Path]:
    """Create both repos from scratch and tag the starting point."""
    repos = {"dev": root / "dev-circuit", "openspec": root / "openspec"}
    if root.exists() and any(root.iterdir()):
        if not overwrite:
            raise SystemExit(f"{root} 不是空目录；加 --overwrite 重新生成两侧仓库。")
        remove_tree(root)
    root.mkdir(parents=True, exist_ok=True)

    for name, repo in repos.items():
        devcircuit("init", "--path", str(repo), "--name", "records")
        for entry in fixture.iterdir():
            destination = repo / entry.name
            if entry.is_dir():
                shutil.copytree(entry, destination, dirs_exist_ok=True)
            else:
                shutil.copyfile(entry, destination)
        shutil.copyfile(bench_open / "AGENTS.md", repo / "AGENTS.md")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "chore: add records fixture")

    dev = repos["dev"]
    reviewer_file = dev / ".dev-circuit" / "reviewer.json"
    reviewer_file.parent.mkdir(parents=True, exist_ok=True)
    reviewer_file.write_text(json.dumps({"mode": "agent", "agent": reviewer}), encoding="utf-8")
    agent_source = bench_open / f"{reviewer}.md"
    if agent_source.is_file():
        agents_dir = Path.home() / ".pi" / "agent" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(agent_source, agents_dir / agent_source.name)
    git(dev, "add", "-A")
    git(dev, "commit", "-qm", "chore: reviewer default for the benchmark")

    openspec_repo = repos["openspec"]
    if not Path(openspec_cmd).is_file():
        # On Windows the npm shim is openspec.cmd, which CreateProcess will not
        # find from a bare "openspec" argument.
        resolved = shutil.which(openspec_cmd)
        if not resolved:
            raise SystemExit(f"找不到 openspec：{openspec_cmd}（用 --openspec-cmd 指定）")
        openspec_cmd = resolved
    result = subprocess.run(
        [openspec_cmd, "init", "--tools", "pi", "--language", "zh-CN",
         "--no-animation", "--no-copilot-cloud"],
        cwd=openspec_repo, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"openspec init failed ({result.returncode}): "
                           f"{(result.stderr or result.stdout).strip()}")
    git(openspec_repo, "add", "-A")
    git(openspec_repo, "commit", "-q", "--no-verify", "-m", "chore: init openspec")

    for repo in repos.values():
        git(repo, "tag", BASE_TAG)
    return repos


def copy_eval_tree(src: Path, dst: Path) -> None:
    remove_tree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*EVAL_IGNORES))


def evidence_text(records: dict[str, dict]) -> str:
    """Facts the judge cannot see in a copy without .git, same shape for each side."""
    lines = [
        "# EVIDENCE",
        "",
        "评审副本去掉了 `.git`。下面是 harness 在原仓库里取到的事实，两边格式相同；",
        "它是证据，不是结论。harness 自己的文件（`.bench/` 等）已排除。",
    ]
    for label in sorted(records):
        record = records[label]
        diff = record.get("diff") or {}
        commits = diff.get("commits") or []
        status = diff.get("status") or []
        tests = (record.get("tests") or {}).get("summary") or "（无输出）"
        lines += ["", f"## {label}", "", f"- 相对起点的提交：{len(commits)} 个"]
        lines += [f"  - `{commit}`" for commit in commits]
        lines.append(f"- `git status --porcelain`：{len(status)} 条")
        lines += [f"  - `{entry}`" for entry in status]
        lines.append(f"- 会话结束后 `python -m pytest -q`：{tests}")
    return "\n".join(lines) + "\n"


def judge_prompt(bench_open: Path) -> str:
    """The judge instruction, with the output contract appended."""
    text = (bench_open / "judge.md").read_text(encoding="utf-8").strip()
    text += """

补充：现在是自动化盲评。`A/`、`B/`、`problem.md`、`rubric.md` 都在当前目录。

先按 `rubric.md` 的输出格式写逐维度的文字与证据，然后在最后追加一个 ```json 代码块，只放分数，键名固定：

```json
{"A": {"product": 0, "correctness": 0, "tests": 0, "docs": 0, "code": 0, "closeout": 0, "total": 0},
 "B": {"product": 0, "correctness": 0, "tests": 0, "docs": 0, "code": 0, "closeout": 0, "total": 0},
 "verdict": "一句话", "uncertainty": "一句话"}
```

分数是 1–5 的整数，`total` 是六项之和（满分 30）。不要输出别的代码块。
"""
    return text


def stage_judge(destination: Path, copies: dict[str, Path], bench_open: Path,
                evidence: dict[str, dict] | None = None) -> None:
    """Lay out a self-contained judge directory: A/, B/, problem, rubric, judge."""
    remove_tree(destination)
    destination.mkdir(parents=True)
    for label, source in copies.items():
        copy_eval_tree(source, destination / label)
    for name in ("problem.md", "rubric.md"):
        shutil.copyfile(bench_open / name, destination / name)
    (destination / "judge.md").write_text(judge_prompt(bench_open), encoding="utf-8")
    if evidence:
        (destination / "EVIDENCE.md").write_text(evidence_text(evidence), encoding="utf-8")


SCORE_FENCE = re.compile(r"```json\s*")
SCORE_KEYS = ("product", "correctness", "tests", "docs", "code", "closeout")


def parse_scores(text: str) -> dict | None:
    """Take the last fenced JSON block that looks like a score card.

    `raw_decode` walks the nested object properly; a non-greedy regex would stop
    at the first inner brace and reject a valid card.
    """
    decoder = json.JSONDecoder()
    for match in reversed(list(SCORE_FENCE.finditer(text or ""))):
        try:
            payload, _ = decoder.raw_decode(text[match.end():].lstrip())
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or not {"A", "B"} <= set(payload):
            continue
        cleaned = {}
        for label in ("A", "B"):
            card = payload.get(label)
            if not isinstance(card, dict):
                break
            scores = {key: int(card[key]) for key in SCORE_KEYS if isinstance(card.get(key), (int, float))}
            if len(scores) != len(SCORE_KEYS):
                break
            scores["total"] = int(card.get("total") or sum(scores.values()))
            cleaned[label] = scores
        else:
            cleaned["verdict"] = str(payload.get("verdict") or "")
            cleaned["uncertainty"] = str(payload.get("uncertainty") or "")
            return cleaned
    return None


def anonymize(seed: int) -> dict[str, str]:
    """Which side hides behind A and B in this run."""
    mapping = ["dev", "openspec"]
    random.Random(seed).shuffle(mapping)
    return {"A": mapping[0], "B": mapping[1]}
