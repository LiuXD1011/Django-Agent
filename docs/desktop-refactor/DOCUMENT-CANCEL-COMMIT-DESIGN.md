# 文档发布取消与提交边界设计

日期：2026-10-12。Goal II.5 授权的只读调查；本轮只新增本设计和独立证据，没有修改产品、运行业务测试、访问实时用户数据、操作 GUI 或调用模型。阶段 2 与原知识只读抽取源码保持冻结。本文件描述待实现和待验证的阶段 3，不能作为取消功能通过的证据。

## 核实的根因与实际路径

当前原生路径是 renderer `api.cancelKnowledge(doc.id)` → Electron 的受校验 `marlin:invoke` → `desktop/runtime.cjs` 的 JSON fork → `tools/desktop-process.ts` → `CoreOwner.invoke` → owner Worker 的 `runCoreOwner` → `CoreIpcAdapter` → `CoreApplication.dispatch` → `POST /api/v1/knowledge/:id/cancel-parse` → `DocumentWorkflow.cancel`。浏览器路径是原 HTTP 同源/CSRF/凭据校验 → `CoreOwner.dispatch` → 同一 owner、路由和 workflow。

这个 POST 未进入阶段 2 的精确 GET allowlist。`Workflow.cancelJobs` 调用 `JobQueue.cancelByRequest`，先写取消终态再 abort 当前 execution；但 owner 正在同步 SQLite 发布时不能处理这条消息、任何 JS timer 或 AbortSignal 回调。`async publish_local` 最终调用的仍是同步 `JobQueue.publish` → `CoreDatabase.transaction().immediate()`。

| 源码证据 | 实际影响 |
| --- | --- |
| [document-routes.ts](../../packages/core/src/adapters/document-routes.ts)，cancel-parse 注册 | 业务取消是 owner 路由；不使用 transport `abort` 代替。 |
| [queue.ts](../../packages/core/src/jobs/queue.ts)，`publish` 88–94 行 | 目前只在 work 前重验 running/attempt/ownerToken/lease，没有可由外线程改变的共享取消状态和提交仲裁。 |
| [pipeline.ts](../../packages/core/src/documents/pipeline.ts)，`publish_local` 184–228 行 | 同一事务删除旧块/FTS/向量引用、插入新块/图像、更新正文来源及 FTS。取消必须让这个完整事务回滚。 |
| [workflow.ts](../../packages/core/src/documents/workflow.ts)，251–256 行 | 没有活动任务也会写 workflow_status=cancelled；迟到取消可以把 completed 文档改成 cancelled。 |
| [workflow.ts](../../packages/core/src/documents/workflow.ts)，246–249 行 | 取消 spans 目前仅约束 job_id，缺 queue_attempt；新精确取消路径必须同时约束 attempt。 |
| [pipeline.ts](../../packages/core/src/documents/pipeline.ts)，393–396 行；[queue.ts](../../packages/core/src/jobs/queue.ts)，149–150 行 | doc/task_records completed、root/progress 和 desktop_jobs completed 分多个事务；新的完成边界应统一发布，避免已完成文档与仍运行 job 的竞态。 |
| [desktop/runtime.cjs](../../desktop/runtime.cjs)，157–160 行 | 外部 fork 使用 serialization=json。SAB 只能在这个核心子进程的 coordinator ↔ owner/query Worker 间共享，不能穿过 Electron/fork。 |

现有 [bulk publication 回归](../../packages/core/test/document-bulk-publication.test.ts) 包含真实中间 INSERT 故障及外层 COMMIT 的延期 FK 故障，但 cancel 分支在 parser 返回前发起，不能证明发布中取消。[WAL publication 回归](../../packages/core/test/core-owner-read-publication.test.ts) 持有真实 SQLite 事务并跨 Worker 等待，证明 GET 可读旧版本；它使用 fixture 路由，不是文档取消测试。现有 [workflow 回归](../../packages/core/test/document-workflow.test.ts) 的真实 Python 子孙进程取消、付费不明结果、重解析保留旧来源均须保留。

## 私有取消预检和精确 attempt 登记

建议保留现有 POST、请求/响应 envelope 和两种 transport。`CoreOwner` 只对规范化后精确匹配的 `POST /api/v1/knowledge/:id/cancel-parse` 执行特殊内部路径，不扩大 GET allowlist，不接受 renderer 的 SAB、SQL、AuthContext、ownerToken、worker URL 或 registry slot。HTTP 校验继续在原 adapter 执行；IPC options 继续按真实 API 校验，私有 access 从 coordinator session mirror 取，不交给 renderer。

新增 Query 内部 `cancel-preflight` operation，输入只包含可信绑定的 access/bearer/apiKey/selectedTenant、documentId、requestId、owner generation、authority epoch 和 deadline。它不是一个公开 GET，也不执行业务写入。Query 在同一个 deferred WAL snapshot 内：

1. 按现有 bearer → legacy bearer、apiKey、private access 的优先级重新 authenticate，执行现有 membership、session/revocation 和 selectedTenant 规则。
2. 用现有 `KnowledgeReadDomain.doc(ctx,id,'document.write')` 核查租户、未删除文档/KB 与写权限，禁止仅凭已展示的 DTO 授权。
3. 查询 doc 当前 workflow_job_id 对应的 process_knowledge job，核查 job tenant、payload tenant/knowledge_id/knowledge_base_id、未取消状态、running 的 attempt/ownerToken/有效 lease。queued 任务使用精确 jobId、attempt=0、claim=null 的独立 owner 分支，不假造 running claim。
4. 返回仅供可信 coordinator 使用的精确身份 tuple 与当前终态；不能把 claim/payload.auth/凭据包含在公开响应里。不存在当前任务时返回真实当前状态，不能把取消状态写到文档。

建议私有 tuple 为 `{ownerGeneration, jobId, attempt, ownerToken, tenantId, jobUserId, knowledgeId, knowledgeBaseId}`。保持原 document.write 权限语义：有权限的协作者可以取消该文档任务；jobUserId 由真实 job 确定，不改成任意 renderer 的 userId，也不新增“只有上传者可取消”的产品限制。“only own attempt”指写回、子进程清理及共享槽严格绑定这个 owner claim，不能覆盖别的 attempt。

在 Query 入队、执行前/后及 coordinator 接收结果时检查 owner 活着、generation/epoch 相同、无 pending authority mutation。coordinator 在处理预检结果的同一 JS message turn 中完成 epoch/ticket/registry 验证与 CAS，不能在验证与 CAS 之间 await。Query snapshot 中通过权限的意图在这个 CAS 处线性化；之后发生的 logout 不复活已经获准取消的 attempt。权限/epoch 变化在 CAS 前必须拒绝且不改共享槽。owner 的后续数据库写回仍重验精确 claim、document pointer/namespace；不得信任 caller AuthContext。禁止取消不存在的旧 attempt 后重新按 docId 找当前 attempt。

queued没有running claim，需单独保存有界private intent `{ownerGeneration,jobId,previousAttempt,tenantId,jobUserId,knowledgeId,knowledgeBaseId}`。owner优先处理时以status=queued/attempt=previousAttempt/claim=null取消；若owner已开始claim，则登记消息必须同时证明原queued previousAttempt到本次running previousAttempt+1的唯一转移。在registry ACK前匹配这个intent并取消这个全新SAB，handler不能先执行。它不能推广到之后的retry或新workflow_job_id。若预检snapshot恰好读到转移前queued版本，而registry已有这一次已ACKclaim，可仅对该经owner证明的唯一下一attempt CAS，仍不得找后续attempt。queued意图的成功也等待对应owner耐久终态ACK，不把内存reservation当取消完成。running预检没有匹配registry/owner generation时fail closed，不绕过登记执行任意数据库取消。

`JobQueue.run` claim 的 SQLite COMMIT 成功之后，owner 为真正的 running claim 生成一次性 SAB，并登记到 coordinator。建议 `attempt-register`/`attempt-register-ack` 私有消息；必须等待登记 ACK 后才调用文档 handler，尤其在第一次重活前。ACK 仅表示槽登记成功，不是业务成功。登记 tuple 来自 owner 当前 claim/DB payload，不能由请求体构造。传递 SAB 不放 transferList；每次 retry/new owner 都新建 SAB，不复用旧内存。

startup recovery 可能在 Application 构造期间启动 safe job，因此控制桥必须在构造 Application 前就准备好，作为可信本地 queue option 注入；coordinator 允许经过 generation 校验的登记早于 ready，但业务预检要等完整 bootstrap/query ready。不能构造完成后才“尽量”补登记。登记超时/关闭不能继续执行没有可取消槽的重活；走现有 safe/manual 的失败/中断规则，期间没有模型请求。

## 有界准入与生命周期

建议 registry 最多 64 个 running document attempts；不够时等待有界 claim 准入或返回可见 busy，不能丢失登记后继续跑。登记/注销、取消意图、终态 ACK 为独立有界控制通道，不排在普通 owner 64+64 SQL 请求队列后；注销只按完整 tuple 和 SAB 身份匹配删除。取消为同 tuple 合并的最多 8 个意图、每意图最多 8 个等待者；拒绝额外请求时不新增槽。Query 预检最多 1 active+8 queued，取得结果前按 deadline 失败不得触发 CAS。若复用现有单 Query Worker，priority 只能跳过未开始 GET，不能抢占一个已经同步执行的查询；其残余延迟要实测，不能承诺立即取消。

整个链路都必须保留取消容量。当前 `desktop/ipc.cjs`、`desktop/runtime.cjs`、`tools/desktop-process.ts` 都有 64 请求上限：正常请求占满时，业务取消 POST 在到达 CoreOwner 前就会被拒绝。最小策略是从既有 64/128 总预算中保留固定控制额度，例如每层 8 个取消槽（普通最多 56，所有仍最多 64），而不是无界突破上限；CoreOwner 对 registration/ACK 使用固定协议控制消息，对取消等待者仍计数。普通 transport cancel 只断开一个请求订阅，不能不经 document.write 校验就取消文档任务。

caller AbortSignal 在 CAS 前取消则不提交意图；CAS 后断开只取消响应等待，不能撤回已经获准的业务取消，也不能释放底层 attempt/意图槽到 owner 终态 ACK 之前。超时只结束等待，不回报 cancelled 成功；迟到 ACK 仍消耗并清理正确槽，不重复写。owner crash/close 立即停止新预检、清空可信 session/registry 入口、拒绝等待者；旧 SAB 和旧 generation 永久失效。close 可直接给已登记 ACTIVE 槽设置可信 shutdown 意图，随后等 owner 回滚和拥有的 descendants/Workers 实际退出；不以 terminate owner 模拟普通取消。

## 单原子字与局部/最终提交

每个 attempt 用一个 8 字节 BigUint64Array 原子字表示 `{publicationOrdinal,state}`，低 8 位为状态、高位为单调递增 ordinal。所有更新使用 BigInt CAS，不拆成先读 generation 后写 state 的两步，以免 ABA。ordinal 溢出时 fail closed；不同 ownerGeneration/attempt 的槽从不复用。可信 registry 以 tuple+SAB 引用绑定，renderer 看不到字或槽号。

| 状态 | 外线程取消行为 | owner 行为 |
| --- | --- | --- |
| ACTIVE(n) | CAS → CANCEL_REQUESTED(n) | 任一 checkpoint 抛 job_cancelled；正在进行的外层事务回滚。 |
| COMMITTING_LOCAL(n) | CAS → LOCAL_CANCEL_AFTER_COMMIT(n) | 保留当前提交资格；COMMIT 后停止后续阶段，保留刚发布的正文/FTS。 |
| LOCAL_CANCEL_AFTER_COMMIT(n) | 合并同意图 | native COMMIT 返回成功后持久化精确 attempt 取消；若 COMMIT 失败则旧 generation 保留。 |
| COMMITTING_FINAL(n) | 不改变字，等待真实终态 | 完成提交或真实失败；不能把“获得资格”冒充 completed。 |
| DONE / CANCELLED_DURABLE / FAILED / INVALID | 返回真实终态或失效 | 不再写 completed→cancelled；不可重新打开旧 attempt。 |

这里 ACTIVE→COMMITTING CAS 是**取消与本次提交资格**的线性化点，SQLite COMMIT 成功才是耐久数据结果，两者不可混用。局部 publish 返回后 owner 用 CAS 将 COMMITTING_LOCAL(n) 变成下一 ordinal 的 ACTIVE；若这时外线程先写 LOCAL_CANCEL_AFTER_COMMIT，则转成 CANCEL_REQUESTED，不能用 Atomics.store(ACTIVE) 擦掉取消。最终完成 CAS 成功后，后到的取消只等真实结果，不能改为取消，也不能触发 retry。

普通 `JobContext.publish` 保持同步 API。仅 running 文档 attempt 的业务 publication 采用 gate，计时 heartbeat/journal 与取消终态清理不应误用一个已经关闭的 business gate。外层步骤为：

1. 新 ordinal 的 ACTIVE，BEGIN IMMEDIATE，重验 owned、document.write、KB/当前 workflow_job_id。
2. 执行同步 work；在删除旧块、去重/预分配、插入批、图像、FTS 批边界检查共享取消，仍保留每个原权限/rowid/来源检查。
3. work 完成、拒绝 thenable 后，提交前再验 claim/文档范围/取消，CAS 本 ordinal ACTIVE→COMMITTING_LOCAL 或 FINAL。取消赢则抛 job_cancelled，完整 outer rollback。
4. 让当前 driver 实际 COMMIT。只有 `CoreDatabase.transaction` 整体返回才确认 durable；callback 返回或嵌套 SAVEPOINT RELEASE 都不能标 committed。
5. 捕获 COMMIT 失败并执行原 rollback/失败路径，绝不发布 DONE。局部 commit 已成功而取消要求停后续时，`pub` 不能在返回前伪装成 rollback；先返回已提交结果，使 pipeline 的 published=true/artifact 清理正确，再 abort 并持久化取消。最后 ACK 说明实际终态。

嵌套 publish/span/index/insertMany 的 SAVEPOINT 共用同一个外层 ordinal，不再次 CAS、更不提前 DONE。用显式 publication depth/当前 scope 管理；若受控 publication 的入口已经处于不由该 scope 拥有的外层事务，必须拒绝或把 fence 委托给真实 outer owner，不能把 nested return 当 COMMIT。通用 CoreDatabase.transaction 和 insert 返回契约不改；当前 better-sqlite3 实现是在 callback 返回后调用 commit/release，catch 再 rollback，现有 API足以在队列外层回调最后一行 CAS、在 transaction 返回后确认结果。

检查点只能在同步 `.run()` 调用之间工作，无法中断一个正在执行的 SQLite statement、同步读图像/hash 或大字符串处理。`insertMany` 已按 ≤900 bind 参数，FTS 已按 64 ID 分批；建议增加可选可信同步 checkpoint callback到这两个实际 batch 边界，保持字段验证、默认值、原子事务、稳定来源、64位 rowid 碰撞检查不变。不引入 async transaction、分批 COMMIT、第二写连接或付费模型 Worker。

## 最终完成与精确取消写回

建议新增一个 `JobContext.onOutcome(work:(outcome)=>void)`，每个 document handler 最多登记一次可信同步终态 publisher，outcome 是仅核心构造的 completed/cancelled/failed/interrupted、result/errorCode。completed分支登记当前最后的 doc/task_records completed、root span done、最终 progress；pipeline仍返回原 JSON result。Queue 在最后一个 outer transaction 内重验 claim、执行 completed publisher、记录 desktop_jobs result/completed 和 contiguous completed event，然后 FINAL CAS。全部在一个事务提交，取消赢则 doc/task/root/job 均不能假装完成。失败/取消分支用同一注册回调在它们各自的耐久终态事务中结束精确文档telemetry，不能借一次已取消的business gate写入。Queue 其他领域未注册 publisher仍保留原结果 API和语义。

这个失败回调是必要的：最终完成 publisher现在发生在handler Promise返回之后，其COMMIT失败不会再进入原 `DocumentWorkflow.handle` 的 Promise catch。必须由Queue terminal catch显式调用failed/interrupted publisher，否则会出现job failed而doc/task/root仍processing。completion事务的所有修改先rollback，再用同一claim重新核查并写失败终态；若取消或更新attempt已取得所有权则只按匹配的真实终态审计，不覆盖新attempt。

取消清理走专门的 owner 精确方法，例如 `cancelClaim(expected, outcomePublisher)`，不能把校验退化成 cancelByRequest(requestId) 或再遍历同 doc 的所有任务。SQL 同时约束 id/tenant/user/status/attempt/ownerToken，running 必须校验当前 lease；queued 同时约束 claim=null/attempt=0。在事务中仅实际改变这一 attempt 时记录一次 cancelled event，关闭本 attempt 的 desktop_job_steps、task_records、spans（job_id+queue_attempt）。文档 metadata 仅在 tenant/KB/当前 workflow_job_id 仍匹配时改变；有 processed_at 保留 parse_status=completed、已发布 content/source_generation/chunks/FTS/images。其余任务和旧历史不删除。不匹配的新 attempt 返回 superseded，不写任何新结果。

WORKFLOW 的 catch/finally、Queue 的 terminal catch 不能把共享取消当普通 stage_failed/document_processing_failed。先以同一 owner claim 结束取消 telemetry，再 abort 当前 execution/owned descendants 和纯 chunking Worker；最后等待它们真实退出和 pipeline cleanup完成才返回现有 cancelled 成功 envelope。最终 CAS 已获资格的任务若 COMMIT失败，回报实际失败并保留旧 generation，不把迟到 cancel 改当完成或取消。已 terminal 的 doc/job 直接返回真实状态，不调用无条件 metadata.cancelled 写入。

最终 onOutcome在 Queue执行时 pipeline 的临时目录/未引用artifact finally已经结束；本地已经提交的媒体与原来源须保持存活。最终完成 publisher只做同步数据库/telemetry工作，不能再次访问已删除workspace，也不能发模型请求。

## 重启与付费结果

SAB 不耐久，禁止把共享字作为启动恢复依据。取消成功 ACK 只能在 owner 的精确取消事务 COMMIT、handler/owned helpers 完成之后给出。建议先保持当前等待终态的 POST contract；不新增瞬时 200 cancelled或把 volatile CAS包装成耐久取消。

- cancel赢、尚未写 cancelled 就 SIGKILL：请求得到 owner_failed/未确认，不承诺已取消。SQLite回滚到旧完整generation；按现有lease等候和safe/manual恢复。manual仍 interrupted，不自动重发付费模型；safe可恢复，这不是一条“已经确认成功”的取消丢失。
- 已确认 cancelled 后重启：数据库 cancelled/cancel_requested_at阻止任何自动运行，旧SAB失效；同request重试读取同终态。
- local COMMIT后、取消终态前 crash：新正文/索引保留；剩余manual工作 interrupted；不虚构所有阶段完成。
- final COMMIT成功但ACK未送达：doc/task/root/job都已completed；重开读取相同结果，不因丢ACK回退或重放。若final COMMIT失败则全体回滚，故不能依据内存COMMITTING/DONE宣称完成。

若产品要求“CAS意图被接收就算耐久取消”，必须另设计安全的持久化意图日志及恢复协议；在owner持有写锁时，coordinator无法通过同一SQLite写者持久化。当前最小方案不引入文件日志或第二数据库写者，也不声称解决volatile意图未ACK的掉电耐久性。

## 文件归属建议和实现顺序

| 实施组 | 最小文件/API | 边界 |
| --- | --- | --- |
| root runtime协调组 | runtime/owner-client.ts、owner-host.ts、owner-contracts.ts、owner-worker.ts；新增 runtime/document-cancel-registry.ts | attempt register/ACK、private admission、epoch/CAS、终态 ACK、close/crash清理；Application只注入可信本地queue控制桥。 |
| Query鉴权组 | runtime/query-client.ts、query-contracts.ts、query-dispatcher.ts、query-worker.ts；新增 documents/cancel-preflight.ts | 同一只读snapshot认证+document.write+精确tuple；首批16 GET保持不变。不改AuthReader/ReadDatabase的权限和readonly初始化。 |
| queue/document组 | jobs/queue.ts；新增 jobs/attempt-control.ts；documents/workflow.ts、pipeline.ts | 注册实际claim、publication gate、同步completion publisher、精确取消审计、当前pointer保护、原付费策略和清理。 |
| batch检查点组 | storage/database.ts的insertMany可选checkpoint；retrieval/search-index.ts的indexKeywords可选checkpoint | 仅真实批次边界；不改通用insert/transaction、FTS语义或来源碰撞/namespace校验。需重新分配这两个阶段2冻结文件后再实施。 |
| 原生有界控制组 | desktop/ipc.cjs、desktop/runtime.cjs、tools/desktop-process.ts及必要纯请求分类helper | 在现有总上限内保留取消容量；继续JSON fork和真实窗口sender校验；无需传SAB或秘密到renderer。 |

先实现私有 tuple/控制字与真实SQLite取消回归，再接Query预检/registry/两种transport和最终completion，最后实测batch取消响应与Windows构建。以上只是文件归属建议，本任务没有实施，所有共享产品文件仍由原owner管理。

## 可执行的真实 RED/GREEN 路径

新增 `test/document-cancel-publication.test.ts` 与 `test/fixtures/document-cancel-publication-worker.ts`。真实 owner Application配置真实Python parser、CoreDatabase、SearchIndex、JobQueue、formal runCoreOwner。使用小Unicode文本先完成旧generation，再正式reparse；不开任何模型。fixture仅增加可控同步barrier，不覆盖workflow.cancel、publish、parser、db.transaction或index方法来制造成功。

1. **首个业务RED**：通过真实SQLite `function('fixture_publication_barrier', ...)` 和 `AFTER INSERT ON chunks` trigger，在替换事务已删旧块且已实际插入一批新块时设置SAB/Atomics.wait barrier。用真实CoreOwner HTTP/IPC cancel-parse POST；断言可信预检和CAS在writer阻塞期间完成、释放barrier后outer rollback、取消ACK、旧正文/块/FTS/邻接/图片哈希仍一致。现实现的具体失败应是取消只能等待owner/没有取消意图，而非missing module。deadline和finally barrier release防挂死。
2. **FTS后取消赢**：SQLite不允许给FTS虚拟表创建trigger，因此通过新可信publication检查点的仅测试observer，在实际`INSERT INTO chunks_fts`返回后设置barrier，记录该真实statement的changes/新FTS行数。observer只观察和等待，不替换index/db函数。CAS赢后整事务rollback，旧MATCH/短中文召回与注册rowid/vec引用/来源恢复、无running spans/steps。
3. **COMMIT资格赢**：测试only可信publication observer在FINAL CAS后、native COMMIT前用SAB阻塞；请求迟到取消，不得改原子字，释放后doc/task/root/job一次completed。同一fixture加真实延期FK trigger，确认COMMIT失败不会变DONE或completed，FTS/正文仍旧。observer只是barrier观察真实边界，不替换业务函数。
4. **local资格赢但workflow仍活跃**：local CAS后barrier中发取消，进入LOCAL_CANCEL_AFTER_COMMIT；COMMIT后正文/FTS保留，后续受控local HTTP provider fixture不应产生新请求，任务cancelled且无假rollback。若已发模型响应再取消，实际usage/未知结果记录保留，retry/recovery不自动重发。
5. **ownattempt与授权**：跨tenant/KB、reader角色、revoked会员、wrong selectedTenant、API key/bearer优先级、未登录、authority pending、预检后epoch变化都不能写SAB。A预检后B的新attempt/currentpointer取代，A意图只影响A槽，owner写回不得改B。原租户内有document.write协作者语义保留。
6. **生命周期**：registry未ACK不得启动handler；8-slot溢出、去重/等待者上限、64/128饱和仍留取消容量、caller abort前/后CAS、close、deadline、lateACK、owner失联均有bounded真实Worker断言。SIGKILL采用隔离fixture core子进程，自身SAB在其中共享；从外部kill已知fixture句柄，不按端口或进程名杀用户服务。
7. **重开SQLite**：SIGKILL分别发生于cancelCAS前后/rollback后取消COMMIT前/取消ACK后/final COMMIT后ACK前；核查durable原/新完整generation、精确attempt、manual不自动模型重放、外键一致。另保留真实Python owned descendant和纯chunking Worker的实际退出断言。

目标命令（待实现后执行，不是本轮已运行）：在 `packages/core` 执行 `node --import tsx --test test/document-cancel-publication.test.ts test/document-bulk-publication.test.ts test/jobs.test.ts test/chunking-workers.test.ts test/document-startup-recovery.test.ts`；相关workflow选择取消/付费/recovery用例，再 `npm run typecheck`。root统一整套、编译JS Worker/JSON fork/Desktop回归、Windows实际平台和真实Orca/native取消采样。每次保留RED与GREEN原日志，记录barrier所在真实SQL阶段和取消CAS→rollback/COMMIT→持久化ACK各自耗时；不用一次小fixture证明大文件P95。

本轮未解决：发布的SQLite CPU耗时、单条SQL不能中断、owner内provider timer/流仍受同步发布影响、Query active查询延迟、目标Windows原子/Worker/ABI实际行为、掉电时未ACKvolatile取消意图。阶段2页面读或health成功不能替代这些阶段3验收。

独立调查与输入SHA见 [design review evidence](../refactor-evidence/20261012-document-cancel-commit-design-review.json)。
