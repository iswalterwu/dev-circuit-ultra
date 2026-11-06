"""Acceptance tests for the 20-check report feature. Not visible to the agents."""

import csv
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


def table_rows(text):
    return [[cell.strip() for cell in line.split("\t")] for line in text.strip().splitlines()]


def csv_rows(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def test_01_table_default():
    result = run("report")
    assert result.returncode == 0, result.stderr
    rows = table_rows(result.stdout)
    assert rows[0] == ["id", "name", "amount"]
    assert [row[0] for row in rows[1:]] == ["1", "2", "3", "4"]


def test_02_table_values():
    result = run("report")
    rows = table_rows(result.stdout)
    assert rows[1] == ["1", "Ada Lovelace", "1200"]
    assert rows[3] == ["3", "Katherine Johnson", "1430"]


def test_03_csv_default(tmp_path):
    out = tmp_path / "all.csv"
    result = run("report", "--format", "csv", "-o", str(out))
    assert result.returncode == 0, result.stderr
    rows = csv_rows(out)
    assert rows[0] == ["id", "name", "amount"]
    assert [row[0] for row in rows[1:]] == ["1", "2", "3", "4"]


def test_04_csv_escapes(tmp_path):
    out = tmp_path / "all.csv"
    result = run("report", "--format", "csv", "-o", str(out))
    assert result.returncode == 0, result.stderr
    raw = out.read_text(encoding="utf-8")
    assert '"Grace ""Amazing"" Hopper"' in raw
    assert '"O\'Brien, Inc."' in raw
    rows = csv_rows(out)
    assert rows[2][1] == 'Grace "Amazing" Hopper'
    assert rows[4][1] == "O'Brien, Inc."


def test_05_json_default():
    result = run("report", "--format", "json")
    assert result.returncode == 0, result.stderr
    records = json.loads(result.stdout)
    assert [r["id"] for r in records] == [1, 2, 3, 4]
    assert records[1]["name"] == 'Grace "Amazing" Hopper'


def test_06_sort_id():
    result = run("report", "--sort", "id", "--format", "json")
    assert [r["id"] for r in json.loads(result.stdout)] == [1, 2, 3, 4]


def test_07_sort_name():
    result = run("report", "--sort", "name", "--format", "json")
    names = [r["name"] for r in json.loads(result.stdout)]
    assert names == ["Ada Lovelace", 'Grace "Amazing" Hopper', "Katherine Johnson", "O'Brien, Inc."]


def test_08_sort_amount():
    result = run("report", "--sort", "amount", "--format", "json")
    assert [r["amount"] for r in json.loads(result.stdout)] == [780, 950, 1200, 1430]


def test_09_desc():
    result = run("report", "--sort", "amount", "--desc", "--format", "json")
    assert [r["amount"] for r in json.loads(result.stdout)] == [1430, 1200, 950, 780]


def test_10_filter():
    result = run("report", "--filter", "hopper", "--format", "json")
    records = json.loads(result.stdout)
    assert [r["id"] for r in records] == [2]


def test_11_min_amount():
    result = run("report", "--min-amount", "1000", "--format", "json")
    assert [r["id"] for r in json.loads(result.stdout)] == [1, 3]


def test_12_max_amount():
    result = run("report", "--max-amount", "1000", "--format", "json")
    assert [r["id"] for r in json.loads(result.stdout)] == [2, 4]


def test_13_limit():
    result = run("report", "--sort", "amount", "--limit", "2", "--format", "json")
    assert [r["id"] for r in json.loads(result.stdout)] == [4, 2]


def test_14_offset():
    result = run("report", "--sort", "amount", "--offset", "3", "--format", "json")
    assert [r["id"] for r in json.loads(result.stdout)] == [3]


def test_15_columns():
    result = run("report", "--columns", "id,name")
    rows = table_rows(result.stdout)
    assert rows[0] == ["id", "name"]
    assert rows[1] == ["1", "Ada Lovelace"]

    result = run("report", "--columns", "amount,id")
    rows = table_rows(result.stdout)
    assert rows[0] == ["amount", "id"]
    assert rows[1] == ["1200", "1"]


def test_16_total(tmp_path):
    result = run("report", "--total")
    rows = table_rows(result.stdout)
    assert rows[-1] == ["TOTAL", "", "4360"]

    out = tmp_path / "total.csv"
    result = run("report", "--format", "csv", "--total", "-o", str(out))
    assert result.returncode == 0, result.stderr
    assert csv_rows(out)[-1] == ["TOTAL", "", "4360"]


def test_17_output_file(tmp_path):
    out = tmp_path / "out.csv"
    result = run("report", "--format", "csv", "-o", str(out))
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert csv_rows(out)[0] == ["id", "name", "amount"]


def test_18_errors():
    for args in (
        ("report", "--sort", "nope"),
        ("report", "--columns", "nope"),
        ("report", "--limit", "-1"),
        ("report", "--offset", "-1"),
        ("report", "--min-amount", "x"),
    ):
        result = run(*args)
        assert result.returncode == 2, (args, result.returncode, result.stderr)
        assert result.stdout == ""
        assert result.stderr.strip()


def test_19_empty():
    result = run("report", "--filter", "zzz")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "id\tname\tamount"

    result = run("report", "--filter", "zzz", "--format", "json")
    assert json.loads(result.stdout) == []


def test_20_legacy_export():
    result = run("export", "--id", "2")
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record == {"id": 2, "name": 'Grace "Amazing" Hopper', "amount": 950}
