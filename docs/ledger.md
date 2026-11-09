# 设计与账本：两条边界

dev-circuit-ultra 把"现在怎么做"和"为什么变成现在这样"分开：

- **现行设计**：项目里的能力规格（`docs/requirements/`）、`docs/architecture.md`（开头是框架摘要）和其他 docs。开发 agent 只读这些，并用 `devcircuit context` 按编号取需要的部分。
- **账本**：项目外的私有 git repo，只记选定的决定、被否方案和原因。开发 agent 对它只写不读；human 用 `dev-circuit-ledger` 查。

现行设计是 read model，账本是 event log。设计变了，开发 agent 原地覆盖或删除项目里的旧内容，同时用 `devcircuit ledger add` 把这次的决定和被否方案追加进账本。

## 什么时候写、写什么

| 时机 | 命令 | 记什么 |
|---|---|---|
| 框架设计定了 | `devcircuit ledger add --kind framework` | 选定的结构、被否方案和原因 |
| 功能设计定了 | `devcircuit ledger add --kind design --ids … --removed-ids …` | 选定的设计、被否方案、涉及和删掉的要求编号 |
| 设计中途改了 | `devcircuit ledger add --kind design-change` | 新的决定、被否的旧决定和原因 |
| 收尾 | `devcircuit close` 自动写 `close` 记录 | 一句话交付、审核结果、close 提交 |
| 核对出不一致 | `devcircuit ledger add --kind correction` | 补记或更正；原因不清楚时先问 human |

每个功能一般 2–3 条，不用另开会话。`add` 只回一行"已记录：<编号>"，不回显内容。记录格式见账本里的 `schema.md`。

## 核对

`devcircuit ledger check` 对照项目和账本，只报不一致的功能、编号和提交，不报记录内容：

| 规则 | 什么时候报 |
|---|---|
| `close-missing` | 有 `close <feature>` 提交，账本没有它的收尾记录 |
| `design-missing` | 在研的卡没有设计记录 |
| `framework-missing` | 卡上写着"框架：已改"，账本没有框架记录 |
| `bad-feature-name` | 卡的目录名不合规：功能名只用字母、数字、点、下划线和连字符，一段，不含斜杠 |
| `commit-missing` | 在研功能的记录指向的提交不在仓库里；已收尾的功能不查，squash、rebase 合并本来就会丢掉分支上的提交 |
| `removal-unrecorded` | 本分支从能力规格里删了要求，账本没有删除记录 |
| `id-stale` | 记录里的现行要求编号已经不在能力规格里，也没有删除记录 |

记录里的提交号可以是短 SHA，核对时按仓库里的完整 SHA 比。同一个功能的 `correction` 记录算补记：它之前的 `commit-missing` 和 `id-stale` 不再报，它也能补上缺的收尾、设计和框架记录。

`ledger add` 当场拒绝写错的输入，因为开发侧读不回来：`--ids` 必须是能力规格里现有的编号，删掉的编号用 `--removed-ids`；编号之间用逗号、顿号、分号或空格隔开。

`devcircuit close` 在提交前后各核对一次：提交前本功能或本分支有不一致就不收尾；别的功能的不一致不挡收尾，写进交付报告的"潜在问题"。

## 隔离

隔离分四档，成本和保证各不相同。默认从 hook 起步：它拦的是真实的工具调用，不是模型自觉。

| 级别 | 做法 | 能保证什么 | 开发侧能不能 `ledger add` / `check` |
|---|---|---|---|
| 弱 | prompt 里写"不要读账本" | 只能防误读 | 能 |
| **中（默认）** | `devcircuit hooks install`：工具调用层拦截 | agent 拿不到账本；跨平台、可审查 | 能 |
| 强 | 账本属主是另一个 OS 用户 / ACL 不授权给开发进程 | 开发进程没有读权限 | 不能，由 human 在账本一侧跑 |
| 最强 | 开发容器不挂载账本、无凭证 | 进程内没有可达路径 | 不能，由 human 在账本一侧跑 |

hook 装在项目里，配置写在 `<project>/.dev-circuit/guard.json`（本机路径，`hooks install` 会把它写进 `.gitignore`）：

```powershell
devcircuit hooks install --harness pi --project D:\code\my-app --ledger D:\ledgers\my-app
devcircuit hooks status --project D:\code\my-app
```

hook 也不许 agent 读 `guard.json` 本身，那里面就有账本路径。`devcircuit ledger add` / `check` 的命令行里不带账本路径，hook 放行；路径由 CLI 进程自己从 `guard.json` 读，相对路径按项目根解析。

hook 拦不住什么：开发进程仍以同一个 OS 用户运行，一条不用账本路径的命令（遍历文件系统）仍可能发现可读目录。要那种保证，用强 / 最强；那两档里开发侧碰不到账本，在开发侧的 `guard.json` 里写 `"ledger_side": "human"`：`ledger add` / `check` 在开发侧会说明账本在 human 一侧，`devcircuit close` 跳过账本步骤，并打印账本一侧要补的命令。账本一侧用 `DEVCIRCUIT_LEDGER`、`DEVCIRCUIT_PROJECT` 指向挂载的账本（容器参考见 [`docker/README.md`](../docker/README.md)）。完整说明见 [`hooks/README.md`](../hooks/README.md)。

在 prompt 里写"不要读"永远只是约定，不是隔离。

## 授权

开发 agent 需要历史时，停下来问 human。human 可以：

- 直接回答；
- 让 `dev-circuit-ledger` 生成 brief；
- 只把 brief 里的"现行约束"贴进设计或交给开发 agent。

不要把账本原文、旧方案列表或完整历史交给开发 agent。

## 不做什么

- 不在项目里建 `ledger/`、`decisions/`、`adr/`、`history/`、`maintenance/`；
- 不在项目里写旧版本、被替代内容或备选方案；
- 不把账本挂进开发容器；
- 开发 agent 不读账本，`ledger check` 也不回显记录内容。
