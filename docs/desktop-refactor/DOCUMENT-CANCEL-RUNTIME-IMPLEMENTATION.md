# 文档取消运行时实现与验收边界

2026-10-12。依据[取消提交设计](DOCUMENT-CANCEL-COMMIT-DESIGN.md)，使用同一 TypeScript 核心、真实 readonly SQLite、Owner Worker 和桌面 JSON fork；不连接 Django，不新增公共 SQL、AuthContext 或共享缓冲区入口。当前来源的Orca发布取消、发布读取及分页已有真实结果；最新Windows安装版及其他页面仍待完成。

## 授权与精确任务

原 `POST /api/v1/knowledge/:id/cancel-parse` 进入私有 Query 预检。认证、read/document.write 权限、文档/知识库命名空间、当前任务指针及实际 job payload/租约在同一个 native readonly snapshot 内检查。读取窄字段，不加载完整正文或 parser metadata。未配置解析器时保持先认证的原顺序。

Query 结果只向可信 coordinator 提供完整 job、attempt、ownerToken、tenant、job user、document、KB 元组。generation、authority epoch/pending ticket、deadline 和 caller abort 复核后，在同一消息回调中对真实共享状态执行 CAS。SAB 和 ownerToken 不进入公共响应、渲染进程或 JSON fork。已认领任务完成私有 register ACK 后才开始 handler；ACK 失败或超时按同一元组注销，不能清理另一代任务。

queued 预检只允许原 queued row 或紧接的下一 claim；重试的更晚代次不受影响。已持久化的终态按原任务返回，完成后的迟到取消不会改成取消。无任务时，直接返回认证快照中的原 `knowledge_id/task_id/status` DTO，不再向 Owner 回退并重新选择未来任务。SQLite JSON 文本投影保留字符串、布尔、数组、对象、null 的原 JavaScript `String(value || parse_status)` 行为。

## 有界准入与真正确认

| 边界 | 普通请求 | 文档取消预留 | 清理条件 |
| --- | --- | --- | --- |
| Electron IPC、Runtime、桌面 JSON fork | 64 | 8 | 已发出的取消控制等待实际 Owner ACK 或终态 Owner 失败 |
| Query | 1 执行、32 等待 | 8 个控制预检，优先于等待中的普通读取 | 实际结果、超时退出或故障；活动同步 SQL 的 caller abort 不虚假释放 Query 槽 |
| coordinator attempt registry | 64 个真实注册 attempt | 8 个不同取消意图，每意图最多 8 个等待者 | 精确注销、实际控制回复、故障或封准入关闭 |
| Owner 私有 cancel command | 原业务准入保持 | 64 个控制执行 | 实际 workflow/queue settled 后回复 |

调用方 abort 可以立即结束其公开 Promise，但这不代表后台已取消。`CoreOwner.waitForCancellation` 仅供可信 Node 传输等待，同外部 request ID 保守等待全部已在途匹配控制。`desktop-process` 在发送 JSON transport 终态回复和删除 control lifetime 前等待它，避免桌面 8 槽因早期错误回复而过早开放。实际 cancel-response、send 失败、Owner fault 或封准入的 close 才结算该 lifetime；共享 gate 的正常关闭由 Owner 决定，故障才使其失效。

事务、实际 SQL 批次、局部/最终提交门、子进程清理及终态故障语义见[队列实现](DOCUMENT-CANCEL-QUEUE-IMPLEMENTATION.md)。取消前的局部发布可完整回滚；局部 COMMIT 已获准则保留已发布代次并停止后续阶段；最终 COMMIT 获准后返回真实完成。单条 SQLite SQL 不可被 CAS 抢占。双重终态事务故障是 `503 job_outcome_failed` 和未确认槽，不能算取消成功，需 Owner 恢复/重启。

## 实际失败与回归

- HTTP 和 IPC 两个真实 Owner 回归，在实际 native chunk INSERT 暂停期间发取消，证明 coordinator 先 CAS、不会提前 ACK；释放后检查旧正文、完整分块、FTS 及无 running processing span。[校正后的 4/4 日志](../refactor-evidence/20261012-root-owner-document-cancel-corrected-green.tap)。初始 registration 能力缺失和 `task.id/task_id` 夹具错误分开保留，不冒充提交取消缺陷的 RED。
- 独立审查 P1：真实 JSON fork 中 8 个 caller abort 后，修复前 0 槽保留而预期 8；修复后全部保留，实际取消落库后清理并允许再次取消。[真实 RED](../refactor-evidence/20261012-root-desktop-cancel-abort-red.tap)、[GREEN](../refactor-evidence/20261012-root-desktop-cancel-abort-green.tap)。测试仅替换可信启动工厂来挂接真实 barrier Worker；production desktop-process、CoreOwner、Query、Auth、SQLite、Python 和业务处理不替换。
- 独立审查 P2：真实无任务认证快照完成后暂停，再真实 reparse/claim/registry ACK，旧取消释放后误把新 SAB 改成 CANCEL_REQUESTED。[真实业务 RED](../refactor-evidence/20261012-core-owner-no-job-cancel-red-business.tap)。修复后新任务保持 ACTIVE，完整真实 Python/分块/发布完成，0 模型请求。[P2 与预检 5/5 GREEN](../refactor-evidence/20261012-root-cancel-no-job-green.tap)。首次共享缓冲区 MessagePort 交付早晚差异是夹具错误，原日志保留。
- 独立审查 P3：解析器缺失时未登录原 401 被提前 503 替代。[真实 RED](../refactor-evidence/20261012-root-cancel-auth-order-red.tap)、[4/4 GREEN](../refactor-evidence/20261012-root-cancel-auth-order-green.tap)。旧 JSON true 状态投影曾变成数字 1；真实 SQLite [RED](../refactor-evidence/20261012-root-cancel-no-job-coercion-red.tap) 后使用实际 SQLite 3.53.4 支持的 JSON 文本操作符，[5/5 GREEN](../refactor-evidence/20261012-root-cancel-no-job-coercion-green.tap)。
- Query 真实只读 Worker 验证 32 个等待读取饱和时仍有 8 个取消预检、过量 429，且 authority 改变后不会 CAS。[4/4 日志](../refactor-evidence/20261012-root-query-cancel-admission-green.tap)。registry 与 Electron 入口的单位测试单独标记，不代替真实业务 ACK。
- 原分块页先读取全部内容的真实 RED 已改成只 hydration 当前页；仍扫描全部候选 ID/type，未宣称 O(page size)。完整 DTO、严格类型过滤、分页规则、64 位 ID、权限和同一 WAL generation 保留。[分页实现与证据](KNOWLEDGE-CHUNK-PAGINATION.md)。

独立[审查说明](DOCUMENT-CANCEL-RUNTIME-REVIEW.md)记录问题、原始范围与后续核查。Queue 六源已冻结，[清单](../refactor-evidence/20261012-document-cancel-queue-freeze.json)绑定定向 21/21、相关 60/60、重点 workflow 6/6 和类型检查，不能把它当 Root runtime 或 Windows 通过。

Root [统一来源清单](../refactor-evidence/20261012-root-cancel-source-freeze.json)绑定 350 份输入和 435 份编译产物：业务/任务相关 265/265（204.111 秒）、运行时相关 46/46（213.055 秒）、桌面传输 14/14（29.861 秒）、plain Node 编译入口 2/2（14.741 秒）、类型检查和构建均退出 0。六条命令前后来源相同，原始日志、命令与环境在清单中；这些是检查命令时长，不是产品延迟，不累加重复用例作为覆盖数量。临时统一检查脚本已消费删除。本轮无前端产品修改，不把此前 338/338 称为新一轮执行；当前 live 与 Windows 页面仍需另验。

Orca 抽屉动画停在 0 帧的观察经原生窗口恢复后，实际到 280ms finished、transform 0、visible 且位于 x669/width620；未强制修改 CSS 或动画。[恢复后只读观察](../refactor-evidence/20261011-browser-model-page/933-orca-host-restored-animation-state.json)、[实际截图](../refactor-evidence/20261011-browser-model-page/937-orca-restored-drawer-stable-screen.png)。这些仍绑定旧 live 核心 PID4110766，不算当前新取消源码的页面验收；工具参数错误保留为工具失败。

## 当前来源真实页面结果

旧核心已正常退出，当前PID245516与350输入/435产物逐项匹配，[运行证明](../refactor-evidence/20261012-root-cancel-live-proof.json)。Orca实际重解析168次读取全部200，publish_local内56次全部200；实际第2页显示#50–52、请求200/88ms。两次右侧裁切的click没有发送取消API，单独保留，不计通过。另一轮1次正文409没有响应体，原因未确认，不能称全部真实读取始终成功。[原始三轮分析](../refactor-evidence/20261012-root-cancel-live-rounds-analysis.json)。

996–999是实际键盘操作：重解析Enter、Tab选择当前取消、Enter触发cancel-parse。请求实际开始于publish_local期间，200/866.1ms；任务、root、publish_local均cancelled，running span0。完整正文、11429分块行、10000 FTS行哈希全部前后相同，模型/用量保持，250次观察全部200。1002/1004实际打开并展开解析记录，状态已取消/18.2秒。[真实取消证据及单样本限制](../refactor-evidence/20261012-root-cancel-keyboard-live-analysis.json)。采样设备正常退出并核实撤销，observer脚本已按SHA消费删除。

Windows最新正式clean prepare和追加随包Node/Python compiled2/2已通过，NSIS正在打包；隔离安装及正式IPC界面仍是独立必做项。原始Auth issue到异步journal的早期窗口、跨进程未确认模型结果及单条同步SQL限制保持明确，不以取消CAS宣称全部原子或全部性能完成。
