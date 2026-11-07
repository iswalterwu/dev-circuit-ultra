# 变更记录

只记对使用者有影响的变化。版本号对应 git tag；`doc_guard` / `spec_check` 的脚本版本是各自独立的一条线，不跟包版本走。

## 未发布

- `doc_guard --include GLOB`：把默认范围之外的 `.md` 也纳入扫描；ignore 优先于 include。
- `spec_check` 的"已合并"提示跟随卡片语言：英文卡不再收到中文提示。
- demo 增加工具调用层边界：hook 在读取之前拦下账本，绝对路径和相对路径都拦。
- 开放 A/B 可以脚本化重跑：`bench/open/run_open_ab.py --runs N` 用 `--dry-run` 先看计划，跑完自动做随机 A/B 的盲评；`bench/summarize.py` 把多轮结果汇成中位数与配对差值。`tests/test_bench_harness.py` 用桩 `pi` / `openspec` 覆盖这套流程，不花 token。

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
