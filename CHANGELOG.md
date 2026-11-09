# 变更记录

只记对使用者有影响的变化。版本号对应 git tag；`doc_guard` / `spec_check` 的脚本版本是各自独立的一条线，不跟包版本走。

## 未发布

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
