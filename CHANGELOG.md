# 变更记录

只记对使用者有影响的变化。版本号对应 git tag；`doc_guard` / `spec_check` 的脚本版本是各自独立的一条线，不跟包版本走。

## 未发布

- 脚手架：`.gitignore` 带上常见的缓存和依赖目录；文档地图不再把还不存在的 `architecture.md` 写成已有；AGENTS 模板注明检查器直接运行、不必读源码。
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
