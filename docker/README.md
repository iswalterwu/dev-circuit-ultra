# 最强隔离参考

这不是一个完整的产品运行环境，而是 **挂载 / 权限边界** 的参考：开发进程碰不到账本，账本只在另一个容器里读写。只在 prompt 里写"不要读账本"不算隔离。

这里是最强一级。日常更轻的默认做法是工具调用层拦截（`devcircuit hooks install`），那一档里开发 agent 可以自己用 `devcircuit ledger add` 写账本；四档对比见 [`../hooks/README.md`](../hooks/README.md)。这一档的代价是开发侧写不了账本：在项目的 `.dev-circuit/guard.json` 里写 `"ledger_side": "human"`，开发容器里的 `devcircuit close` 就跳过账本步骤并打印要补的命令，记录和核对由 human 在 `ledger` 容器里补上。没有这个文件就新建，内容写成 `{"ledger_side": "human"}`；已经有的（比如跑过 `hooks install`），加上这一项并删掉里面的 `ledger` 一项：`dev` 容器读得到项目里的这个文件，账本路径和 `LEDGER_DIR` 一样不给 `dev`。`git check-ignore .dev-circuit/guard.json` 没有输出时，把它加进 `.gitignore` 并在主干上提交，不然 `devcircuit close` 会因为工作区不干净而拒绝收尾。

## 前提

1. 账本已用 `devcircuit ledger init --path <项目外目录>` 创建在 **项目目录之外**。
2. 账本是私有 git repo；remote 也是私有。
3. 开发 agent 和 `devcircuit` CLI 由你装进镜像（Claude Code、pi、Codex 等）；本目录只给基础镜像和用户。
4. 本目录的 `Dockerfile` 和 `compose.yaml` 已复制到项目根目录的 `docker/` 下并在主干上提交，下面的命令都在项目根目录跑：compose 把 `docker/` 的上一级当项目，挂成 `/work`。这份 README 不要拷进去：它链接的 `../hooks/README.md`、`../docs/ledger.md` 在项目里不存在，doc_guard 会报 broken-link。
5. Linux 上直接用 Docker Engine（不是 rootless 模式）时，你的镜像里 `dev` 的 uid 已改成项目目录属主的 uid，`ledger` 的已改成账本目录属主的 uid：挂进来的目录在容器里保留宿主上的 uid，`ubuntu:24.04` 自带 uid 1000 的 `ubuntu` 用户，Dockerfile 里建的 `dev`、`ledger` 是 1001、1002，和宿主上的属主（通常是 1000）对不上时，`dev` 写不了项目，`ledger` 写不了账本（验证时不打印 `ledger: writable`）。uid 已被占用时（`ubuntu` 就占着 1000），`usermod -u` 要加 `-o`；已经按旧 uid 起过容器的，改完先在设好下面"起容器"一节三个变量的窗口里跑 `docker compose -f docker/compose.yaml down -v` 删掉 `dev-home`、`ledger-home` 两个卷，再 build、起容器，重做下面的 git 登记（包括 `core.autocrlf` 那一条）和 `ledger` 容器里的 `devcircuit sync`。

## 起容器

PowerShell：

```powershell
$env:LEDGER_DIR = 'D:\ledgers\my-app'   # 必须在项目目录之外
$env:PROJECT_NAME = 'my-app'            # 账本里 entries/<PROJECT_NAME>/ 的目录名
$env:COMPOSE_PROJECT_NAME = 'my-app'    # compose 项目名，每个项目各用一个；不设就都叫 docker
docker compose -f docker/compose.yaml build
docker compose -f docker/compose.yaml up -d dev ledger
```

后面每条 `docker compose` 命令（包括 `exec`）都要读这三个变量：新开的 PowerShell 窗口先重新设一遍，不然 compose 报缺变量，或者连到别的项目的容器。不要写进项目里的 `.env`：`dev` 容器读得到它。

开发容器里的 `/work` 从宿主挂进来，属主和 `dev` 用户不同，git 会拒绝读取；开发 agent 和 `devcircuit close` 都要提交，还得有 git 身份。先登记一次：

```powershell
docker compose -f docker/compose.yaml exec dev sh -lc 'git config --global --add safe.directory /work && git config --global user.name "<名字>" && git config --global user.email "<邮箱>"'
```

宿主是 Windows、项目在 `core.autocrlf=true` 下按 CRLF 检出，而 `.gitattributes` 里没有 `* text=auto` 这类管所有文件的规则时（`devcircuit init` 新建的项目有 `* text=auto eol=lf`，`--adopt` 接入时只加 `.githooks/** text eol=lf` 一条），容器里的 git 也要转换换行，不然文本文件都显示为已修改，`devcircuit close` 拒绝收尾：

```powershell
docker compose -f docker/compose.yaml exec dev sh -lc 'git config --global core.autocrlf true'
```

## 验证边界

```powershell
# 开发容器：没有 /ledger
docker compose -f docker/compose.yaml exec dev sh -lc 'test ! -e /ledger && echo "dev: no ledger"'

# ledger 容器：项目只读、账本可写
docker compose -f docker/compose.yaml exec ledger sh -lc 'test -w /ledger && echo "ledger: writable"; test ! -w /work && echo "ledger: project read-only"'
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

账本记录都在这里补：框架设计定了、功能设计定了或改了、收尾以后各补一条，`--kind` 和要带的参数按 [`../docs/ledger.md`](../docs/ledger.md#什么时候写写什么) 的时机表。

`/work` 和 `/ledger` 都是从宿主挂进来的，属主和容器里的 `ledger` 用户不同，git 会拒绝读取；`ledger add` 还要在账本里提交，得有 git 身份。先登记一次：

```powershell
docker compose -f docker/compose.yaml exec ledger sh -lc 'git config --global --add safe.directory /work && git config --global --add safe.directory /ledger && git config --global user.name "<名字>" && git config --global user.email "<邮箱>"'

# 收尾记录：对应开发容器里 devcircuit close 打印的命令（DEVCIRCUIT_LEDGER / DEVCIRCUIT_PROJECT 已由 compose 设好）
docker compose -f docker/compose.yaml exec ledger sh -lc 'devcircuit ledger add --project /work --feature add-report --kind close --decision "交付报告命令" --commit <close 提交>'

# 核对
docker compose -f docker/compose.yaml exec ledger sh -lc 'devcircuit ledger check --project /work'

# 查询：先在 ledger 容器里装技能（Claude Code，装一次就行），再跑 dev-circuit-ledger
docker compose -f docker/compose.yaml exec ledger sh -lc 'devcircuit sync'
docker compose -f docker/compose.yaml exec ledger sh -lc 'cd /ledger && <your-agent> -p "/dev-circuit-ledger 为什么 total 只选 amount 时要加 TOTAL"'
```

`dev-circuit-ledger` 只由 human 显式调用，模型不会自己加载它，所以提问写成技能命令（上面是 Claude Code 的 `/dev-circuit-ledger <问题>`），技能也要装在 `ledger` 容器里 `ledger` 用户的技能目录下。具体 agent 命令和装技能的方式按你安装的 CLI 调整；容器边界不变。
