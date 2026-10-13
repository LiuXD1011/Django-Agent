# 侧栏安装版退出后的独立数据复核

本轮保持原 normal launcher 的失败回执和 exit 1 不变。已拥有的应用正常退出与保护进程末态是两个独立结论；本复核仅补充只读数据投影，不能将 strict launcher 标为通过。

## 范围与计划

1. 对原保护 PID 25268（FILETIME 134361236166333286）及本轮应用 PID 12324（FILETIME 134363313315163659）读取 Toolhelp 快照和同一 Win32 句柄的路径、创建时间、wait、exit API 结果。无法重新获取历史句柄时，不猜测退出码或原因。
2. 原失败发生在 `visible-after` 的 `process_preflight` 内，复制 after 快照前。`protected_handle → process_handle` 的路径查询失败直接抛出 `protected_process_path_unavailable`；该历史失败路径没有保存句柄 wait/exit/last-error。必须保留这项证据限制。
3. 仅读取 `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\浏览器资料副本 20261012 第1轮`。持有 deny-write/delete 数据库句柄，拒绝非零 WAL/SHM、活动任务及未决认证回执，记录原目录完整文件与目录清单。
4. 在新建、固定自有目录 `.sidebar-clone-postclose-20261013-1` 中复制数据库和 key 的原字节快照。仅快照使用本安装的 Node、readonly SQLite、sqlite-vec 和 Vault；不打开原库，不启动主程序、核心或 HTTP，不调用模型。
5. 沿用已审 `typed-native-v1` 算法，仅变更新审计入口的固定输出目录。核对全部 72 表，比较 68 保护表、保护元数据、25 托管文件、24 媒体引用及 79 加密字段。认证表和 Electron profile 的正常变化分别报告，不声称全部文件与全部表跨 GUI 不变。
6. 审计 Node 使用独立 private Job，保留真实 bootstrap 和完整进程树终态；核原资料在本次审计期间前后字节与目录 exact，相同历史证据的 SHA 保持不变。成功后删除精确自有快照中的数据库/key和已消费临时脚本。

方案与固定脚本： [preparation.json](../refactor-evidence/20261013-sidebar-postclose-audit/preparation.json)、[审计脚本归档](../refactor-evidence/20261013-sidebar-postclose-audit/reviewed-harness.source.txt)、[新快照入口](../refactor-evidence/20261013-sidebar-postclose-audit/postclose-snapshot-audit.mjs)。原 [失败回执](../refactor-evidence/20261013-sidebar-clone-launch-preparation/executed-visible-clone.json) SHA 为 `7a3d2ee1664e6c4964d8cc51a7aba34b5a63a3591e63aefd81ebc3678327b293`，原 [fresh baseline](../refactor-evidence/20261013-sidebar-clone-launch-preparation/fresh-clone-baseline.json) SHA 为 `5b5ef889ed5503f90d4d259e04d040e27cfa6f59ccac7e96b4294a991b051848`。

## 当前结果

独立确认审计实际 exit0，状态为 `verified_independent_data_projection_only`；原 strict launcher 的 actual exit1、失败状态和原字节完全保留，原保护进程持续完整的验收仍未验证。

### Win32 当前观测及证据边界

[进程投影](../refactor-evidence/20261013-sidebar-postclose-audit/process-observation.json)实际 session21245/exit0。PID25268 不在本次 Toolhelp 快照，`OpenProcess` 返回87（ERROR_INVALID_PARAMETER），不能再获得原历史句柄。该观测不能补出原进程的退出码、退出时间或原因，也不能证明它在本轮 GUI 期间保持存活。

本轮 PID12324 的创建 FILETIME 精确匹配 `134363313315163659`，同一句柄 `WaitForSingleObject` 前后均为0、`GetExitCodeProcess` 为0，退出 FILETIME 为 `134363319050577022`。路径查询失败31，但时间和终态可读；它独立支持 Root 已持有的 Job 记录中的本轮程序正常退出。不能将本轮 PID 的观测套用到原 PID25268。静态审查发现旧 `process_handle` 在路径查询失败时直接抛错，未记录同句柄 wait/exit/last-error；无法判断原失败是否由退出后路径不可读、权限或其他观察问题造成。

### 首轮自有审计脚本错误与修正

首轮 session95812 actual exit1：语法和数据审计两个 Node 均实际 bootstrap0、Job active0、0强制终止；随后自有脚本删除快照 db/key 后，对非空快照目录调用 `rmdir`，导致总回执未写出。[原始 Node 投影](../refactor-evidence/20261013-sidebar-postclose-audit/first-attempt-node-audit.json)和[残留清单](../refactor-evidence/20261013-sidebar-postclose-audit/first-attempt-owned-residuals.json)保留。这轮未持久化快照数据库 SHA 前后和完整原副本前后清单，不能称总体验收通过。

[原生 rmdir 复核](../refactor-evidence/20261013-sidebar-postclose-audit/first-attempt-native-rmdir-observation.json)实际 exit0，得到 errno41 / WinError145；剩余文件恰为自有 `marlin.sqlite3-shm`（32768字节，SHA `fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb`）及零字节 WAL。修正仅增加本轮四个精确快照文件的清理及清理前持久化结果，不改变原副本门禁或历史脚本。第二轮使用同一自有根目录下新的 `confirmation-1` 子目录，增加 readonly 快照 db 的 before/after SHA；表的 typed 摘要和保护比较算法保持一致。

确认前一次 hash 参数误填由 `reviewed_script_changed` 拒绝，actual exit1，发生在 context/native 子进程前；第一轮残留清理第一次因 Windows 默认 GBK 读取公开 UTF-8 回执失败，actual exit1，发生在删除前。两次工具错误均保留在[真实命令结果](../refactor-evidence/20261013-sidebar-postclose-audit/execution-tool-results.json)，不能算产品失败或通过。纠正 UTF-8 后[精确残留清理](../refactor-evidence/20261013-sidebar-postclose-audit/first-attempt-exact-residual-cleanup.json)actual exit0，仅删除本次新建快照的 SHM/WAL，原副本和历史快照均未清理。

### 独立确认审计

[第二轮固定脚本](../refactor-evidence/20261013-sidebar-postclose-audit/confirmation-harness.source.txt) SHA `2d6f15d26e9359d6c3d64dd14cc55be0253f02b9eff5cc89dc47c065c8972683`，新[审计入口](../refactor-evidence/20261013-sidebar-postclose-audit/postclose-confirmation-audit.mjs) SHA `a539f37c25e7c21237dfcb3003de483a8c1844d9e8ed9b72481ba244f470931c`。session5782 actual exit0，[独立结果](../refactor-evidence/20261013-sidebar-postclose-audit/independent-postclose-confirmation.json) SHA `da7481598c9eb24d10c5c686fa36447ac3a763f25f74da6d2f779a8c5668f6fc`。

| 检查 | 实际结果 |
| --- | --- |
| 当前表集合及内容投影 | 全部72表使用 native SQLite、sqlite-vec、typed integer/blob/null/real/text 摘要，包含 FTS 与向量扩展表 |
| 业务与索引保护 | 68保护表的记录数量和全部摘要与 fresh baseline、visible-before 均相等；模型5、用量170、分块22908等内容未变 |
| 凭据、媒体及元数据 | 25托管文件 SHA、24媒体引用、79个解密认证字段、保护 desktop_meta 摘要全部相等；活动工作及未决认证回执0 |
| 原副本在审计期间 | [before](../refactor-evidence/20261013-sidebar-postclose-audit/source-before-confirmation.json)与[after](../refactor-evidence/20261013-sidebar-postclose-audit/source-after-confirmation.json)的123文件/79目录 exact；原数据库未打开 |
| readonly 快照数据库 | before/after SHA 同为 `95253890a0eb21b6eac2ca9ce3785efce1c027137adde1940837a4503fcf95f4`，与复制时原数据库字节绑定一致 |
| 历史绑定 | 13个历史/审计输入 SHA 在确认审计前后保持一致，含原 strict failed receipt、fresh baseline、6e freeze、升级及 artifact binding |
| 自有 Node 生命周期 | 语法与审计均 bootstrap0、Job active0、完整自有树退出，0强制终止、0泛化杀进程；PATH 仅 System32，使用已安装 Node22.23.2 |
| 自有秘密材料清理 | 确认快照 db/key/WAL/SHM 精确删除，目录已移除；第一轮剩余两旁文件另行精确删除 |

GUI 跨前后仅3表摘要改变：`desktop_meta` 54→54、`device_refresh_tokens` 130→131、`device_sessions` 26→26；其余69表相等，包含 `auth_tokens`。保护 meta 相等意味着变化局限于排除的 IPC 会话/回执范围；未决回执仍为0。完整文件清单比启动前新增7个 profile 文件、改变20文件（19 profile、1数据库）、无文件删除，blob_storage 子目录更换；这些变化分别公开，不能声称整个数据库、全部表或整个 profile 在 GUI 前后字节不变。

语法 Node 总耗时128.101毫秒、数据审计 Node4444.361毫秒是验收工作耗时；reap 为0.022/0.025毫秒，均不能当作产品启动或页面延迟。没有启动应用或业务核心、HTTP 或付费模型请求；没有改变认证、真实用户设备、API Key 或密码。

### 实际打包退出链路的静态范围

[打包源绑定与审查](../refactor-evidence/20261013-sidebar-postclose-audit/packaged-shutdown-static-review.json)核对实际安装 ASAR `895f93…`、runtime manifest `36b2bc…`、历史来源 `6e37bc…`，绑定13个文件；没有用当前 mutable 源码代替历史安装包。`main.cjs` 先确定 data-dir 并设 `desktop-profile`，再请求单实例锁；second-instance 仅显示本模块窗口。托盘 Quit 调用本实例的 `app.quit`，before-quit 清理本模块 IPC、托盘、Langfuse 对象及 Runtime。Langfuse 仅处理自己随机分区中的当前窗口/连接/缓存。

Runtime 正常向自己 `fork` 的 ChildProcess 发送私有 `shutdown`；CoreOwner、查询线程和注册 supervisor 通过本实例持有的 worker/子进程对象及 unnamed Windows Job 清理。已审链路未发现按进程名或端口泛化终止其他实例。应保留一个具体限制：Runtime 的30秒超时 fallback 使用 `taskkill.exe /PID captured_child.pid /T /F`，子进程退出会清除 timer，但该 fallback 没有 FILETIME pin；本轮没有证据证明它执行过，也没有证据将原 PID25268 消失归因于该路径。静态范围不能代替实际多实例、异常退出或 PID 复用验收。

本复核完成独立退出后数据投影、可取得的进程终态及静态归属调查。原保护进程的历史终态与死因仍未验证，原 strict launcher 仍是 exit1；不将整组 J 或整个 Goal 标为完成。
