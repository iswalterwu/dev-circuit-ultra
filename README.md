<img src="assets/banner.svg" alt="Dev-circuit-ultra" width="100%">

# Dev-circuit-ultra

Less context. Less ceremony. One feature at a time.

A design-first development flow for coding agents.

<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea44f?style=flat-square" alt="license"></a> <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="python 3.10+"> <img src="https://img.shields.io/badge/pwsh-7-5391FE?style=flat-square&logo=powershell&logoColor=white" alt="pwsh 7"> <img src="https://img.shields.io/badge/works%20with-Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20pi%20%C2%B7%20DeepSeek%20Harness-6b4fbb?style=flat-square" alt="Claude Code / Codex / pi / DeepSeek Harness">

[![XERJ Corpus Hub contributor](https://hub.xerj.org/contributors/iswalterwu/badge.svg)](https://hub.xerj.org/contributors/iswalterwu)

[Flow](#flow) · [Quick start](#quick-start) · [Commands](#commands) · [Ledger](#ledger) · [How it differs from OpenSpec](#how-it-differs-from-openspec) · [中文](README.zh-CN.md)

Dev-circuit-ultra is a feature development flow for independent developers, delivered as a skill for coding agents such as Claude Code, Codex, pi and DeepSeek Harness, plus a `devcircuit` command-line tool. The skill, the CLI output and the linked docs are written in Chinese.

It keeps no proposal, tasks or archive. **The design is the single current source**: capability specs and `docs/architecture.md` are overwritten in place; why things changed and which options were rejected go to a private ledger outside the project. The development agent writes the ledger but never reads it, and `devcircuit ledger check` cross-checks the two.

> Selected for the [XERJ Corpus Hub](https://hub.xerj.org/corpus/iswalterwu--dev-circuit-ultra) as a reference implementation for AI coding agents, with author and repository attribution. The corpus uses a pinned snapshot, not a live mirror; use this repository for current instructions.

## Flow

```text
request → ① Classify ─┬─ continue or correct a feature in progress ─────────→ ④
                      ├─ change an existing capability ─┐
                      ├─ new capability ────────────────┴─ four fit questions ─all OK──→ ③
                      │                                                       └any not OK → ② Framework design → ③
                      ├─ bug → fast lane: fix on a fix/ branch + test, review when it qualifies
                      └─ exploration → throwaway prototype; bring what you learn back to ③, delete it
③ Feature design → ④ Build slices → ⑤ Review + one fix round → ⑥ Deliver (accept, close, report)
```

1. **Classify**: `devcircuit context --map` lists the capabilities, the features in progress and where the framework summary is. Decide whether the request continues a feature in progress, changes an existing capability, adds a new one, fixes a bug or is an exploration (a throwaway prototype that never enters product code). New capabilities and capability changes go through four fit questions: who owns the data, do the current extension points and contracts suffice, is a new dependency or persistence structure needed, does it break a framework constraint.
2. **Framework design** (when the current framework cannot accommodate the request, or for the first feature of a new project): name the gap and offer two or three structures with trade-offs and a recommendation. The structure the user picks is first drafted into `docs/architecture.md`, which opens with a framework summary of at most 60 lines; an independent structure review checks the draft, and only then is the user asked to settle it.
3. **Feature design**: on a `feat/<feature>` branch, draft the requirement text in the capability spec (`docs/requirements/<capability>.md`; every new command or interface gets at least one requirement for an error case) and start the card (`specs/<feature>/spec.md`: goal, scope and slice progress, deleted at close). Then send a design summary in the conversation, one line per requirement change. Nothing is committed and no code changes until the user settles it; then the capability spec and the card go into one commit of their own, and the decision and the rejected options are recorded with `devcircuit ledger add`. More than 12 requirement changes, or three or more capability specs touched: propose a split first.
4. **Build**: each session starts with `devcircuit context --feature <feature>` and reads only the card, the requirement text this feature touches and the related tests. One end-to-end slice at a time; tests carry the requirement IDs they prove.
5. **Review + one fix round**: when the feature is done and before acceptance, a reviewer in a fresh context (it does not change project files but must be able to run commands) reviews once and exercises the failure paths first. Key features (over the split threshold but not split, or touching a risk item) also get a requirement review before the design is settled and, with two or more slices, a skeleton review after the first slice. Must-fix items get one fix round and one re-check each time.
6. **Deliver** (accept, close, report): after the user accepts, `devcircuit close` runs the checks, cross-checks the ledger, deletes the card, commits, and records the close; the branch is then merged as AGENTS.md says (`close` does not merge). The final reply is the delivery report: what changed, how to verify, review result, potential issues, next steps.

A bug takes the fast lane: cut a `fix/<name>` branch from the trunk (not a `feat/` branch, and no card), fix the code and add a test that carries the ID of the requirement it broke. It is reviewed only when a contract changes or the diff exceeds about 200 lines. Once the user confirms, merge and write the delivery report; `devcircuit close` is not run and nothing is recorded in the ledger.

The user takes part in three places only: framework clarification (when needed), feature clarification, and acceptance.

A blanket go-ahead given in advance ("you decide", "settle the details yourself") waives none of them: only a stop the user names is skipped, just that one, and the potential issues in the delivery report say which stops were skipped; nothing runs `devcircuit close` or merges before acceptance.

## Quick start

```bash
# 1. Install the CLI (the flow uses it; same on Windows / macOS / Linux)
pipx install git+https://github.com/iswalterwu/dev-circuit-ultra   # not on PyPI yet

# 2. Sync the skills into Claude Code / agents / DeepSeek Harness (with the DSH plugin, sync with --target only; see docs/dsh.md)
devcircuit sync

# 3. New project (an existing repo takes --adopt and only fills the gaps)
devcircuit init --path ~/code/my-app --name "My App"

# 4. Create the private ledger outside the project and seal the boundary at the tool-call layer (Claude Code: claude instead of pi)
devcircuit ledger init --path ~/ledgers/my-app
devcircuit hooks install --harness pi --project ~/code/my-app --ledger ~/ledgers/my-app

# 5. On the trunk, commit the files hooks install left (its output lists them; for Claude Code add .dev-circuit/hooks/ledger_guard.py instead of the .pi file)
git -C ~/code/my-app add .gitignore .pi/extensions/ledger-guard.js
git -C ~/code/my-app commit -m "chore: add the ledger boundary hook"
```

Do not skip step 5: while those files stay uncommitted, `devcircuit close` refuses to close because the working tree is not clean. Claude Code also needs the printed hooks block merged into `.claude/settings.local.json` before the hook takes effect; that file holds machine-local paths and is not committed, so if `git check-ignore .claude/settings.local.json` prints nothing, add it to `.gitignore` and commit that on the trunk. Hooks exist for pi and Claude Code only, so nothing blocks the tool calls of another agent such as Codex or DeepSeek Harness: to isolate the ledger from it, use the strong or strongest level in the Ledger section below, where the dev side's `.dev-circuit/guard.json` says `"ledger_side": "human"` (see [docs/ledger.md](docs/ledger.md#隔离)); if the agent writes the ledger itself, still run `hooks install` once (either `--harness`) and commit what it leaves on the trunk, because `ledger add` / `check` and `close` find the ledger through the `.dev-circuit/guard.json` it writes.

Then use the `dev-circuit-ultra` skill inside the project: bring a request, the agent classifies it, then goes to framework design or feature design.

To upgrade an older project, run `devcircuit migrate --check --project <project>` first. It lists what to change (old card sections, `design.md`, AGENTS.md routing, checker versions, ledger setup) and changes nothing; migrate the features in progress before syncing the new skill. After any upgrade of `devcircuit`, run `devcircuit vendor` in the project root to refresh the two checkers and commit them (the pre-commit hook and CI run the copies in the project's `scripts/`), then `devcircuit sync` (with the DSH plugin, `--target` only; see [docs/dsh.md](docs/dsh.md)); whatever else a version needs is listed in its upgrade steps in [CHANGELOG.md](CHANGELOG.md).

`sync.ps1`, `new-project.ps1` and `new-ledger.ps1` still work; they forward to the same implementation. Implementation: a Markdown skill + Python 3.10+ (`devcircuit`, `doc_guard`, `spec_check`) + git; PowerShell 7 only for the forwarding scripts; no server component.

## Commands

| Command | What it does |
|---|---|
| `devcircuit context --map` | capabilities, features in progress, where the framework summary is, other docs, backlog size |
| `devcircuit context --capability <CODE>` / `--ids <ID,...>` | one capability's requirement list / the requirement text with examples |
| `devcircuit context --feature <name>` / `--review <name>` | the card, requirement text the branch changed or cites, related tests, what was left out; `--review` adds the base and a diff summary |
| `devcircuit ledger add` | append one ledger record; answers with a receipt only |
| `devcircuit ledger check` | cross-check ledger and project; reports features, IDs and commits that disagree, never record content |
| `devcircuit close <name> --summary <one line>` | full checks → ledger check → delete the card and commit → close record → delivery report skeleton; refuses while the working tree has uncommitted changes |
| `devcircuit check` / `doc-guard` / `spec-check` / `rules` | the two checkers |
| `devcircuit migrate --check` | before upgrading, list what an older project must change |
| `devcircuit init` / `vendor` / `sync` / `hooks install` / `hooks status` / `ledger init` | create or adopt a project, refresh the checkers, sync the skills, install hooks, show hook status, create the ledger |

## Two checkers

Both scripts are still single files you can copy into a project; the pre-commit hook and CI run them:

```bash
devcircuit check --root .                 # both checks, one exit code
devcircuit doc-guard --root .             # forbidden paths, history phrases, broken links, size limits, framework summary
devcircuit spec-check --root . --report   # requirement IDs, dangling references, card before code, test coverage
devcircuit rules                          # what every rule checks
```

- `doc_guard`: forbidden paths (`ledger/`, `docs/adr` and more), history phrases, decision IDs, hashes, broken links; capability specs over 400 lines, cards over 80 lines, a missing framework summary or one over 60 lines.
- `spec_check`: codes and IDs, duplicate IDs, dangling references in code and tests; on a `feat/<feature>` branch, code changes before the card is committed are reported as `code-before-design` (the commit that holds only the capability spec and the card, or only `docs/architecture.md`, is let through; bug fixes go on a `fix/<name>` branch).
- `--ignore GLOB`, `.dcuignore`, `--ignore-rule NAME` and inline `doc-guard:ignore` / `off` / `on` whitelist false positives; `doc-guard` also takes `--include GLOB` to scan extra `.md` files outside the default scope.
- Pure Python 3.10+, no dependencies; CI runs on Windows and Ubuntu.

They also work in repositories that do not use this flow:

```bash
devcircuit doc-guard --root ~/work/legacy-repo --ignore 'vendor/**' --ignore CHANGELOG.md
devcircuit spec-check --root ~/work/openspec-repo --ignore-rule dangling-ref
```

## Ledger

The ledger is a private git repo outside the project. It records the chosen decision, the rejected options and why. The development agent writes one record when a design is settled and one when it changes; `devcircuit close` writes the close record. That is usually two or three records per feature and no extra session. The agent gets a receipt, never the content. `devcircuit ledger check` compares both sides and reports missing close or design records, records pointing at commits the repo no longer has, and removed requirements with no recorded reason. Humans query the ledger with `dev-circuit-ledger` in a separate session.

A prompt that says "do not read the ledger" is **not** isolation. Four levels:

| Level | Setup | Guarantee |
|---|---|---|
| Weak | prompt convention | prevents accidental reads only |
| **Medium (default)** | `devcircuit hooks install`: block at the tool-call layer (pi, Claude Code) | blocks recognized ledger-path access, not filesystem isolation; `ledger add` / `check` keep working |
| Strong | the ledger is owned by another OS user / an ACL the dev process lacks | no read permission for the dev process; records and checks run on the ledger side, by a human |
| Strongest | the dev container has no ledger mount or credentials | nothing to reach inside the process; same as above |

Details: [docs/ledger.md](docs/ledger.md), [hooks/README.md](hooks/README.md) and [docker/README.md](docker/README.md).

## DeepSeek Harness

The same repository is also a DSH plugin package and a set of DSH-compatible skills. The plugin registers both skills at once:

```powershell
dsh plugin --profile web add dev-circuit-ultra
```

The Skill Store's one-click install downloads only `SKILL.md`, so install `dev-circuit-ultra` with the plugin or `devcircuit sync`. `dev-circuit-ledger` is human-invoked only; the development model cannot auto-load it. See [docs/dsh.md](docs/dsh.md) for installation, store publishing and listing copy.

## Demo

```powershell
python demo/run_demo.py
```

The demo creates a throwaway project and an external ledger and walks one feature through the flow: a design commit on a branch, `ledger add`, a design change, `context --feature`, the build, `close`. It also checks that `doc_guard` rejects a project `ledger/` directory and that the hook blocks a ledger read while letting `ledger add` through. It does not call an LLM and needs PowerShell 7 (`pwsh`), Python 3.10+ with pytest installed, and git. See [demo/README.md](demo/README.md).

## How it differs from OpenSpec

| | OpenSpec | Dev-circuit-ultra |
|---|---|---|
| Design | proposal / design / tasks / spec delta, kept after archiving | capability specs and `docs/architecture.md` edited in place; the card is deleted at close |
| Decision history | in the change and the archive, inside the repo | private ledger outside the project; the agent writes but never reads it, `ledger check` cross-checks it against the project |
| What the agent reads | per-phase skill instructions and several files per change | current requirements and the card, fetched by ID through `devcircuit context` |
| Review | optional verify | one independent review per feature that exercises failure paths first; key features and framework changes get more; one fix round for must-fix items |
| Close | `openspec archive` merges the delta and archives | one `devcircuit close` command |
| Fits | audit trails, hand-offs between people, cross-repo planning | one person with an agent, one feature at a time |

Measured: one pair on each of three open-ended tasks (pi 1.5.2 + deepseek-flash; OpenSpec 1.15.0 with its core profile, which has no verify; a script played the user and always replied "可以，开始做吧。", "OK, go ahead"). A small sample, so take it as a reference point only.

- Failure paths (bad data, an output that cannot be written; judged by script): Dev-circuit-ultra 26/26, OpenSpec 18/23. The 5 misses are one kind of defect: a traceback when the data file is not valid UTF-8 (one unguarded file read in each of two tasks, counted once per command). Each side also crashed once on valid input, both in the task built from scratch: Dev-circuit-ultra raised `UnicodeEncodeError` on Chinese Windows when a project name with an emoji went to a pipe, and OpenSpec raised `OverflowError` on `--week 9999-12-31`.
- Scores: the judge was deepseek-flash too and was told only A and B, not which workflow was which (the files in the repositories still give it away); it scored twice with A and B swapped. Over the three tasks, 82.5 to 82.5 out of 90, a tie: Dev-circuit-ultra scored higher on the two tasks that changed existing code, OpenSpec on the one built from scratch.
- Price: over the three tasks Dev-circuit-ultra spent $0.78 on the model and OpenSpec $0.26, about 3×, and took about 2.7× the time; 44% of Dev-circuit-ultra's cost went to the independent review subagents.

## FAQ

**What happens when the design changes?**

Go back to feature design: edit the draft of the capability spec (overwrite or delete the old text) and send only what changed. Once the user settles it, commit, then change code and tests, and record the rejected old decision with `devcircuit ledger add --kind design-change`, listing every removed ID in `--removed-ids` (without it `ledger check` reports `removal-unrecorded` or `id-stale` and `close` refuses). Mid-build the card is already committed, so when a removed requirement is still cited by tests or code, fix those citations in the same commit as the spec; otherwise `spec_check` reports `dangling-ref`. A change to the framework summary goes back to framework design; detail in `docs/architecture.md` is committed with the code.

**What if the development agent needs an earlier design?**

It stops and asks the human. The human queries the ledger with `dev-circuit-ledger` and hands over only the current constraints from the brief, never the raw ledger.

**Can the development agent read the ledger?**

The hook blocks ledger and `guard.json` access that its path-matching rules recognize, reducing accidental reads; it is not an unbypassable security boundary. Runtime-built paths and commands that change directory before using a relative path can evade it; see [hook limitations](hooks/README.md#它不做什么). `ledger add` answers with a receipt only and `ledger check` reports only features, IDs and commits. For a filesystem-level guarantee, use another OS user or a container without the ledger mount.

**Does it work in a git worktree?**

Yes. `.dev-circuit/guard.json` is machine-local and not in git, so when a worktree has none, `devcircuit ledger add` / `check` and `close` use the main working tree's copy and file the records under the same project name. The hook is different: it looks for `guard.json` by walking up from the session's working directory, so in a worktree outside the project directory it finds none and cannot block ledger reads.

For a setup that uses hooks, before opening an agent session in the worktree:

1. Have a human prepare a copy of the main working tree's `guard.json`, preserving `project`, `deny` and `ledger_side`. In the copy, resolve relative paths in `ledger` and `deny` against the main working tree and replace them with absolute paths before saving it as `<worktree>/.dev-circuit/guard.json`. Otherwise a path such as `../notes` can point to a different directory in the worktree.
2. Run `devcircuit hooks install --harness <pi|claude> --project <worktree> --ledger <absolute-ledger-path>` and follow its output. This updates `ledger`, not the paths in `deny`; without the prepared copy, the new config contains only the ledger path.
3. Start the harness at the worktree root, ensure the hook is loaded, and run an interception self-check with a nonexistent file under the ledger and each `deny` directory. The hook must block the call; a file-not-found error alone does not prove it is active.

A worktree inside the project directory (such as `.claude/worktrees/`) belongs in `.gitignore`, committed on the trunk (or in `.git/info/exclude` to ignore it on this machine only); otherwise the main working tree counts it as an untracked change and `close` run there refuses to close.

**Which model reviews?**

AGENTS.md has one "审核模型" (review model) line: the same model in a fresh context, or a named agent or model; without it, the current model reviews. A named agent must be able to run commands, because the review exercises the failure paths first; it does not change or commit project files.

**How many reviews does a feature get?**

One, before acceptance. Key features also get a requirement review before the design is settled and, with two or more slices, a skeleton review after the first slice. Framework design gets a structure review by default. Bugs in the fast lane are reviewed only when a contract changes or the diff exceeds about 200 lines.

**How many tests?**

As many as the boundaries and contracts in the requirements need: core logic, contracts, state machines, migrations and security are written test-first; at most one end-to-end test per key path. Test files carry the requirement IDs they prove, and `spec_check --report` lists the requirements with no test; no test matrix.

## Docs

- [SKILL.md](skills/dev-circuit-ultra/SKILL.md): the full flow and rules
- [docs/ledger.md](docs/ledger.md): current design vs. ledger, when to write, check rules, isolation levels
- [hooks/README.md](hooks/README.md): the four isolation levels and how the hook works
- [docker/README.md](docker/README.md): the strongest level, as a container reference
- [CHANGELOG.md](CHANGELOG.md): user-facing changes per version
- [docs/dsh.md](docs/dsh.md): DeepSeek Harness installation, compatibility and store publishing
- [demo/README.md](demo/README.md): the deterministic end-to-end demo

## License

MIT
