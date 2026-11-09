# 账本边界：hook、OS 用户与容器

这张表回答一个问题：**开发 agent 读不到账本，靠什么保证？** 开发 agent 对账本只写不读：写用 `devcircuit ledger add`（只回执编号），核对用 `devcircuit ledger check`（只报不一致的功能、编号和提交）。

| 级别 | 做法 | 能保证什么 | 开发侧能不能 `ledger add` / `check` | 成本 |
|---|---|---|---|---|
| 弱 | prompt 里写"不要读账本" | 只能防误读 | 能 | 0 |
| **中** | `devcircuit hooks install`：工具调用层拦截 | agent 无法通过工具拿到账本；跨平台；可审查 | 能 | 一条命令 |
| 强 | 账本属主是另一个 OS 用户 / ACL 不授权给开发进程 | 开发进程没有读权限 | 不能，由 human 在账本一侧跑 | 建用户或改 ACL |
| 最强 | 开发容器不挂载账本、无凭证 | 进程内没有可达路径 | 不能，由 human 在账本一侧跑 | Docker |

中级别不是"弱"的另一种说法：它拦的是**真实的工具调用**（read / write / edit / bash / grep），不是模型自觉。它拦不住的是——开发进程仍以同一个 OS 用户运行，一条不用账本路径的命令（例如遍历文件系统）仍可能发现可读目录。要那种保证，用强 / 最强；代价是开发侧写不了账本：在开发侧的 `guard.json` 里写 `"ledger_side": "human"`，`devcircuit close` 就跳过账本步骤并打印要补的命令，记录和核对由 human 在账本一侧补上。

## 中级别：hook

pi 和 Claude Code 都提供在工具执行前拦截的机制。`devcircuit hooks install` 把对应 hook 装进项目并写好配置（包还没发布到 PyPI，先从仓库装：`pipx install git+https://github.com/iswalterwu/dev-circuit-ultra`）：

`--ledger` 必须在项目之外；给它一个项目内的路径会被拒绝（账本进项目就破坏了整条边界）。

```powershell
# pi：写 .pi/extensions/ledger-guard.js
devcircuit hooks install --harness pi --project D:\code\my-app --ledger D:\ledgers\my-app

# Claude Code：写 .dev-circuit/hooks/ledger_guard.py + 生成 settings 片段
devcircuit hooks install --harness claude --project D:\code\my-app --ledger D:\ledgers\my-app

# 看当前项目的边界
devcircuit hooks status --project D:\code\my-app
```

配置在 `<project>/.dev-circuit/guard.json`：

```json
{
  "ledger": "D:\\ledgers\\my-app",
  "project": "my-app",
  "deny": ["../notes"]
}
```

- `ledger` 和 `deny` 里的路径解析规则：绝对路径按原样；相对路径按**项目根**（`.dev-circuit` 的父目录）解析。
- `project` 可选，是账本里 `entries/<project>/` 的目录名；不写就用项目目录名。
- `ledger_side` 可选，写 `"human"` 表示账本由 human 在账本一侧维护（强 / 最强档）：开发侧不写也不核对，`devcircuit close` 跳过账本步骤。
- hook **也拒绝读取 guard.json 本身**：配置文件里就有账本路径，它是最直接的泄漏点。`devcircuit ledger add` / `check` 的命令行里不带账本路径，所以放行；路径由 CLI 进程自己读。
- `guard.json` 记录的是本机路径，加进 `.gitignore`；hook 脚本本身可以提交，它是边界的一部分，值得被 review。

hook 的判定对每个工具生效，不看工具名：它扫描这次调用的全部字符串参数和参数 JSON，命中账本路径就拒绝。所以 `read`、`bash`（命令文本里带路径）、`write`、`grep` 以及以后新增的工具都被覆盖。

两种命中方式：

1. **按字面**：参数里直接出现账本路径（正斜杠、反斜杠、大小写变体都算）。
2. **按解析**：把参数和命令里的每个 token 按项目根解析成真实路径（跟随软链、展开 `..`、展开 `~`），再判断是否落在账本目录里。所以 `../ledgers/my-app/x.md`、`cat ../ledgers/my-app | head` 同样会被拦。

### 它不做什么

- 不解析运行时求值：`$(echo ~/ledgers | sed s/x/y/)`、base64、从环境变量拼出来的路径，字面上不含账本路径就拦不到。
- 不替代 OS 权限：同一用户下，账号本身对账本目录仍然可读。
- 不阻止"人"把账本内容贴进对话。

所以它是**默认档**，不是终点。需要硬保证时继续往上走。

## 强 / 最强：OS 用户与容器

```powershell
# 参考：dev 和 ledger 两个容器，dev 不挂载账本
docker compose -f docker/compose.yaml up -d
```

- `dev`：只挂项目；没有 `/ledger`；没有账本 remote 凭证；没有 Docker socket。
- `ledger`：项目只读 + 账本读写；human 在这里跑 `devcircuit ledger add` 补记、`devcircuit ledger check` 核对，或用 `dev-circuit-ledger` 查询。容器里用 `DEVCIRCUIT_LEDGER`、`DEVCIRCUIT_PROJECT` 指向挂载的账本。
- 账本 remote 必须私有；凭证只在 human 的环境。

完整参考见 `docker/README.md`。

## 验证

```powershell
# 1. 边界配置正确
devcircuit hooks status --project D:\code\my-app

# 2. hook 真的会拦（Claude Code 用的那一个可以单独跑）
'{"cwd":"D:\\code\\my-app","tool_name":"Read","tool_input":{"file_path":"D:\\ledgers\\my-app\\entries\\x.md"}}' `
  | python D:\code\my-app\.dev-circuit\hooks\ledger_guard.py
# 退出码 2 + stderr 说明 = 拦住了

# 3. 账本目录对开发进程不可读（强 / 最强级别）
docker compose -f docker/compose.yaml run --rm dev sh -c 'ls /ledger'
# 应当报不存在或无权限
```
