工作目录 `{{DIR}}`。先读 `specs/add-report/spec.md` 和 `{{REVIEW}}`。

1. 处理审核里的“必须改”：改代码和测试，跑 `python -m pytest -q`、`python scripts/doc_guard.py` 和 `python scripts/spec_check.py`。
2. 按 dev-circuit-ultra 的收尾：把“规格变化”合并进 `docs/requirements/report.md`（能力代号 REPORT，按 `docs/requirements/README.md` 的格式），按流程提交；然后删除 `specs/add-report/`，提交 `close add-report`。

不要创建或读取项目外的账本，不要问我问题。
