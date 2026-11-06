# DeepSeek Harness

Dev-circuit-ultra 同时是一个 Pi 包、一个 DSH 插件包，以及三个可单独发布的 skill。三种入口装的是同一份 `skills/`，不要混装同一来源的多个副本。

## 兼容性

DSH 的本地 skill provider 只扫描一层目录：

```text
<root>/<skill-name>/SKILL.md
```

它不会递归查找 `skills/<name>/SKILL.md`，也不读取 `package.json`。因此：

- **Skill Store / 手动安装**：把单个 `skills/<name>/` 目录放到 `~/.dsh/skills/`、项目 `.dsh/skills/` 或 `~/.agents/skills/`。
- **DSH 插件安装**：根目录的 `package.json` 声明 `dsh.bundle`，`index.js` 把三个 skill 注册进 `ctx.skills`；一条命令装齐。
- **Pi 安装**：同一份 `package.json` 声明 `pi.skills`，Pi 从 `skills/` 加载三个 skill。

`SKILL.md` frontmatter 使用 DSH 可识别的字段：

```yaml
name: dev-circuit-ultra
description: ...
whenToUse: ...
```

`dev-circuit-archivist` 和 `dev-circuit-ledger` 标记了 `disable-model-invocation: true`：模型不会自动调用它们，human 仍可通过命令显式加载。这是隔离边界的一部分，不要删。

## 安装

### 方式 A：DSH 插件（推荐，装齐三个 skill）

发布 npm 包后：

```powershell
dsh plugin --profile web add dev-circuit-ultra
```

从源码 checkout 安装：

```powershell
dsh plugin --profile web add file:D:\path\to\dev-circuit-ultra
```

`cordis.patch.yml` 插入一行插件，`index.js` 在插件挂载时注册：

- `dev-circuit-ultra`（model + human）
- `dev-circuit-archivist`（human only）
- `dev-circuit-ledger`（human only）

### 方式 B：同步到 DSH skill 根目录

```powershell
pwsh -NoProfile -File sync.ps1
```

会同步到：

```text
~/.claude/skills
~/.agents/skills
$DSH_HOME/skills（未设置时为 ~/.dsh/skills）
```

适合不想装 DSH 插件、只想用纯 skill 的用户。

### 方式 C：Skill Store

社区商店 [dsh-skill-store](https://github.com/cxy9204/dsh-skill-store) 从 SkillHub、ClawHub 和 GitHub 镜像安装 skill。装好后在 DSH Web 的 Settings → Skill Store 搜索 `dev-circuit-ultra`，一键写入 `~/.dsh/skills/<name>/SKILL.md`。

商店安装的是单个 skill 目录；三个 skill 需要分别发布/安装。需要一次装齐时用方式 A。

## 发布到商店

商店本身不托管代码；它读取上游 registry。至少发布到 SkillHub 或 ClawHub 之一。

### ClawHub

```powershell
npm install -g clawhub
clawhub login
clawhub skill publish ./skills/dev-circuit-ultra `
  --slug dev-circuit-ultra `
  --name "Dev-circuit-ultra" `
  --version 0.1.0 `
  --categories development `
  --topics "agent-skills,workflow,design,code-review,deepseek-harness"
```

同伴 skill 用相同命令，把路径和 `--slug` 换成 `dev-circuit-archivist`、`dev-circuit-ledger`。

### SkillHub

```powershell
$env:SKILLHUB_TOKEN = "<token>"
npx @astron-team/skillhub@latest publish ./skills/dev-circuit-ultra
```

同伴 skill 分别执行。SkillHub 的评测/审核通过后，商店的 SkillHub 标签页即可搜到。

### npm（Pi / DSH 插件）

```powershell
npm publish --access public
```

发布前先跑：

```powershell
npm pack --dry-run
python -m pytest -q
```

## Store 文案

标题：

```text
Dev-circuit-ultra
```

一句话：

```text
设计是源，账本在外：通过更少的上下文占用实现增效减负，一个去掉繁琐流程的开发loop。
```

详情：

```text
Dev-circuit-ultra 把功能开发拆成设计澄清、单个切片、实现与验证、独立审核、收尾合并五步。项目里只保留现行设计和能力规格；旧设计原地覆盖或删除；为什么这么做、哪些方案没选，由 human 在项目外的私有账本记录，开发 agent 不读。适合独立开发者用 Claude Code、Codex、pi 或 DeepSeek Harness 连续交付，不想维护 proposal / tasks / archive 的人。
```

标签：

```text
agent-skills, workflow, design, code-review, spec-driven-development, deepseek-harness
```

## 发布检查

- `python -m pytest -q` 通过。
- `npm pack --dry-run` 包含 `index.js`、`cordis.patch.yml`、`skills/` 和 README。
- 在干净的 DSH profile 中执行 `dsh plugin --profile web add <包>`，确认三个 skill 出现在目录里。
- `dev-circuit-archivist` / `dev-circuit-ledger` 不出现在模型自动调用目录中。
- 只把 `skills/<name>/` 发布到商店，不要把整个仓库根目录当作单个 skill 发布。
