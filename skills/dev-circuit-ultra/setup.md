# dev-circuit-ultra：新建项目、接入、账本与升级

只在新建项目、给已有仓库接入本流程、建账本或升级旧项目时读。项目和账本是两件事，账本永远在项目外。

流程依赖 `devcircuit` CLI（`pipx install git+https://github.com/iswalterwu/dev-circuit-ultra`）：`context`、`ledger`、`close` 都靠它。

- **同步技能**：`devcircuit sync`，把技能写进 Claude Code / agents / DSH 目录。
- **新建**：`devcircuit init --path <项目目录> --name <项目名>`。它生成下面第 1–5 步的全部文件，执行 `git init`，并做第一次提交。
- **接入已有仓库**：同一命令加 `--adopt`。只补缺失的文件，已有文件不覆盖，也不提交，最后报出 doc_guard 发现的旧文档问题。
- **账本**：`devcircuit ledger init --path <项目外的私有目录>` 创建独立私有 git repo；再 `devcircuit hooks install --harness pi|claude --project <项目> --ledger <账本>`，它写 `.dev-circuit/guard.json`（本机路径，同时写进 `.gitignore`，不用再手动加）并装上 hook。之后开发 agent 只用 `devcircuit ledger add` 写、`devcircuit ledger check` 核对，hook 拦下其他访问。它在项目里留下 hook 脚本和 `.gitignore` 的改动：在主干上提交它们，再开始做功能。
- **升级旧项目**：先跑 `devcircuit migrate --check --project <项目>`，它列出要改的地方，不动任何文件。先按它迁移进行中的功能，再同步新版技能；有未提交改动的，先问用户。

本技能目录里的 `new-project.ps1`、`new-ledger.ps1` 和仓库根目录的 `sync.ps1` 只是转发到同样的实现，供 pwsh 用户使用。

跑完 CLI 后，仍要填写 AGENTS.md 里的项目事实。不用 CLI 生成文件时，按下面的步骤手动做：

1. 把 `templates/AGENTS.md` 复制到项目根目录，填上项目事实：命令、代码地图、红线、主干、审核模型。
2. 项目根目录的 `CLAUDE.md` 只写一行：`@AGENTS.md`。
3. 建 `specs/` 目录，把 `templates/backlog.md` 放进去，改名为 `specs/backlog.md`。
4. 建 `docs/requirements/`，放入 `templates/project/docs/requirements/README.md`；以后每个能力一份规格，按 `templates/requirements.md` 写。
5. 设置检查：
   - 把 `scripts/doc_guard.py` 和 `scripts/spec_check.py` 复制到项目的 `scripts/`（也可以 `devcircuit vendor`）；
   - 新建 `.dcuignore`（可以只有注释）：误杀时用它或 `--ignore` 加白名单，不要关掉检查；
   - 新建 `.githooks/pre-commit` 依次运行这两个脚本，然后执行 `git config core.hooksPath .githooks`；
   - CI 里也加上这两步。
6. 长文档按 `templates/doc-header.md` 加上"读我"块。
