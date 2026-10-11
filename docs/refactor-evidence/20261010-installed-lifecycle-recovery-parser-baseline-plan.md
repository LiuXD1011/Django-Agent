# 固定安装生命周期手工恢复计划（2026-10-10）

**Goal:** 在不重放第三次成功 smoke/auth 的前提下，独立复核缺失的后置条件，生成新的恢复收据和 refresh 后保留基线，供 root 逐阶段决定卸载保留、重装、post-reinstall。

**Architecture:** 新一次性 wrapper 只在明确批准执行时 import 冻结 harness 的验证和 owned Job 函数，不调用其 run/main。旧失败目录/收据不改，使用独立 recovery-owned 目录，固定阶段按前序原字节 SHA 串接；无通用路径、命令或杀进程入口。

**Tech Stack:** Windows Python3.13 测试主机、原 frozen Python harness、原 Windows JobObject、只读 SQLite/文件 hash、正式 installed TS Core IPC（只在未来明确 post-reinstall）。本轮仅写工具和纯逻辑测试，禁止 Windows/Core/API/GUI/安装动作。

## 固定授权边界

原 harness `/tmp/marlin-installed-lifecycle-20261010.py` 548行36701bytes，SHA `cbf8d846590bef7ef54eb12dfaeac635e53af5c312e92f14b613128d2547af30`，NTFS reviewed-3 版本必须同字节。第三失败收据 SHA `a8dbbdf6b725fbd9d9dccf5dc7a7572ad10e2d54a60e7b01d6edee19faf814a8`，error_code existing_application_process_refused，原guard未保存命中条件，不能推定原因。只继承并重核同一次真正成功的 hidden_smoke/saved_auth 产物，不再次执行。

固定 formal stage、installer、安装/数据目录、GUID、原 user/KB、PID15700和exactexe均沿原harness；后续复用 actual formal_identity、installed_identity、check_registry、protected_handle、retained_state、run_fixed_tree/smoke_and_auth，不能换renderer或caller参数。

## 独立阶段

1. `recover-post-upgrade`：原8项产物 hash/同源成功谓词、当前 protected handle+exactimage、当前 CIM零候选/策略、formal source/artifact/full code/runtime/registry、原 backup12表与原钥匙hash。仅 normal_refresh_used=true 已实际证明的 device_sessions 表变化允许，count保持；其他11表必须完全相等。生成新的 retained-baseline，原失败文件不改，旧preflight原因仍unproven。
2. `uninstall-retain`：精确 verified恢复receipt SHA及新baseline绑定；默认实际owned注册卸载器 /S /currentuser，不带delete-app-data、/D或_?=；等原privateJob整个树退出。数据完整文件/12表/钥匙对refresh后baseline完全相等，注册和安装目录消失，PID15700仍活。
3. `reinstall`：精确前序卸载收据SHA；目标空、同installer正式hash，固定silent/currentuser/no-shortcut与NSIS最后raw /D尾参；code/runtime/注册全部核验，完整数据hash未变。
4. `post-reinstall`：精确前序重装收据SHA；先匹配旧baseline，再且仅此phase调用原smoke_and_auth，真实正常refresh如发生单列device变化与新的final-retained-state，不声称刷新后DB字节等于旧baseline。

每phase默认review-only，执行必须明确 phase、root核准的新工具SHA、原harnessSHA；后续还须前序原字节SHA。独占wx/fsync attempt和receipt，已有即拒绝，任何失败留unknown/failed证据，不自动retry/overwrite。当前/后置CIM仅保存3项safe事实，不输出进程commandline或任意用户信息。

## 本轮制作与验证

- [x] 全文读取原harness与第三失败/原smoke/auth，核原字节hash。
- [x] 纯逻辑先RED验证实际normal_refresh允许device变化，但未知/错身份/缺hash/其它表变化必须拒绝。
- [x] 实现固定wrapper，复用验证/owned functions，旧run不调用。
- [x] AST/compile不生成PYC，默认/非法参数只运行Linux静态CLI，纯逻辑和自己的wx/fsync临时文件测试。
- [x] 根本不启动Windows/Core/SQL/API，不执行任何phase；持久化安全静态证据/计划/最终SHA，清理临时test，冻结handoff交root。


## 冻结交付与证据范围

新 handoff `/tmp/marlin-installed-lifecycle-recovery-20261010.py`：325行、27190bytes，SHA256 `e24e50f67900f1c97c7cad0d46e90e8eb1e13ac9b185cd8f4aa326558dbffb69`，后续不修改。只复用 NTFS 固定 `marlin-installed-lifecycle-reviewed-3-20261010.py`；本轮实际文件读取确认它和 `/tmp` 原工具均为 `cbf8d846590bef7ef54eb12dfaeac635e53af5c312e92f14b613128d2547af30`，原工具未改。

[原安全元数据/8项哈希 fixture](20261010-installed-lifecycle-recovery-parser-baseline-fixtures.json) 来自真正第三次收据、smoke结果、auth结果和 attempt，只有元数据/文件hash，没有数据库行、PW、token、Key、密文、原日志正文。已完整读第三失败收据；原8项文件最终仍等于工具 ORIGIN_FILES。它们证明第三次 smoke/auth 的既有成功，不能证明当时为何命中后置拒绝，亦不能当本轮新 GUI/应用通过。

- [首次纯逻辑 RED](20261010-installed-lifecycle-recovery-parser-baseline-logic-red.log)：允许的 actual-refresh device 差异未实现，1项失败；不是产品修改。
- [两个安全回归 RED](20261010-installed-lifecycle-recovery-parser-baseline-safety-red.log)：20通过、2失败，分别是 bool false被当integer0、post-reinstall离线读之前缺当前进程检查。
- [最终纯逻辑 GREEN](20261010-installed-lifecycle-recovery-parser-baseline-logic-green.log)：22/22，0失败/skip，0.103s。包括真实安全第三次元数据、合成表hash/前序收据、拒绝外部URL/错误owner/source或审批身份漂移的相关输入、当前3事实schema、以及自己临时目录实际wx/fsync不覆盖。
- [静态测试源](20261010-installed-lifecycle-recovery-parser-baseline-logic-test.py)、[Linux CLI证据](20261010-installed-lifecycle-recovery-parser-baseline-cli-static.json)、[验证汇总](20261010-installed-lifecycle-recovery-parser-baseline-verification.json)：AST/compile通过且没有生成PYC，5项默认/各phase review-only和10项非法输入/native-platform refusal符合预期，共15/15。CLI不import旧harness，执行branch在Linux native guard前停下。

本轮只读取NTFS已有安全产物与hash、编写脚本和纯逻辑测试。**没有执行新phase、Windows/CIM/handle、Core、SQLite、API、smoke/auth、安装/卸载、GUI或模型请求**。当前零候选/Undefined策略是root先前独立描述，本轮没有重复查询；工具未来的真实查询必须重新得到safe facts，不能复用计划中的0当证据。12表/keys/current protected handle/code inventory也必须由root后续明确执行工具才算实际核验。

## Root 独立审阅后如何恢复（当前未执行）

root先全文读325行新wrapper和548行冻结harness，按原字节复制新tool为固定父目录中的 `marlin-installed-lifecycle-recovery-20261010.py`；工具拒绝换目录/换basename、link/junction/reparse，导入的reviewed-3必须同SHA。旧目录 `.lifecycle-20261010-reviewed-3` 和其failed receipt/attempt/probe产物原封不动；不要再执行原harness的post-upgrade（它的前置12表等于旧backup条件已不符合真实refresh后状态）。

以下是未来root手工命令形状，不能解释成当前授权执行或实际执行日志。各phase之间都须停止、读实际收据与原字节SHA，再独立决定下一步，不把这些块合成自动顺序脚本。

```powershell
$qaParent = 'C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010'
$tool = Join-Path $qaParent 'marlin-installed-lifecycle-recovery-20261010.py'
$work = Join-Path $qaParent '.lifecycle-20261010-recovery-reviewed'
$recoverySha = 'e24e50f67900f1c97c7cad0d46e90e8eb1e13ac9b185cd8f4aa326558dbffb69'
$harnessSha = 'cbf8d846590bef7ef54eb12dfaeac635e53af5c312e92f14b613128d2547af30'
# 完全review-only，不访问Windows API/DB，不import原harness。
& 'C:\Python313\python.exe' -I -B $tool
```

只有root核查源码SHA及固定第三失败证据后明确执行，才可生成新的恢复收据。这阶段仅新的PowerShell只读进程事实/registry/native handle/SQLite/file checks，不再执行smoke/auth/API/NSIS，也不重新更新会话凭据。

```powershell
& 'C:\Python313\python.exe' -I -B $tool `
  --phase recover-post-upgrade --execute-reviewed-phase `
  --reviewed-recovery-sha256 $recoverySha --reviewed-harness-sha256 $harnessSha
```

成功才生成新 `.lifecycle-20261010-recovery-reviewed\recover-post-upgrade.json` 与 `retained-baseline.json`；成功receipt必须 `state=verified`，包括：原failed8项hash不变、`original_preflight_failure_cause=unproven`、原probes引用且`old_probes_replayed=false`、两个当前CIM三字段事实、formal source/artifact及完整installed/runtime前后核验、原registry、protected15700 exactimage handle仍活、12表比旧backup只允许actual device refresh变化、count不变、原keys hash、已固定新完整数据基线hash。11表必须精确相等；不会声称device_sessions变化后12表与旧backup全相等。该恢复是补齐当前后置条件，不把旧failed改成verified，也不声称已经证明旧失败原因。

原backup和原私有decryption manifest仍作为来源，`retained-baseline.json`基于第三次真实refresh之后的当前状态。它包含完整12表行hash、完整数据文件inventory及keys hash，无行值/Key值；以后卸载保留/重装都必须严格匹配这个baseline。恢复phase如果已有work/attempt/receipt，或条件不满足，立即STOP保留失败文件，不清marker或自动重试。

## 用成功恢复收据继续三个独立阶段

root先读取恢复收据，核基线文件与receipt中的hash，并决定唯一一次卸载。仅owned HKCU/GUID注册匹配、当前零候选、protected handle、正式身份及完整数据基线全部通过才执行。未带 `--delete-app-data`、`--updated`、`_?=` 或 `/D`；exact owned uninstaller `/S /currentuser`通过原private Job完整等待，注册和安装目录必须实际消失。

```powershell
$prior = (Get-FileHash -LiteralPath (Join-Path $work 'recover-post-upgrade.json') -Algorithm SHA256).Hash.ToLowerInvariant()
& 'C:\Python313\python.exe' -I -B $tool `
  --phase uninstall-retain --execute-reviewed-phase `
  --reviewed-recovery-sha256 $recoverySha --reviewed-harness-sha256 $harnessSha `
  --prior-receipt-sha256 $prior
```

root读取新verified `uninstall-retain.json`，确认完整数据字节/12表/keys对refresh后基线完全相同、原failed保留且15700仍活，再独立决定重装。只用同正式installer/full facts，固定silent/currentuser/no-desktop-shortcut；原harness的NSIS最后raw `/D=<固定应用目录>`调用保留，不交给shell，也不接受任意路径。

```powershell
$prior = (Get-FileHash -LiteralPath (Join-Path $work 'uninstall-retain.json') -Algorithm SHA256).Hash.ToLowerInvariant()
& 'C:\Python313\python.exe' -I -B $tool `
  --phase reinstall --execute-reviewed-phase `
  --reviewed-recovery-sha256 $recoverySha --reviewed-harness-sha256 $harnessSha `
  --prior-receipt-sha256 $prior
```

root读取verified `reinstall.json`，确认新installed code/runtime/registry与正式artifact/source相同、数据仍完全等于baseline，再独立决定post-reinstall。**只有此最后阶段才执行新的重装后smoke/auth**，不是重放第三次旧post-upgrade；仍是正常保存的CoreIpcAdapter认证和必要时一次正常refresh，无AuthContext/Key/PW输入，0模型/网络，120s原owned Job/每probe预算。

```powershell
$prior = (Get-FileHash -LiteralPath (Join-Path $work 'reinstall.json') -Algorithm SHA256).Hash.ToLowerInvariant()
& 'C:\Python313\python.exe' -I -B $tool `
  --phase post-reinstall --execute-reviewed-phase `
  --reviewed-recovery-sha256 $recoverySha --reviewed-harness-sha256 $harnessSha `
  --prior-receipt-sha256 $prior
```

post-reinstall先确认旧retained baseline精确匹配，结束时记录真正新auth是否refresh、device差异及完整文件inventory是否相同。若发生新的真实refresh，保存独立 `retained-post-reinstall.json`和SHA，保留原baseline；不把刷新后的DB字节冒充旧字节。只有正常probes/完整Job退出/current进程0/code-runtime-credential-source全部核验和protectedhandle仍活才verified。所有阶段GUI/trayquit均false，installer maintenance-stop不能计normal tray quit。原frozen run_fixed_tree的600s NSIS预算、5s失败清理和Job kill-on-close逻辑不改，不声称新wrapper已做Windows进程测试。

## 留存与失败边界

新work每phase exclusive/fsync attempt，成功/失败receipt都exclusive，不覆写原文件；存在attempt就STOP。所有后续阶段同时绑定新tool SHA、旧harness SHA、第三failed/8proof hash、完整正式identity、精确前一条receipt原字节SHA和新retained-baseline原字节SHA。未知/失败不得继续下一阶段，不能清attempt再执行，也不得回用原harness规避refresh基线。

stdout只safe phase/state/path/hash/0 paid，原始subprocess stderr/stack不发布；query只保存candidate_count、cim_available、policy。卸载若directory/registry没真正消失，或键/文件/表hash变化，即使bootstrap exit0也失败。成功仍须等待整个owned Job的active processes0，不推称每个后代exit码。

本轮精确清理自己的临时测试runner与日志（稳定原字节证据保留），新handoff供root审阅后使用完才删。未触碰root旧harness、原failed证据、STATUS/TEST-MATRIX、source/stage、Windows用户QA/真实四模型或原数据。
