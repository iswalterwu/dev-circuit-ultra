# spec-loop

用户级、可复用的功能开发流程：意图卡 → 只拆下一刀 → 实现+验证 → 独立审一次 → 验收合并。目标是快，而且不丢质量。

## 内容

- `skills/spec-loop/SKILL.md`：流程本身，agent 按需加载
- `skills/spec-loop/reviewer.md`：独立审核协议
- `skills/spec-loop/templates/`：意图卡、项目入口、文档"读我"块、待做池
- `skills/spec-loop/scripts/doc_guard.py`：防回流检查（只禁止，不要求）
- `sync.ps1`：同步到 `~/.claude/skills` 和 `~/.agents/skills`
- `tests/`：doc_guard 的测试

## 安装与升级

先看会做什么（不实际执行）：

```
pwsh -NoProfile -File D:\2030\spec-loop\sync.ps1 -WhatIf
```

确认无误后正式同步：

```
pwsh -NoProfile -File D:\2030\spec-loop\sync.ps1
```

## 在项目里接入

见 `skills/spec-loop/SKILL.md` 第 9 节。

## 修改规则

- 流程只在这个仓库里改，改完运行 `sync.ps1`。不要在项目里改流程。
- doc_guard 只禁止记账内容和历史目录：从不要求文档里出现某句话，也不设任何数字上限。
- 项目里复制的 `doc_guard.py`，文件头写着来源版本；升级时整体覆盖，不在项目里改。
- 运行测试：`python -m pytest tests -q`。
