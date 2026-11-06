# Pre-rename spec-loop baseline vs OpenSpec：完整流程 A/B（受控审核预算）

> **Historical baseline.** 这组数据来自改名前的 `spec-loop`，早于 design-first 和项目外账本；它是实现循环的旧基线，不是新 `design-loop` 的 benchmark。

同一个需求、同一个模型、同一个起点，两边都跑完整流程，审核预算也拉到同一档：最多 8 个 assistant 轮次、约 10k output。spec-loop 走卡片、实现、独立审核、收尾；OpenSpec 走 propose、apply、独立审核、修复、agent-driven archive。

## 结果

| | spec-loop | OpenSpec 1.15 |
|---|---|---|
| agent 会话 | 3（实现 / 审核 / 收尾） | 5（提案 / 实现 / 审核 / 修复 / 归档） |
| 总成本 | $0.0961 | $0.1031 |
| 墙钟时间 | 389.6 s | 444.2 s |
| 代码改动 | +143 / −1 | +214 / −0 |
| 自带测试 | 27 | 51 |
| 隐藏验收 | 20/20 | 20/20 |
| 留存文档 | 66 行现行规格 | 500 行归档 + 304 行现行规格 |
| 独立代码审核 | 1 轮（1 必须改，5 条建议） | 1 轮（2 必须改，5 条建议） |
| 审核耗时 / 成本 | 65.6 s / $0.0145 | 65.8 s / $0.0171 |
| 提交 | 3 个 | 2 个 |

成本 1.07 倍、时间 1.14 倍；文档 12 倍差距；测试 OpenSpec 多 24 个。这是目前最接近 apple-to-apple 的一组。

参考点：

| 跑法 | 成本 | 时间 | 审核 | 说明 |
|---|---|---|---|---|
| spec-loop 完整 | $0.0961 | 389.6 s | 65.6 s / 1 必须改 | 本表主对比 |
| OpenSpec 受控完整 | $0.1031 | 444.2 s | 65.8 s / 2 必须改 | 本表主对比 |
| OpenSpec 不限审核 | $0.1540 | 665.2 s | 270.7 s / 3 必须改 | 审核深度重尾，仅参考 |
| OpenSpec 最短路径 | $0.0514 | 224.6 s | 无 | 只 propose + apply + `archive -y` CLI，下限 |

## 每一段花了多少

| 流程 | 会话 | 秒 | 输入 | 输出 | 缓存读 | 成本 |
|---|---|---|---|---|---|---|
| spec-loop | 实现（全部切片） | 192.9 | 21,697 | 31,312 | 885,888 | $0.0494 |
| spec-loop | 独立审核 | 65.6 | 10,125 | 9,094 | 89,216 | $0.0145 |
| spec-loop | 收尾（修必须改 + 合并 + 提交） | 131.1 | 20,703 | 18,496 | 630,656 | $0.0322 |
| OpenSpec | 提案 | 110.5 | 13,443 | 13,989 | 246,784 | $0.0223 |
| OpenSpec | 实现 | 144.1 | 22,720 | 16,812 | 842,368 | $0.0320 |
| OpenSpec | 独立审核（受控） | 65.8 | 19,088 | 9,029 | 86,784 | $0.0171 |
| OpenSpec | 修复 | 84.4 | 18,710 | 11,030 | 234,240 | $0.0203 |
| OpenSpec | agent 归档 | 39.4 | 19,534 | 3,601 | 199,552 | $0.0114 |

“输入 / 输出”是新 token；“缓存读”是每轮重新加载的上下文，按缓存价计费。

## 拆开看

| 阶段 | spec-loop | OpenSpec |
|---|---|---|
| 提案 / 规划 | 卡 102 s / 19.3k / $0.0250 | propose 111 s / 14.0k / $0.0223 |
| 实现 / 测试 | 51 s / 9.9k / $0.0163 | apply 144 s / 16.8k / $0.0320 |
| 独立审核 | 66 s / 9.1k / $0.0145 | 66 s / 9.0k / $0.0171 |
| 修复 / 收尾 | 112 s / 18.5k / $0.0322 | fix 84 s / 11.0k / $0.0203 + archive 39 s / 3.6k / $0.0114 |
| 探索 / 杂项 | 17 s / 1.9k / $0.0078 | — |
| 合计（模型时间） | 348 s / 58.9k / $0.0961 | 444 s / 54.5k / $0.1031 |

- **核心实现接近。** spec-loop 实现会话 193 s / $0.0494（含规划、代码、测试、探索）；OpenSpec 提案 + 实现 255 s / $0.0543。OpenSpec 多 62 s、$0.0049。
- **审核预算对齐后，审核几乎一样。** spec-loop 65.6 s / 9.1k output / 26.2k thinking / 1 必须改；OpenSpec 65.8 s / 9.0k output / 26.4k thinking / 2 必须改。OpenSpec 的审核成本略高（$0.0171 vs $0.0145），因为它的文档和测试更大，输入/缓存更多。
- **收尾也接近。** spec-loop 收尾 131 s / $0.0322；OpenSpec 修复 + agent 归档 124 s / $0.0317。
- **总差 7%。** 核心 +$0.005、审核 +$0.003、收尾 −$0.001，合计 +$0.007。文档 12 倍、测试 1.9 倍，但总成本没有拉开一个数量级。

## 审核预算

| | 轮次 | output | thinking 字符 | 秒 | 成本 | 必须改 |
|---|---:|---:|---:|---:|---:|---:|
| spec-loop | 8 | 9,094 | 26,232 | 65.6 | $0.0145 | 1（CRLF） |
| OpenSpec 受控 | 7 | 9,029 | 26,399 | 65.8 | $0.0171 | 2（`--total`/列选择、排序稳定性） |
| OpenSpec 不限 | 11 | 45,652 | 158,534 | 270.7 | $0.0632 | 3（含默认排序/spec 冲突） |

受控审核的 OpenSpec 和 spec-loop 几乎同预算；不限审核是重尾。不限审核那次多跑了 4 轮 / 36.7k output / 132k thinking，总成本 $0.154。

## 起点

- 4 条记录的 Python CLI，数据在 `records.json`。
- 已有 `export --id N`，输出单条 JSON。
- 需求见 [feature.md](feature.md)：加 `report` 命令，20 条验收，覆盖表格、CSV、JSON、排序、过滤、分页、列选择、合计、错误处理和旧命令兼容。
- 隐藏验收见 [hidden/test_report.py](hidden/test_report.py)：20 条，agent 看不到。

## 环境

- Windows 11，Python 3.14
- pi 1.5.0，`deepseek/deepseek-flash`，thinking high（pi 实际记录；两边相同）
- OpenSpec 1.15.0
- 运行日期：2026-11-06

## 流程

**spec-loop**

1. `new-project.ps1` 生成项目骨架，放进 fixture，提交为 `bench-base`。
2. 会话 1：读 skill，写 `specs/add-report/spec.md`，按 2–3 个切片完成全部实现和测试；不合并、不提交。
3. 会话 2：新会话独立审核全部切片，基线 `bench-base`。
4. 会话 3：修掉审核里的必须改，合并规格到 `docs/requirements/report.md`，提交，删卡。

**OpenSpec 受控完整流程**

1. `openspec init --tools pi`，放进 fixture，提交为 `bench-base`。
2. 会话 1：`openspec-propose`，生成 proposal、规格 delta、设计、任务。
3. 会话 2：`openspec-apply-change`，实现任务并跑测试。
4. 会话 3：独立审核，读 change 的 proposal/spec/design/tasks 和 `git diff bench-base`；用同一份 `reviewer.md` 标准；最多 8 轮 / 10k output。
5. 会话 4：处理必须改，补测试，跑 `pytest` 和 `openspec validate`，提交。
6. 会话 5：`openspec-archive-change`，检查 artifact/task，sync delta specs 到主规格，归档，提交。

**参考跑法**

- 不限审核：同一个 review 提示词，不设 8 轮 / 10k 上限；OpenSpec 审核跑了 11 轮 / 45.7k output。
- 最短路径：propose + apply + `openspec archive -y` CLI，不跑审核、fix、agent archive。

## 怎么测的

- 会话：`pi -p`，每次独立 `--session-dir`，从 session JSONL 汇总 token 和成本。
- 代码：`git diff --numstat bench-base..HEAD`，加上工作树里的未提交改动。
- 测试：项目自己的 `pytest tests -q`，再加隐藏验收 `pytest hidden_tests -q`。
- 文档：数最终留存的行数；spec-loop 的卡在收尾后已删除，不计入留存。
- 审核：两边都用 `skills/dev-circuit-ultra/reviewer.md` 的常规审核模式；OpenSpec 没有独立 code review skill，这一步是补上的同类质量门。
- 审核预算：最多 8 个 assistant 轮次、约 10k output；实际 spec-loop 8 轮 / 9.1k，OpenSpec 7 轮 / 9.0k。

## 注意

- **n=1。** 一次运行只能看差异，不能当基准。审核轮次/输出受模型状态影响；OpenSpec 不限审核的 271 s 是重尾。
- **审核预算对齐，但审核内容不完全对齐。** OpenSpec 的测试 51 个、文档 804 行，spec-loop 27 个、66 行；OpenSpec 的审核面更大，抓到 2 条必须改，spec-loop 抓到 1 条。spec-loop 更便宜，但测试/审核覆盖也更少；这不是“同等质量下更便宜”的证明。
- **spec-loop 的 `--total --columns amount` 仍有边角问题。** 手工复现：`report --total --columns amount` 最后一行是裸 `4360`，没有 `TOTAL` 标签；它的 27 个测试和这次审核没覆盖。OpenSpec 的 51 个测试和审核抓到了同类问题。这是 lean 测试面的代价。
- **两边都没有人类 plan sign-off/clarify。** feature.md 足够具体，提示词也明确不让提问；spec-loop 的卡“点头”和 OpenSpec propose 后的 plan review 都是人类步骤，这次都跳过了。
- **OpenSpec 不限审核的参考跑有 spec 漂移。** 那次 propose 把默认排序写成“保持文件顺序”，和 feature.md 的“默认 id”不一致；审核按它自己的 spec 修了代码。受控这次 propose 写的是默认 id，和 feature 一致。propose 有方差，不能把不限审核那次的 spec 当成稳定行为。
- **OpenSpec 的 archive 用了 agent-driven skill，不是 CLI `-y`。** 39.4 s / $0.0114；最短路径 CLI 是 1.1 s。
- 成本由 pi 按当时的模型价格计算，不一定是最终扣费金额。

## 复现

需要 Windows、PowerShell 7、Python 3、Node 22、pi 和 OpenSpec 1.15。

```powershell
# spec-loop 起点
pwsh -NoProfile -File <repo>/skills/dev-circuit-ultra/scripts/new-project.ps1 `
  -Path <ab>/spec-loop -Name records
cp -r bench/fixture/. <ab>/spec-loop/
cp bench/setup/AGENTS.spec-loop.md <ab>/spec-loop/AGENTS.md
git -C <ab>/spec-loop add -A
git -C <ab>/spec-loop commit -m "chore: add records fixture"
git -C <ab>/spec-loop tag bench-base

# OpenSpec 起点
cp -r bench/fixture <ab>/openspec
git -C <ab>/openspec init
git -C <ab>/openspec add -A
git -C <ab>/openspec commit -m "chore: add records fixture"
openspec init --tools pi --language zh-CN --no-animation --no-copilot-cloud <ab>/openspec
git -C <ab>/openspec add -A
git -C <ab>/openspec commit -m "chore: init openspec"
git -C <ab>/openspec tag bench-base

# spec-loop 完整流程
python bench/run_ab.py --root <ab> --skills <repo>/skills/dev-circuit-ultra

# OpenSpec 受控完整流程（propose/apply/review/fix/archive）
python bench/run_openspec_capped.py

# 参考：OpenSpec 不限审核
python bench/run_openspec_full.py
```

`run_ab.py` 每次都会把两边重置到 `bench-base`，结果写到 `bench/out/`。完整结果见 [results.json](results.json)；`openspec_capped`、`openspec_full`、`openspec_minimal` 三个字段分别是受控、不限审核、最短路径。
