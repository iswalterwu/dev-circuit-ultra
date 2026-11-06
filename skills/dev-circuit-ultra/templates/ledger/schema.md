# 账本条目格式

`entries/<project>/<feature>.jsonl`，一行一个 JSON 对象。追加写，不改旧行。

## 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 唯一 ID；建议 `<UTC 时间>-<短随机>` |
| `ts` | 是 | ISO 8601 UTC |
| `project` | 是 | 项目名 |
| `feature` | 是 | 功能名 |
| `kind` | 是 | `design` / `design-change` / `slice` / `review` / `close` / `correction` |
| `commit` | 否 | 对应 commit SHA；没有就写 null |
| `decision` | 是 | 当时的现行决定，一句话 |
| `discarded` | 否 | 被删除/替代的思路数组：`[{"idea": "...", "why": "..."}]` |
| `constraints` | 否 | 仍然有效的约束数组 |
| `reason` | 否 | 为什么这样定；不写空话 |
| `source` | 否 | `session` / `diff` / `design` / `review`，可带路径 |
| `human_only` | 是 | 固定 `true` |

## 示例

```json
{"id":"20261106T120000Z-a1b2c3","ts":"2026-11-06T12:00:00Z","project":"records","feature":"add-report","kind":"design-change","commit":"abc1234","decision":"只选 amount 时输出 TOTAL + 合计两个字段","discarded":[{"idea":"只输出裸合计 4360","why":"无法与数据行区分"}],"constraints":["--total 不得静默丢失"],"reason":"合计必须可辨识","source":"session:add-report/review","human_only":true}
```

## 不写什么

- 密钥、token、cookie、个人数据；
- 大段代码或完整 diff（用 commit/path 引用）；
- 对开发 agent 的指令或待办（账本不是任务系统）。
