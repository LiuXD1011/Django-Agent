task_id: MARLIN-P02A
round: 1
updated_at: 2026-09-30T12:53:56+00:00
workspace_realpath: /home/liuxuedeng/orca/workspaces/Django-Agent/marlin
branch: prep-desktop-commercial-release
base_head: afa7e0138f9fbad80e80aa4ead6f1d80af0145da

# 当前任务：剩余运行时文件锁的Windows兼容

approval_status: superseded_by_orca_dispatch
owner: Codex
executor: 桌面 ZCode
coordination_state: file_handoff_retired
codex_session_state: orca_coordinator_active
next_actor: Orca Task/Dispatch 对应执行者；此文件不得再触发执行

## 协作机制迁移（task_id=MARLIN-P02A, round=1）

记录时间：2026-09-30T12:53:56+00:00。用户已确认旧桌面ZCode停止写入；产品仍Windows优先，只将协作改为Orca orchestration。下方内容保留为历史技术计划，不再是文件派发许可。后续只接受Orca实际注入preamble和当前Task/Dispatch，禁止恢复本文件的旧Goal轮询/审批流程。已批准技术范围保留，执行须由Orca新任务明确承接；不因旧STATUS仍working自行恢复编辑。
当前Orca Run：run_c0d51a93432f；只读评估Task：task_6a5a296d43ba。P01/r3验收仍有效。本迁移不修改ZCode的STATUS/RESULT，不声称其陈旧状态已自动改变。

## 当前任务与证据

P01/r3已passed，详见REVIEW末尾正式验收；当前仅批准P02A/r1。REVIEW顶部仍指被验收的P01/r3，与新TASK不同是阶段交接，不是要求等待旧轮重验。首先核对真实路径/分支/HEAD及TASK/DECISIONS，再原子写STATUS task_id=MARLIN-P02A、round=1、working并确认新范围，才能修改业务文件。

实际代码仍有三处fcntl：model_rate_limit.py模块级导入和_bucket_lock、open_rag_benchmark.py::open_rag_prepare_lock函数内导入、scripts/local_services.py::ensure_langfuse函数内导入。第一处在模型调用时动态进入，第二/三处影响评测准备/本地启动；不能以URL能导入推定它们已兼容Windows。

## 起点与保护

P01已验收的四个改动继续保留，禁止回滚/重写：
- accounts/views.py: a6c241180c83a7afa2493e7827ae85aff177eb0b99c8a041856eab364558632f
- requirements.txt: b5432b4fb55a9b79463a53d0fea21d32b8776f91a684f670cb5b69465ebbd0c3
- accounts/test_auto_setup_portability.py: cef757cd9bcb49a2879d377a31530507dd7d18d5ad408620f5f2fa80c7fd3e65
- accounts/test_auto_setup_processes.py: b12599687f0c42279bff88835d170720429c6be34b15ac8794bd214318a8fadf

其余当前业务文件应与base_head一致。发现不明改动先报告，不reset/clean/stash。无凭据读取、真实外部调用、真实Docker启动或安装包发布。

## 本轮允许路径

主体仅：
- personal_knowledge_base/model_rate_limit.py
- personal_knowledge_base/open_rag_benchmark.py（仅锁上下文相关，不改评测算法/数据集/下载）
- scripts/local_services.py（仅锁集成及必要的超时映射，不改启动产品策略）

测试可在以下既有文件补充必要用例，或新增一份集中测试 personal_knowledge_base/test_runtime_lock_portability.py；不要为形式全改：
- personal_knowledge_base/test_llm_providers.py
- personal_knowledge_base/test_open_rag_benchmark.py
- personal_knowledge_base/test_settings_thinking.py
- personal_knowledge_base/test_langfuse_access_regressions.py

另允许ZCode自己的STATUS/RESULT、忽略的graphify产物及OS临时测试数据。requirements/P01四文件/模型迁移/前端/配置/其它目录不改；需要范围变化先waiting_approval并给唯一request_id。

## 方案和验收标准

A1. 复用已声明filelock>=3.13,<4，不增加依赖。三处在fcntl不可导入时应能导入且实际进入对应功能路径；用新子进程阻断fcntl的探针给证据，不只搜索文本。不能mock掉待验锁本身、静默无锁、改第三方库或强制SoftFileLock。

A2. 模型限流保留原key/缓存锁位置/0600权限意图及数据库事务、补充速率、blocked_until行为。相同key跨进程互斥，不同key不互相串行；关键区异常/进程退出后可获取。保留原阻塞获取语义，本轮不设计分布式限流/新超时API。锁获取错误必须阻断关键区，不能fallback执行；不改变无限token等待策略，此策略作为后续可靠性检查项。

A3. Open RAG保留.prepare.lock资源位置和contextmanager返回布尔语义：blocking=False在已被独立进程持有时及时yield False，不误入保护的修改；blocking=True等待释放再yield True。返回/异常都释放，下一持有者可进入。验证实际open_rag_prepare_lock函数的争用；不把裸FileLock独立测试充当业务集成证据。原有评测算法/缓存数据保持不变。

A4. Langfuse保留disabled/external早退、missing_server_configuration、compose_failed、healthy和既有失败状态。锁争用纳入原有同一个monotonic启动deadline，不能在锁后重置整段时间；争用到期返回startup_timeout且不调用Docker；释放后正常路线用mock Docker/HTTP验证。FileLock Timeout不要被一般except错误映射成startup_failed。所有测试禁止真实启动容器或联网健康检查。

A5. 测试以行为/再次获取/数据结果为准，不断言锁文件释放后保留。跨进程测试用真实独立子进程，所有创建/失败/超时路径有界回收并drain/close管道；资源用context/finally。时间断言有宽裕CI容差，数据与cache路径全部在临时目录。不要复制大段框架或人为增加冗余测试；覆盖关键分支所需最小集即可。

A6. 保留现有锁语义之外不做产品/架构扩展。先运行/记录对应现有离线基线，再用必要测试暴露三处Windows导入/执行阻断，修复后给真实命令/退出码。Windows native execution仍未跑则明确not_run；fcntl阻断probe不等于原生Windows通过。P02后续再处理完整本地运行/打包，本轮不安装Windows工具链。

## 回归与隔离

新测试按实际文件/类运行，并至少运行：

```bash
python manage.py test personal_knowledge_base.test_llm_providers personal_knowledge_base.test_open_rag_benchmark personal_knowledge_base.test_settings_thinking.LocalStartupTests personal_knowledge_base.test_langfuse_access_regressions.LangfuseConfigurationRegressions --noinput --verbosity 1
```

先检查这些用例的隔离条件：独立临时DJANGO_DB_PATH/BASE_DIR或等效缓存路径、白名单基础环境、根目录无.env、LANGFUSE_ENABLED=false、LANGFUSE_AUTOSTART=false、NEO4J_ENABLE=false；专项启用启动行为仅在mock subprocess/HTTP和临时假配置内。不可读真实.env.langfuse，不运行真实模型/下载评测语料。新增测试与以上模块可以合并一次执行，无须无变化重复P01/迁移/全仓测试。

按AGENTS先graphify query查询实际代码关系，修改后graphify update .。git diff --check，记录新增/删除清单、依赖实际版本和跳过项。若基线不通过，报告具体失败及是否与本任务有关，不能擅自改其它模块。

## 持续协作规则



- Codex 只写 TASK.md、DECISIONS.md、REVIEW.md；ZCode 只写 STATUS.json、RESULT.md 及本轮批准业务文件。同一时间只由 ZCode 改业务文件；Codex 负责只读检查和停止写入后的独立验收。
- 不使用 Orca orchestration，不自动启动/控制 ZCode，不另派业务执行代理。
- 所有协作记录包含 task_id、round；审批请求使用全局唯一 request_id，例如 MARLIN-P01-r2-REQ-001。回复对应 ID 且 decision 为 approved/rejected/needs_user。只执行当前任务/当前轮获准内容；旧轮决定、沉默、缺文件或超时不代表批准。
- 协作文件使用同目录唯一临时文件 + flush/fsync + 原子替换；不原地截断，不覆盖对方文件。执行前核对跨文件 task_id/round；不一致时暂停受影响操作。
- 状态仅用 working、waiting_approval、ready_for_review、failed。保留请求和已处理 ID 历史；轮次变化时保留必要旧轮证据，不把它记为本轮新结果。
- 不写入密钥/令牌/个人数据/带凭据 URL；不使用真实凭据，不运行外部付费调用。
- 总体目标内技术选择由 Codex 决定。扩大总体范围、不可逆删除、付费、凭据使用、生产变更、对外发布需用户明确确认。
- 未经用户确认不提交、推送、合并、发布；不切分支/worktree，不修改用户数据。
- 活跃会话可每30～60秒检查协作文件，不因未更新重复派发。当前没有独立后台定时唤醒服务；Codex本次答复结束后停止检查，需用户转发“继续读取协作文件”恢复。



## 交付、会话结束与恢复

STATUS保留路径握手字段、task_id/round、phase、updated_at、requests/handled_request_ids、summary、business_writes_stopped、next_actor、resume_instruction。新请求例如MARLIN-P02A-r1-REQ-001，含question/proposed_solution/impact/waiting_on/affected_paths；仅执行当前任务当前轮对应approved决定。

完成先原子写RESULT（保留P01结论为历史），再STATUS ready_for_review/business_writes_stopped=true，停止修改。ZCode Goal活跃时只读等待Codex验收，不自行开始其它阶段；单批完成不等于总体完成。

本次Codex答复结束后不后台轮询，未创建自动调度。下一负责人ZCode执行P02A；有审批请求或交付后，用户向Codex转发“继续读取协作文件”。若ZCode也已结束，用户向ZCode转发同一句恢复。沉默/超时不代表批准，不能因对方未醒重复派发或越界工作。

## 后续路线（未授权）

P02后续：Windows原生运行、可写数据目录、回环监听/静态资源、首次使用及进程生命周期；P03：worker恢复/租约竞争/SSE和限定并发验证，SQLite不宣称多节点HA；P04：证实无用文件清理、构建打包/备份升级、依赖及数据集许可证盘点和商业化缺口。本次检查发现评测注册测试声明CC-BY-NC-4.0，仅记为后续授权边界核验线索，不在本轮改数据集或作商用可用结论。
