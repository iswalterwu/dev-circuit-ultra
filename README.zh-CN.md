<img src="assets/banner.svg" alt="Dev-circuit-ultra" width="100%">

# Dev-circuit-ultra

更少上下文，更少流程，一次交付一个功能。

面向编码 agent 的设计驱动开发流程。

<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-2ea44f?style=flat-square" alt="license"></a> <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="python 3.10+"> <img src="https://img.shields.io/badge/pwsh-7-5391FE?style=flat-square&logo=powershell&logoColor=white" alt="pwsh 7"> <img src="https://img.shields.io/badge/works%20with-Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20pi%20%C2%B7%20DeepSeek%20Harness-6b4fbb?style=flat-square" alt="Claude Code / Codex / pi / DeepSeek Harness">

[![XERJ Corpus Hub contributor](https://hub.xerj.org/contributors/iswalterwu/badge.svg)](https://hub.xerj.org/contributors/iswalterwu)

[流程](#流程) · [快速开始](#快速开始) · [命令](#命令) · [账本](#账本) · [和 OpenSpec 的区别](#和-openspec-的区别) · [English](README.md)

Dev-circuit-ultra 是一套面向独立开发者的功能开发流程，以 skill 的形式加载到 Claude Code、Codex、pi、DeepSeek Harness 等编码 agent 中，配一个 `devcircuit` 命令行工具。

它不维护 proposal、tasks 或 archive。**设计是唯一现行源**：能力规格和 `docs/architecture.md` 原地覆盖或删除旧内容；为什么这么做、哪些方案没选，写进项目之外的私有账本。开发 agent 对账本只写不读，`devcircuit ledger check` 核对两边一致。

> 本项目入选 [XERJ Corpus Hub](https://hub.xerj.org/corpus/iswalterwu--dev-circuit-ultra)，供 AI 编码 agent 检索参考实现，并保留作者和仓库归属。语料库采用固定版本快照，不是实时镜像；最新用法以本仓库为准。

## 流程

```text
需求 → ① 识别 ─┬─ 在研功能的续做或修正 ─────────────────→ ④
               ├─ 已有能力的变化 ─┐
               ├─ 新能力 ─────────┴─ 衔接四问 ─都行────→ ③
               │                              └有一问不行 → ② 框架设计 → ③
               ├─ bug → 快车道：在 fix/ 分支上修 + 测试，按条件审核
               └─ 探索 → 一次性原型，收获带回 ③，原型删掉
③ 功能设计 → ④ 切片实现 → ⑤ 审核 + 一轮修复 → ⑥ 验收、收尾、交付
```

1. **识别**：`devcircuit context --map` 列出能力清单、在研功能和框架摘要在哪。判断需求属于在研功能、已有能力、新能力、bug 还是探索（先做一次性原型看效果，不进产品代码）；新能力和已有能力的变化过一遍衔接四问：数据归谁、现有扩展点和契约够不够、要不要新依赖或新的持久化结构、会不会违背框架约束。
2. **框架设计**（框架接不住时，或新项目的第一个功能）：讲清缺口，给 2–3 个结构方案，写清取舍并推荐一个；选定的结构先写成 `docs/architecture.md` 的草稿（开头是不超过 60 行的框架摘要），独立的结构审看过之后，再请用户说"定了"。
3. **功能设计**：在 `feat/<feature>` 分支上先把要求条文写进能力规格（`docs/requirements/<能力>.md`；新的命令或接口至少写一条出错时的要求），再起卡（`specs/<feature>/spec.md`：目标、范围和切片进度，收尾时删掉），然后在对话里发设计摘要，每条要求变化一行。用户说"定了"之前不提交、不改代码；定了以后把能力规格和卡放进同一个提交（不带别的改动），`devcircuit ledger add` 记下决定和被否方案。要求变化超过 12 条或改到 3 份及以上能力规格，先发拆分方案。
4. **实现**：每个会话先跑 `devcircuit context --feature <feature>`，只读卡、本功能涉及的要求原文和相关测试；一次一个端到端切片，测试里写上要求编号。
5. **审核 + 一轮修复**：功能做完、验收前，独立上下文的 reviewer（不改项目文件，但要能执行命令）审一次，先实际触发出错路径。重点功能（超过拆分门槛又不拆，或命中风险加项）另在定了之前做一次要求审，至少有两个切片时，第一个切片后再做一次骨架审。每次必须改的都修一轮、复查一次。
6. **验收、收尾、交付**：用户验收后，`devcircuit close` 跑检查、核对账本、删卡并提交、写收尾记录；分支再按 AGENTS.md 的分支约定合并（`close` 不合并）。最后的回复是交付报告：做了什么、怎么验收、审核结果、潜在问题、下一步建议。

bug 走快车道：从主干切出 `fix/<名>` 分支（不放 `feat/`，不写卡），修代码并补上引用被违反要求编号的测试；改了契约或 diff 超过约 200 行才审核。用户确认后合并、写交付报告，不跑 `devcircuit close`，不记账本。

用户只在三处参与：框架澄清（需要时）、功能澄清、验收。

事先泛泛的授权（"你定""能自己拍板的自己定"）不免除这三处：用户点名跳过哪一处，才只跳那一处，交付报告的"潜在问题"里写明跳过了哪几处；验收之前不跑 `devcircuit close`，也不合并。

## 快速开始

```bash
# 1. 安装 CLI（流程要用它；Windows / macOS / Linux 相同）
pipx install git+https://github.com/iswalterwu/dev-circuit-ultra   # 还没发布到 PyPI

# 2. 同步技能到 Claude Code / agents / DeepSeek Harness 目录（DSH 用插件装技能的，同步只带 --target，见 docs/dsh.md）
devcircuit sync

# 3. 新建项目（已有仓库用 --adopt 只补缺失文件）
devcircuit init --path ~/code/my-app --name "My App"

# 4. 在项目外创建私有账本，并在工具调用层封住边界（Claude Code 把 pi 换成 claude）
devcircuit ledger init --path ~/ledgers/my-app
devcircuit hooks install --harness pi --project ~/code/my-app --ledger ~/ledgers/my-app

# 5. 在主干上提交 hooks install 留下的文件（以它输出的"下一步"一行为准；Claude Code 把 .pi 那个文件换成 .dev-circuit/hooks/ledger_guard.py）
git -C ~/code/my-app add .gitignore .pi/extensions/ledger-guard.js
git -C ~/code/my-app commit -m "chore: 装账本边界 hook"
```

第 5 步别省：这些文件留着不提交，`devcircuit close` 会因为工作区不干净而拒绝收尾。Claude Code 还要照输出把 hooks 段合并进 `.claude/settings.local.json` 才生效；这个文件是本机路径，不提交，`git check-ignore .claude/settings.local.json` 没有输出时，把它加进 `.gitignore` 并在主干上提交。hook 只有 pi 和 Claude Code 两种，Codex、DeepSeek Harness 等别的 agent 的工具调用没有拦截：要隔离账本，就用下面账本一节的强档或最强档，开发侧的 `.dev-circuit/guard.json` 写 `"ledger_side": "human"`（见 [docs/ledger.md](docs/ledger.md#隔离)）；让这些 agent 自己写账本的，也要跑一次 `hooks install`（`--harness` 任选一种）并在主干上提交它留下的文件，因为 `ledger add` / `check` 和 `close` 靠它写的 `.dev-circuit/guard.json` 找账本。

然后在项目里用 `dev-circuit-ultra` skill：提一个需求，agent 先识别，再进框架设计或功能设计。

升级旧项目先跑 `devcircuit migrate --check --project <项目>`。它列出要改的地方（旧卡的节、`design.md`、AGENTS.md 路由、检查器版本、账本配置），不改任何文件；先迁移进行中的功能，再同步新版技能。平时升级 `devcircuit` 之后，在项目根目录跑 `devcircuit vendor` 更新两个检查器并提交（提交前钩子和 CI 跑的是项目 `scripts/` 里的这两份），再 `devcircuit sync`（用 DSH 插件的只带 `--target`，见 [docs/dsh.md](docs/dsh.md)）；每个版本另外要做的事见 [CHANGELOG.md](CHANGELOG.md) 里那一版的"升级"小节。

`sync.ps1`、`new-project.ps1`、`new-ledger.ps1` 仍然可用，它们只是转发到同样的实现。实现：Markdown skill + Python 3.10+（`devcircuit`、`doc_guard`、`spec_check`）+ git；PowerShell 7 只用于转发脚本；没有服务端组件。

## 命令

| 命令 | 做什么 |
|---|---|
| `devcircuit context --map` | 能力清单、在研功能、框架摘要在哪、其他文档、待做数 |
| `devcircuit context --capability <代号>` / `--ids <编号,...>` | 一个能力的要求清单 / 要求原文和例子 |
| `devcircuit context --feature <名>` / `--review <名>` | 卡、本分支改到或引用到的要求原文、相关测试、省略了什么；`--review` 另加基线和改动统计 |
| `devcircuit ledger add` | 追加一条账本记录，只回执编号 |
| `devcircuit ledger check` | 核对账本和项目，只报不一致的功能、编号和提交 |
| `devcircuit close <名> --summary <一句话>` | 全量检查 → 账本核对 → 删卡并提交 → 收尾记录 → 交付报告骨架；工作区有没提交的改动就不收尾 |
| `devcircuit check` / `doc-guard` / `spec-check` / `rules` | 两个检查器 |
| `devcircuit migrate --check` | 升级前列出旧项目要改的地方 |
| `devcircuit init` / `vendor` / `sync` / `hooks install` / `hooks status` / `ledger init` | 新建或接入项目、更新检查器、同步技能、装 hook、看 hook 状态、建账本 |

## 两个检查器

两个脚本仍然是单文件、可直接拷进项目跑；提交前钩子和 CI 都跑它们：

```bash
devcircuit check --root .                 # 两个检查，一个退出码
devcircuit doc-guard --root .             # 禁止路径、历史短语、断链、体积上限、框架摘要
devcircuit spec-check --root . --report   # 要求编号、悬空引用、先有卡再改代码、测试覆盖
devcircuit rules                          # 每条规则查什么
```

- `doc_guard`：禁止路径（`ledger/`、`docs/adr` 等）、历史短语、决策编号、哈希、断链；能力规格超过 400 行、卡超过 80 行、框架摘要缺失或超过 60 行。
- `spec_check`：代号与编号、重复编号、代码和测试里的悬空引用；在 `feat/<功能>` 分支上，卡还没提交就改了代码时报 `code-before-design`（只提交能力规格和卡、或只提交 `docs/architecture.md` 的那次提交放行；修 bug 用 `fix/<名>` 分支）。
- `--ignore GLOB`、`.dcuignore`、`--ignore-rule NAME`、行内 `doc-guard:ignore` / `off` / `on` 用来白名单误杀；`doc-guard` 另有 `--include GLOB`，把默认范围之外的 `.md` 也纳入扫描。
- 检查器是纯 Python 3.10+，没有依赖；CI 同时跑 Windows 和 Ubuntu。

它们也能用在不接受这套流程的仓库里：

```bash
devcircuit doc-guard --root ~/work/legacy-repo --ignore 'vendor/**' --ignore CHANGELOG.md
devcircuit spec-check --root ~/work/openspec-repo --ignore-rule dangling-ref
```

## 账本

账本是项目外的私有 git repo，记选定的决定、被否方案和原因。开发 agent 在设计定了、设计改了的时候各写一条，`devcircuit close` 自动写收尾记录；每个功能一般 2–3 条，不用另开会话。它只拿到回执编号，读不到内容。`devcircuit ledger check` 对照两边，报出缺的收尾或设计记录、指向不存在提交的记录、没记删除原因的要求。human 用 `dev-circuit-ledger` 在独立会话里查询。

只在 prompt 里写"不要读账本"**不算隔离**。分四档：

| 级别 | 做法 | 能保证什么 |
|---|---|---|
| 弱 | prompt 约定 | 只能防误读 |
| **中（默认）** | `devcircuit hooks install`：在工具调用层拦（pi、Claude Code） | 拦截能识别出的账本路径访问，不提供文件系统隔离；`ledger add` / `check` 照常可用 |
| 强 | 账本属主是另一个 OS 用户 / ACL 不授权给开发进程 | 开发进程没有读权限；记录和核对由 human 在账本一侧跑 |
| 最强 | 开发容器不挂载账本、无凭证 | 进程内没有可达路径；同上 |

细节见 [docs/ledger.md](docs/ledger.md)、[hooks/README.md](hooks/README.md) 和 [docker/README.md](docker/README.md)。

## DeepSeek Harness

同一个仓库也是 DSH 插件包和一组 DSH 兼容 skill。装插件可一次注册两个 skill：

```powershell
dsh plugin --profile web add dev-circuit-ultra
```

商店（Skill Store）一键安装只下载 `SKILL.md`，`dev-circuit-ultra` 要用插件或 `devcircuit sync` 装。`dev-circuit-ledger` 只由 human 显式调用，开发模型不会自动加载；安装、发布和文案见 [docs/dsh.md](docs/dsh.md)。

## Demo

```powershell
python demo/run_demo.py
```

demo 在临时目录里建一个项目和一个项目外的账本，走一遍：分支上的设计提交、`ledger add`、设计变更、`context --feature`、实现、`close`；并验证 `doc_guard` 拒绝项目内的 `ledger/`、hook 拦下账本读取而放行 `ledger add`。它不调用 LLM，需要 PowerShell 7（`pwsh`）、Python 3.10+（装好 pytest）和 git。详见 [demo/README.md](demo/README.md)。

## 和 OpenSpec 的区别

| | OpenSpec | Dev-circuit-ultra |
|---|---|---|
| 设计 | proposal / design / tasks / spec delta，归档后长期保留 | 能力规格和 `docs/architecture.md` 原地改；卡收尾时删掉 |
| 决策历史 | 写进 change 和 archive，留在仓库里 | 项目外私有账本；开发 agent 只写不读，`ledger check` 核对一致 |
| 开发 agent 读什么 | 各阶段的技能指令和 change 里的多份文件 | `devcircuit context` 按编号取的现行要求和卡 |
| 审核 | 可选的 verify | 每个功能一次独立审核，先实际触发出错路径；重点功能和框架改动多审；必须改的修一轮 |
| 收尾 | `openspec archive` 合并 delta、归档 | `devcircuit close` 一条命令 |
| 适合 | 审计轨迹、跨人交接、跨仓库规划 | 一个人带 agent，一次交付一个功能 |

实测：3 道开放题各跑一对（pi 1.5.2 + deepseek-flash；OpenSpec 用 1.15.0 的 core 档，不含 verify；扮用户的是脚本，每次都回"可以，开始做吧。"）。样本小，只当参考。

- 出错路径（坏数据、输出写不进去，按脚本判定）：Dev-circuit-ultra 26/26，OpenSpec 18/23。没过的 5 项是同一类问题：数据文件不是合法 UTF-8 时直接 traceback（两道题各有一处读文件没接住，按命令记了 5 次）。合法输入上两边各崩过一次，都在从零写的那道：Dev-circuit-ultra 在中文 Windows 上把含 emoji 的项目名输出到管道时报 `UnicodeEncodeError`，OpenSpec 在 `--week 9999-12-31` 上报 `OverflowError`。
- 评分：评委也是 deepseek-flash，只知道 A、B，不知道各是哪套流程（仓库里的文件其实看得出来），A/B 互换各评一次。三题合计 82.5 对 82.5（满分 90），打平：改已有代码的 2 道 Dev-circuit-ultra 高，从零写的 1 道 OpenSpec 高。
- 代价：三题合计，Dev-circuit-ultra 的模型成本 $0.78，OpenSpec $0.26，约 3 倍；耗时约 2.7 倍。Dev-circuit-ultra 的成本里 44% 花在独立审核的子 agent 上。

## 常见问题

**设计变了怎么办？**

回到功能设计：改能力规格的草稿（原地覆盖 / 删除旧内容），只发变化的部分；用户定了再提交，然后改代码和测试，并 `devcircuit ledger add --kind design-change` 记下被否的旧决定，删掉的编号写进 `--removed-ids`（漏了，`ledger check` 报 `removal-unrecorded` 或 `id-stale`，`close` 不收尾）。实现中途（卡已经提交）删掉的要求，如果还被测试或代码引用，引用要和规格放进同一个提交，不然 `spec_check` 报 `dangling-ref`。要改框架摘要就回框架设计；`docs/architecture.md` 的细节随代码提交。

**开发 agent 需要以前的设计怎么办？**

停下来问 human。human 用 `dev-circuit-ledger` 查账本，只把 brief 里的现行约束交给开发 agent，不给账本原文。

**账本会不会被开发 agent 读到？**

hook 拦截路径匹配规则能识别出的账本和 `guard.json` 访问，减少误读；它不是不可绕过的安全边界。运行时拼出来的路径、先切目录再使用相对路径的命令等可能绕过匹配，见 [hook 的限制](hooks/README.md#它不做什么)。`ledger add` 只回执编号，`ledger check` 只报不一致的功能、编号和提交。要文件系统级的保证，用另一个 OS 用户或不挂载账本的容器。

**能在 git worktree 里用吗？**

能。`.dev-circuit/guard.json` 是本机配置、不进 git，worktree 里没有它时，`devcircuit ledger add` / `check` 和 `close` 用主工作区的那份，记录记在同一个项目名下。hook 不一样：它从会话的当前目录往上找 `guard.json`，worktree 在项目目录之外时找不到，就拦不住读账本。

使用 hook 的配置，在 worktree 里开 agent 会话之前：

1. 由 human 准备主工作区 `guard.json` 的副本，保留 `project`、`deny`、`ledger_side`。在副本中把 `ledger` 和 `deny` 的相对路径按主工作区解析成绝对路径，再保存到 `<worktree>/.dev-circuit/guard.json`；否则 `../notes` 这类路径到了 worktree 可能指向另一个目录。
2. 跑 `devcircuit hooks install --harness <pi|claude> --project <worktree> --ledger <账本绝对路径>`，并照它的输出做。它只更新 `ledger`，不转换 `deny` 里的路径；没准备副本时，新配置只有账本路径。
3. 从 worktree 根目录启动 harness，确认 hook 已加载，再用账本和每个 `deny` 目录下的不存在文件做拦截自检。应由 hook 拦下调用，单纯的“文件不存在”报错不能证明 hook 生效。

worktree 建在项目目录里面（比如 `.claude/worktrees/`）时，把这个目录写进 `.gitignore` 并在主干上提交（只想在本机忽略就写进 `.git/info/exclude`），不然主工作区把它当成未跟踪的改动，在主工作区跑 `close` 会拒绝收尾。

**审核用什么模型？**

AGENTS.md 里写一行"审核模型"：同模型的独立上下文，或指定一个 agent / 模型；没写就用当前模型。指定的 agent 要能执行命令（审核先实际触发出错路径），它不改、不提交项目里的文件。

**一个功能审几次？**

验收前审一次。重点功能另在设计定了之前做一次要求审，至少有两个切片时，第一个切片做完再做一次骨架审。框架设计默认做结构审。快车道的 bug 只在改了契约或 diff 超过约 200 行时审。

**测试要写多少？**

由要求里的边界和契约决定：核心逻辑、契约、状态机、迁移、安全先写测试，关键路径最多 1 条端到端测试。测试文件里写上它证明的要求编号，`spec_check --report` 据此列出没有测试的要求；不写测试矩阵。

## 文档

- [SKILL.md](skills/dev-circuit-ultra/SKILL.md)：完整流程和规则
- [docs/ledger.md](docs/ledger.md)：现行设计与账本、写入时机、核对规则、隔离分级
- [hooks/README.md](hooks/README.md)：四档隔离与 hook 的工作方式
- [docker/README.md](docker/README.md)：最强一级的容器参考
- [CHANGELOG.md](CHANGELOG.md)：每个版本对使用者有影响的变化
- [docs/dsh.md](docs/dsh.md)：DeepSeek Harness 安装、兼容性与 Store 发布
- [demo/README.md](demo/README.md)：确定性的端到端演示

## 许可

MIT
