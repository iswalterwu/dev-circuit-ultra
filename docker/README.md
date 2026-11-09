# 强隔离参考

这不是一个完整的产品运行环境，而是 **挂载 / 权限边界** 的参考：开发进程碰不到账本，账本只在另一个容器里读写。只在 prompt 里写"不要读账本"不算隔离。

这里是最强一级。日常更轻的默认做法是工具调用层拦截（`devcircuit hooks install`），那一档里开发 agent 可以自己用 `devcircuit ledger add` 写账本；四档对比见 [`../hooks/README.md`](../hooks/README.md)。这一档的代价是开发侧写不了账本：在项目的 `.dev-circuit/guard.json` 里写 `"ledger_side": "human"`，开发容器里的 `devcircuit close` 就跳过账本步骤并打印要补的命令，记录和核对由 human 在 `ledger` 容器里补上。

## 前提

1. 账本已用 `devcircuit ledger init --path <项目外目录>` 创建在 **项目目录之外**。
2. 账本是私有 git repo；remote 也是私有。
3. 开发 agent 和 `devcircuit` CLI 由你装进镜像（Claude Code、pi、Codex 等）；本目录只给基础镜像和用户。

## 起容器

PowerShell：

```powershell
$env:LEDGER_DIR = 'D:\ledgers\my-app'   # 必须在项目目录之外
$env:PROJECT_NAME = 'my-app'            # 账本里 entries/<PROJECT_NAME>/ 的目录名
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d dev ledger
```

## 验证边界

```powershell
# 开发容器：没有 /ledger
docker compose -f docker/compose.yaml exec dev sh -lc 'test ! -e /ledger && echo "dev: no ledger"'

# ledger 容器：项目只读、账本可写
docker compose -f docker/compose.yaml exec ledger sh -lc 'test -w /ledger && echo "ledger: writable"; test ! -w /work/README.md && echo "ledger: project read-only"'
```

如果 `dev` 能看到 `/ledger`，说明挂载写错了，不要开始开发。

## 谁在哪个容器

| 容器 | 项目 | 账本 | 用途 |
|---|---|---|---|
| `dev` | 读写 | **不挂载** | 开发 agent；只读现行设计 / 代码 |
| `ledger` | 只读 | 读写 | human 补记、核对、查询 |

## 关键规则

- **不要把 Docker socket 挂进任何容器**；否则容器可以操控宿主机，隔离失效。
- 不要把 `LEDGER_DIR` 或账本凭证传给 `dev`。
- 账本远程凭证只放在 human 的环境，不放在 dev。
- 这个 compose 不安装 agent；在你的镜像里安装，但保持上面的挂载边界。

## 在 ledger 容器里记录、核对、查询

`/work` 是只读挂载、属主不同，git 会拒绝读取，先登记一次：

```powershell
docker compose -f docker/compose.yaml exec ledger sh -lc 'git config --global --add safe.directory /work'

# 功能设计定了、收尾以后，补记录（DEVCIRCUIT_LEDGER / DEVCIRCUIT_PROJECT 已由 compose 设好）
docker compose -f docker/compose.yaml exec ledger sh -lc 'devcircuit ledger add --project /work --feature add-report --kind close --decision "交付报告命令" --commit <close 提交>'

# 核对
docker compose -f docker/compose.yaml exec ledger sh -lc 'devcircuit ledger check --project /work'

# 查询：在 ledger 容器里跑 dev-circuit-ledger
docker compose -f docker/compose.yaml exec ledger sh -lc 'cd /ledger && <your-agent> -p "使用 dev-circuit-ledger 回答：为什么 total 只选 amount 时要加 TOTAL"'
```

具体 agent 命令按你安装的 CLI 调整；容器边界不变。
