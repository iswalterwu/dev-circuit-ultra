"""Make the dev-circuit-ultra script importable by the tests."""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "dev-circuit-ultra" / "scripts"))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
