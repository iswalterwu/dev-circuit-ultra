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
import json, subprocess, sys
from pathlib import Path

argv = sys.argv[1:]
session_dir = Path(argv[argv.index("--session-dir") + 1])
prompt = sys.stdin.read()
session_dir.mkdir(parents=True, exist_ok=True)

USAGE = {"input": 1000, "output": 500, "cacheRead": 10000, "cacheWrite": 0,
         "totalTokens": 11500,
         "cost": {"input": 0.001, "output": 0.002, "cacheRead": 0.003,
                  "cacheWrite": 0.0, "total": 0.01}}

with open(session_dir / "session.jsonl", "w", encoding="utf-8") as log:
    for role, text in (("user", prompt[:40]), ("assistant", "first step"), ("assistant", "second step")):
        message = {"role": role, "content": text, "timestamp": 1}
        if role == "assistant":
            message["usage"] = dict(USAGE)
        print(json.dumps({"type": "message_end", "message": message}, ensure_ascii=False), file=log)

if "键名固定" in prompt:
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
            assert record["turns"] == 2
            assert record["input"] == 2000 and record["output"] == 1000
            assert record["cache_read"] == 20000
            assert record["cost"] == pytest.approx(0.02)
            assert len(record["diff"]["commits"]) == 1

        assert run["judge"]["parsed"] is True
        mapping = run["judge"]["mapping"]
        assert sorted(mapping.values()) == ["dev", "openspec"]
        # A scores 26 and B scores 21 in the stub; the mapping decides who owns which.
        assert run["judge"]["result"]["dev"]["total"] == (26 if mapping["A"] == "dev" else 21)
        assert run["judge"]["result"]["openspec"]["total"] == (21 if mapping["A"] == "dev" else 26)
        assert run["judge"]["verdict"] == "A 收尾更干净"

    judge_text = (tmp_path / "out" / "run-01" / "judge" / "judge.md").read_text(encoding="utf-8")
    assert "```json" in judge_text
    assert (tmp_path / "out" / "run-01" / "judge" / "A").is_dir()
    assert not (tmp_path / "out" / "run-01" / "judge" / "A" / ".git").exists()


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


def test_dry_run_touches_nothing(tmp_path: Path) -> None:
    result = run_runner(tmp_path, "--dry-run", "--runs", "3")

    assert result.returncode == 0
    assert "run 1: dev -> openspec" in result.stdout
    assert "run 2: openspec -> dev" in result.stdout
    assert not (tmp_path / "repos").exists()
    assert not (tmp_path / "out").exists()


def test_missing_fixture_is_a_usage_error(tmp_path: Path) -> None:
    result = run_runner(tmp_path, "--fixture", str(tmp_path / "absent"))

    assert result.returncode == 2
    assert "fixture" in result.stderr
