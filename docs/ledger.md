# 设计与账本：两条边界

dev-circuit-ultra 把“现在怎么做”和“为什么变成现在这样”分开：

- **现行设计**：项目里的 `specs/<feature>/spec.md` 的 `## 设计`，框架级再加 `design.md`。开发 agent 只读这个。
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

## 强隔离

只有“独立容器/用户 + 挂载隔离”能保证开发 agent 读不到账本：

- `dev` 容器：只挂项目；没有 `/ledger`；没有账本凭证；没有 Docker socket。
- `archivist` 容器：项目只读 + 账本读写；不改项目。
- `ledger` 容器：账本只读；供 human 查询。
- 账本 repo 必须是私有的；开发容器不持有 remote 凭证。

参考 `docker/compose.yaml`。在 prompt 里写“不要读”只是约定，不是隔离。

## 流程

1. **设计澄清**：开发 agent 问设计问题，human 选方案；设计只写选中的方案。
2. **点头**：现行设计和意图卡确认。
3. **切片**：实现/测试范围从设计推导；设计变了先改设计，再改代码/测试。
4. **审核**：审核子 agent 只看现行设计、diff、基线；不读账本。
5. **收尾**：合并现行设计/规格，删除卡和 feature design；archivist 在项目外记录最终状态。
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
