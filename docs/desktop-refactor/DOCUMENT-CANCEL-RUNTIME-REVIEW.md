# 文档取消运行时独立审查

2026-10-12，只读审查阶段 3 工作区源码；阶段 2 比对依据为 [源码冻结记录](../refactor-evidence/20261012-root-query-source-freeze.json)，SHA-256 `7cea0aeb8edd34b7ffe5d99763c6fc8eed495b68bc644c041ee2b545490c76df`。Git HEAD 并非阶段 2 源码快照。根任务负责修复和最终整合，本审查未编辑产品源码，也未运行全套测试、构建、GUI、用户数据库或模型请求。

已完整阅读根任务指定的 runtime 文件、桌面 IPC/fork 边界、新增回归，并核查实际 JobQueue、AttemptControl、DocumentWorkflow、AuthReader 和路由接口。[取消设计](DOCUMENT-CANCEL-COMMIT-DESIGN.md)仍是设计依据；文件哈希和审查范围见[独立证据](../refactor-evidence/20261012-document-cancel-runtime-review.json)。以下行号对应该证据中的初次审查快照，后续修复可能移动行号。

| 等级 | 位置 | 触发条件与后果 | 最小修复与回归 |
| --- | --- | --- | --- |
| P1 | `desktop-process.ts:72–84`，交界 `owner-client.ts:290–300`、`desktop/runtime.cjs:209–210` | 真实取消 CAS 后调用方 abort。CoreOwner 的公开 Promise 立即 reject，但内部控制槽仍等 owner durable ACK；fork 此时发送普通错误 response 并删除请求，Electron 据此提前释放 8 个取消槽。连续中止可占满内部 waiter/控制容量，后续取消遭到 429。 | 为可信 Node 提供精确取消 lifetime 的终态等待；fork 在 transport 终态回复和删除 control lifetime 前等待真正 ACK、owner fault 或已封准入的 close 清理。真实 INSERT 暂停期间 abort 后仍保持 8 槽，释放后逐层清理。 |
| P2 | `owner-client.ts:318`，交界 `workflow.ts:243–253` | Query 已授权快照发现旧 file 无 workflow_job_id，随后同文档 reparse 创建并 claim 新任务。旧取消回退 owner 普通 route，重新选择最新 currentAttempt，误取消授权快照之后出现的新任务。 | 同一个认证读取快照直接投影原无任务 DTO，作为无副作用终态回复；禁止回退按文档重新选任务。真实 Query snapshot barrier 后创建/claim 新任务，再释放旧取消，证明新任务保持 ACTIVE 并最终完成。 |
| P3 | `query-dispatcher.ts:52` | parser 未配置且调用方未登录。新增 preflight 在 authenticate 之前返回 503；原 Application 先认证并检查 read，再由 route 返回 parser 503，原结果为 401。 | 在同一快照先认证及 read 校验，然后执行 parser 检查；覆盖未登录 401、已登录 503。 |
| P3（补充） | 初版 `readCancelProjection` 的 `json_quote(json_extract(...))` | JSON true 被 SQLite 投影成数字 1，取消无任务 DTO 的 status 变为 `'1'`，原 JavaScript 转换得到 `'true'`。正常生成的字符串状态不受影响。 | 核查实际 native SQLite 后采用 `metadata -> '$.workflow_status'` 文本 JSON 投影；真实 scalar/array/object/null 回归保留原 `String(x || parse_status)` 语义。 |

根任务已核查并接受 P1/P2，正在独立编写真实 RED 和产品修复；本次记录不将待修复问题记为通过。P2 的新增真实回归由本代理按根任务再次授权编写，仅拥有新的 `core-owner-no-job-cancel.test.ts` 与必要新的 `*no-job*` fixtures。

2026-10-12 最终补充：根任务已修复上述四项，本代理已复读实际补丁和原始 TAP，无新增具体缺陷。`CoreOwner.waitForCancellation` 保守等待当前所有同外部 requestId 的控制 lifetime；caller abort 不 settle，owner ACK、fault、send 失败和已封准入的正常 close 均清理 lifetime。桌面 fork 在错误回复前等待该 lifetime。无任务 DTO 直接来自同一认证快照，owner 不再回退选择未来任务；parser 检查回到鉴权之后；文本 JSON 投影保留布尔、数组、对象和空值的原转换。

P2 真实回归由本代理先执行：首次夹具交付顺序失败不计业务 RED，保留[原始日志](../refactor-evidence/20261012-core-owner-no-job-cancel-red.tap)；修正 Atomics 通知早于 MessagePort 交付的测试等待后，[业务 RED](../refactor-evidence/20261012-core-owner-no-job-cancel-red-business.tap)真实显示未来 claim 从 ACTIVE 变成 CANCEL_REQUESTED，`1 !== 0`。三项新测试/夹具随后冻结，产品修复由根任务执行。[主任务复测](../refactor-evidence/20261012-root-cancel-no-job-green.tap)包含该竞争用例及 preflight，共 5/5 通过；该竞争用例 subtest 为 7798.578ms，整个 TAP 为 10802.714ms。它证明未来真实 Python/分块/发布任务完成、完整正文保留且零模型调用，不构成性能百分位测量。

其他已核验根任务日志：[真实 fork RED](../refactor-evidence/20261012-root-desktop-cancel-abort-red.tap)为取消槽 `0 !== 8`，[GREEN](../refactor-evidence/20261012-root-desktop-cancel-abort-green.tap)为 1/1；[认证顺序 RED](../refactor-evidence/20261012-root-cancel-auth-order-red.tap)为 `503 !== 401`，[GREEN](../refactor-evidence/20261012-root-cancel-auth-order-green.tap)为 4/4；[状态转换 RED](../refactor-evidence/20261012-root-cancel-no-job-coercion-red.tap)为 `'1' !== 'true'`，[GREEN](../refactor-evidence/20261012-root-cancel-no-job-coercion-green.tap)为 5/5。全部日志均无 skip/cancel，且本代理没有重复执行这些根任务检查。最终源码哈希、冻结测试和日志哈希见[补充冻结证据](../refactor-evidence/20261012-core-owner-no-job-cancel-evidence.json)。根任务仍负责最终绑定源码的 typecheck/build/domain/runtime/Desktop 整合与真实 GUI。

其余已读边界未发现新增具体缺陷：Query 的授权回调与 registry CAS 位于同一 coordinator 消息 turn，保留 authority epoch/ticket/signal 检查；凭据优先级、selectedTenant、16 个 GET 白名单和 IPC auth_mode 保持现有语义。真实 payload/租约/当前文档指针用于精确取消；queued intent 仅绑定下一 claim，旧 unregister 不能移除重试代次。caller abort 不释放 CoreOwner 内部控制槽；fault 失效共享 gate，正常 close 封准入并保留 owner 已决定的提交。SAB、claim ownerToken 和 AuthContext 未进入 renderer/fork JSON 协议。

这些结论是源码审查，不替代 Windows/Orca 真实取消、完整整合检查和性能验收。单条同步 SQLite SQL 不可被 SAB 抢占；未 ACK 的易失取消意图不等于 durable 取消；崩溃后的人工模型任务不得盲重放。共享 queue/pipeline/storage 仍由另一代理细化，最终文件冻结后需要根任务再次整合复核。
