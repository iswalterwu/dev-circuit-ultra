# spec-loop

给 AI 编码 agent（Claude Code、Codex）用的轻量功能开发流程：

**意图卡 → 只拆下一刀 → 实现 + 验证 → 独立审一次 → 验收合并**

目标是快，而且不丢质量：

- 用户只在两处出场：点头（意图卡）和验收（每个切片）。
- 一件事只放一个地方：要做什么写在意图卡，做没做对靠测试，为什么写在提交说明里。
- 审代码，不审文档；一刀只审一次，复查最多一次。
- 文档只写现在。防回流检查 `doc_guard` 只禁止记账内容、历史目录和断链，从不要求文档里出现某句话，也不设任何数字上限。

完整规则见 [SKILL.md](skills/spec-loop/SKILL.md)，独立审核协议见 [reviewer.md](skills/spec-loop/reviewer.md)。

## 内容

| 路径 | 作用 |
|---|---|
| `skills/spec-loop/SKILL.md` | 流程本身，agent 按需加载 |
| `skills/spec-loop/reviewer.md` | 独立审核协议 |
| `skills/spec-loop/templates/` | 意图卡、项目入口、文档"读我"块、待做池，以及新项目骨架（`project/`） |
| `skills/spec-loop/scripts/doc_guard.py` | 防回流检查 |
| `skills/spec-loop/scripts/new-project.ps1` | 新建项目，或给已有仓库接入 spec-loop |
| `sync.ps1` | 把技能同步到 `~/.claude/skills` 和 `~/.agents/skills` |
| `tests/` | doc_guard 与 new-project 的测试 |

## 安装

需要 PowerShell 7（`pwsh`）、Git 和 Python 3。

```
git clone https://github.com/iswalterwu/spec-loop.git
```

先预演一遍，看看会做什么（不会实际改动）：

```
pwsh -NoProfile -File spec-loop/sync.ps1 -WhatIf
```

确认无误后正式安装：

```
pwsh -NoProfile -File spec-loop/sync.ps1
```

## 新建项目

```
pwsh -NoProfile -File $HOME/.claude/skills/spec-loop/scripts/new-project.ps1 -Path <新项目目录> -Name <项目名>
```

脚本会做这些事：

- 生成短入口 `AGENTS.md`，`CLAUDE.md` 只导入它；
- 生成 `specs/backlog.md` 和文档地图 `docs/README.md`；
- 放入 `scripts/doc_guard.py`、pre-commit hook 和 CI 检查；
- 执行 `git init`，并做第一次提交。

之后填好 AGENTS.md 里的项目事实（命令、代码地图、红线），就可以写第一张意图卡。

## 接入已有项目

```
pwsh -NoProfile -File $HOME/.claude/skills/spec-loop/scripts/new-project.ps1 -Path <已有仓库> -Adopt
```

- 只补缺失的文件，已有文件一律不覆盖，也不自动提交。
- 最后会运行一次 doc_guard，报出需要清理的旧文档，例如决策记录目录、维护记录、计划文件和 history 目录。
- 旧内容建议先打一个 Git tag 留档，再从工作树里移出；仍然有效的规则改写成现在时，并入 `docs/`。

## 让 agent 默认使用

在用户级配置里加一段说明。Claude Code 写在 `~/.claude/CLAUDE.md`，Codex 写在 `~/.codex/AGENTS.md`。大意是：

- 功能开发、改行为或接口、多文件重构，默认使用 `spec-loop` 技能；
- 项目 AGENTS.md 声明了别的流程，就按项目的走；项目里还有进行中的 OpenSpec 变更时，先用 OpenSpec 收尾；
- superpowers 只当技巧用（TDD、调试、完成前验证），在 spec-loop 项目里不生成 `docs/superpowers/` 下的文件。

## 升级

在本仓库里拉取更新后，重新运行 `sync.ps1`。

项目里复制的 `scripts/doc_guard.py` 不会自动更新，需要时从技能目录复制过去覆盖。

流程只在本仓库里改，不要在项目里改流程。

## 测试

```
python -m pytest tests -q
```

## 许可

[MIT](LICENSE)
