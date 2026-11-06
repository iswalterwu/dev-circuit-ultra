import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run(
        [sys.executable, "records.py", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_single_record_json_still_works():
    result = run("export", "--id", "2")
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record == {"id": 2, "name": 'Grace "Amazing" Hopper', "amount": 950}
