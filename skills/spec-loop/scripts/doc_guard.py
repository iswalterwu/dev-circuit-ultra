"""doc_guard v0.1.0

用途：只禁止，不要求；检查文档中的历史记账内容、禁止路径和断链。
用法：python doc_guard.py [--root DIR] [--json]
退出码：0 无问题；1 有问题；2 根目录不存在或参数错误。
本文件来自 spec-loop 仓库，项目里不要修改，升级时整体覆盖。
"""

import argparse
import fnmatch
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


VERSION = "0.1.0"

BOOKKEEPING_PHRASES = (
    "轮次记录",
    "决策台账",
    "输入清单",
    "冻结对象",
    "基线提交",
    "固定提交",
    "BUDGET_",
    "SPEC_FROZEN",
    "via anthropic",
    "via openai",
    "via deepseek",
    "已移植",
    "移植日期",
    "原文快照",
)

SKIPPED_DIRS = frozenset({
    ".git", "node_modules", "dist", "build", ".venv", "venv",
    "__pycache__", ".pytest_cache",
})
FORBIDDEN_DIRS = frozenset({
    "docs/decisions", "docs/adr", "docs/maintenance", "docs/superpowers",
    "openspec/changes/archive",
})
FORBIDDEN_SPEC_FILES = frozenset({"plan.md", "tasks.md", "checklist.md", "review.md"})

DECISION_ID = re.compile(r"\b(?:D-\d{3}|ADR-\d+)\b")
LONG_HASH = re.compile(r"\b[0-9a-f]{32,64}\b")
SHORT_HASH = re.compile(r"(?<![#\w-])[0-9a-f]{7,12}(?![\w-])")
INLINE_LINK = re.compile(r"\[[^\]\n]*\]\(([^)\n]+)\)")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    message: str


def _is_forbidden_dir(relative: Path) -> bool:
    parts = relative.parts
    return relative.as_posix() in FORBIDDEN_DIRS or (
        len(parts) >= 2 and parts[0] in {"docs", "specs"} and parts[-1] == "history"
    )


def _is_forbidden_file(relative: Path) -> bool:
    parts = relative.parts
    return (
        len(parts) == 1 and fnmatch.fnmatchcase(relative.name, "HANDOFF*.md")
    ) or (
        len(parts) == 3 and parts[0] == "specs" and parts[-1] in FORBIDDEN_SPEC_FILES
    )


def _is_scanned_doc(relative: Path) -> bool:
    parts = relative.parts
    return (
        relative.suffix == ".md" and (
            len(parts) == 1 or (len(parts) >= 2 and parts[0] in {"docs", "specs", "design"})
        )
    ) or (relative.name == "README.md" and len(parts) in {2, 3})


def _walk(root: Path, directory: Path, findings: list[Finding]) -> list[Path]:
    documents: list[Path] = []
    for path in sorted(directory.iterdir()):
        relative = path.relative_to(root)
        if path.is_dir():
            if path.name in SKIPPED_DIRS:
                continue
            if _is_forbidden_dir(relative):
                findings.append(Finding("forbidden-path", relative.as_posix(), 0, "禁止的目录"))
                continue
            documents.extend(_walk(root, path, findings))
        elif path.is_file():
            if _is_forbidden_file(relative):
                findings.append(Finding("forbidden-path", relative.as_posix(), 0, "禁止的文件"))
            if _is_scanned_doc(relative):
                documents.append(path)
    return documents


def _is_absolute_target(target: str) -> bool:
    return (target.startswith("\\") or PurePosixPath(target).is_absolute()
            or PureWindowsPath(target).is_absolute())


def _scan_links(line: str, document: Path, root: Path, number: int) -> list[Finding]:
    findings: list[Finding] = []
    relative = document.relative_to(root).as_posix()
    for match in INLINE_LINK.finditer(line):
        target = match.group(1)
        if (target.startswith("#") or target.lower().startswith(("http:", "https:", "mailto:"))
                or _is_absolute_target(target)):
            continue
        location = re.split(r"[?#]", target, maxsplit=1)[0]
        if location and not (document.parent / location).exists():
            findings.append(Finding("broken-link", relative, number, f"链接目标不存在：{target}"))
    return findings


def _scan_document(document: Path, root: Path) -> list[Finding]:
    findings: list[Finding] = []
    relative = document.relative_to(root).as_posix()
    fence_char = ""
    fence_length = 0
    for number, line in enumerate(document.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        for match in DECISION_ID.finditer(line):
            findings.append(Finding("decision-id", relative, number, f"决策编号：{match.group()}"))
        for match in LONG_HASH.finditer(line):
            findings.append(Finding("long-hash", relative, number, f"长哈希：{match.group()}"))
        for match in SHORT_HASH.finditer(line):
            value = match.group()
            if any(char.isdigit() for char in value) and any(char.isalpha() for char in value):
                findings.append(Finding("short-hash", relative, number, f"短哈希：{value}"))
        for phrase in BOOKKEEPING_PHRASES:
            if phrase in line:
                findings.append(Finding("bookkeeping-phrase", relative, number, f"记账短语：{phrase}"))

        fence = FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if not fence_char:
                fence_char, fence_length = marker[0], len(marker)
            elif (marker[0] == fence_char and len(marker) >= fence_length
                  and not line[fence.end():].strip()):
                fence_char, fence_length = "", 0
            continue
        if not fence_char:
            findings.extend(_scan_links(line, document, root, number))
    return findings


def scan(root: Path) -> list[Finding]:
    """Report forbidden paths and content under a project root."""
    root = Path(root)
    findings: list[Finding] = []
    documents = _walk(root, root, findings)
    for document in documents:
        findings.extend(_scan_document(document, root))
    return sorted(findings, key=lambda item: (item.path, item.line, item.rule, item.message))


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Check project documentation for forbidden content")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root (default: current directory)")
    parser.add_argument("--json", action="store_true", help="print findings as JSON")
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
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
