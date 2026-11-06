# records

小型 Python 命令行项目，数据在 `records.json`。

## 命令

- 跑测试：`python -m pytest -q`
- 导出单条（现状）：`python records.py export --id 2`

## 代码地图

| 路径 | 作用 |
|---|---|
| `records.py` | CLI 入口、命令行参数、导出 |
| `records.json` | 测试数据 |
| `tests/` | pytest 测试 |

## 红线

- 不改 `records.json` 里的测试数据。
- 不引入第三方依赖。
