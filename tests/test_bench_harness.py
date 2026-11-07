"""The A/B runner is only trustworthy if it can be tested without model spend.

Both `pi` and `openspec` are replaceable, so these tests drive the real runner
with stubs: a fake session writer with known usage, and a fake score card.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "bench" / "open" / "run_open_ab.py"
SUMMARIZER = REPO / "bench" / "summarize.py"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")

STUB_PI = '''#!@@PY@@
import json, os, subprocess, sys
from pathlib import Path

argv = sys.argv[1:]
session_dir = Path(argv[argv.index("--session-dir") + 1])
prompt = sys.stdin.read()
session_dir.mkdir(parents=True, exist_ok=True)
judging = "键名固定" in prompt

USAGE = {"input": 1000, "output": 500, "cacheRead": 10000, "cacheWrite": 0,
         "totalTokens": 11500,
         "cost": {"input": 0.001, "output": 0.002, "cacheRead": 0.003,
                  "cacheWrite": 0.0, "total": 0.01}}
# What the subagent extension stores: the child's usage lives only in details.
REVIEWER = {"role": "toolResult", "toolName": "subagent", "toolCallId": "c1", "content": [],
            "details": {"results": [{"agent": "reviewer-fast", "usage": {
                "input": 300, "output": 200, "cacheRead": 4000, "cost": 0.005, "turns": 3}}]}}

with open(session_dir / "session.jsonl", "w", encoding="utf-8") as log:
    for role, text in (("user", prompt[:40]), ("assistant", "first step"), ("assistant", "second step")):
        message = {"role": role, "content": text, "timestamp": 1}
        if role == "assistant":
            message["usage"] = dict(USAGE)
        print(json.dumps({"type": "message_end", "message": message}, ensure_ascii=False), file=log)
    if not judging:
        print(json.dumps({"type": "message", "message": REVIEWER}), file=log)

if judging:
    where = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd="A",
                           capture_output=True, text=True)
    (session_dir / "judge-env.json").write_text(json.dumps({
        "cwd": os.getcwd(),
        "git_toplevel": where.stdout.strip(),
        "evidence": Path("EVIDENCE.md").read_text(encoding="utf-8") if Path("EVIDENCE.md").exists() else None,
    }, ensure_ascii=False), encoding="utf-8")
    print("评审完成。")
    print("```json")
    print(json.dumps({
        "A": {"product": 5, "correctness": 4, "tests": 3, "docs": 4, "code": 5, "closeout": 5, "total": 26},
        "B": {"product": 4, "correctness": 4, "tests": 5, "docs": 3, "code": 3, "closeout": 2, "total": 21},
        "verdict": "A 收尾更干净",
        "uncertainty": "样本少",
    }, ensure_ascii=False))
    print("```")
else:
    (Path.cwd() / "report.md").write_text("report\\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-qm", "feat: report"], check=True)
    print("done")
'''

STUB_OPENSPEC = '''#!@@PY@@
import sys
from pathlib import Path

if sys.argv[1:2] != ["init"]:
    sys.exit(0)
target = Path("openspec/specs/report/spec.md")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text("# report\\n", encoding="utf-8")
skill = Path(".pi/skills/openspec-explore/SKILL.md")
skill.parent.mkdir(parents=True, exist_ok=True)
skill.write_text("# explore\\n", encoding="utf-8")
print("openspec ready")
'''


def write_stub(path: Path, body: str) -> Path:
    """Write the stub, plus a .cmd shim on Windows where a shebang is not enough."""
    script = path.with_suffix(".py")
    script.write_text(body.replace("@@PY@@", sys.executable), encoding="utf-8")
    script.chmod(0o755)
    if os.name != "nt":
        return script
    shim = path.with_suffix(".cmd")
    shim.write_text(f'@"{sys.executable}" "{script}" %*' + "\n", encoding="utf-8")
    return shim


def run_runner(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    stub_pi = write_stub(tmp_path / "stub-pi.py", STUB_PI)
    stub_openspec = write_stub(tmp_path / "stub-openspec.py", STUB_OPENSPEC)
    return subprocess.run(
        [sys.executable, str(RUNNER),
         "--root", str(tmp_path / "repos"),
         "--out", str(tmp_path / "out"),
         "--pi", str(stub_pi),
         "--openspec-cmd", str(stub_openspec),
         "--reviewer", "no-such-reviewer",
         *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
    )


def test_two_runs_and_a_blind_judge(tmp_path: Path) -> None:
    result = run_runner(tmp_path, "--runs", "2", "--seed", "7")
    assert result.returncode == 0, result.stdout + result.stderr

    payload = json.loads((tmp_path / "out" / "runs.json").read_text(encoding="utf-8"))
    assert payload["model"] == "deepseek-flash"
    assert len(payload["runs"]) == 2

    first, second = payload["runs"]
    assert first["order"] == ["dev", "openspec"]
    assert second["order"] == ["openspec", "dev"]

    for run in payload["runs"]:
        for side in ("dev", "openspec"):
            record = run[side]
            assert record["exit"] == 0 and not record["timeout"]
            # Two parent turns plus one reviewer subagent that only exists in details.
            assert record["turns"] == 2
            assert record["input"] == 2300 and record["output"] == 1200
            assert record["cache_read"] == 24000
            assert record["cost"] == pytest.approx(0.025)
            assert record["subagents"] == {"calls": 1, "input": 300, "output": 200,
                                           "cache_read": 4000, "cost": 0.005, "turns": 3}
            assert len(record["diff"]["commits"]) == 1

        assert run["judge"]["parsed"] is True
        mapping = run["judge"]["mapping"]
        assert sorted(mapping.values()) == ["dev", "openspec"]
        # A scores 26 and B scores 21 in the stub; the mapping decides who owns which.
        assert run["judge"]["result"]["dev"]["total"] == (26 if mapping["A"] == "dev" else 21)
        assert run["judge"]["result"]["openspec"]["total"] == (21 if mapping["A"] == "dev" else 26)
        assert run["judge"]["verdict"] == "A 收尾更干净"

    out = tmp_path / "out"
    judge_text = (out / "run-01" / "judge" / "judge.md").read_text(encoding="utf-8")
    assert "```json" in judge_text
    assert (out / "run-01" / "judge" / "A").is_dir()
    assert not (out / "run-01" / "judge" / "A" / ".git").exists()


def test_traces_and_final_trees_survive_the_next_reset(tmp_path: Path) -> None:
    assert run_runner(tmp_path, "--runs", "2").returncode == 0

    for run in ("run-01", "run-02"):
        for side in ("dev", "openspec"):
            assert (tmp_path / "out" / run / f"{side}-sessions" / "session.jsonl").is_file()
            assert (tmp_path / "out" / run / "final" / side / "report.md").is_file()
            assert not (tmp_path / "out" / run / "final" / side / ".git").exists()


def test_judge_sees_evidence_but_not_the_bench_checkout(tmp_path: Path) -> None:
    assert run_runner(tmp_path, "--runs", "1").returncode == 0

    seen = json.loads((tmp_path / "out" / "run-01" / "judge-sessions" / "judge-env.json")
                      .read_text(encoding="utf-8"))
    assert not Path(seen["cwd"]).resolve().is_relative_to(tmp_path.resolve())
    assert not Path(seen["cwd"]).resolve().is_relative_to(REPO.resolve())
    assert seen["git_toplevel"] == ""
    assert "## A" in seen["evidence"] and "## B" in seen["evidence"]
    assert "相对起点的提交：1 个" in seen["evidence"]
    assert "`python -m pytest -q`：" in seen["evidence"]
    # The staged copy is kept with the run for the record.
    assert (tmp_path / "out" / "run-01" / "judge" / "EVIDENCE.md").is_file()


def test_relative_out_keeps_judge_sessions_with_the_run(tmp_path: Path) -> None:
    """The judge runs in a temp dir; a relative --out must not follow it there."""
    stub_pi = write_stub(tmp_path / "stub-pi.py", STUB_PI)
    stub_openspec = write_stub(tmp_path / "stub-openspec.py", STUB_OPENSPEC)
    common = ["--pi", str(stub_pi), "--openspec-cmd", str(stub_openspec), "--reviewer", "none"]
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--root", "repos", "--out", "out", "--runs", "1", *common],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "out" / "run-01" / "judge-sessions" / "session.jsonl").is_file()
    assert not (tmp_path / "out" / "run-01" / "judge" / "out").exists()
    judge = json.loads((tmp_path / "out" / "run-01" / "judge.json").read_text(encoding="utf-8"))
    assert judge["usage"]["cost"] == pytest.approx(0.02)

    result = subprocess.run(
        [sys.executable, str(RUNNER), "--rejudge", "out", "--repeats", "1", *common],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    again = json.loads((tmp_path / "out" / "run-01" / "rejudge-ev-1.json").read_text(encoding="utf-8"))
    assert again["usage"]["cost"] == pytest.approx(0.02)


def test_rejudge_alternates_positions_and_reports_spread(tmp_path: Path) -> None:
    assert run_runner(tmp_path, "--runs", "1").returncode == 0

    result = run_runner(tmp_path, "--rejudge", str(tmp_path / "out"), "--repeats", "2",
                        "--jobs", "2", "--no-evidence")
    assert result.returncode == 0, result.stdout + result.stderr

    first = json.loads((tmp_path / "out" / "run-01" / "rejudge-noev-1.json").read_text(encoding="utf-8"))
    second = json.loads((tmp_path / "out" / "run-01" / "rejudge-noev-2.json").read_text(encoding="utf-8"))
    assert first["mapping"] == {"A": "dev", "B": "openspec"}
    assert second["mapping"] == {"A": "openspec", "B": "dev"}
    assert first["evidence"] is False and second["evidence"] is False
    assert not (tmp_path / "out" / "run-01" / "rejudge-noev-1" / "EVIDENCE.md").exists()
    # The stub always prefers A, so the two positions disagree by the full 5 points.
    assert first["result"]["dev"]["total"] == 26 and second["result"]["dev"]["total"] == 21

    summary = subprocess.run(
        [sys.executable, str(SUMMARIZER), str(tmp_path / "out")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    assert summary.returncode == 0, summary.stdout + summary.stderr
    assert "评委信度" in summary.stdout
    assert "dev 在 A 时差值均值 +5.00" in summary.stdout
    assert "在 B 时 -5.00" in summary.stdout


def test_summarizer_pools_runs(tmp_path: Path) -> None:
    assert run_runner(tmp_path, "--runs", "2").returncode == 0

    result = subprocess.run(
        [sys.executable, str(SUMMARIZER), str(tmp_path / "out")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "轮数：2" in result.stdout
    assert "配对差值中位数" in result.stdout

    summary = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summary["runs"] == 2
    assert summary["sides"]["turns"]["dev"] == [2, 2]
    assert summary["judge"]["wins"] + summary["judge"]["ties"] + summary["judge"]["losses"] == 2
    # Two rounds of two sides ($0.025 each with the reviewer) plus two judges at $0.02.
    assert summary["cost"]["sessions"] == pytest.approx(0.10)
    assert summary["cost"]["judge"] == pytest.approx(0.04)

    # A pooled summary written elsewhere gets its own JSON next to it.
    pooled = tmp_path / "pooled.md"
    result = subprocess.run(
        [sys.executable, str(SUMMARIZER), str(tmp_path / "out"), "--out", str(pooled)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(pooled.with_suffix(".json").read_text(encoding="utf-8"))["runs"] == 2
    assert not (tmp_path / "summary.json").exists()


def test_dry_run_touches_nothing(tmp_path: Path) -> None:
    result = run_runner(tmp_path, "--dry-run", "--runs", "3")

    assert result.returncode == 0
    assert "run 1: dev -> openspec" in result.stdout
    assert "run 2: openspec -> dev" in result.stdout
    assert not (tmp_path / "repos").exists()
    assert not (tmp_path / "out").exists()


def test_dry_run_without_root_creates_no_temp_dir() -> None:
    import tempfile

    before = set(Path(tempfile.gettempdir()).glob("dcu-ab-*"))
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--dry-run", "--pi", sys.executable],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(Path(tempfile.gettempdir()).glob("dcu-ab-*")) == before


def test_missing_fixture_is_a_usage_error(tmp_path: Path) -> None:
    result = run_runner(tmp_path, "--fixture", str(tmp_path / "absent"))

    assert result.returncode == 2
    assert "fixture" in result.stderr
