"""Exercise normal and framework changes from project creation to closeout."""

import subprocess
import sys

import pytest

from test_new_project import PWSH, git, run_script


pytestmark = pytest.mark.skipif(PWSH is None, reason="需要 PowerShell 7（pwsh）")


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def check(root, script, *args):
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(root / "scripts" / script), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def test_walkthrough_normal_and_framework(tmp_path):
    root = tmp_path / "walkthrough"
    result = run_script("-Path", str(root), "-Name", "Walkthrough")
    assert result.returncode == 0, result.stdout + result.stderr

    write(root, "docs/requirements/demo.md", """# 导出能力
代号：DEMO

- DEMO-1：导出当前一条记录。
  - 例：选中一条记录后导出，得到该记录。
  - 证明：src/test_demo.py
""")
    write(root, "docs/requirements/sync.md", "# 同步能力\n代号：SYNC\n")
    ordinary = write(root, "specs/add-export/spec.md", """# add-export：扩充导出格式

## 目标
导出当前选中的多条记录，并支持 CSV。

## 范围
- 做：扩充已有导出函数。
- 不做：远程上传。
- 反目标：未选中的记录出现在结果里。

## 结构影响
- 动哪些模块：现有导出模块。
- 新契约 / 新数据结构 / 全局机制：无。
- 结论：普通。

## 规格变化
- 新增 DEMO-2：支持 CSV 导出。例：选择 CSV 时生成带表头的 CSV。
- 修改 DEMO-1：导出当前选中的全部记录。例：选中两条时导出两条。

## 风险
- 风险档：低。
- 风险加项：无。
- 验收方式：功能结束时一起验收。

## 切片
- S1：扩充导出并合并规格变化。
  - [ ] 更新能力规格并收尾。

## 待定
无。
""")
    framework = write(root, "specs/new-sync/spec.md", """# new-sync：内存同步

## 目标
将选中的记录同步到本地内存仓库。

## 范围
- 做：同步服务与内存仓库。
- 不做：网络传输、磁盘持久化。
- 反目标：界面直接写入仓库。

## 结构影响
- 动哪些模块：调用入口、同步服务、内存仓库。
- 新契约 / 新数据结构 / 全局机制：有，sync(records) 本地接口。
- 结论：框架级。

## 规格变化
- 新增 SYNC-1：同步成功后可读回相同的记录。例：同步两条记录后读回两条相同记录。

## 风险
- 风险档：低。
- 风险加项：无。
- 验收方式：功能结束时一起验收。

## 切片
- S1：打通入口到内存仓库的骨架路径。
  - [ ] 验证契约，合并规格变化与结构决定。

## 待定
无。
""")
    design = write(root, "specs/new-sync/design.md", """# new-sync 设计

## 现状与约束
当前只有导出模块；同步在同一进程内运行，不引入外部依赖。

## 设计目标与非目标
- 目标：明确记录的唯一写入者。
- 非目标：分布式同步。

## 结构
- 模块与职责：入口接收调用，同步服务编排，内存仓库存取记录。
- 依赖方向：入口 → 同步服务 → 内存仓库。
- 数据归属：记录由内存仓库拥有，只有仓库写入。
- 组件契约：sync(records) 返回写入数量；非法记录抛 ValueError；本地同步调用无远程超时；接口版本为 v1。

## 关键决定
- 决定：由内存仓库统一写入。理由：保持单一数据归属。
  - 放弃的备选：入口直接写记录，会分散写入职责。

## 风险与缓解
- 写入过程中部分失败 → 校验全部记录后一次替换。

## 迁移与回滚
新增本地接口不改已有数据；失败时撤回入口与同步模块，继续使用原有导出功能。

## 骨架切片
调用入口 → 同步服务 → 仓库写入 → 读回；优先验证跨模块数据归属与参数传递。

## 结构守护
契约测试验证入口只调用同步服务，数据只由仓库写入。

## 可以晚点再答的问题
- 是否支持批量取消，后续有需求再决定。
""")
    write(root, "src/test_demo.py", 'REQUIREMENT_IDS = ("DEMO-1", "DEMO-2", "SYNC-1")\n')

    for script in ("doc_guard.py", "spec_check.py"):
        result = check(root, script)
        assert result.returncode == 0, result.stdout + result.stderr

    conflict = write(root, "specs/other/spec.md", "## 规格变化\n- 修改 DEMO-1：另一种导出行为。\n")
    result = check(root, "spec_check.py")
    assert result.returncode == 1
    assert "conflict" in result.stdout
    conflict.unlink()
    conflict.parent.rmdir()

    demo = write(root, "docs/requirements/demo.md", """# 导出能力
代号：DEMO

- DEMO-1：导出当前选中的全部记录。
  - 例：选中两条时导出两条。
  - 证明：src/test_demo.py
- DEMO-2：支持 CSV 导出。
  - 例：选择 CSV 时生成带表头的 CSV。
  - 证明：src/test_demo.py
""")
    sync = write(root, "docs/requirements/sync.md", """# 同步能力
代号：SYNC

- SYNC-1：同步成功后可读回相同的记录。
  - 例：同步两条记录后读回两条相同记录。
  - 证明：src/test_demo.py
""")
    architecture = write(root, "docs/architecture.md", """# 结构

入口 → 同步服务 → 内存仓库；依赖只能单向。
记录由内存仓库拥有，只有仓库写入。由仓库统一写入的理由：保持单一数据归属。
sync(records) 返回写入数量，非法记录抛 ValueError；本地同步调用无远程超时，接口版本为 v1。
相关行为要求见 [同步能力](requirements/sync.md) 的 SYNC-1；导出行为见 [导出能力](requirements/demo.md) 的 DEMO-1、DEMO-2。
""")
    write(root, "docs/README.md", """# 文档地图

- [导出能力](requirements/demo.md)：DEMO 要求。
- [同步能力](requirements/sync.md)：SYNC 要求。
- [结构](architecture.md)：模块、契约与数据归属。
""")
    for path in (ordinary, framework, design):
        path.unlink()
    ordinary.parent.rmdir()
    framework.parent.rmdir()

    assert "- DEMO-1：导出当前选中的全部记录。" in demo.read_text(encoding="utf-8")
    assert "- DEMO-2：支持 CSV 导出。" in demo.read_text(encoding="utf-8")
    assert "- SYNC-1：同步成功后可读回相同的记录。" in sync.read_text(encoding="utf-8")
    assert "保持单一数据归属" in architecture.read_text(encoding="utf-8")
    assert not list((root / "specs").glob("*/spec.md"))
    assert not ordinary.parent.exists()
    assert not framework.parent.exists()
    for script in ("doc_guard.py", "spec_check.py"):
        result = check(root, script)
        assert result.returncode == 0, result.stdout + result.stderr
    result = check(root, "spec_check.py", "--report")
    assert result.returncode == 0
    assert result.stdout == ""

    assert git(root, "add", "-A").returncode == 0
    result = git(root, "commit", "-m", "test: close add-export and new-sync",
                 "-m", "为什么：验证规格变化与结构决定合并后可通过两项 hook 检查。")
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(root, "status", "--short").stdout.strip() == ""
