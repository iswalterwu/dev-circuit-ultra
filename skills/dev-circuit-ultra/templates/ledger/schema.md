# 账本记录格式

`entries/<project>/<feature>.jsonl`，一行一个 JSON 对象。`devcircuit ledger add` 追加写，不改旧行。

## 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 唯一 ID：`<UTC 时间>-<短随机>` |
| `ts` | 是 | ISO 8601 UTC |
| `project` | 是 | 项目名：`guard.json` 的 `project`，没有就用项目目录名 |
| `feature` | 是 | 功能名，和 `specs/<feature>/` 一致 |
| `kind` | 是 | `framework` / `design` / `design-change` / `close` / `correction` |
| `commit` | 否 | 对应提交的完整 SHA；默认是写入时的 HEAD |
| `decision` | 是 | 选定的决定，一句话 |
| `discarded` | 否 | 被否方案：`[{"idea": "...", "why": "..."}]` |
| `reason` | 否 | 为什么这样定 |
| `ids` | 否 | 涉及的现行要求编号 |
| `ids_removed` | 否 | 删掉的要求编号 |
| `review` | 否 | 审核结果（收尾记录） |
| `source` | 是 | 写入方；开发侧写的是 `dev-agent` |
| `human_only` | 是 | 固定 `true` |

更早的记录里可能有 `constraints` 字段和 `slice`、`review` 这类 kind，照样保留，`ledger check` 不会因为它们报错。

## 示例

```json
{"id":"20261108T120000Z-a1b2c3","ts":"2026-11-08T12:00:00Z","project":"records","feature":"add-report","kind":"design","commit":"<完整提交 SHA>","decision":"只选 amount 时输出 TOTAL + 合计两个字段","discarded":[{"idea":"只输出裸合计 4360","why":"无法与数据行区分"}],"ids":["REPORT-3"],"source":"dev-agent","human_only":true}
```

## 不写什么

- 密钥、token、cookie、个人数据；
- 大段代码或完整 diff（引用提交即可）；
- 对开发 agent 的指令或待办（账本不是任务系统）。
