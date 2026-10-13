# 正常安装版 GUI 验收准备计划

> 给后续执行者：按照本计划与 Root 的逐阶段精确授权执行。Goal 的设计/隔离验收授权已经存在；本轮只准备，不执行 clone、正常应用、sentinel、模型、安装器或服务。Root 单独协调所有 UI 操作。技能默认提交/默认文档目录由本任务的独占目录与“不得提交”约束覆盖。

**Goal:** 让 Root 在一份新的完整 QA 数据副本上，一次正常启动已安装869包，连续复核多页面、关闭后台、托盘退出和自有树终态。

**Architecture:** Linux只读SQLite事务加backup生成新Windows数据副本；独立只读utility不依赖四个旧临时wrapper。正常installed Marlin.exe在独立Win32 Job中运行，原main/后代HANDLE保留至终态，旁sentinel为独立Job；固定控制文件仅接受有限动作。

**Tech Stack:** installed Electron44.7.0/Node24.21.0、bundled Node22.23.2/Python3.13.16、NAPI8、Win32公开HANDLE/FILETIME/Job API、SQLite backup/read-only/vec0.1.9、Root computer-use。

## 固定范围

- Installed: `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用\Marlin.exe`；actual installed receipt0ee5a94b…/独立postcheck bfbe7393…。
- New DATA: `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\业务验收 20261013`，不存在才允许未来创建，marker `marlin-owned-runtime-installed-gui-data-v1\n`。
- New CONTROL: 同父 `.owned-runtime-installed-gui-control-20261013`，独占不存在才创建，marker `marlin-owned-runtime-installed-gui-control-v1\n`。
- Source: `/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa`；root拥有专用QA正常口令，helper不读取private-auth、不解密/注入认证、不改models、用户密码或device。
- Old DATA `验收数据 二次`、source、安装资源、旧证据/binding/index保持；installer不再执行。
- 869绑定旧468源；当前新sidebar/detail/autostart不在此包，GUI结果不代替最终新版包。
- 原外层升级工具overall1/GBK错误保持，NSIS0/child0/独立只读0分别记录。

## 准备1：实际源码与依赖证据

- [x] 原installed ASAR d4d16…读取main/runtime/owned/bootstrap/preload，五项字节SHA校验，全文读。
- [x] 核实际Electron类型中的requestSingleInstanceLock/setPath/quit，Node fork execPath/IPC/json类型；不猜API。
- [x] Source mode=ro/query_only事务，schema1/FK0/自动queued-running0，25必要文件；物理路径与关联只读校验，无row/secret输出。
- [x] Source有非零WAL，禁止直接copy主DB；仅未来SQLitebackup。
- [x] 独立utility、clone observer、launcher/controller、sentinel源码归档并绑定；默认模式零clone/产品执行。

## 阶段2：Root未来批准 clone

**Inputs:** clone-reviewed-binding.json中固定source材料/实际schema/QA UUID SHA、精确helper SHA；该阶段已由Root唯一执行actual0，77表/25材料，见REPORT。
**Output:** 新DATA的marker、SQLite一致快照、25材料、`clone-receipt.json`，全表hash/count与关联/media比较。

1. 要求新DATA及CONTROL不存在、父owned marker匹配；.secrets/.settings/media仅允许已核必要25文件，跳过private-auth/cache/logs/profile/WAL/SHM。
2. 只读source开启明确事务，加载已核本机vec0.1.9仅用于只读schema/哈希；检查queued/running0、actual列和所有物理引用为相对media、hash/关联匹配。
3. `source_connection.backup(destination_connection, pages=512, progress=bounded_callback)`，使用实际Pythonbackup签名；新DB之后用read-only验证，不启动Core或迁移。
4. 复制25材料，逐文件source-before/copy/source-after SHA相等，绝不解密key。source/clone每张实际表按全部行规范化hash/count比较，包括FTS/vec定义；不猜schema、不rewrite任何路径。
5. 要求FK0、document/image文件引用存在且SHA符合、tenant/KB/session/user关联无缺口。任何路径不portable或source材料改变即保留失败、停止、Root协调，不改models/auth来绕过。
6. 复制仅创建新的owned副本，不写source；若有并行source正常业务改变，不宣称source final freeze，clone对应明确backup快照。

## 阶段3：Root未来批准一次正常启动

**Input:** installed pinned inventory、成功clone receipt、readonly utility、固定launcher/controller/sentinel绑定。
**Output:** `visible-started.json`的actual main PID/FILETIME/image、Job membership/descendant状态；不声称页面/auth已通过。

1. 所有安装代码/runtime全量资源再核；exact新DATA marker/cloneSHA；HKLM/HKCU双view只owned，既有Marlin须自然退出；真正present的outside handles持至终态，0不记保护PASS。
2. fixed command仅 `Marlin.exe --data-dir <新DATA>`，无smoke/no-sandbox/inspect/devserver。最小OS env，PATH仅System32；product由resources/runtime启动bundledNode/Python/privateIPC。
3. 单独spawn sentinel：固定bundledNode与固定小脚本，单独Job、无TCP/API/Core，仅ready/stop标志；原HANDLE/FILETIME保留。
4. main CREATE_SUSPENDED→private Job→Resume，原mainHANDLE验证FILETIME/image；每1秒观察原Job成员并只保留经IsProcessInJob核验的原HANDLE。受控worker/pipeline后代同样记录。
5. 多页默认budget14400秒；明确extend-once只增加7200，硬上限21600。正常关闭窗口进入tray不被当作退出，main早退而后代仍alive不记成功。
6. 每5秒写/输出无凭据状态，工具yield<=60秒，Root可持续沟通。stdout/stderr送NUL，不把用户provider/auth错误写报告。
7. Root用真实GUI正常登录专用QA账号，若自然恢复账号则先核身份，必要时正常GUI退出登录再登录；不使用旧realadmin口令，不修改token/localStorage/desktop_meta。

## 有限控制接口

仅固定control目录，protocol1/session nonce/递增sequence/action字段，拒绝任意PID/path/argv/端口/多余字段。

- `snapshot`：真实原Job accounting和原HANDLE/窗口可见状态；不读CommandLine、不点击GUI。
- `natural-exit`：向Root给出“用当前窗口自己的tray Exit”的请求，继续观察原树；helper不把WM_CLOSE当app.quit，不按PID终止。Root负责真实托盘动作。
- `force-crash-main`：仅Root后续明确授权的crash case，对本次保留的原mainHANDLE TerminateProcess(code77)；先观察product kill-on-close的Core/worker后代和独立sentinel。超时保留失败，再只清自己的GUI Job。
- `second-instance`：Root明确发该动作后，同固定exe/data-dir在另一短寿命privateJob启动，观察second-instance退出与原main保留；UI聚焦由Root证明。
- `extend-once`：只允许一次7200秒扩展，拒绝无限保活。

Root正常tray Quit时只接受原main退出/原Job active0/所有保留成员原HANDLE终态，exit0记正常；crash77另记，不混称graceful。独立sentinel在GUI树退出后先核仍alive，再通过它自己的固定stop标志退出0；cleanup只操作自产Job，任何失败与真实码保留。

## 后置与Root UI验收

- [ ] Actual installed GUI startup与真正IPC/账户/KB/文档页面，需要Rootcomputer-use，不从launcher“alive”推断。
- [ ] Root验证窗口关闭后台、同generation托盘恢复、single-instance、真正tray Exit；记录操作截图/时延，时延不由sleep预算推断。
- [ ] Core/owner/query/文档Python worker后代按原HANDLE记录before/after、root早退、force crash、新generation重启；没有旁实例时不声称保护通过。
- [ ] Exit后新DATA只读完整audit：credentials key与原25材料保持（有Root批准的新增/删除另记录），所有表hash/count变化明列；正常认证/session/profile变化不宣称全DB不变。
- [ ] Source原QA与旧DATA不被launcher写入，旧installed receipt/sourceFreeze/GBK failure不重写。
- [ ] 消费helper按归档精确SHA删除；新utility独立后可解除对4个旧tmphelper的需要，Root确认无活跃消费者后精确删，不改旧binding字节。

## 验证与交接

准备期只执行schema/hash/AST/控制字段拒绝检查及native只读preflight；不执行clone、launch、sentinel或control mutation。后续exact commands与SHA写REPORT；Root读完整代码后分别批准clone、正常GUI和特定crash动作。整个Goal及最终新源码交付持续未完成。

后续实际：Root批准唯一v2正常launch，用户原图显示loading与Core代码1，正式启动FAIL。树终态0不满足以上GUI/登录/tray验收项，详见REPORT；不自动重放。
