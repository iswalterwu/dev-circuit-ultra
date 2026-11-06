结论：需修改

必须改：
1. `records.py:71` + `records.py:180` — `sys.stdout.reconfigure(encoding="utf-8")` 没有关闭换行转换，在 Windows 上 `python records.py report --format csv > out.csv` 写入文件的字节是 CRLF（实测 `b'id,name,amount\r\n...'`），违反 RPT-2“行尾为 LF”，也违反设计要点“统一 LF 行尾”；表格输出同样带 CRLF。测试没有发现，是因为 `subprocess.run(..., text=True)` 的通用换行转换把 `\r\n` 还原成 `\n` — 修复方式：`reconfigure(encoding="utf-8", newline="")`（或 `sys.stdout.buffer.write(text.encode("utf-8"))`），并把测试改为断言 `result.stdout` 的原始 bytes。

建议：
1. `tests/test_report.py:10-16` — 读取 stdout 时用 `text=True` 会掩盖行尾与编码问题；建议保留 `encoding` 但去掉换行归一化（`newline=""` 或比较 bytes），至少 RPT-2 用 bytes 断言。
2. `tests/test_report.py:test_RPT_17_output_files_are_utf8` — RPT-17 同时要求 stdout 使用 UTF-8，现在只测了 `-o` 文件；建议补一条含非 ASCII 名字的 stdout 用例（可临时写入临时数据文件，或单测 `write_text`）。
3. `records.py:37` `column_list` — `--columns "id, name"` 直接报错；建议对每段 `strip()`，或至少错误信息提示不要带空格。
4. `records.py:157` `total_row` — 选中列里没有 `amount`（如 `--columns name,id --total`）或重复列（`--columns id,id --total`）时合计被静默丢掉；建议明确该行为并补一条测试。
5. `records.py:120` `in_amount_range` — `--min-amount` 大于 `--max-amount` 时静默输出空表；可接受，但可考虑在边界处直接报错。

未覆盖的要求：无