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

# 分层看状态：脚本、配置、登记；宿主是否加载要在会话里探（见下面"验证"）
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

- `ledger` 和 `deny` 里的路径解析规则：绝对路径按原样；相对路径按这份配置所在的目录（`.dev-circuit` 的父目录）解析。git worktree 里用的是主工作区那份时，就按主工作区解析。
- `project` 可选，是账本里 `entries/<project>/` 的目录名；不写就用项目目录名（git worktree 里用主工作区的目录名）。
- `ledger_side` 可选，写 `"human"` 表示账本由 human 在账本一侧维护（强 / 最强档）：开发侧不写也不核对，`devcircuit close` 跳过账本步骤。human 在账本一侧跑 `devcircuit ledger add` / `check` 时，设 `DEVCIRCUIT_LEDGER` 指向账本（`DEVCIRCUIT_PROJECT` 可选，指定 `entries/` 下的项目名）：环境变量优先于 `guard.json`，不设的话，命令读到这份写着 `"human"` 的 `guard.json` 就会拒绝。开发侧这份只写 `ledger_side`、不写 `ledger` 时，`hooks install` 不要求 `--ledger`：换 hook 脚本带 `--force` 重跑即可，不用把账本位置写回来。
- hook 的路径匹配**也覆盖 guard.json 本身**：配置文件里就有账本路径，它是最直接的泄漏点。hook 用的是主工作区那份、或会话开在项目的子目录里时，从会话目录到找到配置的那一级，沿途各级的 `.dev-circuit/guard.json` 位置也拦：agent 不能在更近处另放一份，把边界换成它写的那份；worktree 要自带配置的，由 human 放。`devcircuit ledger add` / `check` 的命令行里不带账本路径，所以放行；路径由 CLI 进程自己读。`hooks install` 和 `hooks status` 的输出也不带账本路径和 `deny` 里的路径：只说账本配没配、目录在不在（当前用户没有权限看的，写“目录看不到”）、额外拒绝几项，要看路径由 human 打开 `guard.json`。
- `guard.json` 记录的是本机路径，`hooks install` 会自己把它写进 `.gitignore`（已被更宽的规则忽略就不写）。别让 agent 去改：hook 生效后，命令里出现这个路径就会被拦。hook 脚本和 `hooks install` 对 `.gitignore` 的改动都要在主干上提交：hook 脚本是边界的一部分，值得被 review；留着不提交，`devcircuit close` 会因为工作区不干净而拒绝收尾。
- Claude Code 的片段只在 hook 脚本存在时才运行它：切到还没装 hook 的旧分支时放行，而不是拦下所有工具调用（python 打不开脚本时退出码是 2，Claude Code 会当成拦截）。Windows 上片段用 `python`，不用 WindowsApps 里的 `python3` 别名。
- hook 和 `devcircuit ledger add` / `check`、`close`、`hooks status` 用同一条规则找 `guard.json`：先看本目录，git worktree 里没有就用主工作区的那份；`ledger` 和 `deny` 里的相对路径按那份配置所在的目录（主工作区）解析。hook 还会从会话的当前目录继续往上找，都找不到就不拦任何调用；CLI 的 `--project` 要给项目目录，通常是工作树的顶层：给的是它里面的目录、而上层已经有配置时，`hooks status` 写出该给哪个目录，`hooks install` 以退出码 2 拒绝，不在里面另写一份 `guard.json`。升级前的旧 hook 脚本（没有版本行）没有“用主工作区那份”这一步：分支上还带着旧脚本的 worktree，只要不在主工作区目录里面，旧脚本就找不到配置、不拦任何调用。`hooks status` 这时以退出码 2 写出“这里不拦”一行，`hooks install` 留下旧脚本时也会提醒：把主干合并进那个分支，或在那个 worktree 里 `hooks install --force` 后提交。这个 worktree 的 settings 里登记的是别处的 Claude 脚本（比如主工作区那份）时，status 不拿 worktree 里这份旧脚本判“这里不拦”，“登记 claude”一行会写明命令指向的不是本工作树这份。
- `hooks install` 在 git worktree 里不另写 `guard.json`，也不要求 `--ledger`：它沿用主工作区的那份，`--ledger` 与现有配置不同就拒绝，主工作区也没有配置时让 human 先到主工作区配置。worktree 里自带一份的（以前手抄的）继续优先，和主工作区那份不一样时 `hooks status` 会提醒，想跟主工作区一致就删掉它。子模块、`--separate-git-dir` 建的仓库、bare 仓库加 worktree 这三种布局没有这条回退，要在 worktree 里自带 `guard.json`：别的工作区已经有一份的，由 human 照那份抄，保留 `project` / `deny` / `ledger_side`，相对路径改成绝对路径；`hooks install` 在那里新写的一份只有账本位置，`hooks status` 和 `hooks install` 在这种 worktree 里会这样提示。在 worktree 里开会话之前要做什么，见 [README 常见问题](../README.zh-CN.md#常见问题)。
- `hooks install` 写 `guard.json` 是整份替换，内容没变就不重写；`--force` 覆盖项目里的 hook 脚本，但项目里的比本机 devcircuit 带的新时不覆盖，先升级本机的 devcircuit。

hook 的判定不看工具名：它检查参数中的路径文本，命中当前规则能识别的账本或拒绝路径时就拦截。因此 `read`、`bash`、`write`、`grep` 以及新增工具都可以触发拦截，但不能保证识别每一种访问方式。

两种命中方式：

1. **按字面**：参数里直接出现账本路径（正斜杠、反斜杠都算；Windows 上大小写变体，`\\?\`、`//?/` 前缀，以及 Git Bash / Cygwin / WSL 的 `/d/…`、`/cygdrive/d/…`、`/mnt/d/…` 写法也算）。
2. **按解析**：把参数和命令里的 token（每个字符串的前 64 个）解析成真实路径（跟随软链和 junction，包括目标还没建的；展开 `..`、`~`），再判断是否落在账本目录里。相对路径按会话所在工作树的顶层解析，也就是找到配置的那一级目录：git worktree 里是那个 worktree 的根，不是主工作区。成对引号里的整段、用反斜杠转义空格的路径也当成一个 token。所以项目在 `D:\code\my-app`、账本在 `D:\ledgers\my-app` 时，`../../ledgers/my-app/x.md`、`cat ../../ledgers/my-app | head` 同样会被拦。

### 它不做什么

- 不解析运行时求值：`$(echo ~/ledgers | sed s/x/y/)`、base64、从环境变量拼出来的路径，字面上不含账本路径就拦不到。
- 不按命令实际所在的目录解析相对路径：相对路径一律按会话所在工作树的顶层解析。会话的当前目录在项目的子目录里，或命令里先 `cd` 到别处时，从那里写的、走得到账本的相对路径可能拦不到。粘在别的字符后面的相对路径（`--file=../ledgers/x`、`FOO=../…`）同样拦不到；绝对路径仍按字面拦。
- 不拦向上这条路以外的配置：agent 先在会话目录之外的某个子目录里放一份 `guard.json`，再把会话切进那个子目录，下一次调用就用它。
- 一个字符串只解析前 64 个 token：后面的内容只按字面比对，相对路径、`~` 开头的路径、带 `..` 的绝对路径、经软链的路径都拦不到。
- 在 macOS 和 Linux 上不忽略大小写：macOS 默认的文件系统不区分大小写，换了大小写的账本路径照样读得到，hook 拦不到。
- 项目路径里有 shell 会展开的字符（`$`、`%`、反引号、双引号）时，Claude Code 的 hook 不拦：命令把脚本路径放在双引号里，sh / bash / PowerShell 展开 `$NAME`，cmd 展开 `%NAME%`，展开后路径对不上，命令当成脚本不在而放行。`hooks install` 和 `hooks status` 遇到这种路径会明说；把项目放到不含这些字符的路径下。pi 不经过 shell，不受影响。
- 仅 pi 的 hook 拦不到的两种：Windows 上目录名后多写一个点或空格（`ledgers.\app`），以及百分号编码的路径所在的字符串里另有一个落单的 `%`。
- 这些写法拦不到：UNC 回环与管理共享（`\\localhost\D$\ledgers\…`、`\\127.0.0.1\D$\…`）、环境变量和不在开头的 `~`（`$HOME/ledgers/…`、`%USERPROFILE%\ledgers\…`、`X=~/ledgers/…`）、通配符（`../led*/…`）、对账本上级目录的递归命令（`grep -r … ..`）、指向账本文件的硬链接。
- 卷 GUID 路径（`\\?\Volume{…}\ledgers\…`）不保证拦到：hook 不认这种写法，花括号后面那段被当成项目所在盘上的路径来比对，所以只有账本和项目在同一个盘时才碰巧拦得到。
- `guard.json` 读不出账本位置时（不是 UTF-8 的合法 JSON、不是 JSON 对象、`ledger` 不是非空字符串、文件打不开）不放行：hook 拦下全部工具调用，直到 human 修好这个文件，agent 自己修不了；`hooks status` 这时以退出码 2 写明无法解析。`deny` 写错只是那几项不拦，`hooks status` 会指出来。
- 不管项目之外的安装：全局安装的 pi 扩展（`~/.pi/agent/extensions/`）和用户级登记的 Claude Code hook，`hooks status` 看不到，`hooks install --force` 也更新不到，要手工换成新脚本。
- 不证明宿主已经加载了 hook：`hooks status` 只看得到文件和 settings，宿主是否已加载，CLI 证明不了，要照下面“验证”第 3 步做一次会话内探针。
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
# 1. 分三层看，各一行（账本和 deny 的路径不打印）：
#    脚本：pi / claude 的 hook 文件在不在，和本机 devcircuit 带的相比是相同、较旧还是较新
#    配置：用的是本工作树还是主工作树的 guard.json、能不能解析、账本配没配、额外拒绝几项
#    登记：本工作树的 .claude/settings.local.json 或 settings.json 里有没有运行 ledger_guard.py 的命令；pi 的脚本在不在 .pi/extensions/
devcircuit hooks status --project D:\code\my-app
# 退出码：0 正常；1 既没有配置也没有 hook 脚本；2 有 hook 脚本却找不到配置（包括 worktree 里的旧脚本找不到主工作树
# 那份，这时多一行"这里不拦"），或配置无法解析。2 都由 human 处理。
# Claude Code 没登记只提示，不改变退出码：用户级设置 CLI 看不到

# 2. hook 脚本会拦（Claude Code 用的那一个可以单独跑）
'{"cwd":"D:\\code\\my-app","tool_name":"Read","tool_input":{"file_path":"D:\\ledgers\\my-app\\entries\\x.md"}}' `
  | python D:\code\my-app\.dev-circuit\hooks\ledger_guard.py
# 退出码 2 + stderr 说明 = 拦住了

# 3. 宿主是否已加载，CLI 证明不了：照 status 最后一行做会话内探针。在项目根目录（git worktree 就在那个 worktree 的根目录）
#    新开一个 pi 或 Claude Code 会话，让它读 status 给出的 <配置所在目录>\.dev-circuit\guard.json.selftest（一个不存在的文件）
# 回"账本边界"说明已加载；回"文件不存在"说明没加载。探针一行后面带"先修好配置再探"或"换上新脚本再探"的，
# 先照它说的做：那两种状态下旧脚本已加载也回"文件不存在"。Claude Code 没拦，先看 status 的"登记 claude"一行；
# pi 没拦，先确认会话是在项目根目录启动的、项目是可信项目，再 /reload

# 4. 最强级别：照 docker/README.md 的"验证边界"一节确认 dev 容器里没有 /ledger
```
