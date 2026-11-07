# 最新 A/B：Dev-circuit-ultra vs OpenSpec

> 2026-11-06。同一个 fixture、同一个开放提示、同一个模型，各跑一次端到端会话。n=1；这是最终交付物盲评，不是统计基准，也不是“Dev 全面更好”的结论。

这次没有固定验收清单、切片数、审核预算或指定命令形状。两个 skill 自己决定设计、实现、测试和收尾。

## 结果

| 指标 | Dev-circuit-ultra | OpenSpec | 差异 |
|---|---:|---:|---:|
| 盲评总分（30） | **27** | 26 | +1 |
| 墙钟时间 | **408.9 s** | 421.0 s | −12.1 s（−2.9%） |
| 模型成本 | **$0.0743** | $0.1060 | −$0.0317（−29.9%） |
| 输入 + 输出 tokens | **72,308** | 113,337 | −41,029（−36.2%） |
| 缓存读取 tokens | **1,891,968** | 3,678,333 | −1,786,365（−48.6%） |
| 观测 tokens 合计 | **1,964,276** | 3,791,670 | −1,827,394（−48.2%） |
| assistant 轮次 | **39** | 50 | −11（−22%） |
| 留存文档 | **2 个文件 / 132 行** | 3 个文件 / 273 行 | −1 个 / −141 行（−51.6%） |
| 项目测试 | 13 passed | **21 passed** | 覆盖更窄，见下 |
| 收尾 | **1 个提交，0 条未提交交付物** | 0 个提交，11 条未提交 | 收尾干净 vs 未收尾 |
| 原有 `export --id 1` | 通过 | 通过 | 相同 |
| 隐藏验收 | 未使用 | 未使用 | 相同 |

时间/成本/token/文档/轮次/收尾都是 **相对 OpenSpec 的减少量**；测试数不是“越少越好”，单独列为代价。

<p align="center"><img src="../assets/ab-comparison-zh.svg" alt="最新开放 A/B：Dev-circuit-ultra 对比 OpenSpec" width="100%"></p>

## 节省在哪

- **时间**：409 s vs 421 s，少 12 s；差距很小，不能包装成数量级提升。
- **token 成本**：模型成本低 30%；输入+输出 token 少 36%；缓存读取少 49%。缓存读取的单价和计费方式取决于 provider，不能直接按 token 数换算成钱。
- **文档**：需求 + 使用说明 + OpenSpec 主规格这组留存文档，Dev 132 行，OpenSpec 273 行，少约一半。这里没有计 OpenSpec 的 proposal/design/tasks，所以不是“OpenSpec 全部文档只有 273 行”。
- **轮次**：39 vs 50，少 11 个 assistant turn；不是单纯少做事，而是少了结构审、重复审核和重复全量检查。
- **收尾**：Dev 1 个提交、没有未提交交付物；OpenSpec 0 个提交、11 条未提交。这一项是两者最大差距，也是 Dev 盲评高 1 分的主要来源。

## 代价

- Dev 只有 13 条测试，OpenSpec 有 21 条；Dev 没覆盖数据文件缺失、坏 JSON、`-o` 不可写等错误路径，会 traceback。
- OpenSpec 的错误处理更完整：缺失文件、坏 JSON、非 UTF-8、非法记录结构、不可写输出都退出 2。
- OpenSpec 的金额合计用 float，`0.1+0.2` 会输出 `0.30000000000000004`；Dev 用 Decimal。
- Dev 的胜点主要是干净收尾和 Decimal，不是测试更全；OpenSpec 的胜点是测试和错误处理，不是收尾。

## 这次测了什么

- 起点：同一个 records CLI fixture、同一个 `new-project` 骨架、同一份中性 [AGENTS.md](open/AGENTS.md)。
- 任务：[open/problem.md](open/problem.md) 的每周费用报告，命令、参数和输出由 agent 自己定。
- 每边一个 `pi -p` 会话；没有额外 review/fix 轮次，没有隐藏验收。
- Dev 的 `.dev-circuit/reviewer.json` 预置为 `reviewer-fast`，因为 benchmark 非交互；真实用户第一次运行时由 skill 询问并保存，见 SKILL §1.2。
- 评审：[open/rubric.md](open/rubric.md)；盲评结果与映射：[open/judge-result.md](open/judge-result.md)。
- Dev trace：[open/dev-trace.md](open/dev-trace.md)。

## 限制

- n=1，模型和实现选择都有方差；分差只有 1 分，在评审噪声之内（同一份产物重评的差值范围是 −3 到 +9，见下一节）。
- LLM 盲评不是人类评审；分数用于比较，不是质量认证。
- 评审副本去掉了 `.git`、`.bench`、`.dev-circuit`；提交/未提交状态来自 `EVIDENCE.md`，不是本地可复核的 git 历史。
- 上表的成本和 token 只算了主会话，不含 Dev 的 reviewer 子 agent（它只把用量写在工具结果里）。用仍在的会话文件含 reviewer 重算：成本 **$0.1036 vs $0.1060（−2.3%）**，输入 + 输出 122,064 vs 113,337（**+7.7%**），缓存读取 2,175,232 vs 3,678,333（−40.9%）。reviewer 两次调用共 $0.0292，占 Dev 成本 28%。墙钟时间本来就包含子 agent。
- Dev 的错误路径 bug 和 OpenSpec 的 float 合计问题都还在；这不是“两边都完成”的证明。

## 脚本化重跑（2026-11-07，3 轮；第 1 轮产物共评 9 次）

同一问题、同一模型，用 `run_open_ab.py` 跑 3 轮；第 1 轮的同一份产物另外盲评 8 次（A/B 交替、有无 EVIDENCE 各半）。

| 指标（3 轮中位数，括号为范围） | Dev-circuit-ultra | OpenSpec |
|---|---:|---:|
| 盲评总分（30） | 26（23–26） | 27（25–27） |
| 错误路径探针（9 项，机械判定；11-06 那轮是 2 vs 6） | 4（2–6） | **8（8–9）** |
| 模型成本（第 1 轮 / trace-a / trace-b） | $0.0752* / 0.0738 / 0.1022 | $0.0825 / 0.0971 / 0.0886 |
| 主会话 assistant 轮次 | 33 / 28 / 59 | 49 / 61 / 42 |
| 墙钟时间 | 414 s（333–547） | 381 s（337–464） |
| 项目测试 | 15（13–18） | 22（20–24） |
| 提交 / 未提交 | **2–3 / 0** | 0 / 12 |

- **单次盲评分辨不了 ±3 分**：同一份产物 9 次评审，Dev 22–28、OpenSpec 19–29，差值 −3 到 +9。
- **EVIDENCE 左右总分**：有 EVIDENCE（评审看得到提交状态）时差值均值 +3.75（4/4 Dev 胜），没有时 −0.4。差别几乎全在“收尾”：OpenSpec 三轮都是 0 提交、12 条未提交。
- **去掉收尾，质量分 4 轮都不占优**：第 1 轮 9 次评审的其余 5 项（满分 25）Dev 21.6、OpenSpec 21.8；另外三轮的差值是 −1（11-06）、−7（trace-a）、−1（trace-b）。Dev 产品用途和测试略高，正确性、文档、代码偏低。trace-a 那轮 Dev 收尾多 3 分也补不回来，总分 23 vs 27。
- **稳定的差距只有一个：错误路径**。探针在 `export`/`report` 上试缺数据文件、坏 JSON、非数组、写不进去和小数金额；连同 11-06 共 4 轮，Dev 2/9、6/9、2/9、4/9，OpenSpec 6/9、8/9、8/9、9/9，每轮都是 OpenSpec 高。只看新命令 `report` 自己的 4 种失败：OpenSpec 16/16，Dev 5/16。有 trace 的三轮里，Dev 处理了哪些失败，恰好就是意图卡设计里写到的那几种。
- 成本：Dev 的 reviewer 子 agent 占其成本 18–28%（含 11-06）。\* 第 1 轮的 trace 已丢失，只有主会话成本；按同一占比估算约 $0.092–0.105，高于 OpenSpec。连同 11-06，4 轮里 Dev 两轮更便宜（−2.3%、−24%）、两轮更贵，两轮更快；主会话轮次 3 轮更少。按 deepseek-flash 价格（输入 / 输出 / 缓存读取每百万 $0.30 / $1.20 / $0.006），成本约三分之二是输出 token，缓存读取少 40–60% 每轮只省约 $0.01。
- 上面 n=1 那张表的 27 vs 26 和这里的单轮分数一样，都落在评审噪声里。

不确定性：评委与被测是同一个模型；骨架是 Dev 自己的（OpenSpec 侧要豁免 `doc_guard`）；是否把“已提交”算进收尾，rubric 只写了“提交或工作树状态可解释”。

## 复现

需要 Python 3.10+、git、Node 22、pi、OpenSpec 1.15。脚本自己搭起点，不再需要手工敲一遍流程：

```powershell
# 先看一眼它会做什么（不创建任何目录、不花 token）
python bench/open/run_open_ab.py --dry-run --runs 3

# 三轮成对运行 + 盲评，结果落在 bench/out/open-<时间戳>/
python bench/open/run_open_ab.py --runs 3

# 汇总（可把多个结果目录并在一起，得到 n>1 的中位数与配对差值）
python bench/summarize.py bench/out/open-*
```

一轮做了什么：

- 从 `bench/fixture` + 骨架生成两侧仓库，打 `bench-base` 标签，Dev 侧预置 `reviewer.json`（`--reviewer` 可换）。
- 同一份 `open/prompt.md`、同一个模型，每侧一个 `pi -p` 会话；跑完把两侧从 `bench-base` 重置，所以多轮互不污染。
- 每侧跑完立刻把会话 trace 存到 `run-NN/<side>-sessions/`、最终代码树存到 `run-NN/final/<side>/`；下一次 `git clean` 不会带走它们。
- 每轮随机指定 A/B 并交换先后顺序（`--seed`），在仓库外的临时目录搭出只含 `A/`、`B/`、`problem.md`、`rubric.md` 和 `EVIDENCE.md` 的盲评目录（git 不会向上找到本仓库），交给另一个 `pi -p`，分数解析成 JSON 后按映射还原。`EVIDENCE.md` 写两侧的提交、`git status` 与 pytest 结果，因为副本里没有 `.git`。
- 记录耗时、成本（含 reviewer 等子 agent）、token、轮次、测试数、提交/未提交、留存文档行数；汇总表给中位数和区间，不把单一数字当结论。

量评委本身：`--rejudge <结果目录> --repeats 4 --jobs 2` 对已存的产物重新盲评，偶数次 Dev 在 A、奇数次在 B；加 `--no-evidence` 可以看证据的影响。`summarize.py` 会把同一份产物的多次评审列成“评委信度”一节。

常用参数：`--no-judge` 只测指标、`--model`/`--thinking`/`--judge-model` 换模型、`--root` 复用固定目录、`--keep` 保留临时仓库、`--timeout` 单侧超时。

原始会话输出在结果目录里（不提交）；上一轮的手写结果仍在 [results_open_ab.json](results_open_ab.json) 与 [open/judge-result.md](open/judge-result.md)。

> OpenSpec 初始化用 `--no-verify`，是因为骨架的 `doc_guard` 会把 `openspec/changes/archive/` 当作禁止目录；这个 hook 不是 OpenSpec 侧的被测对象。
