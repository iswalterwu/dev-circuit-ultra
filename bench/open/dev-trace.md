# Dev-circuit-ultra trace (latest A/B)

> session：`C:/Users/iswal/open-ab/dev-circuit/.bench/sessions/open/2026-11-06T17-56-12-493Z_01a1b201-004c-73b0-9fd1-2bfa90a5f347.jsonl`
> 总墙钟：408.9 s；成本 $0.0743；39 个 assistant turn；13 tests passed。

## 时间花在哪

| 部分 | 耗时 | 占比 |
|---|---:|---:|
| 主模型推理 | 269.5 s | 65.9% |
| 工具总耗时 | 139.4 s | 34.1% |
| 其中 subagent | 107.0 s | 26.2% |
| 其中 bash | ~32 s | 7.8% |

## 两次子 agent

| 时间 | agent | 目的 | 耗时 |
|---|---|---|---:|
| 最终审核 | `reviewer-fast` | 常规代码审 | 93.2 s |
| 复查 | `reviewer-fast` | 只核对必须改 | 13.8 s |
| **合计** | | | **107.0 s** |

没有写代码前的结构审，也没有全量重审；复查只审修复 diff。`reviewer-fast` 不固定模型，继承当前会话模型。

## 代价

- 13 条测试，覆盖比 OpenSpec 的 21 条窄；数据文件缺失、坏 JSON、`-o` 不可写会 traceback。
- 盲评正确性/测试各 4/5；OpenSpec 是 4/5 + 5/5。
- 速度提升不是靠删掉最终审核，而是取消写前结构审、只审一次、复查 diff、检查不逐切片全量。

## 结论

这次 trace 说明：普通功能把审核放在收尾后一次，reviewer 由用户配置为轻量只读 agent，能把 subagent 时间压到 107 s；但测试覆盖不足是实际代价，下一轮应补错误路径测试。
