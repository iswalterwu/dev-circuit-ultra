# 私有账本

这是 **项目外** 的私有 git 仓库，记"为什么变成现在这样"：选定的决定、被否方案和原因。

## 边界

- 开发 agent 对它只写不读：用 `devcircuit ledger add` 追加，只拿到回执编号；用 `devcircuit ledger check` 核对，只看到不一致的功能、编号和提交。项目里的 hook 拦下其他访问。
- human 用 `dev-circuit-ledger` 在独立会话里查询；需要给开发 agent 时，只给一份只含现行约束的 brief。
- 开发容器不挂载这个目录，也不持有它的 remote 凭证。

## 目录

```
<ledger>/
  README.md          # 本文件
  schema.md          # 记录格式
  entries/
    <project>/
      <feature>.jsonl
  access.jsonl       # human 查询 / 授权记录（可选）
```

## 规则

- 只追加，不改旧记录；要更正就追加一条 `correction`。
- 记录不写密钥、token、个人数据。
- 账本不是产品的现行源，现行设计在项目里；账本只解释"为什么变成现在这样"。
- 这是私有仓库：remote 必须私有，不要推到公开仓库。
