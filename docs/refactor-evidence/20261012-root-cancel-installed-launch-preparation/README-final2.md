# 已安装包启动验收最终交接（final2）

此文档与 [最终执行命令](EXECUTION-final2.md)、[最终脚本](reviewed-harness-final2.source.txt) 取代初版 README/EXECUTION 的启动命令和全目录复扫说明。初版 69 文件及中间版本均保留，不覆盖旧证据。脚本默认 review_only；准备阶段没有启动 Marlin、产品 core、GUI、模型或安装器，没有写用户数据或注册表。

验收对象是已安装冻结包：桌面 0.6.2、核心 0.7.0，位于 `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用`。绑定 [实际升级 receipt](../20261012-root-cancel-install-preparation/executed-upgrade.json)、[ASAR 审计](../20261012-root-cancel-windows-build/asar-audit.json)、已安装 `source-manifest.json` 和 [关键 Electron 基线](installed-critical-file-baseline.json)。当前工作区源码已继续修改，不参与启动身份检查。

实际升级已验证全部 25,378 安装文件和 25,303 runtime 文件。此脚本每阶段前后重新校验 17 个安装关键文件（14 个顶层 Electron 文件、ASAR、runtime manifest、卸载器）与 274 个 runtime 文件：所有已打包 core/dist 的 146 文件、frontend 的 85 文件、Python worker、自带 Node、Python 启动关键文件和 core 原生 .node/.dll。ASAR 10 项白名单逐项字节一致；固定 Node/Python EXE 在每次 CreateProcess 前再次校验。当前核验是关键子集，未重新哈希其他第三方 Python/Node 文件；receipt 中明确 `whole_inventory_rehashed=false`，不把历史全量校验说成新检查。关键 Electron 基线是在冻结 win-unpacked 与实际安装目录之间逐文件只读匹配得到的。

执行只有两个步骤，路径/参数固定，不接受任意 command、PID、账号、token 或额外路径。

1. **hidden-smoke**：独占新建中文含空格 `启动验收 取消工作线程 20261012`。真实安装 `Marlin.exe --smoke-test --data-dir ...`，校验实际 Vue mounted、隔离 renderer、真实 preload/IPC protocol 1、TypeScript 0.7.0 / 无 HTTP listener、截图和单次 startup_ms。实际窗口数据库必须 schema 1、12 业务表全空、无 Django、完整性/外键通过。再用自带 Node 和安装 ASAR 中原字节 Runtime 执行真实编译 fork + Owner/Query、capabilities 200、auth/me 401、FTS/vec 大于 2^53 ID 与正常 shutdown；自带 Python `-I -B` 验证无 Django。仅这些实际接口，无模型请求。Node 临时 helper 与 Runtime 副本在私有 Job 完整退出后精确删除。原保留数据的 12 表、90 文件及密钥必须全不变。startup_ms 是一次产品测量，不能称为 P95。
2. **visible-retained**：必须提供真实成功 hidden receipt 的 SHA，安装 identity 和 script SHA 均相同。固定原 `验收数据 二次` 启动前要求与升级 90 文件/12 表基线一致：Win32 禁写/删除句柄、WAL 为空、immutable SQLite 完整性/外键、同租户有效用户/库、0 待运行任务、无 IPC receipt、原 32 字节 vault key 和加密 ipc.session 可用。只核文件/hash/envelope，不解密或报告值，也不宣称 auth token 未过期。启动后 5 秒记录新 PID/exe/创建身份，随后每 5 秒输出 owned alive/Job 数量，继续持有 Win32 handle 与私有 Job；root 完成这个新窗口的真实 GUI 测试后，从它自己的托盘“退出”。窗口×只隐藏，exec 工具 yield 150 秒不会使 loop 退出。正常 GUI 注销后 ipc.session 缺席允许，pending receipt 仍拒绝。退出后的业务表/model_usage 变化如实记录，不推断 GUI 付费次数或全文件不变。

每次执行 Suspend→私有 `KILL_ON_JOB_CLOSE` Job→Resume，等待整个 Job 活动数 0 且 bootstrap exit 0。隐藏窗口和 Node 各 180 秒、Python 30 秒、可见 7200 秒上限；失败只终止自己的暂停进程/Job，不按名称全杀，不自动重试、不删除既有数据。保持 visible 的执行 session，真实 tray Exit 后再读终态和 cleanup。

所有阶段都精确保护原独立四模型窗口 PID 25268、exe 路径与创建 FILETIME `134361236166333286`，只读进程句柄存活；查询进程只投影 PID/name/exe，不读取 CommandLine。安装作用域只读现有 GUID 的 HKCU/HKLM 两视图；有同名或目标安装进程活动、注册表冲突、路径 reparse、重复执行、已有 fixture 均拒绝。原四模型窗口的实际数据未读取，保留验收目录模型数为 0，未克隆模型或修改认证。可见程序真实会话/页面就绪/模型调用由 root 另留 GUI 证据。

## 准备阶段检查

[Linux guards](linux-final2-guard-results.json) 与 [Windows guards](windows-final2-guard-results.json) 各 12/12、exit 0；只运行默认/非法参数，没有向 execute() 提供完整授权。最新 [Windows 只读 readiness](readonly-readiness-final2.json) 2026-10-11 22:01:09 UTC：上述 17+274 关键文件匹配、90 保留文件未变、32 字节 key/encrypted IPC session 可用、原 PID25268 精确身份仍活动、无新 WORK/fixture、无产品启动/API。Node probe 与原通过自带 Node `--check` 的 [源码](reviewed-node_probe.cjs.txt) 完全相同；[Python probe](reviewed-python_probe.py.txt) 只做 AST 解析。本次没有重新执行这两个产品 probe。

[初版冻结](preparation-manifest.json) 中 69 文件全部原 SHA 保留；Win guard 初次 helper 编码失败 transcript 也保留。最终清单记录后续独立证据和 helper 精确消费。唯一保留的临时脚本 `/tmp/marlin-agent-cancel-installed-launch-20261012.py` 交给 root 全读后执行，真实结果留给 root 写 `executed-hidden-smoke.json`、`visible-launched.json`、`executed-visible-retained.json`；这些尚未生成的实际 receipt 不纳入准备冻结。root 两阶段完成后再按准确 SHA 消费删除主脚本。
