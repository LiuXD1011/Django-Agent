task_id: MARLIN-P01
round: 3
updated_at: 2026-09-30T12:30:39+00:00
workspace_realpath: /home/liuxuedeng/orca/workspaces/Django-Agent/marlin
branch: prep-desktop-commercial-release
base_head: afa7e0138f9fbad80e80aa4ead6f1d80af0145da

# 交付报告：双锁失败释放与测试证据收尾（MARLIN-P01 / round 3）

executor: 桌面 ZCode
状态：完成，ready_for_review
next_actor: Codex（独立验收）

## 0. 本轮范围声明

本 round 3 仅按 round 3 TASK（依据 REVIEW round 2 正式验收所余 R2a/R2b）做最小收尾：
只改两份 accounts 测试文件与本协作报告。accounts/views.py、requirements.txt 保持
round 1/round 2 已验收交付不变（SHA256 见 §3，与 TASK 登记一致）。

## 1. R2a / R2b 处理说明

### R2a：双锁失败释放（portability）

`test_distinct_databases_do_not_block_each_other` 改为嵌套 try/finally 管理：
lock_a.acquire 后进入 try，内部 lock_b.acquire 成功后在内层 try 中断言两锁同时持有
（is_locked 均为真，即真实"不同数据库互不阻塞"行为证据），finally 中先释放 lock_b，
外层 finally 释放 lock_a。第二次 acquire 失败（如抛 Timeout）也会保证第一把锁被释放，
finally 后断言两锁均处于未持有状态。锁身份、超时、业务实现均未改动；未增加测试模块。

### R2b：主动清理测试命名与事实一致（processes）

`test_wait_overrun_terminates_and_reaps_stuck_child` 更名为
`test_shutdown_terminates_and_reaps_live_stuck_child`，docstring 修正为事实描述：
该测试验证的是 `_shutdown` 对仍存活卡死子进程的主动有界清理（terminate/kill + 有界回收 +
管道排空，以真实 returncode 与 stdout 关闭状态为观察结果），未触发 `_collect` 的等待超时
kill 分支。未为凑证据新增超时测试（round 3 TASK 明确允许改名路线）；真实子进程中途
spawn 失败回归 `test_midway_spawn_failure_reaps_already_created_child` 原样保留。

## 2. 本轮变更清单

| 文件 | 变更 | 说明 |
| --- | --- | --- |
| accounts/test_auto_setup_portability.py | 修改 | R2a：双锁嵌套 try/finally + is_locked 行为断言。测试数不变（11） |
| accounts/test_auto_setup_processes.py | 修改 | R2b：测试更名 + docstring 修正。测试数不变（6） |
| graphify-out/ | 工具产物 | `graphify update .` 重建，.gitignore 内，未入库 |

未改动：accounts/views.py、requirements.txt、accounts/test_auto_setup_security.py 及其它一切业务文件。无删除、无新增依赖、无 schema 变化。

## 3. 路径与完整性核验

- pwd -P = realpath(cwd) = realpath(git toplevel) = /home/liuxuedeng/orca/workspaces/Django-Agent/marlin；
  分支 prep-desktop-commercial-release；HEAD afa7e0138f9fbad80e80aa4ead6f1d80af0145da（未变）。
- 起点 SHA256 与 round 3 TASK 登记一致；交付后复核：accounts/views.py
  a6c241180c83a7afa2493e7827ae85aff177eb0b99c8a041856eab364558632f；requirements.txt
  b5432b4fb55a9b79463a53d0fea21d32b8776f91a684f670cb5b69465ebbd0c3（主体实现未动）。
- `git status --short --untracked-files=all`：仅两个 tracked 修改（round 1 交付）+ 两个本轮修改测试
  （untracked）+ .ai-collab/；无表外改动、无 staged、无删除。

## 4. 本轮测试证据

环境：Linux (WSL2 5.15.167.4)、Python 3.12.2（/home/liuxuedeng/anaconda3/bin/python）、
Django 5.2.15、filelock 3.13.1（满足声明约束 filelock>=3.13,<4；未安装/升级任何包）。
隔离：新建 OS 临时 DJANGO_DB_PATH、NEO4J_ENABLE=false、LANGFUSE_ENABLED=false、
LANGFUSE_AUTOSTART=false、DJANGO_DEBUG=true、PYTHONDONTWRITEBYTECODE=1；根目录无 .env；
子进程白名单环境，无任何 provider/Neo4j/Langfuse 凭据。

| 编号 | 命令 | 结果 | 退出码 |
| --- | --- | --- | --- |
| V1 | `python manage.py test accounts.test_auto_setup_security accounts.test_auto_setup_portability accounts.test_auto_setup_processes --noinput --verbosity 1` | 20 tests OK（3 + 11 + 6，与 round 3 TASK 预期数量一致） | 0 |

- 跳过项：0（symlink 等价测试在 Linux 实际执行）。
- 按本轮 TASK 未重复运行 71 项联合回归与迁移图检查（round 2 已独立通过 71 项 + 迁移图，
  其余模块与迁移本轮未改动）。
- `graphify update .` 退出码 0；本轮修改后图谱已更新。
- 运行后根目录无 db.sqlite3/media/.cache；临时测试目录已清理。

## 5. 历史保留（前轮结论）

- round 1（changes_requested → round 2 返工）：主体实现 fcntl 移除 + FileLock 有界互斥；
  修复前可证实缺陷为 fcntl 导入阻断与无有界等待/503 契约；r1 中"旧实现锁失败回退无锁建号"
  归因已在 round 2 撤回（patch 的 FileLock.acquire 旧实现不调用）。
- round 2（changes_requested → round 3 收尾）：R1 锁文件残留假设、skip 拆分、R2 有界回收
  与失败路径回归、R3 证据纠正均已完成并经 Codex 独立复跑确认（71 tests OK）；余 R2a/R2b
  由本轮完成。
- 并发预期口径（沿用 round 2 纠正）：正常并发初始化恰为一 201、一 401（setup_already_completed）；
  仅忙锁专项测试期望 503/setup_busy。

## 6. 未验证内容、限制

- Windows native execution: not_run。两份测试文件可在 Windows 运行（stdlib + filelock +
  os.path/Path；symlink 场景无权限时显式 skipTest），但这是可运行性说明，非 Windows 原生
  执行证据；filelock 的 Windows msvcrt 语义未实测。
- 本轮未运行等待超时 kill 分支的专项触发测试（按 TASK 选择改名路线，不新增超时测试）。
- 未运行全量测试套件、前端构建、真实 LLM/Neo4j/Langfuse、打包安装验证（不在本轮范围）。
- 本轮未产生审批请求；requests/handled_request_ids 为空。
- 未提交、未推送、未合并、未发布；未动主 checkout /home/liuxuedeng/Django-Agent。

## 7. 状态

RESULT.md 先于 STATUS 写入；STATUS 随后置 round=3 / ready_for_review、
business_writes_stopped=true。此后未再修改任何业务文件。
如 Codex 会话已结束，请用户向 Codex 转发"继续读取协作文件"。

next_actor: Codex
