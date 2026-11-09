# Demo

这是 `dev-circuit-ultra` 的**一次性**端到端演示，不属于 skill，也不进入任何项目。

它用一个最小的 `greet` 功能走一遍流程，并验证：

1. 设计定了以后只写一次：在 `feat/add-greet` 分支上，要求写在能力规格里，卡只有目标、范围和切片；
2. 设计变更覆盖能力规格里的要求，被否的输出风格只进项目外的账本；
3. 开发侧用 `devcircuit ledger add` 写账本，只拿到回执编号，看不到内容；
4. `devcircuit context --feature` 给出这个功能要的要求原文；
5. `devcircuit close` 跑检查、核对账本、删卡并提交 `close add-greet`、写收尾记录；
6. `doc_guard` 拒绝项目里的 `ledger/` 目录；
7. 工具调用层的 hook 在读取之前拦下账本（绝对路径和相对路径都拦），放行 `devcircuit ledger add`。

## 运行

```powershell
python demo/run_demo.py
```

需要 PowerShell 7、Python 3、git。demo 直接用本仓库的 `tools/` 跑 `devcircuit`，不需要先安装。

强隔离由 [docker/compose.yaml](../docker/compose.yaml) 的挂载边界保证；这个 demo 验证的是路径和协议边界，不启动 Claude Code / pi 容器。

## 60 秒视频

`assets/demo-60s-{en,zh}.webm`（同时保留 `.mp4`）和脚本 `demo/make_demo_60s.py` 还没跟上现在的流程，README 暂时不引用它们。重新生成需要 Windows、Pillow、OpenCV 和 numpy：

```powershell
python demo/make_demo_60s.py
```
