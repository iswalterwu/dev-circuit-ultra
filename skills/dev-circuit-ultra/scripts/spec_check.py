"""spec_check v0.4.0

用途：只检查要求编号是否完整一致，不要求写满任何字段。
用法：python spec_check.py [--root DIR] [--json] [--report] [--ignore GLOB]... [--ignore-rule RULE]...
退出码：0 无错误；1 有错误；2 根目录不存在或参数错误。
--report 列出未被测试引用和标为演示的要求，不影响退出码。
测试引用按 test/tests/__tests__ 目录或常见测试文件名识别；普通源码不算证明。
--json --report 将报告写到标准错误，标准输出保持 JSON 数组。
本文件来自 dev-circuit-ultra 仓库，项目里不要修改，升级时整体覆盖。

认的写法（不强制某一种 Markdown 形状）：
  文件头        代号：DEMO / Code: DEMO / capability: DEMO
  要求          - DEMO-1：… / * DEMO-1: … / + DEMO-1：… / 1. DEMO-1：… / | DEMO-1 | … |
  规格变化      二级标题 规格变化 / Spec changes / Specification changes / Requirement changes
  变化条目      新增|修改|删除 / add|added|modify|modified|change|changed|remove|removed|delete|deleted
  已合并        标题改成 规格变化（已合并）/ Spec changes (merged) 后不再检查本节
忽略白名单：--ignore GLOB、项目根目录的 .dcuignore、--ignore-rule RULE。
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


VERSION = "0.4.0"
IGNORE_FILE = ".dcuignore"

RULES = (
    "bad-header",
    "dup-id",
    "bad-change",
    "conflict",
    "unknown-target",
    "unknown-code",
    "id-exists",
    "dangling-ref",
)

SKIPPED_DIRS = frozenset({
    ".git", "node_modules", "dist", "build", ".venv", "venv",
    "__pycache__", ".pytest_cache",
})
# The vendored guards describe the accepted formats, so their own examples must
# not count as references to project requirements.
VENDORED_GUARDS = frozenset({"scripts/doc_guard.py", "scripts/spec_check.py"})
CODE_EXTENSIONS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue",
    ".go", ".rs", ".java", ".kt", ".cs", ".rb", ".sh", ".ps1",
})
BULLET = r"^(?:[-*+]|\d+[.)])\s+"
IDENTIFIER = r"(?:[A-Z]{2,8}-\d+|AC-\d{3}-\d+)"
HEADER_PREFIX = re.compile(r"^(?i:代号|code|capability)\s*[：:]")
HEADER = re.compile(r"^(?i:代号|code|capability)\s*[：:]\s*([A-Z]{2,8})\s*$")
DEFINITION = re.compile(BULLET + r"(?:\*\*)?(" + IDENTIFIER + r")(?:\*\*)?\s*[：:]\s*")
TABLE_DEFINITION = re.compile(r"^\|\s*(?:\*\*)?(" + IDENTIFIER + r")(?:\*\*)?\s*\|")
CHANGE = re.compile(
    BULLET + r"(新增|修改|删除|add|added|modify|modified|change|changed"
    r"|remove|removed|delete|deleted)\s+([A-Z]{2,8}-\d+|[A-Z]{2,8}:AC-\d{3}-\d+)\b",
    re.IGNORECASE,
)
DEMONSTRATION = re.compile(r"^\s+- (?:证明[：:].*演示|demonstrated by[：:])")
ACTIVE_SECTIONS = frozenset(
    section.casefold() for section in (
        "## 规格变化",
        "## Spec changes",
        "## Specification changes",
        "## Requirement changes",
    )
)
MERGED_HINT = "（如果是本卡收尾已合并，把本节标题改为'## 规格变化（已合并）'）"
BAD_CHANGE = ("规格变化条目格式不对：应以 '- 新增 <编号>'、'- 修改 <编号>' 或 '- 删除 <编号>' 开头"
              "（英文可用 '- add <ID>' 等）")


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


def _fold(value: str) -> str:
    """Windows paths are case-insensitive, POSIX paths are not."""
    return value.casefold() if os.name == "nt" else value


def path_is_ignored(relative: str, patterns) -> bool:
    """Match a posix relative path against ignore globs (see doc_guard for rules)."""
    candidate = _fold(relative.replace("\\", "/").strip("/"))
    for raw in patterns:
        pattern = _fold(str(raw).replace("\\", "/").strip().lstrip("./"))
        if not pattern:
            continue
        if "/" in pattern:
            if fnmatch.fnmatchcase(candidate, pattern):
                return True
            prefix = pattern.rstrip("/")
            if candidate == prefix or candidate.startswith(prefix + "/"):
                return True
        else:
            if fnmatch.fnmatchcase(candidate, pattern):
                return True
            if any(fnmatch.fnmatchcase(part, pattern) for part in candidate.split("/")):
                return True
    return False


def load_ignore_file(path: Path) -> list[str]:
    patterns: list[str] = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            patterns.append(entry)
    return patterns


def _ignores(root: Path, ignores, ignore_file, use_ignore_file: bool) -> list[str]:
    patterns = list(ignores)
    if use_ignore_file:
        candidate = Path(ignore_file) if ignore_file else root / IGNORE_FILE
        if candidate.is_file():
            patterns.extend(load_ignore_file(candidate))
    return patterns


def _normalized_action(verb: str) -> str:
    lowered = verb.lower()
    if verb == "新增" or lowered in {"add", "added"}:
        return "新增"
    if verb == "修改" or lowered in {"modify", "modified", "change", "changed"}:
        return "修改"
    return "删除"


def _requirements(root: Path, patterns=()):
    findings: list[Finding] = []
    codes: dict[str, str] = {}
    requirements: dict[str, _Requirement] = {}
    legacy: set[str] = set()
    demonstrations: set[str] = set()
    for path in sorted((root / "docs" / "requirements").glob("*.md")):
        if path.name == "README.md":
            continue
        relative = path.relative_to(root).as_posix()
        if path_is_ignored(relative, patterns):
            continue
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        headers = [(number, line) for number, line in enumerate(lines, 1)
                   if HEADER_PREFIX.match(line)]
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
            match = DEFINITION.match(line) or TABLE_DEFINITION.match(line)
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


def _changes(root: Path, findings: list[Finding], patterns=()):
    for path in sorted((root / "specs").glob("*/spec.md")):
        relative = path.relative_to(root).as_posix()
        if path_is_ignored(relative, patterns):
            continue
        in_section = False
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if line.startswith("## "):
                in_section = line.strip().casefold() in ACTIVE_SECTIONS
            elif in_section and re.match(BULLET, line):
                if match := CHANGE.match(line):
                    yield relative, number, _normalized_action(match.group(1)), match.group(2)
                else:
                    findings.append(Finding("bad-change", relative, number, BAD_CHANGE))


def _references(root: Path, codes, patterns=()):
    if not codes:
        return
    alternation = "|".join(re.escape(code) for code in sorted(codes))
    pattern = re.compile(
        r"\b(?:" + alternation + r")-\d+\b"                # DEMO-1
        + r"|\b(?:" + alternation + r"):AC-\d{3}-\d+\b"      # legacy <CODE>:AC-xxx-y
    )
    for directory, dirs, files in os.walk(root):
        base = Path(directory)
        dirs[:] = sorted(
            name for name in dirs
            if name not in SKIPPED_DIRS
            and not path_is_ignored((base / name).relative_to(root).as_posix(), patterns)
        )
        for name in sorted(files):
            path = base / name
            if path.suffix.lower() not in CODE_EXTENSIONS:
                continue
            relative = path.relative_to(root).as_posix()
            if relative in VENDORED_GUARDS or path_is_ignored(relative, patterns):
                continue
            for number, line in enumerate(
                    path.read_text(encoding="utf-8-sig", errors="ignore").splitlines(), 1):
                for match in pattern.finditer(line):
                    yield path.relative_to(root), number, match.group()


def _is_test(path: Path) -> bool:
    return (
        any(part.lower() in {"test", "tests", "__tests__"} for part in path.parts[:-1])
        or path.stem.startswith("test_")
        or path.stem.endswith(("_test", ".test", ".spec", "Test", "Tests", "Spec"))
    )


def scan(root: Path, ignores=(), ignored_rules=(), ignore_file=None,
         use_ignore_file: bool = True) -> list[Finding]:
    """Check declared IDs, in-flight changes and references in source files."""
    root = Path(root)
    patterns = _ignores(root, ignores, ignore_file, use_ignore_file)
    findings, codes, requirements, legacy, _ = _requirements(root, patterns)
    added: set[str] = set()
    changed_by: dict[str, str] = {}
    for path, number, action, identifier in _changes(root, findings, patterns):
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
    for path, number, identifier in _references(root, codes, patterns):
        if identifier in requirements or identifier in added or identifier in legacy:
            continue
        findings.append(Finding("dangling-ref", path.as_posix(), number, f"引用的编号不存在：{identifier}"))

    ignored = set(ignored_rules)
    if ignored:
        findings = [finding for finding in findings if finding.rule not in ignored]
    return sorted(findings, key=lambda item: (item.path, item.line, item.rule, item.message))


def report(root: Path, ignores=(), ignore_file=None, use_ignore_file: bool = True) -> list[str]:
    """Report test coverage and demonstration IDs without enforcing coverage."""
    root = Path(root)
    patterns = _ignores(root, ignores, ignore_file, use_ignore_file)
    _, codes, requirements, _, demonstrations = _requirements(root, patterns)
    tested = {identifier for path, _, identifier in _references(root, codes, patterns) if _is_test(path)}
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
    parser.add_argument("--ignore", action="append", default=[], metavar="GLOB",
                        help="ignore a relative path glob (repeatable)")
    parser.add_argument("--ignore-rule", action="append", default=[], choices=RULES,
                        help="ignore one rule (repeatable)")
    parser.add_argument("--ignore-file", type=Path, default=None,
                        help=f"read extra globs from this file (default: <root>/{IGNORE_FILE})")
    parser.add_argument("--no-ignore-file", action="store_true",
                        help=f"do not read {IGNORE_FILE}")
    parser.add_argument("--list-rules", action="store_true", help="print rule names and exit")
    parser.add_argument("--version", action="version", version=f"spec_check {VERSION}")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)

    if args.list_rules:
        for rule in RULES:
            print(rule)
        return 0
    if not args.root.is_dir():
        return 2
    if args.ignore_file is not None and not args.ignore_file.is_file():
        print(f"--ignore-file 指向的文件不存在：{args.ignore_file}", file=sys.stderr)
        return 2
    findings = scan(args.root, args.ignore, args.ignore_rule, args.ignore_file,
                    not args.no_ignore_file)
    if args.json:
        print(json.dumps([asdict(finding) for finding in findings], ensure_ascii=False))
    else:
        for finding in findings:
            print(f"{finding.path}:{finding.line}: [{finding.rule}] {finding.message}")
    if args.report:
        for line in report(args.root, args.ignore, args.ignore_file, not args.no_ignore_file):
            print(line, file=sys.stderr if args.json else sys.stdout)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
