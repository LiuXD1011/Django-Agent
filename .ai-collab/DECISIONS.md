task_id: MARLIN-P02A
round: 1
updated_at: 2026-09-30T12:53:56+00:00
workspace_realpath: /home/liuxuedeng/orca/workspaces/Django-Agent/marlin
branch: prep-desktop-commercial-release
base_head: afa7e0138f9fbad80e80aa4ead6f1d80af0145da

# 技术决定与审批记录

owner: Codex
current_task: MARLIN-P02A / round 1
next_actor: Orca 编排；历史文件审批机制停用

## 初始化决定 INIT-001（task_id=MARLIN-P01, round=1）

来源：用户总体授权和 Windows 优先答复；这不是对某个 ZCode 请求的回复，当前尚无 request_id。
结论：当前 TASK 的批准范围可实施，其它阶段仅为计划。

选型：
1. 采用轻量的成熟跨平台原生文件锁，保留现有数据库事务和锁资源标识。改动小，可以沿用当前初始化流程；代价是增加一个显式依赖。选此方案，首选 filelock。
2. 自行封装 fcntl/msvcrt 的双平台锁：减少依赖，但必须维护平台细节、超时和异常恢复，本轮不选。
3. 为初始化重构 SQLite 事务或新增协调表：牵涉 Django 事务和迁移范围，本轮不选。

批准边界：仅 TASK 中路径和 A1～A8 行为；允许公开依赖在隔离环境安装，不使用凭据；不放宽 ALLOW_AUTO_SETUP，不绕过互斥，不添加桌面壳、服务数据库或新的队列。

现有环境 filelock=3.13.1 只是本机发现，不代表项目已直接声明、版本已选定或 Windows 已验证。ZCode 需报告依赖约束与实际验证版本，不能把 latest 文档中的新功能当作旧版本已有能力。

技术参考（已查阅，适用性仍以所选版本及实测为准）：
- Python 官方 fcntl 可用平台说明：https://docs.python.org/3/library/fcntl.html
- filelock 官方跨平台/进程同步说明：https://py-filelock.readthedocs.io/en/latest/
- Django 5.2 SQLite 并发限制：https://docs.djangoproject.com/en/5.2/ref/databases/#sqlite-notes
- Django 5.2 部署要求：https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

## 请求处理规则（task_id=MARLIN-P01, round=1）

当前没有 ZCode 请求；不要制造“默认批准”记录。

之后每条回复必须包含：task_id、round、request_id、decided_at、decision（approved / rejected / needs_user）、reason、execution_boundary。对应 ID 不存在、当前任务/轮次不匹配的决定不能执行。

Codex 对范围内技术取舍负责；超出总体范围、不可逆删除、付费、凭据使用、生产变更或对外发布必须 needs_user 并向用户请求明确答复。在答复前保持受影响操作暂停，不能按超时批准。

批准文件不能单独授权未发布的新阶段；如果边界变化，Codex 同步更新 TASK，并要求 ZCode 重新核对当前任务/轮次。

## 结束/恢复记录（task_id=MARLIN-P01, round=1）

当前等待用户首次启动 ZCode；Codex 不在会话结束后继续轮询。ZCode 产生请求或交付后，由用户对 Codex 说“继续读取协作文件”。Codex 重新读取 TASK、STATUS、RESULT 及本文件后处理，不重复派发旧任务。

## 协作状态更新（task_id=MARLIN-P01, round=1）

记录时间：2026-09-30T11:38:34+00:00。路径握手已通过；ZCode 当前 working/path_verified，暂无审批请求。该记录是状态确认，不是新增批准，当前 TASK 范围不变。下一步负责人为 ZCode。Codex 会话若结束，需要用户在有请求或交付时转发“继续读取协作文件”；不在后台监督。

## 当前会话轮询（task_id=MARLIN-P01, round=1）

记录时间：2026-09-30T11:44:43+00:00。用户询问后台轮询；当前可执行方式为 Codex 保持本会话活动，每约 45 秒读取 STATUS/RESULT，收到 waiting_approval 后按 request_id 决定，收到 ready_for_review 且停止业务写入后独立验收。未配置退出会话后运行的定时调度，也不启动/控制 ZCode。文件未更新不重新派发任务，旧轮决定不能作为本轮批准。

当前状态仍由 ZCode 的 STATUS 为准。轮询只在本会话运行期间有效；若会话结束或中断，下一步由 ZCode 继续当前任务，有请求或交付后请用户向 Codex 发送“继续读取协作文件”。遇到 needs_user 时等待用户明确答复。

## 返工轮次发布（task_id=MARLIN-P01, round=2）

记录时间：2026-09-30T12:04:46+00:00。round 1 正式验收为 changes_requested，独立 68 项测试通过，但存在 REVIEW 正式验收 R1～R3 所列问题。批准 ZCode 按新 TASK round 2 修复两份新增测试并纠正自己的交付证据；不扩大产品目标、不新增依赖、不修改初始化主体或其它业务模块。此为 Codex 发布返工轮次，不是对 ZCode request_id 的回复；当前无审批请求。

轮次规则：round 1 的 ready_for_review 仅表示上一轮交付；ZCode 必须先将自身 STATUS 原子更新为 round 2/working 并确认当前 TASK 后再动文件。完成后先 RESULT 再 ready_for_review，停止修改。若桌面会话已结束，用户需对 ZCode 发送“继续读取协作文件”；Codex 不启动或控制 ZCode。

## 会话交接更新（task_id=MARLIN-P01, round=2）

记录时间：2026-09-30T12:05:30+00:00。用户明确确认 ZCode 已结束本次会话；其 STATUS 仍为 round1/ready_for_review，未确认 round2。Codex 已完成 round1 独立验收并发布 round2，但协作文件不能自动唤醒 ZCode。当前停止空等轮询，未建立任何独立后台调度。下一步负责人：用户向 ZCode 转发“继续读取协作文件，执行 MARLIN-P01 / round 2”，ZCode 确认新轮次后执行。后续有请求/交付时用户向 Codex 转发“继续读取协作文件”；不重复验收旧 round1，不重复派发任务。

## Goal 启动后的恢复（task_id=MARLIN-P01, round=2）

记录时间：2026-09-30T12:11:26+00:00。用户已确认在 ZCode Goal 模式重新启动。Codex 恢复本会话内约45秒间隔的轮询，当前尚待 ZCode 将 STATUS 从 round1 交付更新为 round2/working。上一条“等待用户唤醒/停止空等轮询”记录已成为历史。当前下一负责人为 ZCode：确认最新 TASK 后执行 round2。每轮交付停止业务修改，若 Goal 仍运行则继续只读等待 Codex 的验收和新轮次，单轮交付不等于总体完成。当前没有创建任何独立于会话的后台定时服务。

## 收尾轮次发布（task_id=MARLIN-P01, round=3）

记录时间：2026-09-30T12:27:16+00:00。round2独立71项及迁移图通过，剩余REVIEW R2a/R2b两处测试清理/证据一致性问题。批准按TASK round3最小修复；优先用context可靠释放双锁、将主动清理测试准确命名，不要求新增测试。主体实现/依赖保持不变。当前无ZCode请求，此记录为Codex任务发布，不是审批请求答复。

## 新阶段发布（task_id=MARLIN-P02A, round=1）

记录时间：2026-09-30T12:33:58+00:00。MARLIN-P01/r3 passed，独立20项通过，前轮71项与迁移图通过。按总体Windows优先授权发布当前TASK，处理model_rate_limit._bucket_lock、open_rag_prepare_lock、scripts.local_services.ensure_langfuse的剩余fcntl依赖。复用已声明FileLock，保留每处阻塞/非阻塞/统一启动截止时间语义，无新依赖、无迁移、无桌面壳或外部服务实际启动。这是Codex技术决定和任务发布，无对应ZCode请求，不制造request_id。

会话交接：当前未配置独立后台轮询/定时唤醒；本次Codex答复结束后不继续检查文件。下一负责人ZCode执行已批准P02A；收到请求或交付后，用户向Codex发送“继续读取协作文件”。ZCode若Goal仍运行，可只读等待审批/验收；缺失新决定不得视作批准。用户关于轮询token的咨询不授权创建付费调度或控制桌面应用，本次未创建此类服务。

## 协作机制迁移（task_id=MARLIN-P02A, round=1）

记录时间：2026-09-30T12:53:56+00:00。用户已确认旧桌面ZCode停止写入；产品仍Windows优先，只将协作改为Orca orchestration。下方内容保留为历史技术计划，不再是文件派发许可。后续只接受Orca实际注入preamble和当前Task/Dispatch，禁止恢复本文件的旧Goal轮询/审批流程。已批准技术范围保留，执行须由Orca新任务明确承接；不因旧STATUS仍working自行恢复编辑。
当前Orca Run：run_c0d51a93432f；只读评估Task：task_6a5a296d43ba。P01/r3验收仍有效。本迁移不修改ZCode的STATUS/RESULT，不声称其陈旧状态已自动改变。

