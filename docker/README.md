# 强隔离参考

这不是一个完整的产品运行环境，而是 **挂载/权限边界** 的参考。开发 agent 和 archivist 必须跑在不同容器/不同用户下；只在 prompt 里写“不要读账本”不算隔离。

这里是最强一级。日常更轻的默认做法是工具调用层拦截（`devcircuit hooks install`）或分 OS 用户；四档对比见 [`../hooks/README.md`](../hooks/README.md)。

## 前提

1. 账本已用 `scripts/new-ledger.ps1` 创建在 **项目目录之外**。
2. 账本是私有 git repo；remote 也是私有。
3. 开发 agent 的镜像/入口由你安装（Claude Code、pi、Codex 等）；本目录只给基础镜像和用户。

## 起容器

PowerShell：

```powershell
$env:LEDGER_DIR = 'D:\ledgers\my-app'   # 必须在项目目录之外
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d dev archivist ledger
```

## 验证边界

```powershell
# 开发容器：没有 /ledger
docker compose -f docker/compose.yaml exec dev sh -lc 'test ! -e /ledger && echo "dev: no ledger"'

# archivist：项目只读、账本可写
docker compose -f docker/compose.yaml exec archivist sh -lc 'test -w /ledger && echo "archivist: ledger writable"; test ! -w /work/README.md && echo "archivist: project read-only"'

# human 查询容器：账本只读
docker compose -f docker/compose.yaml exec ledger sh -lc 'test -r /ledger/schema.md && echo "ledger: readable"'
```

如果 `dev` 能看到 `/ledger`，说明挂载写错了，不要开始开发。

## 谁在哪个容器

| 容器 | 项目 | 账本 | 用途 |
|---|---|---|---|
| `dev` | 读写 | **不挂载** | 开发 agent；只读现行设计/代码 |
| `archivist` | 只读 | 读写 | 独立记账；不改项目 |
| `ledger` | 不挂载 | 只读 | human 查询/brief |

## 关键规则

- **不要把 Docker socket 挂进任何容器**；否则容器可以操控宿主机，隔离失效。
- 不要把 `LEDGER_DIR` 或账本凭证传给 `dev`。
- archivist 不是开发会话的 subagent；由 human/orchestrator 在 `archivist` 容器里单独运行。
- 账本远程凭证只放在 archivist/human 环境，不放在 dev。
- 这个 compose 不安装 agent；在你的镜像里安装，但保持上面的挂载边界。

## 运行记账/查询

```powershell
# 记账：在 archivist 容器里跑 dev-circuit-archivist
docker compose -f docker/compose.yaml exec archivist sh -lc 'cd /work && <your-agent> -p "使用 dev-circuit-archivist 记录 add-report 的 design-change"'

# 查询：在 ledger 容器里跑 dev-circuit-ledger
docker compose -f docker/compose.yaml exec ledger sh -lc 'cd /ledger && <your-agent> -p "使用 dev-circuit-ledger 回答：为什么 total 只选 amount 时要加 TOTAL"'
```

具体 agent 命令按你安装的 CLI 调整；容器边界不变。
