# 私有账本

这是 **项目外** 的私有 git 仓库模板，只给 human 回溯和审计用。开发 agent 不读它，也不写它。

## 边界

- 只由 `dev-circuit-archivist` 在独立会话/容器里追加。
- 项目目录只读；账本目录只写；archivist 不改代码、不改设计。
- 开发容器 **不挂载** 这个目录，也不持有它的凭证。
- 需要历史时，human 让 `dev-circuit-ledger` 生成最小 brief，再决定是否交给开发 agent。

## 目录

```
<ledger>/
  README.md          # 本文件
  schema.md          # 条目格式
  entries/
    <project>/
      <feature>.jsonl
  access.jsonl       # human 查询/授权记录（可选）
```

## 规则

- 只追加，不改旧条目；需要更正就追加一条 `correction`。
- 条目不写密钥、token、个人数据；archivist 负责脱敏。
- 账本不是产品的 source of truth；现行设计才是。账本只解释“为什么变成现在这样”。
- 这是私有仓库：远程仓库必须私有；不要把账本推到公开仓库。
