# <项目名> — agent 入口

> 先读本页，然后按"按任务读什么"只读当前任务需要的文件和小节。不要通读 docs/；除非用户要求，不要翻 Git 历史找规则。

## 1. 项目一句话

<是什么、给谁用、技术栈。>

## 2. 按任务读什么

| 任务 | 读 |
|---|---|
| 判断需求属于哪个能力、框架接不接得住 | `devcircuit context --map`，再读 `docs/architecture.md` 开头的框架摘要 |
| 做或续做一个功能 | `devcircuit context --feature <feature>` 的输出 + dev-circuit-ultra 技能 |
| 查某个能力的现行要求 | `devcircuit context --capability <代号>`，要原文用 `--ids <编号>` |
| 改某个代码目录 | 该目录的 README |
| 找零散的待做事项 | `specs/backlog.md` |
| <领域任务> | `docs/<文档>.md`，先看顶部"读我" |

## 3. 常用命令（提交前检查）

- <测试、类型检查、构建命令>
- 文档防回流：`python scripts/doc_guard.py`
- 要求编号检查：`python scripts/spec_check.py`（加 `--report` 可查看未被测试引用的要求和演示要求清单）
- 误杀时用白名单：`--ignore <GLOB>`、`--ignore-rule <RULE>`，或在项目根写 `.dcuignore`
- 两个检查器直接运行、按输出修；规则名和它们查什么用 `--list-rules` 看，不要读源码
- 上下文：`devcircuit context`；账本：`devcircuit ledger add`（只写）、`devcircuit ledger check`（核对）；收尾：`devcircuit close <feature>`
- 新克隆后执行一次：`git config core.hooksPath .githooks`

## 4. 代码地图

- `<目录>/`：<一句话说明>

## 5. 红线

<产品护栏、数据与安全、环境。>

- 主干：`main`（`devcircuit` 默认拿它当对比的基线）。
- 分支：每个功能在 `feat/<feature>` 上做，主干只放验收过的内容。

## 6. 工程准则

1. 不为猜测出来的竞态或安全边界增加复杂度。只有能说清"具体怎么出错、概率多大、要写多少代码"的才做，而且要先报给用户、得到同意；不悄悄扩大改动范围。
2. 外部数据只在入口层校验：用户输入、外部 API、网络响应在边界处校验一次，并转成确定的类型；往里只传确定类型的值，内部不重复做防御性检查。
3. 不提前抽只用一次的函数。只有会复用、封装了确实复杂的逻辑，或者代表一个能起清楚名字的概念时，才抽出来。
4. 主函数只写正常流程，校验和细节放到它下面的小函数里。
5. 自动生成的文件不手改；改源头，然后重新生成。
6. 测试要测真实实现：不把业务逻辑抄一份进测试，尽量少用 mock（优先用真实实现，或在系统边界注入）。
7. 按仓库现有的做法走，不引入仓库里没在用的工具或流程。

## 7. 开发流程与文档规则

- 做功能、修 bug、改文档按 dev-circuit-ultra 技能进行，规则以技能为准；本项目不使用 OpenSpec，也不生成 superpowers 的设计或计划文件。
- 文档只写现在，为什么这么做写进提交说明和账本；`doc_guard` 会拦历史写法。
- 账本在项目外，只用 `devcircuit ledger add` 写、`devcircuit ledger check` 核对，不读；需要历史时问用户。
- 审核模型：<同模型 / 指定的 agent 或模型>。
