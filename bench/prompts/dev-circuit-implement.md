你在 {{DIR}}，一个 Python 项目。先读 `AGENTS.md`，再完整读 dev-circuit-ultra 的流程文件 `{{SKILL}}/SKILL.md`。

按 dev-circuit-ultra 做功能 `add-report`。这是普通功能，走功能路线。这个功能有 20 条验收，按 2–3 个切片推进：

1. 写 `specs/add-report/spec.md`，按模板包含目标、范围、结构影响、`## 设计`、规格变化、风险、切片、待定；待定项给默认值。规格变化要覆盖 20 条验收。
2. 在本会话内依次完成所有切片；每个切片开始前在卡里写清 3–8 个步骤，完成后跑测试。
3. 全部切片实现并验证：测试名带要求编号；跑 `python -m pytest -q`；跑 `python scripts/doc_guard.py` 和 `python scripts/spec_check.py`。

这是基准测试，不要做独立审核，不要合并规格，不要删卡，不要提交。不要创建、读取或搜索项目外的账本。完成后停手，输出卡片路径、切片列表、改动文件和测试结果。

不要问我问题；有歧义就按下面的验收标准选默认值。

需求：

{{FEATURE}}
