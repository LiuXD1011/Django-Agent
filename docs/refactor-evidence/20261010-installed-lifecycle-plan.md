# 固定私有安装生命周期验收计划（仅准备，2026-10-10）

安装生命周期本身仍只提供一次性脚本与静态验证，未启动 Windows 进程、installed 应用 API、安装器或卸载器，未操作 GUI、修改产品、正式 stage、用户数据或 PID 15700。另已在自己的临时 Linux SQLite 中，通过正常 IPC 注册/登录验证下述 tenant DTO 比较修复；这不是 installed 阶段验收。后续由 root 审阅并独立逐阶段执行；当前没有 post-upgrade、uninstall 或 reinstall 的实际 PASS。

**交付脚本：** `/tmp/marlin-installed-lifecycle-20261010.py`，36,644 bytes、547 lines，SHA256 `20ebcc6f0a4561aaf56ed638f072a033ba0c83dc24b6b083f49f2c0ceed2957f`。这是 Windows Python 3.13 测试主机上的一次性验收调度脚本，应用业务仍使用 installed bundled Node / TS Core。复制时须保留原字节，不用文本转换工具；所有阶段均复核被审阅脚本的 SHA。

## 固定范围与实际来源

- 正式 stage：`C:\Users\lxd\AppData\Local\Temp\Marlin TS Final Build 20261010`。
- 正式 installer：`C:\Users\lxd\AppData\Local\Temp\Marlin TS Final Installers 20261010\Marlin-Setup-0.6.2-x64.exe`。
- 唯一验收父目录：`C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010`，`.marlin-install-qa-owned` 只能为 `marlin-ts-install-qa-20261010` 加 LF 或 CRLF。
- 唯一安装子目录：`应用`；唯一原验收数据子目录：`验收数据 二次`；禁止从 CLI 替换为真实 visible-data 或任意目录。
- 注册 GUID：`5eeaa2c6-7620-5547-ba48-efe96f6ebb0b`。HKLM 32/64 位视图均不得已有同 GUID；installed 阶段 HKCU 两视图的 location / uninstaller / quiet-uninstaller 均须精确匹配此目录，uninstalled 阶段两键都须不存在。
- 原自建用户 `54cb440c-3dff-4087-b36f-7ab5b688ab56`、知识库 `7878fc29-7fbe-4c94-8cea-8b823930ad5a` 只通过已保存的真实 CoreIpcAdapter 凭据和现有 GET API 验证，不构造 AuthContext，不提取 cookie/token，不初始化账户或重置密码。
- 原实际用户 QA PID 15700：保留 SYNCHRONIZE / QUERY_LIMITED_INFORMATION handle，并核对实际 image 是另一父目录中的 `electron-runtime\electron.exe`，阶段前后均须仍存活。退出、PID 重用、image 变化一律拒绝；脚本不能自动选择替代 PID。

已完整核查 `desktop/main.cjs` / `runtime.cjs`、CoreApplication / CoreIpcAdapter / auth / KB DTO、root 的 installed code-upgrade 脚本及 installed initialization、device、registry、只读 preflight、私有 backup 证据；NSIS 实际文件为安装依赖中的 installer/uninstaller、multiUser、assisted/oneClick、installSection、installer/installUtil、allowOnlyOneInstallerInstance 模板及 nsisOptions 类型。未读取密码证据或凭据原值。

此前 installed fixture 与 Windows 四模型 visible-data 相互独立。其原始业务计数为 users=1、KB=1、device_sessions=2，其余本次 12 表为 0；旧证据没有 final 新代码的 post-upgrade 运行证据。此前 device 的 client_type 为 web，不能根据名称猜测 desktop 身份。脚本要求真实 `/auth/me` 的 `auth_mode=ipc` 和 `device.current=true`，实际 saved credentials 无效且正常 refresh 也失败时必须停止，由 root 决定正常私有登录与重新建立验收基线，不伪造成功。

## 构建、数据与进程围栏

每阶段先复用 source-bound 官方 `scripts/build_windows.py::verify_prepared(REPO, STAGE)`，核查完整 frozen source、gates 原生/Python/Electron事实、锁与 payload inventory。再核对 installer SHA sidecar 与 7 项正式报告 sidecar 原字节、ASAR audit、win-unpacked 完整文件集合；installed 目录必须等于 win-unpacked 的完整集合加唯一 `Uninstall Marlin.exe`，runtime manifest 与所有文件必须精确相等。应用 probe 后再次核验安装与正式身份，能发现 import 导致的额外 PYC 或其他修改；不放宽 inventory。

数据比较采用停止应用后的只读 SQLite integrity / foreign_key_check，并逐表对全部行进行规范化 SHA；不输出原行、密码摘要、历史正文或 key 内容。精确 12 表为 users、knowledge_bases、knowledges、chunks、sessions、messages、models、model_usage、wiki_pages、device_sessions、desktop_jobs、task_records。模型、用量和任务须为空。完整数据文件 inventory 及 `.secrets` 的哈希同时保留；这不是并发应用写入下的快照保证。

首次 post-upgrade 必须已有 root 的 verified `20261010-installed-code-upgrade.json`，installer SHA 匹配，12 表与 `.upgrade-backup-20261010` 精确相等，解密材料哈希仍等于私有 UNC backup manifest。正常 refresh 的真实写入仅允许 12 表中的 device_sessions；完成 auth 关闭 Core 后再固定 `retained-baseline.json`。卸载/重装依据此新基线逐字节和逐表比较，不能拿 refresh 前旧 hash 冒充一致。

每阶段拒绝 symlink/junction/reparse。CIM/PowerShell 策略须可用，并要求安装路径前缀下零进程、系统零 Marlin.exe；包含相似前缀兄弟目录的进程也拒绝，以匹配 NSIS 现有 StartsWith 检查。验收器不停止已有应用；本阶段不是 normal tray quit 验收，也不能把 NSIS 的 maintenance-stop 当成正常退出。

测试子进程通过 CreateProcessW suspended → private JobObject → assign → resume。成功须等待整个 Job 的 ActiveProcesses=0，120 秒 application probe / 600 秒 NSIS 上限，失败/中断才终止该 Job，并有 5 秒清理界限。默认 NSIS 卸载器复制到 TEMP 后的子进程必须一同等待，bootstrap code 只按 bootstrap 记录，不宣称已观测所有 descendant exit codes。[Microsoft Job 查询契约](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject)。

环境只保留系统目录、用户 profile、TEMP 等白名单，PATH 固定 `C:\Windows\System32`，不继承 Node options、Electron run-as-node 或模型 key。Node probe 添加零网络 fetch guard，models/model_usage 前后为 0；正常 smoke 使用新建、独占、空的 smoke data-dir，不污染原 `验收数据 二次`。

## 分阶段执行与收据

| 阶段 | 实际动作 | 必须满足的结束事实 |
| --- | --- | --- |
| `post-upgrade` | hidden installed `Marlin.exe --smoke-test --data-dir <新独占目录>`；随后 installed bundled Node 导入正式 CoreApplication + CoreIpcAdapter，GET auth/me，必要时仅正常 POST auth/refresh，再 GET 原 KB | 实际 mounted / sandbox / private TS IPC；原 user / tenant / KB 授权正确；无模型/网络调用；原解密材料未变；固定新 retained baseline |
| `uninstall-retain` | exact owned registered `Uninstall Marlin.exe /S /currentuser` | 等完整 TEMP child Job；注册两视图均移除；安装目录完全移除；完整数据文件、12 表、cipher material 和上阶段基线完全相同；PID 15700 handle 仍活 |
| `reinstall` | 同正式 installer，固定 silent/currentuser/no-desktop-shortcut；最后原始 `/D=<owned应用>` 尾参 | 无任意 shell；仅固定安装目录；HKCU 精确恢复；完整新 installed code/runtime 和正式身份匹配；全部保留数据 hash 未变 |
| `post-reinstall` | 新独占 hidden smoke 目录；再次走正常 installed CoreIpcAdapter saved auth | 相同原 user/KB 实际恢复；真实 refresh 如发生须单独记录；不把刷新后的 DB 字节宣称为原基线完全相同；代码/runtime 再核查；无模型请求/GUI通过声明 |

卸载不携带 `--delete-app-data`、`--updated`、`_?=` 或 `/D`。重装的 `/D=` 是 NSIS 特殊参数，必须最后且不加引号；完整路径中的中文空格直接作为最后 raw CreateProcessW tail，前部固定 argv 仍用 list2cmdline。该行为来自实际 multiUser.nsh 和 [NSIS 官方 CLI](https://nsis.sourceforge.io/Docs/Chapter3.html)，不交给 shell，不接受 renderer、用户路径或任意 raw command。

`.lifecycle-20261010` 只在首次显式 phase 中独占创建；已有目录不会重用。每阶段 exclusive 创建 `.attempt.json`，成功或失败均留 receipt；重复、有未知结果或失败的 phase 不会自动 retry/resume。后续 phase 必须提供实际前一条 verified receipt 的 SHA，且 script/source/artifact identity 和 retained baseline SHA 都相同。

### Root 审阅后的命令形状（当前未执行）

将脚本原字节复制为父目录下 `marlin-installed-lifecycle-20261010.py`，确认 SHA 后，使用 native host `C:\Python313\python.exe -I -B`。以下不带 execution flag 的命令仅输出 review-only 元数据：

```powershell
$handoff = 'C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\marlin-installed-lifecycle-20261010.py'
$stage = 'C:\Users\lxd\AppData\Local\Temp\Marlin TS Final Build 20261010'
$installer = 'C:\Users\lxd\AppData\Local\Temp\Marlin TS Final Installers 20261010\Marlin-Setup-0.6.2-x64.exe'
$reviewedSha = '20ebcc6f0a4561aaf56ed638f072a033ba0c83dc24b6b083f49f2c0ceed2957f'
& 'C:\Python313\python.exe' -I -B $handoff --phase post-upgrade --stage-root $stage --installer $installer
```

Root 完成正式 code-upgrade 并审核所需来源/注册/PID围栏后，单独显式执行首阶段；不一次性连跑所有 phases：

```powershell
& 'C:\Python313\python.exe' -I -B $handoff --phase post-upgrade --stage-root $stage --installer $installer --reviewed-script-sha256 $reviewedSha --execute-reviewed-phase
```

收据为父目录 `.lifecycle-20261010\post-upgrade.json`。Root 阅读该收据后计算原字节 SHA，再单独执行下一 phase：

```powershell
$prior = (Get-FileHash -Algorithm SHA256 'C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\.lifecycle-20261010\post-upgrade.json').Hash.ToLowerInvariant()
& 'C:\Python313\python.exe' -I -B $handoff --phase uninstall-retain --stage-root $stage --installer $installer --reviewed-script-sha256 $reviewedSha --prior-receipt-sha256 $prior --execute-reviewed-phase
```

`reinstall` 只接受 `uninstall-retain.json` 的 SHA；`post-reinstall` 只接受 `reinstall.json` 的 SHA。公开 stdout 只有安全 phase、状态、receipt path/SHA 和 0 paid 元数据。业务错误只保存固定 error_code，原始 stack/error 不进入公开报告。私有 log 不自动发布；Node auth probe 只记录固定 step 与 HTTP status，不打印用户字段、token、password 或解密内容。每次使用的 Node helper 原字节预先 `--check`，实际使用后只删除那个 exclusive 创建的临时 `.cjs`。

## Tenant DTO 一行修复与真实只读证明

Root 已全文审核原 547 行脚本。随后核对实际 `AuthService.publicIdentity` 和 `KnowledgeDomain.kbDto`：前者将 tenant ID 输出为 String，后者保留 SQLite INTEGER 在安全范围内的数字投影。原脚本在同一真实空间上执行 `record.tenant_id !== identity.tenant.id` 会误拒绝。授权变更只有第 386 行这一处，将两侧都转换为 String；知识库 ID、名称、200 状态、原 user、设备、现有 API 权限和阶段围栏全部保留。原脚本 SHA 为 `2a419ff1ba2c1224a3572a1d937b31044f1e603f222dd2a5b4415766317c5573`。

完整一行差异见 [tenant-fix.diff](20261010-installed-lifecycle-tenant-fix.diff)。在自己的 `/dev/shm` 独占临时目录中，使用实际编译的 CoreApplication + CoreIpcAdapter，正常注册/登录两个随机私有账户、创建并 GET 各自知识库、恢复 saved IPC 身份，再只读查询自己数据库的 `typeof(tenant_id)`。没有构造 AuthContext、读取真实用户凭据、修改原安装数据或调用模型。

- [旧断言 RED](20261010-installed-lifecycle-tenant-red.json)：9 项中 8 通过，仅 `handoff_allows_same_actual_tenant` 失败，命令 exit 1。
- [新断言 GREEN](20261010-installed-lifecycle-tenant-green.json)：9/9 通过，命令 exit 0。实际 SQLite 类型为 integer；DB/KB API 投影为 number；auth/me 投影为 string。
- 原始 foreign KB GET 仍 404；通过另一空间 ID 请求仍 401 / unauthorized；新脚本的比较也拒绝该真实 foreign tenant。保存的私有 IPC 身份正常恢复。
- 第一次测试辅助脚本另有错误的 403/404 预期；[初次日志](20261010-installed-lifecycle-tenant-initial-runner-red.json) 原样保留。完整阅读 AuthService 默认 `fail()` 的 401 / unauthorized 契约后，将这个辅助断言改为精确 401 / unauthorized，再运行上述正式 RED。未改产品权限或扩大允许状态。
- 两次正式回归的 8 个相关 source/dist 文件哈希前后相等；models/model_usage 为 0、network_attempts 为 0、Windows processes 为 0、安装/卸载执行为 false。全部临时 SQLite、密钥材料和本次辅助 runner 均删除；handoff 本身保留供 root 审阅。

命令为 `node --check /tmp/marlin-lifecycle-tenant-projection-20261010.cjs`，随后分别执行 `node /tmp/marlin-lifecycle-tenant-projection-20261010.cjs red` 和 `node /tmp/marlin-lifecycle-tenant-projection-20261010.cjs green`；运行器从交付脚本中读取实际比较表达式。Node 为 v22.23.2 / Linux；这是临时 tmpfs 的真实 SQLite/API 契约证据，不是 Windows installed PASS、产品磁盘耐久或延迟结论。语法、差异、清理和哈希汇总见 [tenant-fix-verification.json](20261010-installed-lifecycle-tenant-fix-verification.json)。私有 NTFS 上的旧 handoff 若已有副本，须由 root 按新 SHA 原字节重新复制并审核，不能继续用旧 SHA 执行。

## 本次验证与待执行步骤

2026-10-10 后续独立只读审查发现一个测试 URL 误拒绝：当前正式同源码的 [root source smoke](20261010-root-source-desktop-smoke.json) 实际 `url` 为 `https://marlin.local/login`，但旧 handoff 空 smoke 仅允许 origin 和根斜杠。Root 授权只将该精确 `/login` 值加入允许集合；全部其他协议、主机、路径仍拒绝，未改产品或正式 stage。此前 tenant 修复版 SHA `a6f1d36e5cfc7220455b2418650a3a037ca80048753269c57303593e3eabe1d9` 是这次修改的原字节基线。

实际从 `smoke_and_auth` AST 提取原始 `need(..., "installed_smoke_failed")` 的完整谓词，用现存真实 root smoke JSON 及八个篡改 URL 只读重放：[RED](20261010-lifecycle-url-parser-worker-red.json) 10/11、exit 1（仅真实 `/login` 失败）；[GREEN](20261010-lifecycle-url-parser-worker-green.json) 11/11、exit 0。origin、根斜杠仍通过，HTTP、异域、子域、任意路径、查询/额外路径、javascript、data 均拒绝。完整 [单行 diff](20261010-lifecycle-url-parser-worker-fix.diff) 已保存；从新文件删除唯一新增 URL 字节后，整份文件与原基线 SHA 和字节完全相同。Python compile 通过，不生成 PYC。该检查没有运行 handoff 或 Windows installed 阶段、Core、GUI、安装/卸载或模型请求。

- [x] Python AST parse 与 `compile(..., 'exec')` 通过；未生成 PYC。
- [x] 提取内嵌 Node helper，实际 `node --check` exit 0；仅做语法检查，随后删除精确 `/tmp/marlin-installed-lifecycle-syntax-20261010.cjs`。
- [x] 12/12 Linux CLI 检查通过：四个 review-only phase、unknown flag、duplicate flag、equals form、wrong stage、missing phase、missing reviewed hash、missing prior receipt、native-platform refusal。全部 Windows processes=0、application/API calls=0、installer/uninstaller executed=false、paid calls=0。
- [x] Root 已全文审阅原 frozen script 与本计划。
- [ ] Root 审阅 tenant 与此次 URL 单行变更及最终 `20ebcc6f…` SHA，并重新复制原字节到私有 NTFS；旧 `a6f1d36e…` 副本不能继续执行。
- [ ] Root 在 final 正式 installer/sidecars 全部稳定后执行 code-upgrade；不能用旧 baseline installed smoke 或 artifact-only gate 授权本轮实际阶段。
- [ ] Root 逐 phase 执行并保留新 receipt / private log 的哈希；每次失败、已存在 attempt 或条件缺口都停在真实状态，不自动重试。
- [ ] 实际生命周期完毕后，由 root 持久化无秘密摘要与来源链接；清除已完成用途的精确 handoff/helper，不删除原验收数据、私有 backup、unknown 文件或 protected user QA。

该准备结果不证明 Windows Job、最终 installed code、私有 saved auth、默认 NSIS卸载的数据保留或重新安装已通过；也没有 normal tray exit 或 GUI 交互通过声明。
