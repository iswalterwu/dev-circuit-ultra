"""records: a tiny JSON records CLI used by the spec-loop benchmark."""

import argparse
import json
from pathlib import Path

DATA = Path(__file__).with_name("records.json")


def load_records(path=DATA):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def export_record(record):
    return json.dumps(record, ensure_ascii=False)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="records")
    sub = parser.add_subparsers(dest="command", required=True)

    exp = sub.add_parser("export", help="export a record as JSON")
    exp.add_argument("--id", type=int, required=True)
    exp.add_argument("--data", default=str(DATA))
    exp.add_argument("-o", "--output")

    args = parser.parse_args(argv)
    records = load_records(args.data)
    match = [r for r in records if r["id"] == args.id]
    if not match:
        parser.error(f"record {args.id} not found")

    text = export_record(match[0])
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
