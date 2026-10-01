task_id: MARLIN-P01
round: 3
updated_at: 2026-09-30T12:33:58+00:00
workspace_realpath: /home/liuxuedeng/orca/workspaces/Django-Agent/marlin
branch: prep-desktop-commercial-release
base_head: afa7e0138f9fbad80e80aa4ead6f1d80af0145da

# 初始检查与独立验收台账

owner: Codex
review_state: completed
review_outcome: passed
next_actor: ZCode（读取新任务 MARLIN-P02A / round1）

## 基线（task_id=MARLIN-P01, round=1）

检查时间：2026-09-30，Linux。
- realpath=/home/liuxuedeng/orca/workspaces/Django-Agent/marlin
- 分支 prep-desktop-commercial-release；HEAD=afa7e0138f9fbad80e80aa4ead6f1d80af0145da。
- git worktree list 确认本 worktree；主 checkout 是 /home/liuxuedeng/Django-Agent，不可混用。
- 初始化前 `git status --short --branch` 仅显示分支，tracked/staged/untracked 改动均为空。
- 不存在 db.sqlite3、media、.env、frontend/node_modules、frontend/dist、graphify-out/graph.json 和 graphify-out/wiki/index.md。
- Python 3.12.2（/home/liuxuedeng/anaconda3/bin/python），Django 5.2.15，DRF 3.14.0，sqlite-vec 0.1.9，Gunicorn 26.0.0，Node v22.23.2，npm 10.9.8。
- 尚未核对 ZCode 进程目录，必须由 ZCode 首次 STATUS 自证；不能宣称已确认双方同目录。

## Codex 已独立执行（task_id=MARLIN-P01, round=1）

1. `python manage.py test accounts.test_auto_setup_security personal_knowledge_base.test_task_recovery personal_knowledge_base.test_sqlite_concurrency personal_knowledge_base.test_stream_persistence --noinput --verbosity 1`
   - 退出码 0，54 tests / OK，Django system check 无问题。
   - 子进程仅继承 PATH/HOME/locale/临时目录/系统和证书路径等基础变量；临时 DJANGO_DB_PATH，DJANGO_DEBUG=true，NEO4J_ENABLE=false，LANGFUSE_ENABLED=false，LANGFUSE_AUTOSTART=false，PYTHONDONTWRITEBYTECODE=1；根目录无 .env。数据库用临时目录并已清理。
   - 日志包含预期错误场景输出，但最终测试通过；不能用日志中 ERROR 字样单独断言测试失败。
2. `python tests/test_migration_graph_integrity.py`：退出码 0，1 test / OK。
3. `python tests/test_readme_links.py`：退出码 0；只验证该脚本覆盖的 Markdown 链接，不覆盖 HTML img，README 的图片路径仍不存在。
4. `node --test frontend/src/stores/auth-storage.test.mjs frontend/src/views/chat/tool-call-state.test.mjs frontend/src/views/chat/components/tool-result-output.test.mjs`：退出码 0，4 tests，0 failures。
5. 测试后 git status 仍干净，db.sqlite3/media/.cache/graphify-out 仍不存在。此次 Codex 未改业务文件。

证据限制：以上为定向基线，不是全量测试、前端构建或 Windows 原生测试；未进行真实 LLM/Neo4j/Langfuse、性能容量、安装包或故障切换验证。未运行未审核的全量脚本，避免其中的真实环境/后台恢复副作用。

## 待交付检查表（task_id=MARLIN-P01, round=1）

ZCode ready_for_review 后，Codex：
- 先核对 task_id、round、路径、business_writes_stopped=true 以及 RESULT 已完成；若报告写完后仍改业务文件，退回明确停止。
- 检查 `git status --short --untracked-files=all`、`git diff --stat`、`git diff --name-status`、`git diff --cached`、完整 tracked diff，以及全部新增文件内容；相对 base_head 检查是否出现未批准删除/依赖/迁移。Git diff 不包含 untracked，不能漏读。
- 独立运行 TASK A1～A8 所需测试和定向回归；使用独立临时库及无凭据环境。测试产生数据/缓存只在隔离临时目录；Codex 不编辑业务文件。
- 检查依赖、初始化失败回滚、真实进程争用、超时、锁释放以及 Windows 测试证据的真实边界。
- 写明确 passed 或 changes_requested，以及证据、风险、剩余平台验证项。
- 返工时先发布同 task_id 的 round 2（或递增轮次）和具体修复条件；通过后再发布下一阶段的小任务，不自动扩大当前授权。

## 结束/恢复记录（task_id=MARLIN-P01, round=1）

当前状态：初始化交接完成，未收到 ZCode 的 STATUS.json/RESULT.md；整体桌面交付与商业化目标尚未完成。
下一步负责人：用户首次向 ZCode 发送启动说明；随后 ZCode 执行。
恢复：ZCode 请求审批或交付后，如果 Codex 已结束会话，请用户向 Codex 转发“继续读取协作文件”。文件不会自动唤醒会话，Codex 不在退出后后台监督。

## 路径握手复核（task_id=MARLIN-P01, round=1）

记录时间：2026-09-30T11:38:34+00:00。独立读取实际 STATUS.json（非仅依据截图），确认 MARLIN-P01/r1，workspace_confirmed=true，realpath、branch、HEAD 均匹配。git status 目前只显示四个协调文件：TASK/DECISIONS/REVIEW/STATUS，无业务 diff。ZCode 状态 working/path_verified，未停止写入，暂无 RESULT；尚未进入验收，不运行可能与执行者写操作冲突的验收测试。下一步由 ZCode 完成任务或提交审批请求。

## 实施期间只读观察 OBS-001（task_id=MARLIN-P01, round=1）

记录时间：2026-09-30T11:59:08+00:00。当前 STATUS 仍为 working，下面是对尚未完成代码的预检观察，不是正式 passed/changes_requested，也不授权新范围或新轮次。Codex 未运行项目验收测试、未改业务文件。

发现：两个新增测试文件把“FileLock.release() 后 lock_path 必须仍存在”作为跨平台契约。accounts/test_auto_setup_portability.py 的两处 exists 断言，以及 accounts/test_auto_setup_processes.py 的 contender 释放后 “lock file must not be deleted” 断言均需自检。本机 filelock=3.13.1 源码 `filelock/_windows.py::WindowsFileLock._release` 在内核解锁和关闭描述符后，明确在 suppress(OSError) 中执行 `Path(self.lock_file).unlink()`。因此这些断言依赖 Unix 后端实现细节，在所声明依赖范围内的 Windows 正常释放路径上可能失败；这属于源码证据，尚未在 Windows 原生执行。

本轮 A4 要求“不靠删除真实数据解锁”，不要求第三方锁后端永远保留其自己的协调文件。请在原批准测试范围内检查：以真实互斥、后继获取成功、异常/退出后可恢复和用户数据未被改动为准，不应为维持锁文件存在断言而改写库后端或伪造 Windows 行为。完成报告需说明是否处理该观察。

附带预检：进程测试 finally 中有多处 kill 后没有有界 wait/communicate；异常路径结束前须确认子进程退出并回收，以满足 A4、避免 Windows 临时目录清理竞争。正式验收再检查最终版本。

## 正式验收（task_id=MARLIN-P01, round=1）

reviewed_at: 2026-09-30T12:04:46+00:00
verdict: changes_requested
next_actor: ZCode，确认新 TASK round 2 后执行

ZCode 已提交 RESULT 并声明 business_writes_stopped=true。Codex 检查了全部 tracked diff、两个 untracked 新测试文件（285/480 行）、新增/删除清单及依赖；无 staged 变更、无删除或越界文件，HEAD 未变。验收开始和结束四个业务文件 SHA256 完全一致。业务实现目前未发现需重做的互斥/超时问题，但跨平台测试与失败清理未满足本轮要求，因此不能判 passed。

### 独立复跑证据

- `python manage.py test accounts.test_auto_setup_security accounts.test_auto_setup_portability accounts.test_auto_setup_processes personal_knowledge_base.test_task_recovery personal_knowledge_base.test_sqlite_concurrency personal_knowledge_base.test_stream_persistence --noinput --verbosity 1`：68 tests，OK，退出 0；测试用时 22.207 秒，总命令约 25.12 秒。
- `python tests/test_migration_graph_integrity.py`：1 test，OK，退出 0。
- `python manage.py makemigrations --check --dry-run`：No changes detected，退出 0。
- Python3.12.2/Linux、filelock3.13.1；白名单子进程环境、临时 DJANGO_DB_PATH、外部集成关闭，无 .env；测试结束根目录仍无 db.sqlite3/media/.cache。
- `git diff --check` / staged 检查均退出 0；按 AGENTS 先运行 graphify query，图已由执行者生成。Codex 没有改业务文件。
- Windows 后端最小诊断：从已安装 filelock/_windows.py 的真实 AST 提取 WindowsFileLock._release 原函数，仅 stub msvcrt.locking，使用临时锁文件与真实 os.close/Path.unlink 执行，结果 `lock_path_exists_after_release=False`。这是 Windows 分支的受控逻辑验证，不是 Windows 原生测试。

### 必须修复

**R1（阻断 Windows 测试，A1/A4）：** `accounts/test_auto_setup_portability.py:185`、`:241` 与 `accounts/test_auto_setup_processes.py:396` 在释放后断言锁文件存在。支持范围内 filelock3.13.1 的 Windows 后端正常释放会 unlink，断言把 Unix 细节误当跨平台契约。应验证互斥/后继获取/账号与数据结果；不得通过跳过 Windows 测试、强制 soft lock、修改第三方库或人工 touch 文件来通过。A4 的禁止删除真实数据不限制第三方库管理其锁文件。

**R2（失败时清理不完整，A4）：** processes.py 多个 finally 只 kill 而不 wait/communicate；`test_two_processes_create_exactly_one_first_account` 的 spawn 循环在 try/finally 外，第二次创建失败可遗漏首个进程；普通成功路径也没有检查子进程退出码或正确 drain/close 管道。修复统一有界清理，从首次创建即纳入 finally，确保异常/超时退出临时目录前所有子进程已退出并被回收。补充一个能观察失败路径的必要回归，不能只靠成功路径测试。

**R3（报告证据不成立，A8）：** RESULT 将修复前 patch filelock.FileLock.acquire 但 OSError 未抛出，解释为“原实现锁失败回退无锁建号”。原实现使用 fcntl，并不调用该 patched 方法，该断言失败只能证明测试没有作用于旧锁路径；现有证据不能支持无锁回退结论。保留真实导入阻断/缺失超时的证据，纠正该归因。统一跨进程预期：正常竞争要求 [201,401]，专门忙锁场景才是 503。如没有 Windows 实测继续写 not_run，不得把 Linux 全绿当跨平台已验证。

本轮原始交付记录保留在执行者 RESULT/STATUS 中，Codex 不改它们。下一轮仅修复上述问题，正式实现和依赖无需扩大；round 2 完成后重新提交。

## 正式验收（task_id=MARLIN-P01, round=2）

reviewed_at: 2026-09-30T12:27:16+00:00
verdict: changes_requested
next_actor: ZCode，读取 TASK round 3 后执行限定收尾

Codex 独立检查两份完整新测试、tracked diff、新增/删除文件及实际 STATUS。accounts/views.py、requirements.txt 与 round1 的已验实现一致；验收开始到结束四个文件哈希稳定，无新业务路径、无删除、无 staged 修改，HEAD 未变。

独立复跑：TASK 六模块联合 71 tests / OK（27.802 秒），退出0；迁移图完整性1 test / OK，退出0。白名单环境、独立临时库、Neo4j/Langfuse禁用，无根目录 .env/db.sqlite3/media/.cache。git diff --check通过。Windows native execution: not_run。

已解决：R1锁文件残留假设已删除，符号链接skip已独立；R2子进程正常退出码、管道、有界回收、第二次创建失败清理均有代码与实际运行证据；R3旧实现无锁回退的错误归因及201/401/503场景已纠正。主体实现无新增阻断项，不要求扩大或重写。

仅余以下两项，下一轮禁止扩大：

- R2a：accounts/test_auto_setup_portability.py::test_distinct_databases_do_not_block_each_other 仍连续 acquire A/B 后才 release，没有 finally/context。第二次获取失败会跳过A的显式释放，未满足 round2 TASK 的明确条款；RESULT声称显式锁均已保护也不准确。改为嵌套context或可靠finally，保持真实不同数据库锁独立语义，不增加测试模块。
- R2b：accounts/test_auto_setup_processes.py::test_wait_overrun_terminates_and_reaps_stuck_child 没有触发等待超时，只启动持锁子进程后主动_shutdown。其真实证据是主动清理一个仍存活的进程，不是超时分支验证。允许最小修复为改名/docstring/RESULT使其准确描述主动清理；已有中途spawn失败回归满足本任务最少一个失败路径的条件，无须为此再增加超时测试。也可在现有测试真实触发短超时，但禁止为凑证据大改helper。

这是已批准测试契约和证据一致性的收尾，不是新的产品范围。round3仅需独立复跑三个accounts模块；迁移、恢复、SSE主体未变，不重复扩大回归。

## 正式验收（task_id=MARLIN-P01, round=3）

reviewed_at: 2026-09-30T12:33:58+00:00
verdict: passed
next_actor: ZCode，读取 MARLIN-P02A / round1

独立确认R2a双锁已用嵌套try/finally管理，第二次获取失败也释放第一把；R2b已准确改名为主动清理仍存活子进程，RESULT明确未触发等待超时kill分支。accounts/views.py和requirements.txt保持round1实现；全部工作区变更、新增文件、删除/staged清单均已核对，无越界变更。四文件验收前后哈希稳定。

Codex独立运行三个accounts模块：20 tests / OK（26.295秒），退出0，Django system check无问题，未跳过测试。白名单环境/独立临时库/外部集成关闭；根目录无.env/db.sqlite3/media/.cache。git diff --check通过、无staged、无删除；未提交/推送/合并/发布。round2独立71项与迁移图检查仍为有效回归证据，本轮仅改测试清理和命名，不重复其它模块。

P01完成内容：首次初始化去除模块级fcntl阻断，SQLite按数据库身份使用FileLock互斥，10秒有界等待及503/setup_busy；真实跨进程唯一建号、异常回滚/重试、退出后交接和子进程失败清理得到定向证据。Windows native execution: not_run，不能据此宣布Windows交付或总体项目完成。完整桌面运行、打包、后续商业化/容量/高可用仍属后续阶段。

正式交付SHA256：
- accounts/views.py: a6c241180c83a7afa2493e7827ae85aff177eb0b99c8a041856eab364558632f
- requirements.txt: b5432b4fb55a9b79463a53d0fea21d32b8776f91a684f670cb5b69465ebbd0c3
- accounts/test_auto_setup_portability.py: cef757cd9bcb49a2879d377a31530507dd7d18d5ad408620f5f2fa80c7fd3e65
- accounts/test_auto_setup_processes.py: b12599687f0c42279bff88835d170720429c6be34b15ac8794bd214318a8fadf

Codex决定进入MARLIN-P02A / round1，仅三处剩余fcntl兼容和对应测试。通过P01不授权ZCode自行扩展后续阶段；新范围以TASK为准。
