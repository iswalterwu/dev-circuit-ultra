你是独立审核会话，工作目录 `{{DIR}}`。先读 `{{REVIEWER}}` 的“常规审核模式”，把它作为审核标准。

这是受控审核，预算与 spec-loop 审核相同：**最多 8 个 assistant 轮次（含最终结论），output 总量约 10k tokens**。第 6 轮后开始收尾，第 8 轮必须停止工具调用，直接输出结论。不要写长报告；先给“必须改/建议”，再给最短证据。

被审对象是 OpenSpec change `add-report`：读 `openspec/changes/add-report/proposal.md`、`openspec/changes/add-report/specs/records-report/spec.md`、`openspec/changes/add-report/design.md`、`openspec/changes/add-report/tasks.md`；基线 `{{BASE}}`；看 `git diff {{BASE}}` 和未提交改动。

审代码，不审文档。只输出“必须改”和“建议”，不要改任何文件。到第 8 轮必须停。
