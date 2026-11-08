/**
 * ledger-guard — pi extension (dev-circuit-ultra)
 *
 * Keeps the private ledger out of the dev agent's reach at the tool layer.
 * Every tool call is inspected: read / write / edit / bash / grep and anything
 * else that names a path inside the ledger, or names the guard config itself,
 * is blocked before it runs.
 *
 * Install (project-local, auto-discovered):
 *   <project>/.pi/extensions/ledger-guard.js
 * Install (global):
 *   ~/.pi/agent/extensions/ledger-guard.js
 *
 * Config, found by walking up from the working directory:
 *   <project>/.dev-circuit/guard.json
 *   {"ledger": "D:\\ledgers\\my-app", "deny": ["../notes"]}
 *
 * Relative paths resolve against the directory that holds `.dev-circuit`.
 * Keep guard.json out of git: it names a machine-local path.
 *
 * What is matched: the ledger path as written, and the same path resolved
 * against the project root with symlinks followed — so `../ledgers/app/x.md`
 * and `cat ../ledgers/app/x.md` are blocked too, not just the absolute form.
 *
 * What this guarantees: the agent cannot reach the ledger through a tool call
 * that names it. What it does not: the dev process runs as the same OS user,
 * so a command that never names the ledger (walking the filesystem, command
 * substitution, reading it through another tool) is out of reach. For a
 * filesystem-level guarantee see docker/ and hooks/README.md.
 */

import { existsSync, readFileSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve, sep } from "node:path";

const CONFIG_DIR = ".dev-circuit";
const CONFIG_NAME = "guard.json";
const IS_WINDOWS = process.platform === "win32";
const MAX_TOKENS = 64;
const TOKEN_SPLIT = /[\s"'`;|&<>(){}[\],]+/;

export const name = "ledger-guard";

function normalizePath(value) {
  let text = String(value).trim().replace(/^["']|["']$/g, "");
  if (!text) return "";
  if (text === "~" || text.startsWith("~/") || text.startsWith("~\\")) {
    text = join(homedir(), text.slice(1));
  }
  const normalized = resolve(text).replace(/[\\/]+$/, "");
  return IS_WINDOWS ? normalized.toLowerCase() : normalized;
}

/** Absolute, symlink-resolved when the target exists. */
function resolvePath(base, value) {
  let text = String(value).trim().replace(/^["']|["']$/g, "");
  if (!text) return "";
  if (text === "~" || text.startsWith("~/") || text.startsWith("~\\")) {
    text = join(homedir(), text.slice(1));
  }
  let candidate = isAbsolute(text) ? resolve(text) : resolve(base, text);
  try {
    candidate = realpathSync(candidate);
  } catch {
    /* not created yet: the resolved text still points where it will be */
  }
  const trimmed = candidate.replace(/[\\/]+$/, "");
  return IS_WINDOWS ? trimmed.toLowerCase() : trimmed;
}

function findConfig(start) {
  let directory = resolve(start || process.cwd());
  for (;;) {
    const candidate = join(directory, CONFIG_DIR, CONFIG_NAME);
    if (existsSync(candidate)) return { configPath: candidate, projectRoot: directory };
    const parent = dirname(directory);
    if (parent === directory) return undefined;
    directory = parent;
  }
}

function loadGuard(start) {
  const found = findConfig(start);
  if (!found) return undefined;
  const guard = {
    ...found,
    denied: new Set(),
    deniedReal: new Set(),
    problem: undefined,
  };
  guard.denied.add(normalizePath(found.configPath));
  guard.deniedReal.add(resolvePath(found.projectRoot, found.configPath));
  try {
    const raw = JSON.parse(readFileSync(found.configPath, "utf8"));
    const entries = [raw.ledger, ...(Array.isArray(raw.deny) ? raw.deny : [])];
    for (const entry of entries) {
      if (typeof entry !== "string" || !entry.trim()) continue;
      guard.denied.add(normalizePath(isAbsolute(entry) || entry.startsWith("~")
        ? entry
        : join(found.projectRoot, entry)));
      const real = resolvePath(found.projectRoot, entry);
      if (real) guard.deniedReal.add(real);
    }
  } catch (error) {
    guard.problem = error instanceof Error ? error.message : String(error);
  }
  guard.deniedReal.delete("");
  return guard;
}

/** Every string anywhere in a tool input, plus the raw JSON text. */
function collectStrings(value, out = [], depth = 0) {
  if (depth > 8) return out;
  if (typeof value === "string") {
    out.push(value);
    try {
      out.push(decodeURIComponent(value));
    } catch {
      /* not percent-encoded */
    }
  } else if (Array.isArray(value)) {
    for (const item of value) collectStrings(item, out, depth + 1);
  } else if (value && typeof value === "object") {
    for (const item of Object.values(value)) collectStrings(item, out, depth + 1);
  }
  return out;
}

/** The whole string, its unquoted form, and shell-ish tokens. */
function candidateTexts(text) {
  const seen = new Set([text]);
  const out = [text];
  const unquoted = text.trim().replace(/^["']|["']$/g, "");
  if (unquoted && !seen.has(unquoted)) {
    seen.add(unquoted);
    out.push(unquoted);
  }
  for (const token of text.split(TOKEN_SPLIT).slice(0, MAX_TOKENS)) {
    if (token && !seen.has(token)) {
      seen.add(token);
      out.push(token);
    }
  }
  return out;
}

function escapes(text, guard) {
  if (typeof text !== "string" || text.length < 3) return false;
  const plain = IS_WINDOWS ? text.toLowerCase() : text;
  const slashed = plain.replace(/\\/g, "/");
  for (const target of guard.denied) {
    if (plain.includes(target)) return true;
    if (slashed.includes(target.replace(/\\/g, "/"))) return true;
  }
  for (const target of guard.deniedReal) {
    const resolved = resolvePath(guard.projectRoot, text);
    if (!resolved) continue;
    if (resolved === target || resolved.startsWith(target + sep)) return true;
  }
  return false;
}

export default function (pi) {
  let reportedProblem = false;

  pi.on("session_start", async (_event, ctx) => {
    const guard = loadGuard(ctx?.cwd);
    if (guard?.problem) {
      ctx.ui.notify(`ledger-guard: 无法解析 ${guard.configPath}：${guard.problem}`, "warning");
    }
  });

  pi.on("tool_call", async (event, ctx) => {
    let guard;
    try {
      guard = loadGuard(ctx?.cwd);
    } catch {
      return undefined;
    }
    if (!guard || guard.denied.size === 0) return undefined;
    if (guard.problem) {
      if (!reportedProblem && ctx?.ui) {
        reportedProblem = true;
        ctx.ui.notify(`ledger-guard 未生效：${guard.problem}`, "warning");
      }
      return undefined;
    }

    const payload = event.input ?? {};
    const haystack = collectStrings(payload);
    haystack.push(JSON.stringify(payload));
    for (const text of haystack) {
      if (typeof text !== "string" || text.length < 3) continue;
      for (const candidate of candidateTexts(text)) {
        if (!escapes(candidate, guard)) continue;
        const preview = candidate.length > 120 ? `${candidate.slice(0, 117)}…` : candidate;
        return {
          block: true,
          reason: `账本边界：${event.toolName} 试图访问项目外账本（${preview}）。`
            + "开发侧不读账本，不要换路径、换工具绕开，也不要读 .dev-circuit/guard.json 找路径；"
            + "需要历史时停下来问 human。",
        };
      }
    }
    return undefined;
  });
}
