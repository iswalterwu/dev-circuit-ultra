工作目录 `{{DIR}}`。先读 `{{REVIEW}}`，再读 OpenSpec change `add-report` 的规格、设计和任务。

处理审核里的“必须改”：改代码和测试，跑 `python -m pytest -q` 和 `openspec validate add-report --strict`。不要归档。

完成后提交，提交说明写清修了什么、为什么、跑了哪些验证。不要问我问题。
