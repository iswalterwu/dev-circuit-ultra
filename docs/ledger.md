# 设计与账本：两条边界

dev-circuit-ultra 把“现在怎么做”和“为什么变成现在这样”分开：

- **现行设计**：项目里的能力规格（`docs/requirements/`）和其他 docs，在研的框架级功能再加 `specs/<feature>/design.md`。开发 agent 只读这些。
- **账本**：项目外的私有 git repo。只记决策、被否方案、废弃思路和原因；只给 human 和 `dev-circuit-archivist` 用。

现行设计是 **read model**；账本是 **event log**。设计变更时，开发 agent 原地覆盖/删除旧内容；archivist 把旧决定和被否方案追加到账本。开发 agent 不读 event log。

## 边界

```text
开发容器/会话                         记账容器/会话
┌──────────────────────┐  transcript   ┌──────────────────────┐
│ dev agent            │ ────────────> │ dev-circuit-archivist     │
│ project only         │               │ project read-only    │
│ current design/code  │ <── 不回流 ── │ ledger append-only   │
│ no ledger mount      │               │ no code/design edits │
└──────────────────────┘               └──────────┬───────────┘
                                                  │
                                         human / dev-circuit-ledger
                                                  │
                                         ┌────────▼────────┐
                                         │ brief（授权后）  │
                                         └─────────────────┘
```

## 隔离

隔离分四档，成本和保证各不相同。默认从 hook 起步：它拦的是真实的工具调用，不是模型自觉。

| 级别 | 做法 | 能保证什么 |
|---|---|---|
| 弱 | prompt 里写“不要读账本” | 只能防误读 |
| **中（默认）** | `devcircuit hooks install`：工具调用层拦截 | agent 拿不到账本；跨平台、可审查 |
| 强 | 账本属主是另一个 OS 用户 / ACL 不授权给开发进程 | 开发进程没有读权限 |
| 最强 | dev / archivist 分容器；dev 不挂载账本、无凭证 | 进程内没有可达路径 |

hook 装在项目里，配置写在 `<project>/.dev-circuit/guard.json`（本机路径，加进 `.gitignore`）：

```powershell
devcircuit hooks install --harness pi --project D:\code\my-app --ledger D:\ledgers\my-app
devcircuit hooks status --project D:\code\my-app
```

它也不许 agent 读 `guard.json` 本身——那里面就有账本路径。

hook 拦不住什么：开发进程仍以同一个 OS 用户运行，一条不用账本路径的命令（遍历文件系统）仍可能发现可读目录。要那种保证，用强/最强。完整说明见 [`hooks/README.md`](../hooks/README.md)。

最强级别参考 `docker/compose.yaml`：

- `dev` 容器：只挂项目；没有 `/ledger`；没有账本凭证；没有 Docker socket。
- `archivist` 容器：项目只读 + 账本读写；不改项目。
- `ledger` 容器：账本只读；供 human 查询。
- 账本 repo 必须是私有的；开发容器不持有 remote 凭证。

在 prompt 里写“不要读”永远只是约定，不是隔离。

## 流程

1. **设计澄清**：开发 agent 问设计问题，human 选方案；设计只写选中的方案。
2. **点头**：确认意图卡和能力规格里的要求改动。
3. **切片**：实现/测试范围从设计推导；设计变了先改设计，再改代码/测试。
4. **审核（用户要求时）**：审核子 agent 只看现行设计、diff、基线；不读账本。
5. **收尾**：能力规格已经是现行的，不用合并；框架级把 feature design 里仍然有效的结构决定并入 `docs/architecture.md`，然后删除卡和 feature design；archivist 在项目外记录最终状态。
6. **回溯**：human 用 `dev-circuit-ledger` 查账本；需要给开发 agent 时，只给最小 brief。

## 授权

开发 agent 需要历史时，停下来问 human。human 可以：

- 直接回答；
- 让 `dev-circuit-ledger` 生成 brief；
- 只把 brief 中的“现行约束”贴进设计或交给开发 agent。

不要直接把账本原文、旧方案列表或完整历史交给开发 agent。

## 不做什么

- 不在项目里建 `ledger/`、`decisions/`、`adr/`、`history/`、`maintenance/`；
- 不写旧版本、被替代内容或备选方案；
- 不把账本挂进开发容器；
- 不让开发 agent 派生 archivist 子 agent（那会破坏隔离）。
