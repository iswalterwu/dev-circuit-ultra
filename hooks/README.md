# 账本边界：hook、OS 用户与容器

这张表回答一个问题：**开发 agent 不读账本，各档隔离能保证到哪一步？** 开发 agent 对账本只写不读：写用 `devcircuit ledger add`（只回执编号），核对用 `devcircuit ledger check`（只报不一致的功能、编号和提交）。

| 级别 | 做法 | 能保证什么 | 开发侧能不能 `ledger add` / `check` | 成本 |
|---|---|---|---|---|
| 弱 | prompt 里写"不要读账本" | 只能防误读 | 能 | 0 |
| **中** | `devcircuit hooks install`：工具调用层拦截（pi、Claude Code） | 拦截能识别出的账本路径访问，不提供文件系统隔离；跨平台、可审查 | 能 | 一条命令 |
| 强 | 账本属主是另一个 OS 用户 / ACL 不授权给开发进程 | 开发进程没有读权限 | 不能，由 human 在账本一侧跑 | 建用户或改 ACL |
| 最强 | 开发容器不挂载账本、无凭证 | 进程内没有可达路径 | 不能，由 human 在账本一侧跑 | Docker |

中级别不是"弱"的另一种说法：它通过路径匹配拦截能识别出的**真实工具调用**（read / write / edit / bash / grep），减少误读，不靠模型自觉；但它不是不可绕过的安全边界。开发进程仍以同一个 OS 用户运行，运行时拼路径、切目录后使用相对路径、遍历文件系统等访问可能绕过匹配，完整限制见下面“它不做什么”。要那种保证，用强 / 最强；代价是开发侧写不了账本：在开发侧的 `guard.json` 里写 `"ledger_side": "human"`，`devcircuit close` 就跳过账本步骤并打印要补的命令，记录和核对由 human 在账本一侧补上。

## 中级别：hook

pi 和 Claude Code 都提供在工具执行前拦截的机制。`devcircuit hooks install` 把对应 hook 装进项目并写好 `guard.json`（包还没发布到 PyPI，先从仓库装：`pipx install git+https://github.com/iswalterwu/dev-circuit-ultra`）：

`--ledger` 必须在项目之外；给它一个项目内的路径会被拒绝（账本进项目就破坏了整条边界）。

```powershell
# pi：写 .pi/extensions/ledger-guard.js
devcircuit hooks install --harness pi --project D:\code\my-app --ledger D:\ledgers\my-app

# Claude Code：写 .dev-circuit/hooks/ledger_guard.py + 生成 settings 片段（合并进 .claude/settings.local.json 才生效）
devcircuit hooks install --harness claude --project D:\code\my-app --ledger D:\ledgers\my-app

# 看 guard.json 和 hook 文件在不在
devcircuit hooks status --project D:\code\my-app
```

pi 只从会话启动目录下的 `.pi/extensions/` 自动加载扩展，而且这个目录要是可信项目：在项目根目录启动 pi，从子目录启动的会话不加载这个 hook，什么都不拦；已开的会话用 `/reload` 生效。Claude Code 要照输出把 hooks 段合并进 `.claude/settings.local.json` 才生效（同样的内容写在 `.dev-circuit/claude-settings.hook.json`，Claude Code 不读这一份）。片段里是本机路径，`.claude/settings.local.json` 不提交：在项目里跑 `git check-ignore .claude/settings.local.json`，没有输出就把它加进 `.gitignore` 并在主干上提交，不然 `devcircuit close` 会因为工作区不干净而拒绝收尾。

别的 agent（Codex、DeepSeek Harness 等）的工具调用没有拦截：要隔离账本就用强档或最强档，开发侧 `guard.json` 写 `"ledger_side": "human"`；让它们自己写账本的，也要跑一次 `hooks install`（`--harness` 任选一种）并在主干上提交它留下的文件：`ledger add` / `check` 和 `close` 靠它写的 `guard.json` 找账本。

配置在 `<project>/.dev-circuit/guard.json`：

```json
{
  "ledger": "D:\\ledgers\\my-app",
  "project": "my-app",
  "deny": ["../notes"]
}
```

- `ledger` 和 `deny` 里的路径解析规则：绝对路径按原样；相对路径按**项目根**（`.dev-circuit` 的父目录）解析。
- `project` 可选，是账本里 `entries/<project>/` 的目录名；不写就用项目目录名（git worktree 里用主工作区的目录名）。
- `ledger_side` 可选，写 `"human"` 表示账本由 human 在账本一侧维护（强 / 最强档）：开发侧不写也不核对，`devcircuit close` 跳过账本步骤。human 在账本一侧跑 `devcircuit ledger add` / `check` 时，设 `DEVCIRCUIT_LEDGER` 指向账本（`DEVCIRCUIT_PROJECT` 可选，指定 `entries/` 下的项目名）：环境变量优先于 `guard.json`，不设的话，命令读到这份写着 `"human"` 的 `guard.json` 就会拒绝。
- hook 的路径匹配**也覆盖 guard.json 本身**：配置文件里就有账本路径，它是最直接的泄漏点。`devcircuit ledger add` / `check` 的命令行里不带账本路径，所以放行；路径由 CLI 进程自己读。
- `guard.json` 记录的是本机路径，`hooks install` 会自己把它写进 `.gitignore`（已被更宽的规则忽略就不写）。别让 agent 去改：hook 生效后，命令里出现这个路径就会被拦。hook 脚本和 `hooks install` 对 `.gitignore` 的改动都要在主干上提交：hook 脚本是边界的一部分，值得被 review；留着不提交，`devcircuit close` 会因为工作区不干净而拒绝收尾。
- Claude Code 的片段只在 hook 脚本存在时才运行它：切到还没装 hook 的旧分支时放行，而不是拦下所有工具调用（python 打不开脚本时退出码是 2，Claude Code 会当成拦截）。Windows 上片段用 `python`，不用 WindowsApps 里的 `python3` 别名。
- hook 从会话的当前目录往上找 `.dev-circuit/guard.json`，找不到就不拦任何调用；`devcircuit ledger add` / `check` 和 `close` 在 git worktree 里找不到时用主工作区的那份。所以 worktree 在项目目录之外时，CLI 照常写账本，hook 却拦不住读账本；在 worktree 里开会话之前要补什么，见 [README 常见问题](../README.zh-CN.md#常见问题)。

hook 的判定不看工具名：它检查参数中的路径文本，命中当前规则能识别的账本或拒绝路径时就拦截。因此 `read`、`bash`、`write`、`grep` 以及新增工具都可以触发拦截，但不能保证识别每一种访问方式。

两种命中方式：

1. **按字面**：参数里直接出现账本路径（正斜杠、反斜杠都算；Windows 上大小写变体也算）。
2. **按解析**：把参数和命令里的 token（每个字符串的前 64 个）按项目根解析成真实路径（跟随软链、展开 `..`、展开 `~`），再判断是否落在账本目录里。所以项目在 `D:\code\my-app`、账本在 `D:\ledgers\my-app` 时，`../../ledgers/my-app/x.md`、`cat ../../ledgers/my-app | head` 同样会被拦。

### 它不做什么

- 不解析运行时求值：`$(echo ~/ledgers | sed s/x/y/)`、base64、从环境变量拼出来的路径，字面上不含账本路径就拦不到。
- 不按命令实际所在的目录解析相对路径：相对路径一律按项目根解析。会话的当前目录在项目的子目录里，或命令里先 `cd` 到别处时，从那里写的、走得到账本的相对路径可能拦不到。
- 一个字符串只解析前 64 个 token：后面的内容只按字面比对，相对路径、`~` 开头的路径、带 `..` 的绝对路径、经软链的路径都拦不到。
- 在 macOS 和 Linux 上不忽略大小写：macOS 默认的文件系统不区分大小写，换了大小写的账本路径照样读得到，hook 拦不到。
- 不替代 OS 权限：同一用户下，账号本身对账本目录仍然可读。
- 不阻止"人"把账本内容贴进对话。

所以它是**默认档**，不是终点。需要硬保证时继续往上走。

## 强 / 最强：OS 用户与容器

参考做法是 `dev`、`ledger` 两个容器，`dev` 不挂载账本；前提、要设的三个变量、起容器和验证边界都照 [`docker/README.md`](../docker/README.md) 做。

- `dev`：只挂项目；没有 `/ledger`；没有账本 remote 凭证；没有 Docker socket。
- `ledger`：项目只读 + 账本读写；human 在这里跑 `devcircuit ledger add` 补记、`devcircuit ledger check` 核对，或用 `dev-circuit-ledger` 查询。容器里用 `DEVCIRCUIT_LEDGER`、`DEVCIRCUIT_PROJECT` 指向挂载的账本。
- 账本 remote 必须私有；凭证只在 human 的环境。

## 验证

```powershell
# 1. guard.json 和 hook 文件在不在（不检查 harness 有没有加载 hook）
devcircuit hooks status --project D:\code\my-app

# 2. hook 脚本会拦（Claude Code 用的那一个可以单独跑）
'{"cwd":"D:\\code\\my-app","tool_name":"Read","tool_input":{"file_path":"D:\\ledgers\\my-app\\entries\\x.md"}}' `
  | python D:\code\my-app\.dev-circuit\hooks\ledger_guard.py
# 退出码 2 + stderr 说明 = 拦住了

# 3. harness 真的在调用 hook：在项目根目录新开一个 pi 或 Claude Code 会话，让它读 D:\ledgers\my-app\entries\x.md（文件不用存在）
# 应当被拦下并提示"账本边界"；Claude Code 没拦，先看 .claude/settings.local.json 里有没有合并 hooks 段；pi 没拦，先确认会话是在项目根目录启动的、项目是可信项目，再 /reload

# 4. 最强级别：照 docker/README.md 的"验证边界"一节确认 dev 容器里没有 /ledger
```
