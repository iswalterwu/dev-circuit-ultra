/**
 * ledger-guard — pi extension (dev-circuit-ultra)
 *
 * Blocks tool calls whose arguments name the private ledger or the guard
 * config itself. Every tool call is inspected: read / write / edit / bash /
 * grep and anything else that names a path inside the ledger, or names the
 * guard config, is blocked before it runs.
 *
 * Install (project-local, auto-discovered):
 *   <project>/.pi/extensions/ledger-guard.js
 * Install (global):
 *   ~/.pi/agent/extensions/ledger-guard.js
 *
 * Config:
 *   <project>/.dev-circuit/guard.json
 *   {"ledger": "D:\\ledgers\\my-app", "deny": ["../notes"]}
 * Keep guard.json out of git: it names a machine-local path.
 *
 * Where it is looked for: going up from the session's working directory, each
 * folder is asked twice before the next one up.
 *   1. <folder>/.dev-circuit/guard.json
 *   2. When <folder> is the top of a linked git worktree (`.git` there is a
 *      file whose first line is `gitdir: G`, and G/commondir exists): the same
 *      file in the main working tree, the parent of the git dir that commondir
 *      names. guard.json is gitignored, so a worktree has no copy of its own.
 *      Only those two files are read; git is not run.
 * The first hit wins. `devcircuit ledger` asks the same two questions, of the
 * `--project` folder only. A submodule, a --separate-git-dir repository and a
 * worktree of a bare repository have no main working tree to fall back to.
 * Because the first hit wins, <folder>/.dev-circuit/guard.json of every folder
 * asked on the way (the worktree that uses the main tree's file, a subfolder
 * the session sits in) is blocked like the guard.json in use: written there by
 * the agent, it would be the boundary from the next call on.
 *
 * Relative `ledger` and `deny` entries start at the folder that holds
 * `.dev-circuit` (in case 2, the main working tree). A relative path in a tool
 * call starts at the folder that answered (in case 2, the worktree).
 *
 * How it is read, here and in the Claude Code hook: as UTF-8 with a leading
 * BOM dropped, holding a JSON object. `ledger` may be left out; written, it
 * has to be a non-empty string. `deny` is a list of strings; anything else in
 * its place or among its entries is skipped. Then:
 *   - no guard.json found: the project has no ledger boundary, nothing is
 *     blocked;
 *   - guard.json says where the ledger is, or leaves it out: calls that name
 *     the ledger, a `deny` entry or guard.json are blocked;
 *   - guard.json does not say where the ledger is (it is not UTF-8, does not
 *     parse, is not an object, or `ledger` is not a non-empty string): every
 *     call is blocked until a human repairs the file. The boundary cannot be
 *     told, and the agent cannot fix a file it must not read.
 *
 * What it does: blocks a call whose arguments name the ledger, a `deny` entry
 * or guard.json in a spelling it can recognise: the path as written (either
 * slash; on Windows any case, with or without the \\?\ prefix, and the /c/…,
 * /cygdrive/c/… and /mnt/c/… spellings of a drive), or a token that resolves
 * into it from the session root with links followed, so
 * `../ledgers/app/x.md` and `cat ../ledgers/app/x.md` are blocked too. What it
 * is not: filesystem isolation. The dev process runs as the same OS user, so a
 * path put together at run time, a relative path after a `cd`, or a walk of
 * the filesystem goes past it. For a filesystem-level guarantee see docker/;
 * hooks/README.md lists what the hook misses.
 */

import { Buffer } from "node:buffer";
import { existsSync, readFileSync, readlinkSync, realpathSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, parse, resolve, sep } from "node:path";

// Raised with every change to this script, together with the Claude Code
// hook's. `devcircuit hooks` reads the line as text to tell whether the copy
// installed in a project is older or newer than the one it would install.
const VERSION = "0.2.0";
const CONFIG_DIR = ".dev-circuit";
const CONFIG_NAME = "guard.json";
const IS_WINDOWS = process.platform === "win32";
const MAX_TOKENS = 64;
const MAX_LINKS = 40; // as many as Linux follows in one path before it calls it a loop
const TOKEN_SPLIT = /[\s"'`;|&<>(){}[\],]+/;
const QUOTED = [/"([^"]+)"/g, /'([^']+)'/g];
const POSIX_DRIVE = /^\/(?:cygdrive\/|mnt\/)?([A-Za-z])(?=\/|$)/;

export const name = "ledger-guard";

/** Fixed words: a parser's message can quote the file, and the file names the ledger. */
function brokenReason(configPath) {
  return `账本边界：${configPath} 读不出来（它应该是 UTF-8 的 JSON 对象；写了 ledger 的话，得是非空的路径字符串），`
    + "账本在哪里无法判断，所以拦下全部工具调用。这个文件 agent 读不了也修不了：停下来告诉 human，"
    + "由 human 修好它，或重新运行 devcircuit hooks install；不要换路径、换工具重试。";
}

/**
 * `C:\a` for `\\?\C:\a` and `\\host\share` for `\\?\UNC\host\share`: the same
 * folder either way. A path keeps Windows' extended-length prefix when it came
 * with it, so a ledger written one way matched no text that had it the other
 * way.
 */
function unprefixed(path) {
  if (!IS_WINDOWS || !path.startsWith("\\\\?\\")) return path;
  return path.slice(4, 8).toUpperCase() === "UNC\\" ? `\\\\${path.slice(8)}` : path.slice(4);
}

function normalizePath(value) {
  let text = String(value).trim().replace(/^["']|["']$/g, "");
  if (!text) return "";
  if (text === "~" || text.startsWith("~/") || text.startsWith("~\\")) {
    text = join(homedir(), text.slice(1));
  }
  const normalized = unprefixed(resolve(text)).replace(/[\\/]+$/, "");
  return IS_WINDOWS ? normalized.toLowerCase() : normalized;
}

/**
 * The path resolver for one tool call: (base, value) to an absolute path with
 * links followed and, on Windows, the case folded.
 *
 * Links are followed as far as the path exists and the rest is kept as
 * written, which is what Python's realpath does for the Claude Code hook. A
 * file about to be created under a junction to the ledger, or a wildcard
 * there, exists no more than `*.md` does; kept whole as written it would pass
 * for a project path. A link whose target is missing is followed by what the
 * link itself says: a `deny` folder yet to be made can have a link to it
 * already. The native realpath also expands Windows 8.3 short names, as
 * Python's does.
 *
 * Every token of every string in a call comes through here, most of them
 * under the same few folders, so each folder is asked of the filesystem once
 * per call. The walk goes down from the root and stops at the first folder
 * that is missing: a few hundred KB of source code read as one path has a
 * folder for each "/" in it, and stepping up out of them one by one took
 * minutes.
 */
function pathResolver() {
  const exists = new Map();
  const real = new Map();
  const links = new Map();
  const once = (known, path, ask) => {
    if (!known.has(path)) known.set(path, ask(path));
    return known.get(path);
  };
  const realpath = (path) => {
    try {
      return realpathSync.native(path);
    } catch {
      return path;
    }
  };
  const linkTarget = (path) => {
    try {
      return readlinkSync(path);
    } catch {
      return undefined; // not a link, or nothing there at all
    }
  };
  const loose = (path, followed = 0) => {
    const root = parse(path).root.length;
    let start = root; // where the next folder name starts; all before it exists
    while (start < path.length) {
      const end = path.indexOf(sep, start);
      const upTo = end < 0 ? path : path.slice(0, end);
      if (!once(exists, upTo, existsSync)) {
        // A link to a folder that is yet to be made "does not exist" either,
        // and still says where it leads; Python's realpath goes on from there.
        const target = followed < MAX_LINKS ? once(links, upTo, linkTarget) : undefined;
        if (target === undefined) break;
        return loose(join(resolve(dirname(upTo), target), end < 0 ? "" : path.slice(end + 1)), followed + 1);
      }
      if (end < 0) return once(real, path, realpath);
      start = end + 1;
    }
    return join(once(real, path.slice(0, Math.max(start - 1, root)), realpath), path.slice(start));
  };
  return (base, value) => {
    let text = String(value).trim().replace(/^["']|["']$/g, "");
    if (!text) return "";
    if (text === "~" || text.startsWith("~/") || text.startsWith("~\\")) {
      text = join(homedir(), text.slice(1));
    }
    const resolved = unprefixed(loose(isAbsolute(text) ? resolve(text) : resolve(base, text)));
    const trimmed = resolved.replace(/[\\/]+$/, "");
    return IS_WINDOWS ? trimmed.toLowerCase() : trimmed;
  };
}

/**
 * `/c/a/b` for a normalized `c:\a\b`, as Git Bash writes it. Cygwin's
 * /cygdrive/c/a/b and WSL's /mnt/c/a/b contain it, so matching it as text
 * covers all three.
 */
function posixSpelling(path) {
  if (!IS_WINDOWS || !/^[a-z]:./i.test(path)) return undefined;
  return `/${path[0]}${path.slice(2).replace(/\\/g, "/")}`;
}

/** `c:/a/b` for a `/c/a/b`, `/cygdrive/c/a/b` or `/mnt/c/a/b`, so that it can be resolved. */
function driveSpelling(text) {
  const match = IS_WINDOWS ? POSIX_DRIVE.exec(text) : null;
  return match ? `${match[1]}:${text.slice(match[0].length) || "/"}` : undefined;
}

function isFile(path) {
  try {
    return statSync(path).isFile();
  } catch {
    return false;
  }
}

/**
 * The main working tree when `top` is the top of a linked git worktree.
 *
 * Read from git's own files, not by running git: the hook runs before every
 * tool call. `.git` there is a file naming the worktree's git dir, and
 * `commondir` in that dir leads to the repository's. A submodule and a
 * --separate-git-dir repository have the file without the `commondir`.
 */
function mainTree(top) {
  try {
    const pointer = join(top, ".git");
    if (!isFile(pointer)) return undefined;
    const first = readFileSync(pointer, "utf8").split("\n", 1)[0];
    const target = first.startsWith("gitdir:") ? first.slice("gitdir:".length).trim() : "";
    if (!target) return undefined;
    // a relative one (git worktree add --relative-paths) starts at `top`
    const gitDir = resolve(top, target);
    const common = readFileSync(join(gitDir, "commondir"), "utf8").trim();
    return common ? dirname(resolve(gitDir, common)) : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Where guard.json is, going up from `start`.
 *
 * Each folder is asked twice before the next one up: its own guard.json,
 * then, when it is the top of a linked git worktree, the main working tree's
 * (guard.json is gitignored, so a worktree has no copy of it). `devcircuit
 * ledger` asks the same two questions of the folder it is given. configRoot is
 * where relative `ledger` and `deny` entries start; sessionRoot, the folder
 * that answered, is where a relative path in a tool call starts; asked lists
 * the folders that were asked, the one that answered last.
 */
function findConfig(start) {
  const asked = [];
  let directory = resolve(start || process.cwd());
  for (;;) {
    asked.push(directory);
    const own = join(directory, CONFIG_DIR, CONFIG_NAME);
    if (isFile(own)) return { configPath: own, configRoot: directory, sessionRoot: directory, asked };
    const main = mainTree(directory);
    const borrowed = main && join(main, CONFIG_DIR, CONFIG_NAME);
    if (borrowed && isFile(borrowed)) {
      return { configPath: borrowed, configRoot: main, sessionRoot: directory, asked };
    }
    const parent = dirname(directory);
    if (parent === directory) return undefined;
    directory = parent;
  }
}

/**
 * { ledger, deny } as guard.json gives them; undefined when it does not say
 * where the ledger is.
 *
 * The Claude Code hook reads the file the same way: UTF-8 with a leading BOM
 * dropped, holding a JSON object. `ledger` may be left out ({"ledger_side":
 * "human"} alone is a valid file); when it is there it has to be a non-empty
 * string. `deny` only widens the boundary, so a `deny` that is not a list, or
 * an entry in it that is not a path, is skipped rather than taking the
 * ledger's protection down with it.
 */
function readConfig(configPath) {
  let raw;
  try {
    const bytes = readFileSync(configPath);
    const text = bytes.toString("utf8");
    // Node reads bytes that are not UTF-8 as U+FFFD and goes on, where Python
    // refuses the file: a ledger path saved in GBK would name another folder.
    if (!Buffer.from(text, "utf8").equals(bytes)) return undefined;
    raw = JSON.parse(text.replace(/^\uFEFF/, ""));
  } catch {
    return undefined;
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  const ledger = raw.ledger;
  if (ledger !== undefined && !(typeof ledger === "string" && ledger.trim())) return undefined;
  const deny = Array.isArray(raw.deny) ? raw.deny : [];
  return { ledger, deny: deny.filter((entry) => typeof entry === "string" && entry.trim()) };
}

function loadGuard(start) {
  const found = findConfig(start);
  if (!found) return undefined;
  const resolvePath = pathResolver();
  // The first guard.json on the way up wins, so the places asked before the
  // one that answered are kept with it. Nothing is there yet (a worktree that
  // borrows the main tree's file, a subfolder the session sits in), and a
  // guard.json written there would be the whole boundary from the next call on.
  const guardFiles = [found.configPath];
  for (const folder of found.asked) guardFiles.push(join(folder, CONFIG_DIR, CONFIG_NAME));
  const guard = {
    ...found,
    resolvePath,
    broken: false,
    denied: new Set(guardFiles.map(normalizePath)),
    deniedReal: new Set(guardFiles.map((path) => resolvePath(found.configRoot, path))),
  };
  const read = readConfig(found.configPath);
  if (!read) {
    guard.broken = true;
    return guard;
  }
  for (const entry of [...(read.ledger ? [read.ledger] : []), ...read.deny]) {
    guard.denied.add(normalizePath(isAbsolute(entry) || entry.startsWith("~")
      ? entry
      : join(found.configRoot, entry)));
    guard.deniedReal.add(resolvePath(found.configRoot, entry));
  }
  guard.deniedReal.delete("");
  for (const target of [...guard.denied]) {
    const spelling = posixSpelling(target);
    if (spelling) guard.denied.add(spelling);
  }
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

/**
 * The whole string, its unquoted form, and shell-ish tokens: those of them
 * not in `seen` yet, which holds what this call has judged already.
 *
 * A path with a space in it is no single token, so two more readings: what a
 * pair of quotes holds, and a token with `\ ` (how a POSIX shell escapes a
 * space) read as a space.
 */
function candidateTexts(text, seen) {
  const out = [];
  const add = (item) => {
    if (item && !seen.has(item)) {
      seen.add(item);
      out.push(item);
    }
  };
  add(text);
  add(text.trim().replace(/^["']|["']$/g, ""));
  for (const token of text.split(TOKEN_SPLIT).slice(0, MAX_TOKENS)) add(token);
  for (const quoted of QUOTED) {
    let count = 0;
    for (const match of text.matchAll(quoted)) {
      add(match[1]);
      if (++count >= MAX_TOKENS) break;
    }
  }
  if (text.includes("\\ ")) {
    for (const token of text.split("\\ ").join("\0").split(TOKEN_SPLIT).slice(0, MAX_TOKENS)) {
      if (token.includes("\0")) add(token.split("\0").join(" "));
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
  for (const spelling of [text, driveSpelling(text)]) {
    const resolved = spelling ? guard.resolvePath(guard.sessionRoot, spelling) : "";
    if (!resolved) continue;
    for (const target of guard.deniedReal) {
      if (resolved === target || resolved.startsWith(target + sep)) return true;
    }
  }
  return false;
}

export default function (pi) {
  pi.on("session_start", async (_event, ctx) => {
    let guard;
    try {
      guard = loadGuard(ctx?.cwd);
    } catch {
      return;
    }
    if (guard?.broken) ctx?.ui?.notify?.(brokenReason(guard.configPath), "warning");
  });

  pi.on("tool_call", async (event, ctx) => {
    let guard;
    try {
      guard = loadGuard(ctx?.cwd);
    } catch {
      return undefined;
    }
    if (!guard) return undefined;
    if (guard.broken) return { block: true, reason: brokenReason(guard.configPath) };

    const payload = event.input ?? {};
    const haystack = collectStrings(payload);
    haystack.push(JSON.stringify(payload));
    const seen = new Set(); // the raw JSON repeats every string, and a token is judged the same wherever it is
    for (const text of haystack) {
      if (typeof text !== "string" || text.length < 3) continue;
      for (const candidate of candidateTexts(text, seen)) {
        if (!escapes(candidate, guard)) continue;
        const preview = candidate.length > 120 ? `${candidate.slice(0, 117)}…` : candidate;
        return {
          block: true,
          reason: `账本边界：${event.toolName} 试图访问项目外账本（${preview}）。`
            + "开发侧不读账本，不要换路径、换工具绕开，也不要读 .dev-circuit/guard.json 找路径；"
            + "写记录用 devcircuit ledger add，核对用 devcircuit ledger check；需要历史时停下来问 human。",
        };
      }
    }
    return undefined;
  });
}
