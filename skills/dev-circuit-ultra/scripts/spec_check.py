"""spec_check v0.3.0

用途：只检查要求编号是否完整一致，不要求写满任何字段。
用法：python spec_check.py [--root DIR] [--json] [--report]
退出码：0 无错误；1 有错误；2 根目录不存在或参数错误。
--report 列出未被测试引用和标为演示的要求，不影响退出码。
测试引用按 test/tests/__tests__ 目录或常见测试文件名识别；普通源码不算证明。
--json --report 将报告写到标准错误，标准输出保持 JSON 数组。
本文件来自 dev-circuit-ultra 仓库，项目里不要修改，升级时整体覆盖。
"""

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


VERSION = "0.3.0"
SKIPPED_DIRS = frozenset({
    ".git", "node_modules", "dist", "build", ".venv", "venv",
    "__pycache__", ".pytest_cache",
})
CODE_EXTENSIONS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue",
    ".go", ".rs", ".java", ".kt", ".cs", ".rb", ".sh", ".ps1",
})
HEADER = re.compile(r"^代号[：:]\s*([A-Z]{2,8})\s*$")
DEFINITION = re.compile(r"^- ([A-Z]{2,8}-\d+|AC-\d{3}-\d+)[：:]")
CHANGE = re.compile(r"^- (新增|修改|删除) ([A-Z]{2,8}-\d+|[A-Z]{2,8}:AC-\d{3}-\d+)\b")
DEMONSTRATION = re.compile(r"^\s+- 证明[：:].*演示")
MERGED_HINT = "（如果是本卡收尾已合并，把本节标题改为'## 规格变化（已合并）'）"


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    message: str


@dataclass(frozen=True)
class _Requirement:
    id: str
    path: str
    line: int


def _requirements(root: Path):
    findings: list[Finding] = []
    codes: dict[str, str] = {}
    requirements: dict[str, _Requirement] = {}
    legacy: set[str] = set()
    demonstrations: set[str] = set()
    for path in sorted((root / "docs" / "requirements").glob("*.md")):
        if path.name == "README.md":
            continue
        relative = path.relative_to(root).as_posix()
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        headers = [(number, line) for number, line in enumerate(lines, 1)
                   if re.match(r"^代号[：:]", line)]
        code = None
        if len(headers) == 1 and (match := HEADER.fullmatch(headers[0][1])):
            code = match.group(1)
            if code in codes:
                findings.append(Finding("bad-header", relative, headers[0][0],
                                        f"代号重复：{code}（已在 {codes[code]} 声明）"))
            else:
                codes[code] = relative
        else:
            findings.append(Finding("bad-header", relative, headers[0][0] if headers else 1,
                                    "文件头须有一个代号，由 2–8 个大写字母组成"))

        file_legacy: set[str] = set()
        current = None
        for number, line in enumerate(lines, 1):
            match = DEFINITION.match(line)
            if match:
                identifier = match.group(1)
                current = None
                if identifier.startswith("AC-") and identifier.count("-") == 2:
                    if identifier in file_legacy:
                        findings.append(Finding("dup-id", relative, number, f"编号重复：{identifier}"))
                    file_legacy.add(identifier)
                    if code:
                        legacy.add(f"{code}:{identifier}")
                else:
                    current = identifier
                    if identifier.split("-", 1)[0] != code:
                        findings.append(Finding("bad-header", relative, number,
                                                f"编号代号与文件头不符：{identifier}"))
                    if identifier in requirements:
                        findings.append(Finding("dup-id", relative, number, f"编号重复：{identifier}"))
                    else:
                        requirements[identifier] = _Requirement(identifier, relative, number)
            elif current and DEMONSTRATION.match(line):
                demonstrations.add(current)
            elif line and not line[0].isspace():
                current = None
    return findings, codes, requirements, legacy, demonstrations


def _changes(root: Path, findings: list[Finding]):
    for path in sorted((root / "specs").glob("*/spec.md")):
        relative = path.relative_to(root).as_posix()
        in_section = False
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.startswith("## "):
                in_section = line.strip() == "## 规格变化"
            elif in_section and line.startswith("- "):
                if match := CHANGE.match(line):
                    yield relative, number, match.group(1), match.group(2)
                else:
                    findings.append(Finding("bad-change", relative, number,
                                            "规格变化条目格式不对：应以 '- 新增 <编号>'、"
                                            "'- 修改 <编号>' 或 '- 删除 <编号>' 开头"))


def _references(root: Path, codes):
    if not codes:
        return
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(code) for code in sorted(codes)) + r")-\d+\b")
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name not in SKIPPED_DIRS)
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix.lower() not in CODE_EXTENSIONS:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8-sig", errors="ignore").splitlines(), 1):
                for match in pattern.finditer(line):
                    yield path.relative_to(root), number, match.group()


def _is_test(path: Path) -> bool:
    return (
        any(part.lower() in {"test", "tests", "__tests__"} for part in path.parts[:-1])
        or path.stem.startswith("test_")
        or path.stem.endswith(("_test", ".test", ".spec", "Test", "Tests", "Spec"))
    )


def scan(root: Path) -> list[Finding]:
    """Check declared IDs, in-flight changes and references in source files."""
    root = Path(root)
    findings, codes, requirements, legacy, _ = _requirements(root)
    added: set[str] = set()
    changed_by: dict[str, str] = {}
    for path, number, action, identifier in _changes(root, findings):
        if identifier in changed_by and changed_by[identifier] != path:
            findings.append(Finding("conflict", path, number,
                                    f"编号同时出现在另一张卡：{identifier}（{changed_by[identifier]}）"))
        else:
            changed_by[identifier] = path
        if action == "新增":
            if ":" in identifier:
                findings.append(Finding("unknown-target", path, number,
                                        f"新增要求须使用代号-数字：{identifier}"))
            elif identifier.split("-", 1)[0] not in codes:
                findings.append(Finding("unknown-code", path, number, f"代号未声明：{identifier}"))
            elif identifier in requirements:
                findings.append(Finding("id-exists", path, number, f"编号已存在：{identifier}{MERGED_HINT}"))
            else:
                added.add(identifier)
        elif identifier not in requirements and identifier not in legacy:
            hint = MERGED_HINT if action == "删除" else ""
            findings.append(Finding("unknown-target", path, number, f"目标编号不存在：{identifier}{hint}"))
    for path, number, identifier in _references(root, codes):
        if identifier not in requirements and identifier not in added:
            findings.append(Finding("dangling-ref", path.as_posix(), number, f"引用的编号不存在：{identifier}"))
    return sorted(findings, key=lambda item: (item.path, item.line, item.rule, item.message))


def report(root: Path) -> list[str]:
    """Report test coverage and demonstration IDs without enforcing coverage."""
    root = Path(root)
    _, codes, requirements, _, demonstrations = _requirements(root)
    tested = {identifier for path, _, identifier in _references(root, codes) if _is_test(path)}
    lines: list[str] = []
    for identifier in sorted(requirements):
        if identifier not in tested and identifier not in demonstrations:
            lines.append(f"未被测试引用：{identifier}")
        if identifier in demonstrations:
            lines.append(f"演示要求：{identifier}")
    return lines


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Check requirement IDs and references")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
    parser.add_argument("--report", action="store_true", help="report test references and demonstrations")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    if not args.root.is_dir():
        return 2
    findings = scan(args.root)
    if args.json:
        print(json.dumps([asdict(finding) for finding in findings], ensure_ascii=False))
    else:
        for finding in findings:
            print(f"{finding.path}:{finding.line}: [{finding.rule}] {finding.message}")
    if args.report:
        for line in report(args.root):
            print(line, file=sys.stderr if args.json else sys.stdout)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
