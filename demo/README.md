# Demo

这是 `dev-circuit-ultra` 的**一次性**端到端演示，不属于 skill，也不进入任何项目。

它用一个最小的 `greet` 功能走一遍流程，并验证：

1. 要求条文只写一次：在 `feat/add-greet` 分支上先写草稿（要求写在能力规格里，卡只有目标、范围和切片），定了以后两者原样放进同一个提交；
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

需要 PowerShell 7（`pwsh`）、Python 3.10+（装好 pytest）和 git。demo 自己调用的 `devcircuit` 命令用本仓库的 `tools/`，不需要先安装；建项目和账本的 `new-project.ps1`、`new-ledger.ps1` 先找 PATH 上的 `devcircuit`，找得到就用已安装的那一版，项目里的 `scripts/` 检查器、`.githooks/pre-commit` 和模板也来自那一版：要验证本仓库的改动，先用 `pipx install --force .` 装上这份 checkout，或者让 PATH 上找不到 `devcircuit`。找不到时它们用本仓库的 `tools/`，并按 `python` 这个命令名找解释器，只有 `python3` 的系统要先让 `python` 可用。

最强一级的隔离靠 [docker/compose.yaml](../docker/compose.yaml) 的挂载边界：`dev` 容器不挂载账本，开发 agent 和 `devcircuit` 由你装进镜像，见 [docker/README.md](../docker/README.md)。这个 demo 验证的是路径和协议边界，不启动容器。
