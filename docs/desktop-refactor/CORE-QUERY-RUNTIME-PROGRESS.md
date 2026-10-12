# 只读运行时集成进度

阶段2已完成一次来源冻结、相关检查和隔离浏览器核心正常重启，随后真实页面复测发现分页性能问题。分页与精确文档取消现已实现并完成阶段3来源统一检查，正在重启后复测真实页面。此记录不代表最终桌面/Windows验收。阶段1历史保持在[原传输报告](CORE-OWNER-TRANSPORT-ACCEPTANCE.md)。

## 已实际验证

- [发布事务原RED](../refactor-evidence/20261012-root-owner-read-publication-red.tap)：原owner独占消息泵在实际SQLite更新正文、分块和FTS后、COMMIT前被受控barrier阻塞，两条HTTP/IPC GET均等待写者，commit/rollback两项失败。接入native WAL只读Worker后，[同两项首次GREEN](../refactor-evidence/20261012-root-owner-read-publication-green-first.tap)通过，释放前返回旧完整版本，释放后提交为新版本/回滚仍旧版本。这是私有HTTP facade和IPC集成，未替代Orca真实页面采样。
- [16条GET一致性](../refactor-evidence/20261012-root-query-route-equivalence-corrected.tap)：HTTP和IPC各16条实际读取与同一真实Application DTO逐字核对，保留一万行Unicode正文和9223372036854775806 seq。共1个测试、32条接口比较。首次夹具错误写成不存在的parent_chunk_id，原[失败日志](../refactor-evidence/20261012-root-query-route-equivalence.tap)保留；按实际schema改为context_parent_id，不计产品RED。
- [保存前后IPC epoch](../refactor-evidence/20261012-root-ipc-auth-save-green.tap)：8/8，包含带查询参数auth路径和两次真实凭据保存边界。原RED分别在[路径](../refactor-evidence/20261012-root-ipc-auth-path-red.tap)和[保存](../refactor-evidence/20261012-root-ipc-auth-save-red.tap)。
- [HTTP迟到登录RED](../refactor-evidence/20261012-root-owner-http-auth-fence-red.tap)200而非409；[IPC迟到保存RED](../refactor-evidence/20261012-root-owner-ipc-reply-fence-red.tap)错误保留新device。加入协调器终态检查、精确discard和IPC opaque receipt后，[HTTP/IPC/正常关闭并重启](../refactor-evidence/20261012-root-owner-auth-receipt-close-green.tap)3/3通过。后续加密journal、Refresh及真实强杀恢复20/20、相关19/19，来源和实际恢复边界见[receipt报告](IPC-RECEIPT-RECOVERY.md)。
- [核心死亡health RED](../refactor-evidence/20261012-root-owner-health-red.tap)仍200；修复后[组合6/6](../refactor-evidence/20261012-root-query-auth-health-green.tap)包括实际强杀owner→health503/读取503。
- [Query准入及崩溃](../refactor-evidence/20261012-root-query-related-first.tap)中的两项真实测试通过：1执行+32等待，第34请求429，凭据/空间重新鉴权、queued abort、epoch改变拒绝、真实Worker崩溃后最多一次重启。该组合总体为18PASS/1超时取消，**不是全部通过**；旧stream saturation把已迁入Query队列的63 auth/me误作owner排队请求，已改为owner-only capabilities保持原断言，[修正独立5/5](../refactor-evidence/20261012-root-query-owner-stream-corrected.tap)通过。最终来源统一runtime相关33/33另有原始日志。
- [header投递前取消](../refactor-evidence/20261012-root-owner-abort-header-green.tap)1/1：真实流response屏障期间abort，迟到帧被忽略，后续owner和Query仍正常。
- [15秒Query deadline](../refactor-evidence/20261012-root-query-deadline-green.tap)1/1：真实只读查询后人为暂停私有回复，deadline仅终止只读Worker、close等待实际退出，主业务设备保留。人为等待不计页面延迟。

## 实现边界和剩余工作

owner是唯一RW业务连接，Query仅真正readonly连接；认证、权限和DTO在同一个deferred快照中。查询protocol只允许16条固定GET和私有文档取消窄化预检，没有SQL/AuthContext/refresh/上传/系统命令。最迟期限从准入算15秒，SQLite等待500ms，关闭2500ms后仅对只读隔离强制结束；失败不静默退回owner。设置、下载、流、模型与取消的耐久终态仍由owner执行，可信coordinator只执行精确attempt CAS。

authority epoch由可信协调器在有效变更意图发送前推进，按ID保留ticket到owner终态ACK。所有owner abort/stream.return保留容量直到终态，取消后的迟到header/frame不故障整个核心。仅保留私有access镜像，原tenant选择按每请求传递。IPC接受线性化于协调器处理原receipt response的同一message turn：入队确认并同步公开IpcResponse；rollback必须等待实际owner ACK，确认控制本身不改变授权。凭据清理失败会封闭核心读取，正常shutdown由owner在DB仍open时清理未确认receipt。最新这些失败分支仍待相关统一回归，不能沿用早期GREEN作为最终来源证明。

## 来源冻结与真实页面复测

[阶段2来源清单](../refactor-evidence/20261012-root-query-source-freeze.json)绑定270份输入和423份编译产物；domain相关174/174、runtime相关33/33、typecheck和build退出0、plain Node编译入口2/2（没有tsx或skip）、桌面消费者12/12。六条命令各有原始日志和前后来源比较。此轮没有修改前端，不把此前338/338称作新一轮前端执行。

[正常重启证明](../refactor-evidence/20261012-root-query-live-proof.json)记录同一隔离目录新核心PID4110766。Orca实际点击四万行文档重解析，随后点击Chunk；同时[228条真实HTTP观察](../refactor-evidence/20261012-root-query-publication-live.json)及[按阶段分析](../refactor-evidence/20261012-root-query-publication-live-analysis.json)记录全部业务读取成功且正文/总数完整，但health144次有2次约3秒超时，其中1次早于本轮任务。统计41次98.38–2570.54ms、正文22次775.36–2347.39ms、分页分块21次1727.67–2448.61ms。实际任务23.579秒、publish_local12.806秒；这些是有采样负载的单次任务，不能与早期无相同负载样本直接作性能比较。Orca自然轮询也覆盖发布阶段，Chunk接口返回200，但抽屉显示尚待独立核实。

这轮性能验收**未通过**：只显示20条的分块接口实际先读取全部11429条及元数据。真实只读SQLite回归已复现67条读取而非20条，分页修复正在实施，旧日志保留。health超时原因目前只记录URLError，不能全部归因于发布事务；下一轮需补充错误分类。模型配置摘要保持不变、全局usage101/本验收空间0，没有新增付费调用。

阶段3：[分块分页](KNOWLEDGE-CHUNK-PAGINATION.md)已通过真实SQLite RED→GREEN；仅 hydration 当前页，仍扫描候选 ID/type。[精确取消实现](DOCUMENT-CANCEL-RUNTIME-IMPLEMENTATION.md)已通过真实HTTP/IPC提交屏障、无任务快照与后续claim竞争、桌面8槽caller abort、认证顺序与JSON状态保真回归。[来源清单](../refactor-evidence/20261012-root-cancel-source-freeze.json)绑定350输入/435编译产物：domain相关265/265、runtime相关46/46、plain Node编译2/2、桌面14/14和类型/构建退出0。前端本轮未改，不重复计此前338项。

当前PID245516已正常重启且匹配冻结来源；Orca真实重解析168次观察全部200，发布期间56次全部200。第2页实际点击、#50–52及page=2请求200/88ms已核对；另两轮未触发API的裁切取消点击不计通过，一轮正文409原因待核实。[三轮结果](../refactor-evidence/20261012-root-cancel-live-rounds-analysis.json)。随后实际键盘操作在发布期触发取消请求200/866.1ms，后台job/root/stage全部cancelled、running0，旧正文/11429分块行/10000 FTS行哈希全部相同，250观察全部200。[真实取消](../refactor-evidence/20261012-root-cancel-keyboard-live-analysis.json)。

接下来：Windows当前来源NSIS正在构建，仍需隔离安装和原生页面，以及剩余业务页面。全部Goal仍active。此前Windows包未包含本阶段，旧可见窗口也不算当前安装验证。Auth issue产生到adapter journal写入的早期窗口、协调器确认入队与owner落盘之间的窗口仍明确保留，不能宣称所有崩溃窗口已原子化。

存储/Auth及知识纯查询的独立证据见[只读存储认证](READ-DATABASE-AUTH-IMPLEMENTATION.md)、[纯查询抽取](KNOWLEDGE-READ-EXTRACTION.md)。已有检查日志不覆写，临时owner抽取脚本已消费，其SHA为8e8da72b15e9b3e9905436e5ce552e571678bef1660595d7b852b304b60315e3，清理记录见[收据](../refactor-evidence/20261012-root-owner-extraction-helper-cleanup.json)。
