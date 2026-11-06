# records — agent 入口

> 先读本页。只读当前任务需要的文件和小节；除非用户要求，不要翻 Git 历史找规则。

## 1. 项目一句话

records 是一个 Python 命令行小工具：读 `records.json`，按 id 导出记录。标准库实现，pytest 测试。

## 2. 按任务读什么

| 任务 | 读 |
|---|---|
| 改功能 | `specs/` 下的当前卡片（如果有）、`docs/requirements/` 下的能力规格 |
| 找零散的待做事项 | `specs/backlog.md` |
| 改 CLI 行为 | `records.py`、`tests/` |
| 改某个代码目录 | 该目录的 README（如果有） |

## 3. 常用命令（提交前检查）

- 测试：`python -m pytest -q`
- 文档防回流：`python scripts/doc_guard.py`
- 要求编号检查：`python scripts/spec_check.py`
- 新克隆后执行一次：`git config core.hooksPath .githooks`

## 4. 代码地图

- `records.py`：CLI 入口、参数解析
- `records.json`：测试数据
- `tests/`：pytest 测试

## 5. 红线

- 不改 `records.json` 里的测试数据。
- 不引入第三方依赖。
- 原来的 `python records.py export --id N` 输出单条 JSON，这个行为不能坏。

## 6. 工程准则

1. 不为猜测出来的竞态或安全边界增加复杂度。只有能说清“具体怎么出错、概率多大、要写多少代码”的才做。
2. 外部数据只在入口层校验一次，往里只传确定类型的值。
3. 不提前抽只用一次的函数。
4. 主函数只写正常流程，校验和细节放到它下面的小函数里。
5. 自动生成的文件不手改；改源头，然后重新生成。
6. 测试要测真实实现，尽量少用 mock。
7. 按仓库现有的做法走。
