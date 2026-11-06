<img src="assets/banner.svg" alt="Dev-circuit-ultra" width="100%">

# Dev-circuit-ultra

Less context. Less ceremony. More shipping.

A development loop with the ceremony removed.

<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea44f?style=flat-square" alt="license"></a> <img src="https://img.shields.io/badge/python-3.x-3776AB?style=flat-square&logo=python&logoColor=white" alt="python"> <img src="https://img.shields.io/badge/pwsh-7-5391FE?style=flat-square&logo=powershell&logoColor=white" alt="pwsh 7"> <img src="https://img.shields.io/badge/works%20with-Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20pi%20%C2%B7%20DeepSeek%20Harness-6b4fbb?style=flat-square" alt="Claude Code / Codex / pi / DeepSeek Harness">

[After setup](#after-setup) · [Five steps](#five-steps) · [Quick start](#quick-start) · [Demo](#demo) · [Isolation](#isolation) · [How it differs from OpenSpec](#how-it-differs-from-openspec) · [Chinese](README.zh-CN.md)

Dev-circuit-ultra is a feature development loop for independent developers, delivered as a skill for coding agents such as Claude Code, Codex, pi and DeepSeek Harness. It breaks a feature into five steps: design clarification, one slice, build and verify, independent review, and closeout.

It does **not** maintain proposals, task lists or an archive, and it does not keep a long-lived design archive. **The current design is the only source.** When the design changes, the old text is overwritten or deleted; decision history lives in a private ledger **outside the project**, and the development agent never reads it.

## After setup

<p align="center"><img src="assets/after-setup-en.svg" alt="After setup: two directories, one boundary" width="100%"></p>

<p align="center"><em>Figure 1. The project and the private ledger are separate; the dev container has no ledger mount.</em></p>

`D:\code\my-app` is the project; `D:\ledgers\my-app` is a private git ledger outside it. The development agent only reads and writes the project; the archivist only appends to the ledger; the human is the only bridge.

- **Development side**: current design, capability specs, code and tests; no ledger mount, path or credentials.
- **Bookkeeping side**: project read-only, ledger append-only, in a separate session/container; nothing flows back.
- **Human**: when history is needed, query with `dev-circuit-ledger` and get a minimal brief; the raw ledger never enters the development context.

## Five steps

<p align="center"><img src="assets/five-steps-en.svg" alt="Five steps: design clarification, one slice, build and verify, independent review, closeout" width="100%"></p>

<p align="center"><em>Figure 2. The five-step loop: current design in, history out.</em></p>

1. **Design clarification + intent card**: read the current product design; ask design questions; choose an approach; write the current design and spec delta.
2. **One slice**: plan only the next end-to-end slice; derive implementation/test scope from the design.
3. **Build + verify**: implement and test; change the design before changing code; run project checks.
4. **Independent review**: normal features get one final review; framework-level changes get one structural review before code plus one final review. The reviewer sees the current design, diff and base; one re-check at most.
5. **Accept + merge**: merge current requirements; delete the card/design; the human/orchestrator has the archivist record the final state outside the project.

## Quick start

```powershell
# 1. Sync the skill (Claude Code / agents / DeepSeek Harness directories)
pwsh -NoProfile -File sync.ps1

# 2. Create a project
pwsh -NoProfile -File skills/dev-circuit-ultra/scripts/new-project.ps1 `
  -Path D:\code\my-app -Name "My App"

# 3. Create the private ledger OUTSIDE the project
pwsh -NoProfile -File skills/dev-circuit-ultra/scripts/new-ledger.ps1 `
  -Path D:\ledgers\my-app
```

Then start with design clarification inside the project. On the first feature, the skill asks once how to run the independent review (same model, a named reviewer agent, or ask again each feature) and saves the choice in `.dev-circuit/reviewer.json`. The ledger is a separate step; no `ledger/` appears in the project.

Implementation: Markdown skill + Python 3 (`doc_guard` / `spec_check`) + PowerShell 7 (bootstrap) + git; no server component, Docker isolation optional.

## DeepSeek Harness

The same repository is a DSH plugin package and a set of DSH-compatible skills. Install the package to register all three skills at once:

```powershell
dsh plugin --profile web add dev-circuit-ultra
```

Or publish the individual `skills/<name>/` folders to the Skill Store through SkillHub / ClawHub. `dev-circuit-archivist` and `dev-circuit-ledger` are human-invoked only; the development model cannot auto-load them. See [docs/dsh.md](docs/dsh.md) for installation, store publishing and listing copy.

## Demo

<p align="center"><a href="assets/demo-60s-en.webm"><img src="assets/demo-60s-poster-en.png" alt="Watch the 60-second walkthrough" width="100%"></a></p>

<p align="center"><em>60-second walkthrough: the five steps plus the open-ended OpenSpec A/B (WebM, no audio).</em></p>

```powershell
python demo/run_demo.py
```

The demo creates a throwaway project and an external ledger. It exercises destructive design edits, discarded ideas living only in the ledger, card deletion at closeout, and `doc_guard` rejecting a project `ledger/` directory. It does not call an LLM; strong isolation is the Docker mount boundary. See [demo/README.md](demo/README.md).

## Isolation

A prompt that says "do not read the ledger" is **not** isolation. To guarantee it:

| Level | Setup | Guarantee |
|---|---|---|
| Weak | prompt convention | prevents accidental reads only |
| Medium | private repo outside the project; no path in project | prevents accidental reads, not a determined same-user process |
| **Strong** | separate containers/OS users; dev has no ledger mount or credentials | the dev process has no read permission |

Strong isolation is recommended. See [`docker/compose.yaml`](docker/compose.yaml):

- `dev`: project only; no `/ledger`; no ledger remote credentials; no Docker socket.
- `archivist`: project read-only + ledger writable; append-only; no product edits.
- `ledger`: ledger read-only; for human queries.
- The ledger remote must be private; credentials only in the archivist/human environment.

Full boundary and verification commands: [docs/ledger.md](docs/ledger.md) and [docker/README.md](docker/README.md).

## How it differs from OpenSpec

| | OpenSpec | Dev-circuit-ultra |
|---|---|---|
| Design | proposal/design/tasks/spec delta, kept over time | current design; overwrite/delete on change |
| Decision history | in change/archive, growing | external private ledger, human only |
| What the dev agent reads | potentially the whole history | current design/code only |
| Closeout | archive retained | card/design deleted; current state only |
| Goal | audit trail, cross-person handoff | fast iteration, lean context, no drift |

OpenSpec is a better fit when you need an audit trail, cross-person handoff or cross-repo planning. Dev-circuit-ultra is lighter for one developer shipping continuously with an agent.

## Latest A/B: what it saved

One open brief, one session per skill, one blind review of the final repos. n=1; compare with the caveats, not as a general claim.

| Against OpenSpec | Dev-circuit-ultra | OpenSpec | Difference |
|---|---:|---:|---:|
| Blind rubric (30) | **27** | 26 | +1 |
| Wall time | **408.9 s** | 421.0 s | −12.1 s (−2.9%) |
| Model cost | **$0.0743** | $0.1060 | −$0.0317 (−29.9%) |
| Input + output tokens | **72,308** | 113,337 | −41,029 (−36.2%) |
| Cache-read tokens | **1,891,968** | 3,678,333 | −1,786,365 (−48.6%) |
| Assistant turns | **39** | 50 | −11 (−22%) |
| Retained docs | **2 files / 132 lines** | 3 files / 273 lines | −1 file / −141 lines (−51.6%) |
| Closeout | **1 commit, clean** | 0 commits, 11 uncommitted | clean vs unfinished |
| Project tests | 13 | **21** | narrower coverage (tradeoff) |

The doc count covers requirements + usage guide + the OpenSpec main spec; OpenSpec's proposal/design/tasks files are not included. The token figures are observed usage, not a provider-neutral bill. Dev's 1-point win comes mainly from clean closeout and Decimal totals; OpenSpec has stronger tests and error handling. See [bench/README.md](bench/README.md) for the full artifact review.

<p align="center"><img src="assets/ab-comparison-en.svg" alt="Open A/B: Dev-circuit-ultra vs OpenSpec" width="100%"></p>

<p align="center"><em>Figure 3. Open A/B (n=1, blind artifact review): Dev 27/30, OpenSpec 26/30. Dev was 3% faster, 30% cheaper, and finished clean; OpenSpec had more tests and stronger error handling but left 11 uncommitted entries and a float total. Not a general claim. See <a href="bench/README.md">bench/README.md</a>.</em></p>

## FAQ

**What if the design changes?**

Change the design first: overwrite/delete the old text; then code/tests. The archivist records the old decision and rejected options in the external ledger.

**What if the dev agent needs an old decision?**

Stop and ask the human. The human queries the ledger with `dev-circuit-ledger`, gets a minimal brief, and passes only the current constraints to the dev agent.

**Can the dev agent read the ledger?**

Not under strong isolation: no mount, no path, no credentials. Weak/medium setups are conventions, not guarantees.

**Why keep a design at all?**

The design is the implementation basis, not a history. Without it the agent guesses; the ledger explains past guesses to the human, not to the agent.

**Who chooses the reviewer?**

You do. On the first feature the skill asks whether to use the same model in an independent context, a named read-only reviewer agent, or ask again at the start of every feature; it stores the answer in `.dev-circuit/reviewer.json`. There is no fixed reviewer model in the skill. If the configured agent is missing or fails, it stops and asks instead of silently substituting an implementation worker.

**How many tests?**

Enough to cover the design's boundaries/contracts. Tests are evidence, not a decision archive; disposable tests are fine, only user-visible contract/regression tests need to stay. No test matrix.

## Docs

- [SKILL.md](skills/dev-circuit-ultra/SKILL.md): full workflow, rules and templates
- [docs/ledger.md](docs/ledger.md): boundaries, isolation and verification commands
- [docs/dsh.md](docs/dsh.md): DeepSeek Harness install, compatibility and Store publishing
- [docker/README.md](docker/README.md): dev / archivist / ledger container reference
- [demo/README.md](demo/README.md): deterministic end-to-end demo
- [bench/README.md](bench/README.md): the latest open A/B, blind rubric and measured savings

## License

MIT
