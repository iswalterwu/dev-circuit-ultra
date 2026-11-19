# 变更记录

只记对使用者有影响的变化。版本号对应 git tag；`doc_guard` / `spec_check` 的脚本版本是各自独立的一条线，不跟包版本走。

## 未发布

修复版：一次下游使用评估和对照源码的核实确认了几类问题：账本边界在 git worktree 里不成立，`context` 会静默给出错的下一步或不完整的补读命令，`close` 提交之后账本出错就回不来并带出账本路径，几处检查全绿而状态不对。这一版只修这些，技能文字不变。

### 退出码和行为有变的地方

- 两个 hook：`guard.json` 读不出账本位置时（不是 UTF-8 的合法 JSON、含 NaN / Infinity、嵌套超过 64 层、不是对象、`ledger` 写了却不是非空字符串、文件打不开）拦下全部工具调用，要 human 修好文件。以前 Claude Code 的 hook 静默放行，pi 的告警后放行。
- `hooks status`：配置读不出 0 → 2；有 hook 脚本却找不到配置 1 → 2；linked worktree 里主工作树有配置 1 → 0；worktree 分支上的旧脚本读不到主工作树的配置时 2（“这里不拦”）。
- `hooks install`，linked worktree 里：不带 `--ledger` 2 → 0（沿用主工作树的配置）；给了与现有配置不同的 `--ledger`、或主工作树还没有配置，都是 2，不另写 `guard.json`。在主工作树里给不同的 `--ledger` 仍是 0，整份改写，和以前一样。
- `hooks install`，任何位置：`--project` 给的是已配置项目里面的目录 0 → 2；`guard.json` 读不出又不带 `--ledger` 时 0 → 2；`guard.json` 只写了 `"ledger_side": "human"`、不带 `--ledger` 时 2 → 0。
- Claude Code 的 hook：在 python3 3.8 / 3.9 上（macOS 命令行工具、Debian 11）以前一加载就崩溃、以 1 退出、放行全部调用，现在照常拦截；工具参数嵌套深到 Python 的 json 读不完时，有 `guard.json` 管着，1（放行）→ 2（拦下这一次）。
- `hooks install`：要写回的 `guard.json` 里有 JSON 写不出的值（`1e999` 读成的无穷大、单独的代理项）时，以前写成读不出的文件或 traceback，现在 2，不写文件、不拷脚本。
- `close`：卡已不在、历史里有这个功能的 `close` 提交时 2 → 0 或 1（只补账本）；提交之后账本出错 2 → 1，并照常打印交付报告骨架；重跑时 `guard.json` 读不出 2 → 1，也照常打印报告。首跑在提交之前遇到的账本错误，末尾都写“没有收尾”。
- `ledger add` / `ledger check`：写不进、读不出账本时，带账本路径的 traceback（1）→ 一行不带路径的错误（2）。`entries/<项目>/` 列不出时，`ledger check` 以前当成没有记录、对每个在研功能报 design-missing（1），现在 2。
- `migrate --check`：只有“CI 工作流不在主干上触发”这一种问题的项目 0 → 1；`guard.json` 读不出的项目，不论 `ledger_side` 都列一条（human 一侧以前报“没有要改的”）。
- `spec_check` / `doc_guard`（以及 `check`、`close` 的检查步骤和项目里的提交前检查）：不再报项目目录里别的 git 工作区的问题，这类项目 1 → 0。

### 账本边界

- 两个 hook 在 linked worktree 里用主工作树的 `guard.json`：每一级目录先看本级的配置，再看“本级是 linked worktree 顶层时主工作树的那一份”，这两问和账本命令对 `--project` 那一级问的一样。hook 还会从会话目录逐级往上找；账本命令不往上找，`--project` 要给工作树的顶层。以前建在项目目录之外的 worktree 里 hook 找不到配置，静默放行，而账本命令照常能写账本。`ledger` / `deny` 的相对路径按配置所在的工作树解析，工具调用里的相对路径按会话所在的工作树解析。子模块、`--separate-git-dir`、bare 加 worktree 没有回退，要在 worktree 里自带 `guard.json`。
- `guard.json` 只有一种读法，两个 hook、`hooks status` / `install`、账本命令和 `migrate` 结论一样：严格 UTF-8 并去 BOM；字符串之外嵌套超过 64 层、含 NaN / Infinity、不是对象、`ledger` 写了却按 Python 的 `str.strip()` 是空白都算读不出；超长整数照常读入；两个 hook 把条目变成路径时也按 `str.strip()` 去两端空白；`deny` 写错只跳过那几项，不再 traceback、不再误拦普通文件；只写 `ledger_side` 的配置是合法的。从会话目录到找到配置的那一级，沿途各级的 `guard.json` 位置也拦。
- Windows 上认得 Git Bash / Cygwin / WSL 的 `/d/…`、`/cygdrive/d/…`、`/mnt/d/…` 写法和 `\\?\` 前缀；认得引号里的整段和转义的空格；pi 的 hook 经 junction 或软链访问时，叶子不存在、带通配符、链接目标还没建也拦。两个脚本带版本行（0.2.0）。
- `hooks status` 分层报告：脚本（和本机 devcircuit 带的相比相同、旧、新）、配置（本工作树的还是主工作树的、能否解析）、登记（本工作树的 Claude settings 里有没有这条命令），外加“宿主是否已加载：CLI 证明不了”和一个会话内探针。`hooks status`、`hooks install` 和 hook 脚本的 `--status` 都不再打印账本路径和 `deny` 路径。
- `hooks install` 在 linked worktree 里不再生成第二份只含账本位置的 `guard.json`（以前会丢掉主工作树配置里的 `ledger_side`、`deny`、`project`）。`guard.json` 整份替换写入，内容没变不重写；`--force` 不覆盖比本机带的新的 hook 脚本。
- 项目路径里有 shell 会展开的字符（`$`、反引号、双引号；Windows 上还有 `%`）时，Claude Code 的 hook 命令不拦：`hooks install` 和 `hooks status` 现在会明说。命令本身没改，这种路径下请把项目挪到别处。
- 账本命令遇到 `guard.json` 里 `ledger` 写了却不是路径时，说清楚两个 hook 会因此拦下全部调用，不再说“没有配置账本”。
- 账本仓库上的 git 调用不再继承进程环境里的 `GIT_DIR`、`GIT_INDEX_FILE` 等。以前在 linked worktree 里由 git hook 调起（或从 git hook 里启动的 agent）跑 `ledger add` / `close` 时，账本记录文件会整份被提交进项目仓库，账本仓库反而没有提交，输出照样是“已记录”。用过这种方式的项目，查一下项目历史里有没有 `entries/` 下的文件。
- Claude Code 的 hook 往上找配置时，当前用户看不了的目录当作那里没有文件（Python 3.10–3.13 上以前会 traceback、放行）。
- 文档：README 的 worktree 常见问题不再教人把 `guard.json` 手抄进 worktree；hooks/README.md 写清匹配规则和拦不到的写法；不再有“封住边界”的说法。

### context

- `context --map`：写法走样的切片行（`- S3（下一个）：…`、`- （当前）S3：…`、`### S3：…` 等）和标题后写了不认的状态词的行，报出行号和原文，不再跳过后照常给出“下一个：S4”。结构写法放宽（列表符、任务框、加粗、小写 s）；状态仍只认 ✓、勾上的任务框和标题后的（当前）。卡里有“切片”标题时只读那一节的顶格行。
- 截断提示列全被省略的编号，分成每行一条、可以原样运行的 `devcircuit context --ids …`；原调用带了 `--root` 或 `--base` 时，输出里照着运行的命令带上同样的参数。以前只列前 10 个、末尾接“…”，照着运行报“找不到”。
- 卡的“能力：”一行认加粗、列表符和表格写法；读不到或对不上能力规格时明说。
- `--map` 写明只列本工作树的 `specs/` 和当前分支；`--feature` / `--review` 开头写当前分支和基线，不在 `feat/<功能>` 上时说明。

### close 与账本命令

- `close` 可以重跑：提交之后账本没写成，修好后重跑同一条命令，它只补收尾记录或补账本仓库的提交。只凭功能名认最新的 `close <功能>` 提交，开头写明提交号和日期；同名功能以前收过尾时可能认到以前那次，要看日期。close 提交被 squash 掉之后仍要手工 `ledger add --kind close`。
- 提交之后账本出错：照常打印交付报告骨架，“潜在问题”写明原因（不带路径）和重跑办法。
- `close` 的检查步骤里，`doc_guard` 没通过时也照跑 `spec_check`，一次报全；human 一侧打印的补记命令带上 `--review`；收尾行写真实的当前分支；脏文件清单里的中文文件名不再是八进制转义。
- 没有可比的基线、或当前就在基线上时，`close` 和 `ledger check` 明说哪几项没比。
- `ledger check` 不再回显记录里形状不对的字段（写成“（格式不对，已略）”；记录号只认 `ledger add` 写出的格式），字段类型不对或嵌套过深的记录不再让它崩溃，`entries/<项目>/` 下只读 `.jsonl`。
- `migrate --check` 认卡的“能力：”一行时和 `context` 一样认加粗、列表符和表格写法；`ledger check` 的 framework-missing 认加粗的“框架：已改”。

### 检查器与脚手架

- `spec_check` 0.7.2、`doc_guard` 0.4.2：项目目录里的嵌套 git 工作区（linked worktree、子模块、嵌套克隆）不再检查。只认 git 自己也认、而且本仓库没有跟踪的那种：手放一个假 `.git`，或往已跟踪的目录里放一个真的 `.git`，都照常查。遇到这种目录时检查器会跑一次 `git ls-files`。
- `doc_guard` 0.4.2：`broken-link` 认百分号编码、尖括号和引号标题的链接写法；报错按 UTF-8 输出。
- `init --adopt` 生成的 CI 工作流按 AGENTS.md 的主干触发，不再写死 main。`migrate --check` 列出 push / pull_request 不在主干上触发的工作流（读不懂的写法不报，写进 `.dcuignore` 的不查），检查器副本的提示分方向。
- `vendor` 不把项目里更新的检查器覆盖成本机带的旧版本。
- npm 包里缺模板的 `.gitignore`（npm 打包不收这个文件名），从 npm 包的布局跑 `devcircuit init` 会写到一半停下：模板改名为 `gitignore`，生成的文件名不变。

### 测试

- 全部测试在名字带中文和空格的目录下跑，不读本机的全局 git 配置和 git 的全局 ignore / attributes 文件，PATH 上已安装的 `devcircuit` 不参与；CI 里默认编码的读写当错误；CI 上缺 node、pwsh、sh、npm 就失败，不让依赖它们的测试悄悄跳过。
- 新增 linked worktree、换行、GBK 控制台、四种 shell 下的回归测试，以及账本命令和两个 hook 在 21 种布局（19 种 git 布局和 2 个普通目录）下找到同一份配置的测试。

### 升级

1. 升级 CLI：`pipx install --force git+https://github.com/iswalterwu/dev-circuit-ultra`，装完用 `devcircuit --version` 确认。
2. 每台用这个项目的机器（每个克隆）都要做这一步，别的机器在拉取第 3 步的提交之前做：在主工作树和每个自带 `guard.json` 的 worktree 里跑 `devcircuit hooks status`。`guard.json` 不进 git，每台机器各有一份。它报“无法解析”的，先由 human 把 `guard.json` 改成 UTF-8 的 JSON 对象，`ledger` 是非空的路径字符串（这里不放账本的，删掉这一项）：新的 hook 遇到读不出的配置会拦下全部工具调用。
3. 在主工作树跑 `devcircuit vendor` 更新两个检查器，跑 `devcircuit hooks install --harness <pi|claude> --project <主工作树> --force` 换上新的 hook 脚本（不用再给 `--ledger`），都在主干上提交。装在全局的 pi 扩展要手工换。
4. git worktree：各分支把主干合并进来后才用上新脚本。建在主工作树目录之外、又没有自带 `guard.json` 的 worktree，合并之前旧脚本找不到配置，`hooks status --project <worktree>` 会以 2 报“这里不拦”；建在项目目录里面的、或自带 `guard.json` 的，旧脚本照样能拦，status 是 0。以前按旧说明手抄进 worktree 的 `guard.json` 会继续优先，想跟主工作树一致就由 human 删掉。Claude Code 在每个 worktree 里把 `hooks install` 给的片段合并进 `.claude/settings.local.json`，或在用户级设置里登记一次。照 `hooks status` 最后一行做一次会话内探针。
5. 跑 `devcircuit migrate --check`：列出 CI 工作流不在主干上触发的，把主干写进那一处的 `branches`；有意不在主干上跑的工作流写进 `.dcuignore`。
6. 在每个有在研功能的分支或 worktree 里跑一次 `devcircuit context --map`（它只列本工作树的卡）：报“切片行读不懂”或“没读到切片行”的，照提示把那一行改成顶格的 `- S<n>：<标题>`，在做的加（当前），做完的加 ✓。
7. 依赖输出或退出码的脚本，照上面“退出码和行为有变的地方”核对。技能文字没变；技能目录里带的两个检查器和模板变了，按 setup.md 手动接入、从技能目录拷检查器的，跑一次 `devcircuit sync`。用 `devcircuit vendor` 的不受影响。

## 0.7.1

照 0.7.0 的技能文字按场景走查时确认的 7 个问题：照文字做会被检查拦住、两处说法相反，或者在某种环境下不报错地漏掉。另有 1 个是试跑时发现的：停止点挡不住用户事先泛泛的授权。另外，`devcircuit --version` 带上提交号，分得清装的是哪个构建。

### 流程

- bug 快车道写明在 `fix/<名>` 分支上修，不写卡；用户确认后合并并写交付报告，不跑 `devcircuit close`，不记账本。要审核时，交给 reviewer 的是被违反的要求原文（`devcircuit context --ids`）、基线和 diff。AGENTS 模板的分支约定加上 `fix/<名>`。
- 实现中途设计变了：回 ③ 只改能力规格的草稿；要改框架摘要回 ②，`docs/architecture.md` 的细节随代码提交。④ 里“改 `docs/architecture.md` 的草稿”的写法和 ③ 相反，照它做会跳过结构审，已去掉。
- 审核子 agent 不写成“只读”：它不改、不提交项目里的文件，但要能执行命令。`reviewer.md` 写明出错路径在项目外的临时副本里跑，或者跑完清理干净；真实资金、真实外部调用和不可逆的操作不真跑。
- `setup.md`：`hooks install` 留下的 hook 脚本和 `.gitignore` 改动要在主干上提交。
- 用户事先泛泛的授权（“你定”“能自己拍板的自己定”“不要照抄步骤”“怎么收尾由你定”）不免除 ②③ 的“定了吗？”和 ⑥ 的验收：验收前不跑 `devcircuit close`、不合并，bug 快车道也一样。用户点名跳过哪一处，就只跳那一处（“设计不用给我看”只免设计确认），交付报告的“潜在问题”里写明跳过了哪几处。此前 agent 把这类授权当成事先同意，三处都不停，一路做到 close 和合并。

### 命令与检查器

- `spec_check` 0.7.1、`doc_guard` 0.4.1：白名单模式可以以点开头（`.pi/**`、`.github/**`）。开头的点会被削掉，这类模式写了不生效，也没有提示。
- `spec_check` 0.7.1：
  - `feat/<功能>` 的卡写了还没提交时，草稿删掉的要求还被测试或代码引用不报 `dangling-ref`；卡提交之后照报，引用随第一个实现提交改掉；没有卡的分支和别的分支照报。设计提交不再被 `dangling-ref` 和 `code-before-design` 轮流拦下。
  - 只暂存 `docs/architecture.md`、没有暂存代码的框架提交，不被工作区里别的代码改动拦下；`devcircuit hooks install` 装的 hook 脚本不算代码。新项目的第一个功能能提交框架草稿了。
  - 文件名含中文等非 ASCII 字符的代码文件，`code-before-design` 不再看不见。
  - `code-before-design` 的提示加了一句：修 bug 不放在 `feat/` 分支上。
- `devcircuit context`、`close`、`ledger check`：能力规格的文件名含非 ASCII 字符时，分支上新增、改写、删除的要求不再漏掉。
- 账本在 git worktree 里可用：worktree 里没有 `guard.json` 时用主工作区的那份，记录记在同一个项目名下。此前 `ledger add` 报“没有配置账本”，`devcircuit close` 不写记录就收尾。hook 不跟着进 worktree：建在项目目录之外的 worktree 里，hook 找不到 `guard.json`，拦不住读账本；在那里开会话之前，照 README 常见问题“能在 git worktree 里用吗？”补上。
- `devcircuit hooks install` 的输出提示在主干上提交它留下的文件。
- `devcircuit init --adopt` 猜主干时，`fix/` 开头的当前分支和 `feat/` 一样不当主干。
- `devcircuit --version` 在从 git 地址安装（`pipx install git+…`）时带上提交号，写成 `devcircuit <版本> (git <提交号前 7 位>)`。这种装法装的是分支当时的内容，同一个版本号下可能是不同的构建：提交号和仓库里 `v<版本>` 这个 tag 指向的提交一样，就是发版的构建，不一样就是之后的构建。从 wheel、sdist 或本地目录安装的不带提交号。

### 升级

1. 先升级 CLI 本身：`pipx install --force git+https://github.com/iswalterwu/dev-circuit-ultra`。版本号没变时，再装一次不会换构建，所以带 `--force`；装完用 `devcircuit --version` 确认。后面两步拷的是已安装的 CLI 自带的检查器和技能。
2. `devcircuit vendor` 更新项目里的两个检查器，并提交。
3. `devcircuit sync` 同步新版技能。装过 hook 的项目，把 hook 脚本和 `.gitignore` 的改动在主干上提交。
4. AGENTS.md 第 5 节的分支一行照新模板加上 `fix/<名>`。

## 0.7.0

### 流程

- 定了之前先写草稿：建 `feat/<feature>` 分支，把要求条文写进能力规格、起卡，再发设计摘要（每条要求变化一行）；定了之前不提交、不改代码，定了以后单独提交能力规格和卡，再记账本。用户批的就是要提交的条文，条文只写一次。功能草稿只有能力规格和卡，`docs/architecture.md` 的细节随实现和代码一起提交；要改框架摘要就走框架设计。框架设计同样先写 `docs/architecture.md` 的草稿。
- 用户否掉整个功能：还原改过的能力规格，删掉卡和新建的规格文件，再删分支。设计中途改了：回 ③ 改草稿、只发变化的部分，定了再提交，记 `design-change`。
- 要求变化超过 12 条，或改到 3 份及以上能力规格：先发拆分方案（新文件 `large.md`），拆出来的子功能各走一遍流程。
- 重点功能（超过门槛又不拆，或命中风险加项）：定了之前做一次要求审，先做构建者检查；至少两个切片时，第一个切片做完后做一次骨架审；验收前照常做一次常规审，审整个功能。卡在"能力"一行下面写"重点：是（原因）"。
- 框架设计默认做结构审，审的是没提交的 `docs/architecture.md` 草稿；用户明说不审才跳过。
- 跳过要求审或结构审时，账本记录的 `--review` 写"用户明说不审"；交付报告的"审核"每次审核一行。
- 视觉密集的改动（新图表、新版式、数据面板）先给可点原型或真实数据截图；原型用一次性代码，不算改代码。
- 设计摘要里要求变化的行不计入 25 行。
- 目标改为质量优先：在不降低审核质量的前提下少花钱。

### 命令与检查器

- `spec_check` 0.7.0：`code-before-design` 改为卡要先提交才放行代码；卡已暂存、暂存区里又没有代码时也放行，这次提交就是提交草稿。
- `devcircuit context --map` 给没提交的卡标"草稿"。

### 升级

1. `devcircuit vendor` 更新项目里的 `spec_check.py`：新版只认已提交的卡。进行中的功能，卡还没提交的，先单独提交卡和能力规格，再接着改代码。
2. `devcircuit sync` 同步新版技能。进行中的卡不用改；是重点功能的，在"能力"一行下面补一行"重点：是（原因）"。

## 0.6.1

- `devcircuit` 的报错也用 UTF-8 输出：中文 Windows 上用管道接走输出（如 `devcircuit ledger check 2>&1 | head`）时，报错不再是乱码；路径里有编不了码的字符时，照样给出可读的报错，不打堆栈。
- 基线可以写在 AGENTS.md 里：`context`、`ledger check`、`close` 不带 `--base` 时，先取 AGENTS.md 里"主干"一行写的分支（本地没有就用 origin 上的）；没写就和以前一样取 `main` / `master`，两个都没有才用远端默认分支（origin/HEAD）。写了主干却找不到，或这一行没写分支名，直接报错，不悄悄换成别的分支；列表、加粗、表格几种写法都认。AGENTS 模板第 5 节加了"主干"一行；`devcircuit init --adopt` 依次按远端默认分支、本地的 `main` / `master`、当前分支（`feat/` 分支除外）填写，看不出来就不写，并在输出里说明填了什么。`migrate --check` 会列出没写主干、远端默认分支又和默认基线不一致的项目。
- `hooks install --harness claude` 提示把 hooks 段合并进 `.claude/settings.local.json`：片段里是本机路径，不该提交；写出的 `.dev-circuit/claude-settings.hook.json` 也自动加进 `.gitignore`。
- `spec_check` 0.6.1：`--report` 把旧编号（AC-xxx-y）也算进统计。测试里写成 `<代号>:AC-xxx-y` 就算有测试引用，旧编号下的"证明：演示"也认；首行写明"含 N 条旧编号"。

### 升级

1. 主干不是 `main` / `master` 的项目：在 AGENTS.md 第 5 节加一行 ``- 主干：`<分支>` ``。`devcircuit migrate --check` 会列出远端默认分支和默认基线不一致、需要确认的项目。
2. 老项目的测试里把旧编号写成 `<代号>:AC-xxx-y`，`spec_check --report` 才算它有测试。`devcircuit vendor` 更新项目里的 `spec_check.py`。
3. Claude Code 的 hooks 段如果放在 `.claude/settings.json` 里，挪到 `.claude/settings.local.json`。

## 0.6.0

### 流程

- 每个需求先**识别**：在研功能的续做或修正、已有能力的变化、新能力、bug、探索。新能力和已有能力的变化过"衔接四问"（数据归谁、扩展点和契约够不够、要不要新依赖或新持久化结构、会不会违背框架约束），有一问不行就先做**框架设计**，再做**功能设计**。
- 两种设计都在对话里澄清到用户说"定了"：发出设计摘要就结束本轮回复，"定了"之前不写文件、不改代码。回复里有提问、回答或补充就不算定了，哪怕带着"其他按你的建议"：只发变化的部分，问一句"定了吗？"再停。定了以后建 `feat/<feature>` 分支，改能力规格、写卡、记账本。
- **审核恢复为默认**：每个功能验收前审一次，reviewer 先实际触发出错路径；必须改的修一轮、复查一次，没修好的进交付报告。快车道只在改了契约或 diff 超过约 200 行时审。审核模型写在 AGENTS.md 的"审核模型"一行。
- 派审核时给出本技能目录里 `reviewer.md` 的完整路径，免得审核子 agent 读到本机装的旧版。
- 兼容写明白：以前能成功的输入照样成功、输出不变；把崩溃改成可读错误不算破坏兼容。设计摘要和审核的"必须改"都按这条判断，已有命令现在给堆栈也不例外。
- 收尾用 `devcircuit close`，最后的回复是**交付报告**：做了什么、怎么验收、审核、潜在问题、下一步建议。
- 能力规格模板要求：新的命令、接口或输入至少一条出错时的要求，或写明"无失败路径"。卡多一行"能力：… · 框架：…"，上限 80 行。
- `docs/architecture.md` 开头是用 `<a id="summary"></a>` 标出的框架摘要（不超过 60 行），识别阶段只读这一段。
- 文档地图和能力清单不再手写登记表，由 `devcircuit context --map` 现场生成。

### 账本

- 开发 agent 对账本**只写不读**：`devcircuit ledger add` 追加一条记录，只回执编号。`dev-circuit-archivist` 退役，`devcircuit sync` 会从技能目录里移除它；`dev-circuit-ledger`（human 查询）保留。
- `devcircuit ledger check` 核对账本和项目：`close-missing`、`design-missing`、`framework-missing`、`commit-missing`、`removal-unrecorded`、`id-stale`；只报功能、编号和提交，不报记录内容。`correction` 记录算补记。
- `devcircuit ledger init --path` 取代 `devcircuit ledger --path`（旧写法照样可用）。记录新增 `ids`、`ids_removed`、`review`、`source` 字段，旧记录照样保留。
- `DEVCIRCUIT_LEDGER`、`DEVCIRCUIT_PROJECT` 环境变量优先于 `guard.json`，给容器隔离里账本一侧用；`docker/compose.yaml` 改为 `dev` + `ledger` 两个容器。强 / 最强两档里开发侧写不了账本：开发侧的 `guard.json` 写 `"ledger_side": "human"`，`devcircuit close` 跳过账本步骤并打印要补的命令，由 human 在账本一侧补记和核对。
- `guard.json` 里的相对账本路径按项目根解析（和 hook 一致），`~` 会展开。
- 功能名只用字母、数字、点、下划线和连字符，一段，不含斜杠；卡目录、`feat/<feature>` 分支和账本记录都用它。`ledger check` 对不合规的卡报 `bad-feature-name`，`close` 一开始就拒绝不合规的名字。
- `ledger add` 当场拒绝写错的编号：`--ids` 必须是现有编号，编号之间可以用逗号、顿号、分号或空格隔开。
- `ledger check` 按仓库里的完整 SHA 核对记录（旧记录里的短 SHA 也认）；`commit-missing` 只查在研功能，squash、rebase 合并之后不会把已收尾的功能都报一遍。
- `close` 只因本功能和本分支的不一致而停，别的功能的不一致写进交付报告；提交失败时如实报告卡有没有恢复，不删 git 没跟踪的文件。
- hook 的拦截提示指向 `devcircuit ledger add` / `check`。

### 命令与检查器

- 新增 `devcircuit context`：`--map`、`--capability`、`--ids`、`--feature`、`--review`，按编号和锚点取现行设计，超出上限时截断并列出没给的编号。
- 新增 `devcircuit close <feature>`：全量检查 → 账本核对 → 删卡并提交 `close <feature>` → 收尾记录 → 再核对 → 交付报告骨架；提交前任何一步不过就不动。
- 新增 `devcircuit migrate --check`：列出旧项目要改的地方（包括升级后会被 `oversize` 拦下的卡和能力规格），不改文件。
- `context` 对比时不做改名检测，改名的能力规格不会把原有要求报成"新增"；显式给的 `--base` 不存在时报错，不再悄悄退回"没有基线"。
- 除了 `doc-guard`、`spec-check`、`check` 会把参数转给检查器，其他子命令遇到不认识的参数直接报错退出 2，不再悄悄丢掉。
- `hooks install` 自己把 `.dev-circuit/guard.json` 写进 `.gitignore`（已被更宽的规则忽略就不写，保留原文件的换行风格），不再让 agent 手动加：hook 生效后，命令里出现这个路径会被拦。
- Claude Code 的 hook 片段改为只在脚本存在时运行它：切到没有 `.dev-circuit/hooks` 的旧分支时放行，不再因 python 打不开脚本退出 2 而拦下所有工具调用。Windows 上用 `python`，不再用 WindowsApps 里的 `python3` 别名；路径一律写成正斜杠。
- Claude Code hook 按 UTF-8 读输入，不再跟随控制台编码：中文 Windows 上 stdin 默认是 GBK，紧贴中文写的账本路径（如 `账本：D:\ledgers\…`）会被吞掉一个字母而放行。
- 项目模板的 `.githooks/pre-commit` 用第一个真能运行的解释器（Windows 上先试 `python`），WindowsApps 里跑不起来的 `python3` 别名不再让提交失败。
- `migrate --check` 只把每功能的旧 `design.md`（不带目录的 `design.md` 或 `specs/` 下的）当成旧路由，`docs/design.md` 这类项目自己的文档不再误报；新增一条：`.claude/settings*.json` 里还是旧写法的 hook 命令会被列出来。
- `doc_guard` 0.4.0：新规则 `oversize`（能力规格超过 400 行、卡超过 80 行）和 `arch-summary`（`docs/architecture.md` 缺框架摘要或摘要超过 60 个非空行）。
- `spec_check` 0.6.0：新规则 `code-before-design`，在有 `specs/` 的 git 仓库里，`feat/<feature>` 分支上卡还不存在就改了代码时报出；`--list-rules` 的列宽放宽到 20。

### 其他

- 删除旧流程的图（`five-steps`、`after-setup`）、60 秒演示视频和生成它的 `demo/make_demo_60s.py`；npm 和 pip 的一句话简介改成现在的流程。

### 升级

1. 先跑 `devcircuit migrate --check --project <项目>`，按它的清单处理；有未提交的 `specs/` 改动先问用户。
2. 进行中的功能：卡里的"规格变化 / 设计 / 验收例子 / 风险 / 待定"等节，要求写进能力规格、结构写进 `docs/architecture.md`（加框架摘要），卡只留目标、范围、切片，并补上"能力：… · 框架：…"一行；`specs/<feature>/design.md` 并入 `docs/architecture.md` 后删掉。然后补一条 `devcircuit ledger add --kind design`（或 `correction`）。
3. AGENTS.md 照新模板更新第 2、3、5、7 节（`devcircuit context` 路由、命令、分支规则、账本只写不读、审核模型）；可以删掉 `.dev-circuit/reviewer.json`。
4. `devcircuit vendor` 更新两个检查器；装过 hook 的项目用 `devcircuit hooks install … --force` 换上新的拦截提示；Claude Code 用户再用新生成的 `.dev-circuit/claude-settings.hook.json` 替换 settings 里的 hooks 段。`.githooks/pre-commit` 没改过的，可以用模板里的新版覆盖。
5. 最后 `devcircuit sync` 同步新版技能。

## 0.5.0

- 脚手架：`.gitignore` 带上常见的缓存和依赖目录；文档地图不再把还不存在的 `architecture.md` 写成已有；AGENTS 模板注明检查器直接运行、规则用 `--list-rules` 看，不读源码。
- `doc_guard --include GLOB`：把默认范围之外的 `.md` 也纳入扫描；ignore 优先于 include。
- 要求只写一处：功能的行为要求直接改在 `docs/requirements/<能力>.md`，意图卡只留目标、范围和切片；收尾不再合并规格、改标题。
  `spec_check`（0.5.0）不再读意图卡，去掉 `bad-change`、`conflict`、`unknown-target`、`unknown-code`、`id-exists` 五条规则；
  直接运行脚本时再用 `--ignore-rule` 指定这些规则名会报参数错误。
  升级前，把进行中的卡里还没合并的"规格变化"写进能力规格：新版不再把卡里新增的编号当成已存在，
  测试引用它们会报 `dangling-ref`。
- 独立审核改为按需：用户说"审一下"时才做；命中风险加项或框架级时，提一句可以加审核，由用户定。
  功能循环从五步变为四步；去掉第一次使用时的 reviewer 问答，不再读 `.dev-circuit/reviewer.json`（已有的可以删掉）。
- SKILL.md 精简到原来的一半左右：每条规则只写一处；新建项目与接入挤到 `setup.md`，框架级的设计步骤挤到 `framework.md`，
  只在用到时读。要求编号改为写在测试文件里：Python 测试名不能带 `-`，`spec_check --report` 认不出 `test_DOCK_12`。
- demo 增加工具调用层边界：hook 在读取之前拦下账本，绝对路径和相对路径都拦。
- 删除 A/B 评测：`bench/`、README 里的 A/B 结果和对比图、演示视频里的 A/B 片段。
- 框架级的结构从设计时起直接写进 `docs/architecture.md`（没有就新建并在文档地图登记），收尾不再合并；
  去掉 `templates/design.md` 和 `specs/<feature>/design.md`。迁移步骤写进卡的切片，风险和待定问题在点头时说清。
  升级前，把进行中的框架级功能的 `design.md` 里仍然有效的结构和关键决定并入 `docs/architecture.md`，然后删掉它。
- 有测试的要求不再写"证明"行：测试里写的编号就是证明，`spec_check --report` 照旧据此列出没有测试的要求；
  只有靠演示证明的要求才写"证明：演示"。已有的证明行照样通过检查。
  要求模板的"读我"不再要求链接另一份设计文档。
- `doc_guard`（0.3.0）和 `spec_check` 没有问题时各打印一行"通过"，写明检查了多少份文档 / 能力规格和要求；
  `spec_check --report` 首行给出要求总数和有测试、靠演示、都没有的各几条；`--list-rules` 和 `devcircuit rules`
  给每条规则附一句说明，并列出检查范围。`--json` 和退出码不变；靠"通过时没有输出"判断结果的脚本要改看退出码。
  pre-commit 模板里 `spec_check` 的失败提示不再提已经删掉的规则。
- 去掉重复文字：技能 description 只留一句定位和触发条件；SKILL.md 去掉讲 hook 的一段，"不要绕开、不读 `guard.json`"
  改由 hook 的拦截提示说；AGENTS 模板第 7 节从 7 条减到 3 条，其余规则以技能为准。
  已有项目的 AGENTS.md 不用改；想精简，可以照新模板的第 7 节替换。

## 0.4.0

### 新增

- `devcircuit` CLI：`doc-guard` / `spec-check` / `check` / `rules` / `vendor` /
  `hooks install` / `init` / `ledger` / `sync`，`pipx install <仓库>` 后可用。
- 账本边界分四档，默认档是 hook：pi 扩展与 Claude Code `PreToolUse` 在工具调用层拒绝。
- 检查器白名单：`--ignore`、`.dcuignore`、`--ignore-rule`、行内 `doc-guard:ignore` / `off` / `on`。
- 脚手架产出 `.gitignore` 与 `.dcuignore`；`pre-commit` 探测 `python3`。

### 变化

- 要求定义接受 `-` `*` `+` `1.`、加粗前缀和表格行；变化条目接受英文动词；
  章节接受 `## Spec changes`。
- 遗留 `CODE:AC-xxx-y` 引用改为校验存在性。
- `new-project.ps1`、`new-ledger.ps1`、`sync.ps1` 只转发到 CLI。
- 代码围栏内的内容不再被当成文档主张。

### 修复

- hook 只匹配绝对路径：相对路径与 `..` 穿越现在也会被拦。
- Windows 下 `--ignore` 区分大小写，与文件系统不一致。
- `--ignore` 不接受反斜杠分隔符。
- 显式的 `--ignore-file` 指向不存在的文件时不再静默忽略。
- `hooks install` 允许账本落在项目内。
- POSIX 下 `.githooks/pre-commit` 只改索引的可执行位，提交后工作区一直显示为修改。
- 没有 git 身份时首次提交直接抛原始报错。

### CI

- Windows 与 Ubuntu × Python 3.10 / 3.13；另加打包任务，从 wheel 与 sdist 跑
  `init` / `ledger` / `sync` / `vendor` / `hooks install`。
