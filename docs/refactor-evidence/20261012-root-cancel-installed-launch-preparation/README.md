# 已安装取消 Worker 包启动验收准备

本目录只准备可审阅的固定启动脚本，不执行 Marlin、GUI、安装或注册表写入。根任务全读后分两次显式执行，测试对象是已安装的桌面 0.6.2 / 核心 0.7.0 冻结载荷，不是之后继续修改的工作区。脚本默认 `review_only_no_execution`。

来源绑定 [实际升级结果](../20261012-root-cancel-install-preparation/executed-upgrade.json)（SHA `6f5d202d3d9ff0771858c41405e9aae4d161cdd7aa6e4b3d28e741221c65e5b8`）与 [ASAR 审计](../20261012-root-cancel-windows-build/asar-audit.json)。每阶段启动前、退出后各扫描一次已安装全目录；同一次扫描派生 runtime 清单，避免重复扫描载荷。校验 25,378 个安装文件、25,303 个 runtime 文件、ASAR 10 项白名单与每项字节、固定官方 Node / 嵌入式 Python，以及 Owner / Query / 取消 / 分页模块。完全不读取当前工作区 350/435 文件内容作比较，不调用可变的构建脚本，不加载之前已消费的临时安装脚本。

固定安装目录：`C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用`。原独立四模型 QA 窗口 PID 25268 只以精确 exe 路径、Win32 创建时间 `134361236166333286` 和仍活动的只读进程句柄验证；不借用其窗口或数据，也不按进程名称终止任何程序。安装前后的既有 GUID `5eeaa2c6-7620-5547-ba48-efe96f6ebb0b` 只读取 HKCU/HKLM 的 32/64 位视图；任何安装目录冲突或目标安装载荷进程活动都拒绝执行。

## 第一步：空数据隐藏启动

- 执行真正安装的 `Marlin.exe --smoke-test --data-dir ...`。源码实际参数是 `--smoke-test`；`--desktop-smoke` 不受支持。
- 独占新建 `启动验收 取消工作线程 20261012`（含中文与空格）；拒绝已有目录，不覆盖或自动重试。另有 `.cancel-installed-launch-20261012\私有 IPC 空数据`，供私有 JSON fork 定向检查。
- 从真实窗口输出读取 `smoke-result.json` / `smoke-window.png`，要求 Vue mounted、renderer 无 `process/require`、真实 preload protocol 1 / IPC、TypeScript handshake / 无 HTTP listener。记录产品测得的 `startup_ms`，不称为冷启动 P95。
- 对该实际窗口创建的数据库使用 Win32 禁写/删除句柄和 `immutable` SQLite 只读检查：schema 1、12 表全空、无 Django 表、完整性和外键检查。
- 从已经校验的安装 ASAR 提取**字节完全相同**的 `runtime.cjs`；仅临时落入专用 WORK，以便 plain bundled Node 能加载（Node 不原生读取 Electron ASAR）。复用真实 Runtime、真实编译 `desktop-process.js`、Owner 与 Query Worker，不替换 dispatch/auth/SQL。校验 capabilities 200、未登录 auth/me 401、全新 schema、12 表全空、正常 shutdown、FTS / sqlite-vec 的大于 2^53 精确 ID。
- 使用安装版 `python.exe -I -B` 检查 3.13.16 / x64 与 `find_spec('django') is None`。系统 Node/Python 不进入产品 PATH；外层测试 Python 3.13 是 harness 宿主。
- 每个执行都先创建暂停进程，加入独占 `KILL_ON_JOB_CLOSE` Job，再恢复。等待全部子进程活动数为 0，记录 bootstrap exit 0；不推断每个后代的 exit code。隐藏执行 180 秒上限、Python 30 秒上限，异常只结束自己创建的 Job。
- 临时 Node helper 和 ASAR Runtime 副本在所拥有的进程树结束后精确删除。保留新 fixture、截图和结果用于根任务审阅；原 `验收数据 二次` 的 12 表、所有文件、凭据哈希要求完全不变。

## 第二步：原保留验收数据可见启动

必须显式提供第一步真实成功 receipt 的 SHA；前一步未执行或失败不得进入。对 `验收数据 二次` 进行离线禁写/删除+SQLite immutable 检查，要求与实际升级的 90 文件、12 表基线完全一致，用户和知识库仍有效且同租户、没有待恢复/活动任务、没有未确认 IPC receipt。检查 `.secrets/credentials.key` 正规 32 字节文件及原哈希、`desktop_meta['ipc.session']` 的加密 envelope 存在；不解密或输出 access/refresh/API Key，不声称这已证明凭据未过期。

启动 `Marlin.exe --data-dir <原保留验收目录>` 后，harness 继续持有独占 Job 等待根任务真实 GUI 测试。5 秒时只发布 `visible-launched.json` 和 `owned_process_alive_awaiting_root_gui`，包括新 PID / exe / 创建时间；不把进程存活说成页面就绪或登录通过。根任务针对这个新窗口完成 UI/身份检查后，使用该窗口自身托盘“退出”；点窗口关闭只会隐藏。harness 不应退出/被结束，否则其 Job 会清理自己创建的窗口。7200 秒上限仅保护这棵自有进程树。

正常退出后记录 bootstrap 0、完整 Job 已退出、数据库完整性、凭据文件仍相同、业务表变化和 model_usage 实际数量；GUI 改动属于根任务独立验收，不要求 Chromium 缓存或登录 token 与启动前字节相同，也不伪造 GUI 调用/付费增量为零。托盘点击是否真实执行由根任务 GUI 证据确认，脚本只证明正常退出结果。

## 准备与执行边界

[审阅源码](reviewed-harness.source.txt)、[非执行 guards](guard-results.json)、[只读就绪调查](readonly-readiness.json) 与 [准备冻结清单](preparation-manifest.json) 在准备阶段冻结；`executed-hidden-smoke.json`、`visible-launched.json`、`executed-visible-retained.json` 留给根任务真实执行，不纳入执行前文件冻结。

新脚本保留 `/tmp/marlin-agent-cancel-installed-launch-20261012.py` 给根任务消费，准确 hash / 命令见 [执行交接](EXECUTION.md)。禁止传入任意路径、进程 PID、额外启动参数、命令、账号或 token；重复 flag、等号 flag、hash 无执行选项、缺精确前序 receipt 均拒绝。

本次保留目录有 0 个模型；原四模型保存在 PID 25268 使用的另一个数据目录。没有克隆四模型、启动原 core 或操作原数据。后续若要独立模型克隆，必须在原应用无待执行模型任务时用一致的 SQLite 备份复制整个数据库并保留同一 `.secrets/credentials.key`，将上传文件/设置复制到独占目录；不能直接复制活动 WAL 主文件或只导入模型行。新 Chromium profile 应独立创建；需要检查绝对 `file_path` 引用，避免后续删除/重解析误指向原上传。任何真实模型调用仍由根任务按已授权功能范围控制；此次准备未执行该克隆方案。
