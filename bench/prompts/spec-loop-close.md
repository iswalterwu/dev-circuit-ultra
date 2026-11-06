工作目录 `{{DIR}}`。先读 `specs/add-report/spec.md` 和 `{{REVIEW}}`。

1. 处理审核里的“必须改”：改代码和测试，跑 `python -m pytest -q` 和 `AGENTS.md` 列出的提交前检查。
2. 按 spec-loop 的 ⑤ 收尾：把“规格变化”合并进 `docs/requirements/report.md`（能力代号 REPORT，按 `docs/requirements/README.md` 的格式），把卡里这一节的标题改成 `## 规格变化（已合并）`，按流程提交；然后删除 `specs/add-report/`，提交 `close add-report`。

不要问我问题。
