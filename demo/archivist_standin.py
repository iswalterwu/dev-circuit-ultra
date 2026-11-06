"""Deterministic stand-in for dev-circuit-archivist in the demo.

The real archivist is an agent in a separate container. This script exists so the
demo can exercise the ledger protocol without an LLM or a second agent runtime.
It writes only to the ledger, never to the project.
"""

import argparse
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--feature", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--discarded", default="[]")
    parser.add_argument("--commit", default="")
    parser.add_argument("--constraints", default="[]")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    entry = {
        "id": now.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3),
        "ts": now.isoformat().replace("+00:00", "Z"),
        "project": Path(args.project).name,
        "feature": args.feature,
        "kind": args.kind,
        "commit": args.commit or None,
        "decision": args.decision,
        "discarded": json.loads(args.discarded),
        "constraints": json.loads(args.constraints),
        "reason": "demo",
        "source": "demo",
        "human_only": True,
    }
    target = Path(args.ledger) / "entries" / entry["project"] / f"{args.feature}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"RECORDED {entry['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
