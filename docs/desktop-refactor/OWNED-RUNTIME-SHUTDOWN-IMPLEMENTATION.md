# Runtime 退出修复的源码检查点

本检查点记录实际实现和相关测试，不表示 Windows 安装版已经完成验收。设计和原缺陷见[实施计划](OWNED-RUNTIME-SHUTDOWN-PLAN.md)及[独立只读审查](OWNED-RUNTIME-SHUTDOWN-REVIEW.md)。原 PID25268 的死因仍未知，不把本次修复归因到其退出。

## 已实现

- `runtime.cjs` 保留原 JSON 字节／流／ACK／Langfuse业务协议。Windows先启动小型bootstrap；严格验证本代generation、pid与字符串FILETIME，由native在同一真实HANDLE核验后绑定Job，再发送授权。
- `runtime-bootstrap.cjs` 授权前不导入业务；实际取消、错误generation和连接断开有效。Core入口异步初始化期间保留shutdown guard，直到真实ready证明Core listeners已经安装，恢复原argv及process.send。
- `owned-runtime.cjs` 固定持有原child、generation和opaque Job。保留30秒正常关闭，根进程提前退出后仍核Job完整树；force只调用原Job，最多等5秒。观察失败、终止失败和超时均拒绝stop，不能报告成功或回到裸PID taskkill。
- 5秒等待用单调时钟，系统墙上时间调整不会延长它。迟到IPC失败回调中的信号错误不会抛出为未处理异常，既有deadline与整树终态条件仍生效。
- `main.cjs` 使用 `finishDesktopQuit` 消费关闭链拒绝并记录固定、无凭据的 `desktop-shutdown-error.json`；窗口清理失败仍执行核心退出，诊断写失败仍继续真正退出。OS退出时关闭本实例保留的kill-on-close Job。
- 可信测试启动选项只增加 `nativeModulePath`，父loader与bootstrap使用同一个路径；正式默认资源位置为 `runtime/owned-runtime/runtime-job.node`。
- 独立审查又复现同步fork异常遗留旧启动timer、随后错误停止新generation。正式回归先11PASS／2FAIL；现fork异常经finish清timer，finish只在同代generation时清理当前Runtime，旧回调不能停止新代。

未改变Core业务、权限、模型调用、数据库迁移、前端认证或现有取消控制槽。macOS/Linux的既有根进程关闭路径保留；本检查点不声称这些平台具有Windows Job的整树保证。

## 实际测试

| 范围 | 结果与限制 |
| --- | --- |
| 原Runtime正式六例 | 初次工具4b6973 actual1，1PASS／5FAIL；后续在自有临时目录对不可变2822旧源码再核1PASS／5FAIL，未回退工作区 |
| 正式Windows races及启动回归 | 最终13／13PASS；VM中只有明确标注的Win32／时钟／进程替身，没有实际PID复用或OS杀陌生进程 |
| Bootstrap真实child／JSON IPC | 4／4PASS：授权与argv、授权前取消、错误generation、异步初始化期间取消；native身份函数为明确的单元替身，不能冒充Windows身份验证 |
| 真正退出链 | 3／3PASS：stop拒绝被消费、窗口失败仍关闭Core、诊断失败仍退出；新增helper实现前actual1／0PASS3FAIL |
| 既有Runtime与取消槽 | 原6个Runtime用例及3个取消用例均PASS；真实TSCore／SQLite／私有IPC、上传字节、ACK背压、流取消、设备身份、重启不重放、本地Langfuse协议链继续有效 |
| 最终相关命令 | `node --test desktop/runtime-quit.test.cjs desktop/runtime-shutdown.test.cjs desktop/runtime-bootstrap.test.cjs desktop/runtime.test.cjs desktop/cancel-admission.test.cjs`，session2956／terminal30df95，actual0，29PASS／0FAIL／0SKIP，TAP8122.288011ms |
| 墙上时间停止回归 | 首次10PASS／1FAIL／actual1；改为单调时钟后包含在29PASS中，5秒是退出等待预算而非宣称的实际产品退出延迟 |
| 同步fork与旧timer | 正式13例先11PASS／2FAIL／actual1；修复后包含在29PASS。独立review在VM主动调用已清旧callback再核新代不被stop，1／1PASS，原request_changes／RED单独保留 |

此前26／27例检查点和所有RED日志保持原样；新增29例结论绑定[当前7文件revision](../refactor-evidence/20261013-root-runtime-integration/source-revision-after-startup-timer-fix.json)、[最终开始记录](../refactor-evidence/20261013-root-runtime-integration/final-startup-timer-related-tests-start.json)和[实际终态](../refactor-evidence/20261013-root-runtime-integration/final-startup-timer-related-tests-terminal.json)。原六例再核原始日志见[historical-runtime-formal-red](../refactor-evidence/20261013-root-runtime-integration/historical-runtime-formal-red.json)，原墙上时间失败见[monotonic-deadline-red](../refactor-evidence/20261013-root-runtime-integration/monotonic-deadline-red.json)，同步启动正式失败见[synchronous-startup-timer-formal-red](../refactor-evidence/20261013-root-runtime-integration/synchronous-startup-timer-formal-red.json)。这些耗时是测试工作时间，不能冒充用户界面或安装版退出延迟。

## 尚未完成

native独立[实施报告](../refactor-evidence/20261013-runtime-job-native/REPORT.md)已记录Winx64／NAPI8、Node22.23.2官方输入、同126976字节二进制SHA `b4f053aa1732e07220cd56b37fa5434b953d48e1b26c29e65f60d31f39c8eecb`。Node22、Electron RunAsNode各6／6及普通无窗口Electron main3／3actual0，实际自有树、旁实例、嵌套Job及51个原HANDLE终态有效。这是独立adapter验收；Root还须核最终冻结及正式Runtime／新安装包链路。初次后代fixture受到Node自身Job行为的失败、首轮UNC位置GPU0x80000003及其余工具失败保持实际码，未知GPU死因不补推断。

独立源码审查已确认所发现timer缺陷的对应修复，最终报告收尾中；[打包集成](../refactor-evidence/20261013-runtime-packaging/REPORT.md)在本机43个Python测试（2条件跳过）及133个startup测试（5条件跳过）actual0，正式Windowsbuilder／loader／新包门禁尚未执行。最终installer尚未构建或普通安装复验；历史6e安装包没有这些新文件，也不能替代新包退出验收。主Source浏览器Core／Vite仍已停止，本轮未恢复、未进行新的真实模型请求。

本轮Root自有检查helper和历史RED临时目录已精确清理；原QA凭据文件和待消费验收脚本仍按整个Goal的未完任务保留。Root前置检查及26例验证时的逻辑stage集合SHA为 `c8f6e0465ed59dcf3111b94d994a2604ebee7868656df9166b7b1ca26f1cb731`；随后只读观察到HEAD已为外部提交 `dd5a356a3afdd67492d82a3b3e0e89dafffe2174`，当前逻辑集合变为 `b36c6d28823e225a3c3daa8e75a74c2956982a21b64b4e8a0093e62cd795f278`。不推断提交者，不回滚；这次有新提交的变化与 `.git/index`原始stat-cache刷新分别记录。Root及本轮指定子代理没有执行stage、commit、push或发布；[只读观察](../refactor-evidence/20261013-root-runtime-integration/external-git-checkpoint-observation.json)保留实际码。完整Goal、38组／69UI矩阵与Windows正式交付尚未完成。
