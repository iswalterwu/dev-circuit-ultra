import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh 7 is required")
def test_demo_end_to_end():
    result = subprocess.run(
        [sys.executable, str(ROOT / "demo" / "run_demo.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS dev-circuit-ultra demo" in result.stdout
