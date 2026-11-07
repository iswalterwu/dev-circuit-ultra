"""Mechanical probes for a final `records` tree: exit codes, no model involved.

    python bench/probe.py <tree> [<tree> ...]      # markdown table, then one JSON line

The open runner records the same result for every side as `probes`. Each probe
runs `records.py` in a scratch copy of the tree:

- compatibility: `export --id 1` prints the fixture's record unchanged, and a
  decimal amount still exports;
- failure paths of `export` and of the command the session added: missing data
  file, malformed JSON, a JSON object instead of a list, an output path inside
  a missing directory.

A failure probe passes on a non-zero exit without a traceback. The added
command is read from `records.py --help` (`report` if there are several). A
probe the tree's CLI cannot express (no such command or option, or the bare
command itself fails) is not applicable and is counted apart from failures.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixture" / "records.json"
COPY_IGNORES = (".git", ".bench", "__pycache__", ".pytest_cache", ".venv", "node_modules")
SUBCOMMANDS = re.compile(r"\{([\w,-]+)\}")
NEW = "新命令"

# name, command ("export" or NEW), kind, option the probe needs, input file
PROBES = (
    ("export ok", "export", "compat", None, None),
    ("export 缺数据文件", "export", "fail", "--data", "nope.json"),
    ("export 坏 JSON", "export", "fail", "--data", "bad.json"),
    ("export 写不进去", "export", "fail", "output", None),
    ("export 小数金额", "export", "decimal", "--data", "decimal.json"),
    (f"{NEW} 缺数据文件", NEW, "fail", "--data", "nope.json"),
    (f"{NEW} 坏 JSON", NEW, "fail", "--data", "bad.json"),
    (f"{NEW} 非数组", NEW, "fail", "--data", "object.json"),
    (f"{NEW} 写不进去", NEW, "fail", "output", None),
)

INPUTS = {
    "bad.json": '[{"id": 1,',
    "object.json": '{"id": 1, "name": "x", "amount": 1}',
    "decimal.json": '[{"id": 1, "name": "x", "amount": 10.5}]',
}


def expected_export() -> str:
    record = next(item for item in json.loads(FIXTURE.read_text(encoding="utf-8")) if item["id"] == 1)
    return json.dumps(record, ensure_ascii=False)


def run(work: Path, *argv: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            [sys.executable, "records.py", *argv], cwd=work, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=60,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return None


def added_command(work: Path) -> str | None:
    done = run(work, "--help")
    match = SUBCOMMANDS.search(done.stdout if done else "")
    names = [name for name in (match.group(1).split(",") if match else []) if name != "export"]
    if "report" in names:
        return "report"
    return names[0] if names else None


def options(work: Path, command: str) -> dict[str, str | None]:
    done = run(work, command, "--help")
    text = done.stdout if done else ""
    output = "-o" if re.search(r"(^|[\s\[,])-o\b", text) else ("--output" if "--output" in text else None)
    return {"--data": "--data" if "--data" in text else None, "output": output}


def judge(kind: str, done: subprocess.CompletedProcess | None, expected: str) -> tuple[bool, str]:
    if done is None:
        return False, "超时"
    traceback = "Traceback" in done.stderr
    if kind == "compat":
        return done.returncode == 0 and done.stdout.strip() == expected, f"exit {done.returncode}"
    if kind == "decimal":
        return done.returncode == 0 and '"amount": 10.5' in done.stdout, f"exit {done.returncode}"
    if traceback:
        return False, "traceback"
    return done.returncode != 0, f"exit {done.returncode}"


def run_probes(tree: Path) -> dict:
    scratch = Path(tempfile.mkdtemp(prefix="dcu-probe-"))
    try:
        work = scratch / "tree"
        shutil.copytree(tree, work, ignore=shutil.ignore_patterns(*COPY_IGNORES))
        for name, content in INPUTS.items():
            (scratch / name).write_text(content, encoding="utf-8")
        command = added_command(work)
        flags = {"export": options(work, "export")}
        usable = {"export": True}
        if command:
            flags[NEW] = options(work, command)
            bare = run(work, command)
            usable[NEW] = bool(bare and bare.returncode == 0)
        expected = expected_export()

        results = []
        for name, target, kind, needs, source in PROBES:
            actual = "export" if target == "export" else command
            if actual is None or not usable.get(target):
                results.append({"probe": name, "ok": None,
                                "note": "没有新命令" if actual is None else f"`{actual}` 本身就失败"})
                continue
            argv = [actual] + (["--id", "1"] if actual == "export" else [])
            if needs:
                flag = flags[target][needs]
                if flag is None:
                    results.append({"probe": name, "ok": None, "note": f"`{actual}` 没有 {needs}"})
                    continue
                argv += [flag, str(scratch / "missing-dir" / "out.txt") if needs == "output"
                         else str(scratch / source)]
            done = run(work, *argv)
            if done is not None and ("invalid choice" in done.stderr or "unrecognized arguments" in done.stderr):
                results.append({"probe": name, "ok": None, "note": "参数不被接受"})
                continue
            ok, note = judge(kind, done, expected)
            results.append({"probe": name, "ok": ok, "note": note})
        applicable = [item for item in results if item["ok"] is not None]
        return {"tree": str(tree), "command": command,
                "passed": sum(1 for item in applicable if item["ok"]),
                "applicable": len(applicable), "total": len(PROBES), "results": results}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def label(tree: str) -> str:
    path = Path(tree).resolve()
    if path.parent.name == "final":
        return f"{path.parents[2].name}/{path.parents[1].name}/{path.name}"
    return path.name


def table(reports: list[dict]) -> str:
    lines = ["| 探针 | " + " | ".join(label(report["tree"]) for report in reports) + " |",
             "|---|" + "---|" * len(reports),
             f"| {NEW} | " + " | ".join(f"`{report['command']}`" if report["command"] else "—"
                                       for report in reports) + " |"]
    for index, (name, *_rest) in enumerate(PROBES):
        cells = []
        for report in reports:
            item = report["results"][index]
            cells.append("n/a" if item["ok"] is None else ("✓" if item["ok"] else f"✗ {item['note']}"))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append("| **通过** | " + " | ".join(
        f"**{report['passed']}/{report['applicable']}**" for report in reports) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    trees = []
    for item in (sys.argv[1:] if argv is None else argv):
        # PowerShell and cmd hand the pattern over unexpanded; matches without records.py are skipped.
        matches = sorted(glob.glob(item)) if not Path(item).exists() and any(c in item for c in "*?[") else []
        trees += [Path(match) for match in matches if (Path(match) / "records.py").is_file()] or [Path(item)]
    missing = [str(tree) for tree in trees if not (tree / "records.py").is_file()]
    if not trees or missing:
        print(f"用法：python bench/probe.py <含 records.py 的目录> ...；找不到：{', '.join(missing) or '（没给目录）'}",
              file=sys.stderr)
        return 2
    reports = [run_probes(tree) for tree in trees]
    print(table(reports))
    print()
    print(json.dumps([{key: report[key] for key in ("tree", "command", "passed", "applicable")}
                      for report in reports], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
