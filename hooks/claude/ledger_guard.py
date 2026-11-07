#!/usr/bin/env python3
"""ledger-guard — Claude Code PreToolUse hook (dev-circuit-ultra)

Blocks tool calls that name the private ledger or the guard config itself.

Install: copy this file into <project>/.dev-circuit/hooks/ledger_guard.py and
register it in .claude/settings.json (see hooks/claude/settings.snippet.json):

  "PreToolUse": [
    {"matcher": "*", "hooks": [
      {"type": "command",
       "command": "python \\"<project>/.dev-circuit/hooks/ledger_guard.py\\""}
    ]}
  ]

Config, found by walking up from the hook's working directory:
  <project>/.dev-circuit/guard.json
  {"ledger": "D:\\\\ledgers\\\\my-app", "deny": ["../notes"], "allow": []}

Exit codes follow the Claude Code hook contract: 0 = allow, 2 = block with the
reason on stderr, 1 = non-blocking error. Pass --json to answer with a
permissionDecision payload instead of exit 2.

What this guarantees: the agent cannot reach the ledger through a tool call.
What it does not: the dev process can still walk the filesystem as the same OS
user. For a filesystem-level guarantee use docker/ or a separate OS user.
"""

import json
import os
import re
import sys
from pathlib import Path

CONFIG_DIR = ".dev-circuit"
CONFIG_NAME = "guard.json"
IS_WINDOWS = os.name == "nt"
MAX_DEPTH = 8
MAX_TOKENS = 64
TOKEN_SPLIT = re.compile(r"""[\s"'`;|&<>(){}\[\],]+""")


def normalize(value: str) -> str:
    text = str(value).strip().strip("\"'")
    if not text:
        return ""
    if text == "~" or text.startswith(("~/", "~\\")):
        text = str(Path.home() / text[1:].lstrip("/\\"))
    normalized = os.path.normpath(os.path.abspath(text))
    return normalized.lower() if IS_WINDOWS else normalized


def normalize_real(value: str) -> str:
    """Absolute, symlink-resolved, case-folded on Windows. Empty when unusable."""
    try:
        resolved = os.path.realpath(os.path.abspath(os.path.expanduser(value)))
    except (OSError, ValueError):
        return ""
    return resolved.lower() if IS_WINDOWS else resolved


def find_config(start: str | None) -> tuple[Path, Path] | None:
    """Return (config path, project root) by walking up from `start`."""
    directory = Path(os.path.abspath(start or os.getcwd()))
    for candidate_dir in [directory, *directory.parents]:
        candidate = candidate_dir / CONFIG_DIR / CONFIG_NAME
        if candidate.is_file():
            return candidate, candidate_dir
    return None


def load_guard(start: str | None) -> dict | None:
    found = find_config(start)
    if not found:
        return None
    config_path, project_root = found
    denied = {normalize(str(config_path))}
    denied_real = {normalize_real(str(config_path))}
    raw_entries: list[str] = []
    problem = None
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
        entries = [raw.get("ledger"), *(raw.get("deny") or [])]
        for entry in entries:
            if not isinstance(entry, str) or not entry.strip():
                continue
            absolute = entry if os.path.isabs(entry) or entry.startswith("~") \
                else str(project_root / entry)
            denied.add(normalize(absolute))
            resolved = normalize_real(absolute)
            if resolved:
                denied_real.add(resolved)
            raw_entries.append(entry)
    except (OSError, ValueError, AttributeError) as error:
        problem = str(error)
    denied_real.discard("")
    return {"config": str(config_path), "root": str(project_root),
            "denied": denied, "denied_real": denied_real,
            "raw": raw_entries, "problem": problem}


def collect_strings(value, out: list[str], depth: int = 0) -> list[str]:
    if depth > MAX_DEPTH:
        return out
    if isinstance(value, str):
        out.append(value)
        try:
            from urllib.parse import unquote

            out.append(unquote(value))
        except (ValueError, UnicodeDecodeError):
            pass
    elif isinstance(value, dict):
        for item in value.values():
            collect_strings(item, out, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            collect_strings(item, out, depth + 1)
    return out


def escapes(text: str, denied) -> bool:
    if not isinstance(text, str) or len(text) < 3:
        return False
    plain = text.lower() if IS_WINDOWS else text
    slashed_input = plain.replace("\\", "/")
    for target in denied:
        if target in plain:
            return True
        if target.replace("\\", "/") in slashed_input:
            return True
    return False


def candidate_texts(text: str):
    """The whole string, its unquoted form, and shell-ish tokens."""
    seen = {text}
    yield text
    for variant in (text.strip().strip("\"'"),):
        if variant and variant not in seen:
            seen.add(variant)
            yield variant
    for token in TOKEN_SPLIT.split(text)[:MAX_TOKENS]:
        if token and token not in seen:
            seen.add(token)
            yield token


def resolve_against(root: str, value: str) -> str:
    """Resolve a maybe-relative path against the project root."""
    expanded = os.path.expanduser(value)
    if not os.path.isabs(expanded):
        expanded = os.path.join(root, expanded)
    return normalize_real(expanded)


def inside(path: str, roots) -> bool:
    return any(path == root or path.startswith(root + os.sep) for root in roots if root)


def violation(payload: dict) -> str | None:
    guard = load_guard(payload.get("cwd"))
    if not guard or not guard["denied"]:
        return None
    if guard["problem"]:
        return None
    texts = collect_strings(payload.get("tool_input") or {}, [])
    texts.append(json.dumps(payload.get("tool_input") or {}, ensure_ascii=False))
    tool = payload.get("tool_name") or "tool"
    for text in texts:
        if not isinstance(text, str) or len(text) < 3:
            continue
        for candidate in candidate_texts(text):
            hit = escapes(candidate, guard["denied"])
            if not hit:
                resolved = resolve_against(guard["root"], candidate)
                hit = bool(resolved) and inside(resolved, guard["denied_real"])
            if hit:
                preview = candidate if len(candidate) <= 120 else candidate[:117] + "…"
                return (f"账本边界：{tool} 试图访问项目外账本（{preview}）。"
                        "开发侧不读账本；需要历史时停下来问 human。")
    return None


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    args = list(sys.argv[1:] if argv is None else argv)
    if "--json" in args:
        args.remove("--json")
        use_json = True
    else:
        use_json = False

    if "--status" in args:
        guard = load_guard(None)
        if not guard:
            print(f"未找到 {CONFIG_DIR}/{CONFIG_NAME}；ledger-guard 不会拦截任何调用。")
            return 0
        print(f"配置：{guard['config']}")
        print(f"项目根：{guard['root']}")
        for entry in guard["raw"]:
            print(f"账本：{entry}")
        for target in sorted(guard["denied"]):
            print(f"拒绝：{target}")
        if guard["problem"]:
            print(f"配置无法解析：{guard['problem']}")
            return 1
        return 0

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (OSError, ValueError) as error:
        print(f"ledger-guard: 无法读取 hook 输入：{error}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        return 0

    reason = violation(payload)
    if not reason:
        return 0
    if use_json:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }, ensure_ascii=False))
        return 0
    print(reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
