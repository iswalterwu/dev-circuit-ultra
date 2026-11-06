# Demo

这是 `dev-circuit-ultra` 的**一次性**端到端演示，不属于 skill，也不进入任何项目。

它用一个最小的 `greet` 功能验证：

1. 设计卡包含 `## 设计`，没有旧方案栏；
2. 设计变更通过覆盖卡片完成，旧输出风格从项目里删除；
3. 被删掉的想法只出现在项目外的私有账本；
4. `dev-circuit-ledger` 的 brief 只带现行约束，不带被删想法；
5. 收尾删除卡片，只留现行能力规格；
6. `doc_guard` 拒绝项目里的 `ledger/` 目录。

## 运行

```powershell
python demo/run_demo.py
```

需要 PowerShell 7、Python 3、git。demo 使用 `demo/archivist_standin.py` 作为确定性的账本写入器，替代独立容器里的 `dev-circuit-archivist`；它只写账本，不写项目。

强隔离本身由 [docker/compose.yaml](../docker/compose.yaml) 的挂载边界保证；这个 demo 验证的是路径和协议边界，不启动 Claude Code/pi 容器。

## 60 秒演示

`assets/demo-60s-{en,zh}.webm` 是无声的 60 秒走查（同时保留 `.mp4`），包含五步循环和与 OpenSpec 的开放 A/B；封面是 `assets/demo-60s-poster-{en,zh}.png`。重新生成需要 Windows、Pillow、OpenCV 和 numpy：

```powershell
python demo/make_demo_60s.py
```
