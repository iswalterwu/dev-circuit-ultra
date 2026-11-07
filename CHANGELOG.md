# 变更记录

只记对使用者有影响的变化。版本号对应 git tag；`doc_guard` / `spec_check` 的脚本版本是各自独立的一条线，不跟包版本走。

## 未发布

- 意图卡的"设计"多一行必填的"失败行为"：每个外部输入和输出出错时的退出码、提示、会不会留下半份输出。
  能力规格模板要求至少一条出错时的要求，或写明"无失败路径"。
- SKILL 写明兼容的含义：已有命令以前能成功处理的输入，现在仍然成功、输出不变；把崩溃改成可读错误不算改契约，
  给已有命令加校验时只拒绝以前就会失败的输入。新的命令行约定要么覆盖已有命令，要么写明只对新命令生效。
- 完成标准：设计里的每项失败行为都要有测试；最后一个切片照用户文档把每条命令示例（含出错的）实际跑一遍。
- reviewer 先实际触发失败路径（卡里列的每项，再加至少一项没列的），崩溃、出错却退出码 0、半份输出都算必须改。
  已有命令加了新校验的，再拿样例里没有、以前能处理的输入试一次。
  命令、退出码、输出格式这类行为承诺不算文档措辞；被新的全局约定覆盖的已有命令算相关代码；reviewer 只按 `reviewer.md` 审，不读 SKILL.md、模板和检查器源码。
- 新增 `templates/guide.md`：用户文档写任务和实测示例，规则只引用编号，从源头避免把要求重复写一遍。
- 脚手架：`.gitignore` 带上常见的缓存和依赖目录；文档地图不再把还不存在的 `architecture.md` 写成已有；AGENTS 模板注明检查器直接运行、不必读源码。
- `doc_guard --include GLOB`：把默认范围之外的 `.md` 也纳入扫描；ignore 优先于 include。
- `spec_check` 的"已合并"提示跟随卡片语言：英文卡不再收到中文提示。
- demo 增加工具调用层边界：hook 在读取之前拦下账本，绝对路径和相对路径都拦。
- 开放 A/B 可以脚本化重跑：`bench/open/run_open_ab.py --runs N` 用 `--dry-run` 先看计划，跑完自动做随机 A/B 的盲评；`bench/summarize.py` 把多轮结果汇成中位数与配对差值。
  每轮存下两侧会话 trace 与最终代码树；成本含 reviewer 等子 agent；盲评在仓库外进行并附 `EVIDENCE.md`（提交、`git status`、pytest）；
  `--rejudge` 对已存产物重评（A/B 交替、可关 EVIDENCE），汇总里列出评委信度与盲评成本。
  `tests/test_bench_harness.py` 用桩 `pi` / `openspec` 覆盖这套流程，不花 token。
- 开放 A/B 的测量：
  - `bench/probe.py` 用 9 项机械探针试缺数据文件、坏 JSON、非数组、写不进去和小数兼容，自动找到新增的命令；runner 每侧记录 `probes`，汇总表多一行。
  - 每轮默认评 2 次（`--judges`），第二次交换 A/B；汇总取每轮各次评审的中位数，另列不计收尾的分数。
    少于 5 轮、评委与被测同模型、混用 rubric 版本、只评了 1 次，都会在汇总开头提示。
  - `--judge-provider` / `--judge-model` / `--judge-thinking` 换评委；每次评审记下评委模型和 rubric 版本。
  - rubric 的"收尾"不再按是否提交计分（提交数由 harness 记录）；同一个问题只在最相关的维度扣一次。
  - 中立起点：OpenSpec 侧起点就豁免 `openspec/changes/archive`，初始化不再需要 `--no-verify`；两侧的 `.bench/` 写进 `.git/info/exclude`，会话 trace 不会被提交。
  - 没有 pytest 汇总行时，测试摘要仍是字符串（原来是 list，汇总会崩）。

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
