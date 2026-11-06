给 records CLI 加 `report` 命令。共 20 条验收：

1. 默认表格：第一行 `id<TAB>name<TAB>amount`，之后按 `records.json` 顺序，每行一条，制表符分隔。
2. `--format csv`：表头同上，字段按 RFC 4180 转义，UTF-8。
3. `--format json`：输出对象数组，键是所选的列。
4. `--sort id|name|amount`，默认 `id`；`name` 不区分大小写，`amount` 按数值。
5. `--desc` 反转排序。
6. `--filter TEXT`：按 `name` 做不区分大小写的子串过滤。
7. `--min-amount N`：保留 `amount >= N`。
8. `--max-amount N`：保留 `amount <= N`。
9. `--limit N`：过滤和排序后取前 N 条。
10. `--offset N`：过滤和排序后跳过前 N 条。
11. `--columns a,b`：只输出列出的列，顺序按传入；只允许 `id`、`name`、`amount`。
12. `--total`：表格和 CSV 末尾加一行 `TOTAL`、空 name、amount 合计；JSON 忽略。
13. `-o FILE`：写入文件，stdout 不输出内容。
14. 空结果：表格和 CSV 只有表头；JSON 为 `[]`。
15. 非法 `--sort`、非法 `--columns`、负数 `--limit`/`--offset`、非整数金额：退出码 2，stderr 有错误，stdout 为空。
16. 原有 `python records.py export --id N` 保持单条 JSON 对象，不能坏。
17. 所有输出使用 UTF-8。
18. 不引入第三方依赖。
19. 过滤、金额范围、排序、offset、limit 的处理顺序为：过滤 → 金额范围 → 排序 → offset → limit。
20. `--total` 的合计只统计过滤后的记录。
