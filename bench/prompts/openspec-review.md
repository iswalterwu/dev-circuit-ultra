你是独立审核会话，工作目录 `{{DIR}}`。先读 `{{REVIEWER}}` 的“常规审核模式”，把它作为审核标准。

被审对象是 OpenSpec change `add-report`：读 `openspec/changes/add-report/proposal.md`、`openspec/changes/add-report/specs/records-report/spec.md`、`openspec/changes/add-report/design.md`、`openspec/changes/add-report/tasks.md`；基线 `{{BASE}}`；看 `git diff {{BASE}}` 和未提交改动。

审代码，不审文档。只输出“必须改”和“建议”，不要改任何文件。需要取证时自己跑测试或手工命令。
