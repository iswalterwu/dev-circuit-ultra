# DeepSeek Harness

Dev-circuit-ultra 同时是一个 Pi 包、一个 DSH 插件包，以及两个可单独发布的 skill。三种入口装的是同一份 `skills/`，不要混装同一来源的多个副本。

## 兼容性

DSH 的本地 skill provider 只扫描一层目录：

```text
<root>/<skill-name>/SKILL.md
```

它不会递归查找 `skills/<name>/SKILL.md`，也不读取 `package.json`。因此：

- **手动安装**：把整个 `skills/<name>/` 目录放到 `~/.dsh/skills/`、项目 `.dsh/skills/` 或 `~/.agents/skills/`。放进项目 `.dsh/skills/` 的，在主干上提交它，或把 `.dsh/skills/` 写进 `.gitignore` 并在主干上提交。留着不跟踪的话，`feat/` 分支上卡提交之前，`spec_check` 会把里面的 `.py`、`.ps1` 报成 `code-before-design`，`devcircuit close` 也会因为工作区不干净而拒绝收尾。
- **Skill Store**：一键安装只下载 `SKILL.md`，同目录的其他文件不装，见方式 C。
- **DSH 插件安装**：根目录的 `package.json` 声明 `dsh.bundle`，`index.js` 把两个 skill 注册进 `ctx.skills`；一条命令装齐两个 skill。
- **Pi 安装**：同一份 `package.json` 声明 `pi.skills`，Pi 从 `skills/` 加载两个 skill。

`SKILL.md` frontmatter 使用 DSH 可识别的字段：

```yaml
name: dev-circuit-ultra
description: ...
whenToUse: ...
```

`dev-circuit-ledger` 标记了 `disable-model-invocation: true`：模型不会自动调用它，human 仍可通过命令显式加载。这是隔离边界的一部分，不要删。开发 agent 写账本不靠技能，而是用 `devcircuit ledger add`（只写不读）。

## 安装

三种方式都只装技能，流程还依赖 `devcircuit` CLI（Python 3.10+，`context`、`ledger`、`close` 都靠它）。装 CLI、建项目、建账本、装 hook 照 [README 快速开始](../README.zh-CN.md#快速开始) 做。devcircuit 的 hook 只有 pi 和 Claude Code 两种，没有给 DSH 的：要不要跑 `hooks install`、要隔离账本怎么做，照快速开始里写给别的 agent 的那段做。用方式 A 时不跑快速开始第 2 步的 `devcircuit sync`：不带 `--target` 时它也写进 DSH 读的 `~/.agents/skills` 和 `$DSH_HOME/skills`，和插件混装；别的 agent 要用，就加 `--target` 只写它们的目录（如 `--target ~/.claude/skills`）。

### 方式 A：DSH 插件（推荐，装齐两个 skill）

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
- `dev-circuit-ledger`（human only）

方式 A 的技能跟着插件包，`devcircuit` 跟着 pipx，两边要装同一版：从 npm 装插件时，CLI 装同一版本的 tag（`pipx install --force git+https://github.com/iswalterwu/dev-circuit-ultra@v<版本>`）；从源码 checkout 装插件时，CLI 也从这份 checkout 装（`pipx install --force D:\path\to\dev-circuit-ultra`）。升级时两边一起升；README 升级说明里的 `devcircuit sync` 也只带 `--target` 跑。

### 方式 B：同步到 DSH skill 根目录

```powershell
devcircuit sync
```

会同步到：

```text
~/.claude/skills
~/.agents/skills
$DSH_HOME/skills（未设置时为 ~/.dsh/skills）
```

适合不想装 DSH 插件、只想用纯 skill 的用户。写进去的是已安装的 `devcircuit` 自带的那一版技能：要新版技能，先升级 CLI（`pipx install --force git+https://github.com/iswalterwu/dev-circuit-ultra`），在项目根目录跑 `devcircuit vendor` 并提交，再同步（升级的其余步骤见 [README 快速开始](../README.zh-CN.md#快速开始) 一节）。每次同步都会移除已退役的旧技能目录；`--target <目录>`（可重复）只写给定的目录。仓库根目录的 `sync.ps1` 转发到同一个命令，PATH 上找不到 `devcircuit` 时才用本仓库的 `tools/` 和 `skills/`。

### 方式 C：Skill Store

社区商店 [dsh-skill-store](https://github.com/cxy9204/dsh-skill-store) 从 SkillHub、ClawHub 和 GitHub 镜像安装 skill。装好商店插件后，在 DSH Web 的「设置 → 技能商店」里搜索、一键安装：它只把 `SKILL.md` 写进 `~/.dsh/skills/<name>/`（ClawHub、SkillHub 来源另写一个记录来源的 `.dsh-skill-store.json`），同目录的其他文件不装。

`dev-circuit-ledger` 只有 `SKILL.md`，从商店装是完整的；`dev-circuit-ultra` 还要同目录的 `framework.md`、`large.md`、`reviewer.md`、`setup.md`、`templates/` 和 `scripts/`，从商店装会缺这些文件，要用方式 A 或 B 装。方式 A、B 都会装上两个 skill，用了它们，就不要另从商店装 `dev-circuit-ledger`。

## 发布到商店

商店本身不托管代码；它读取上游 registry。只发到 SkillHub 的话，新发布的 skill 在商店里搜不到（见下面 SkillHub 一节），所以至少发布到 ClawHub。商店一键安装只下载 `SKILL.md`（见方式 C）：`dev-circuit-ultra` 发布到商店后，DSH 用户装它仍用方式 A 或 B。

### ClawHub

```powershell
npm install -g clawhub
clawhub login
clawhub skill publish ./skills/dev-circuit-ultra `
  --slug dev-circuit-ultra `
  --name "Dev-circuit-ultra" `
  --version 0.7.0 `
  --categories development `
  --topics "agent-skills,workflow,design,code-review,deepseek-harness"
```

同伴 skill 用相同命令，把路径和 `--slug` 换成 `dev-circuit-ledger`，`--name` 换成 `"Dev-circuit-ledger"`。

### SkillHub

商店的 SkillHub 标签页读的是 skillhub.cn（`api.skillhub.cn`）。`npx @astron-team/skillhub` 是另一个 SkillHub（iFlytek）的 CLI，默认发到 `skill.xfyun.cn`，商店读不到。

发到 skillhub.cn 用它自己的 CLI，也可以在网页上传。注册、实名认证、建 API key 和装 CLI 见 [skillhub.cn/tutorials](https://skillhub.cn/tutorials)；CLI 支持 macOS 和 Linux，Windows 在 WSL 里跑。skillhub.cn 要求 `SKILL.md` 的 frontmatter 有 `slug`（全站唯一）、`version`（SemVer）和 `displayName`；两个 skill 的 `SKILL.md` 没有这三个字段（名字写在 `name`，版本写在 `metadata.version`），先在两个 `SKILL.md` 的 frontmatter 顶层补上，`version` 和 `metadata.version` 写同一个值，再发布：

```bash
skillhub login --key "<token>" --host https://api.skillhub.cn
skillhub publish ./skills/dev-circuit-ultra --dry-run
skillhub publish ./skills/dev-circuit-ultra --changelog "<这一版的变化>"
```

同伴 skill 分别执行。发布后先审核，通过后才公开。商店的 SkillHub 标签页只收录 skillhub.cn 的热门榜、趋势榜和下载量最高的前 2000 个 skill：新发布的 skill 进这几份榜单之前，在商店里搜不到，也装不了。三个字段补进仓库的话，`tests/test_package.py` 的版本一致性检查也要覆盖顶层的 `version`。

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
Dev-circuit-ultra 一次交付一个功能：先识别需求属于在研功能、已有能力、新能力、bug 还是探索，bug 在 fix/ 分支上走快车道，探索只做一次性原型；框架接不住时先做框架设计，再做功能设计，两种设计都先写成草稿（框架设计写 docs/architecture.md，功能设计把要求条文写进能力规格并起卡），用户说“定了”才提交，批的就是写好的草稿；大功能先拆。然后切片实现，每个功能验收前一次独立审核，重点功能和框架改动多审，必须改的修一轮，最后验收、devcircuit close 收尾、交付报告。项目里只保留现行设计和能力规格，旧设计原地覆盖或删除；为什么这么做、哪些方案没选，写进项目外的私有账本，开发 agent 只写不读，devcircuit ledger check 核对两边一致。适合独立开发者用 Claude Code、Codex、pi 或 DeepSeek Harness 连续交付，不想维护 proposal / tasks / archive 的人。
```

标签：

```text
agent-skills, workflow, design, code-review, spec-driven-development, deepseek-harness
```

## 发布检查

- 当前提交就是发版的 tag：`git describe --exact-match --tags` 输出 `v<版本>`。版本号对应 git tag，从 tag 之后到下一次发版之前的提交都还标着同一个版本号，从这些提交发布会把没发版的改动当成这一版发出去。
- `python -m pytest -q` 通过。
- `npm pack --dry-run` 包含 `index.js`、`cordis.patch.yml`、`skills/` 和 README。
- 在干净的 DSH profile 中执行 `dsh plugin --profile web add <包>`，确认两个 skill 出现在目录里。
- `dev-circuit-ledger` 不出现在模型自动调用目录中。
- 只把 `skills/<name>/` 发布到商店，不要把整个仓库根目录当作单个 skill 发布。
