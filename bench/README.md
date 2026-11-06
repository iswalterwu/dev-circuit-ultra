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

- n=1，模型和实现选择都有方差；分差只有 1 分，换一个评审或只评代码/文档，结论可能反转。
- LLM 盲评不是人类评审；分数用于比较，不是质量认证。
- 评审副本去掉了 `.git`、`.bench`、`.dev-circuit`；提交/未提交状态来自 `EVIDENCE.md`，不是本地可复核的 git 历史。
- Dev 的错误路径 bug 和 OpenSpec 的 float 合计问题都还在；这不是“两边都完成”的证明。

## 复现

需要 Windows、PowerShell 7、Python 3、Node 22、pi、OpenSpec 1.15。

```powershell
# 轻量、只读、继承当前模型的 reviewer（仅 benchmark 用）
copy bench/open/reviewer-fast.md $HOME\.pi\agent\agents\reviewer-fast.md

# Dev 起点
pwsh -NoProfile -File <repo>/skills/dev-circuit-ultra/scripts/new-project.ps1 `
  -Path <ab>/dev-circuit -Name records
cp -r bench/fixture/. <ab>/dev-circuit/
cp bench/open/AGENTS.md <ab>/dev-circuit/AGENTS.md
mkdir <ab>/dev-circuit/.dev-circuit
'{"mode":"agent","agent":"reviewer-fast"}' | Set-Content <ab>/dev-circuit/.dev-circuit/reviewer.json
git -C <ab>/dev-circuit add -A
git -C <ab>/dev-circuit commit -m "chore: add records fixture and reviewer default"
git -C <ab>/dev-circuit tag bench-base

# OpenSpec 起点
pwsh -NoProfile -File <repo>/skills/dev-circuit-ultra/scripts/new-project.ps1 `
  -Path <ab>/openspec -Name records
cp -r bench/fixture/. <ab>/openspec/
cp bench/open/AGENTS.md <ab>/openspec/AGENTS.md
cd <ab>/openspec
git add -A
git commit -q -m "chore: add records fixture"
openspec init --tools pi --language zh-CN --no-animation --no-copilot-cloud
git add -A
git commit --no-verify -m "chore: init openspec"
git tag bench-base

# 跑一次；根路径按需改 run_open_ab.py 的 ROOT
python bench/open/run_open_ab.py --root <ab>

# 生成图表
python bench/make_ab_chart.py
```

原始会话输出在 `bench/out/open/`（不提交）；机器可读结果见 [results_open_ab.json](results_open_ab.json)。

> OpenSpec 初始化用 `--no-verify`，是因为骨架的 `doc_guard` 会把 `openspec/changes/archive/` 当作禁止目录；这个 hook 不是 OpenSpec 侧的被测对象。
