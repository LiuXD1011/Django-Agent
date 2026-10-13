# 当前源码的 Windows owned-runtime 正式 prepare 与 package

当前结果：prepare 与原 builder 的 `--package-only` 均实际 exit0，同一 468 源冻结与新 staging，完整 ASAR/runtime 审计通过；安装器尚未执行，产品 GUI/普通安装链路及整个 Goal 尚未完成。prepare 原报告字节见[历史检查点](prepare-report.source.md)，后续 package 事实见末节。

2026-10-13 prepare 阶段：原 `scripts/build_windows.py --refresh --prepare-only` 在独占本地 Windows staging 实际完成，exit0；该 prepare 阶段没有执行 NSIS、安装器、产品 GUI、真实用户数据或外部厂商模型。整个 Goal、安装版、普通启动与真实业务后代退出仍未完成。

Root 先审核了 [runner](runner.source.txt)、[快照拷贝](copy.source.txt)、[自有 Job 观察器](audited-job.source.txt)和[精确绑定](runner-binding.json)。Job 观察器基于已审 `scripts/desktop/windows-job.py`，只增加原 root HANDLE 的 FILETIME 前后检查和终态回执；保留 suspended→private Job→resume、kill-on-close、原 HANDLE 等待、整树有界 reap，未增加 PID/image/port 清理。没有修改 production、测试、锁文件或他人产物。

## 源码、工具和独占目录

[源冻结](source-freeze.json)包含正式 builder 全量 468 输入，SHA `dd5b9d2f6a59fe3365177a3d35743fe4884e0e369ce15f54e6c6433ffc6cbccb`；与 Root [7 文件最终修复](../20261013-root-runtime-integration/source-revision-after-startup-timer-fix.json)逐项相等。copy/prepare 开始与结束均再次核验，最终 payload、gate、prepared 的 source_sha256 完全相等。

[实际 preflight](preflight.json)：Windows AMD64、`C:\Python313\python.exe` 3.13.3/SHA `d87063e5597f257004c731b66c59c56c91038861c6877b1a3dca6b8c4e919125`；build/product Node22.23.2 executable SHA `0d0f5e39f9f3d9587bc19f73eab3c2c9c4903fd02d6dbf9c853dd81b3d95fad4`，official archive SHA `1177b4137ba5adaa56354ae40f1080c7450e8ae09cecb47da459d1c52ac99f97`。CIM 仅返回相关 build 路径进程的公开身份，发现 writer 为 []，没有打印通用进程命令行。

[编译器 preflight](toolchain-preflight.json)及[本轮构建](runtime-job-build.json)记录实际 MSVC14.29.30133/Windows SDK10.0.19041.0，cl.exe SHA `8e4352b523f4ff37b429aea1d340094be1e17bbdf4f687247fc0be92d6eb9440`。

保留新 staging：`C:\Users\lxd\AppData\Local\Temp\Marlin Owned Runtime Build 20261013`。旧 `Marlin TS Sidebar A11y Final Build 20261012` 只读验证后快照拷贝；没有修改旧目录，没有将旧 prepared/gates/ASAR/release 当成本轮通过证据。新 output `Marlin Owned Runtime Installers 20261013` 尚未创建。

## 实际命令和进程终态

正式 child 命令如下，完整 argv、cwd、绑定及时间见 [prepare attempt](prepare-attempt.json)；环境来自原 builder 的最小环境 allowlist。

```text
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\home\liuxuedeng\Django-Agent\scripts\build_windows.py --refresh --prepare-only --work-dir "C:\Users\lxd\AppData\Local\Temp\Marlin Owned Runtime Build 20261013" --build-node "C:\Users\lxd\AppData\Local\Temp\Marlin Root Build Host 20261010\node-v22.23.2-win-x64\node.exe" --node-cache "C:\Users\lxd\AppData\Local\Temp\Marlin TS Final Build 20261010\node-cache" --output-dir "C:\Users\lxd\AppData\Local\Temp\Marlin Owned Runtime Installers 20261013"
```

| 阶段 | 实际结果 | 时间及原句柄终态 |
| --- | --- | --- |
| preflight | session5887/chunk905d4c actual0 | 旧依赖/payload重新校验68.3768秒；源与工具一致 |
| 依赖快照 copy | session7191/chunk381f15 actual0 | 180.7498秒；81264文件/2146852545字节；PID7320、FILETIME134363398341107534，同原HANDLE wait0/exit0、Job active0 |
| 正式 prepare | session4250/chunk195bf1 actual0 | 215.4512秒；2026-10-13T04:40:41.416537Z→04:44:16.875884Z；PID5400、FILETIME134363400414358266，同原HANDLE wait0/exit0、Job active0 |

[copy stdout](copy.log)、[copy 实际回执](copy-execution.json)、[prepare stdout](prepare.log)、[prepare 实际回执](prepare-execution.json)及[原 Job 回执](prepare.log.job.json)保留。prepare stdout SHA `41e42130155ebdc35ba5dac6055b49f6c88330b0d43bbaaba20a884711cd35cf`。两个阶段均未 timeout、所有自有句柄关闭；观察始终继续同一 live handle，没有重复启动。builder 完成后，runner 又实际调用原 `verify_prepared(ROOT, NEW)`，全部报告、源码、Electron分发与payload绑定再核通过。

## 本轮实际门禁

| 范围 | 实际结果 |
| --- | --- |
| Windows 前端 | 370PASS/0FAIL/0SKIP，TAP57548.9231ms；Vite build17.92秒；仅现有 chunk 大小 warning |
| Core TypeScript | staged `npm run build` / tsc成功 |
| Windows Core 路由/权限/HTTP/IPC/Langfuse | [24PASS/0FAIL/0SKIP](core-tests.log)，10138.1837ms |
| staged compiled production Runtime | [6PASS/0FAIL/0SKIP](production-runtime.log)，7348.7113ms；原 test/assert 保留，只按正式 gate 定义适配路径与 addon |
| native loader/SQLite/FTS5/vec/真实 IPC | [实际报告](core-verification.json)：Node22.23.2/NAPI10、SQLite3.53.4、vec0.1.9；60bit ID1152921504606847297在FTS与vec精确一致；真实TS Core、private JSON、HTTP listener false、capabilities200、实际owned Job授权且闭合、Core exit0 |
| Python helper/文档/Ragas | [11 fixtures](python-verification.json)：bundled Python3.13.16、isolated1/no_site1、Django不存在、Ragas0.4.3/core_rpc；没有付费模型请求 |
| 普通 Electron main loader | [实际报告](owned-runtime-electron.json)：Electron44.7.0/Node24.21.0/NAPI10，同一新 addon SHA及真实PID/FILETIME；无窗口、无Core；不是 RunAsNode 替代 |
| 受控 NextAuth/Langfuse | [实际报告](langfuse-native.json)：真实本地协议、private child JSON、isolated memory session、host-only HttpOnly Lax cookie、sandbox/no preload Node、取消/退出/配置变更、旁浏览器cookie保留，owned Core exit0、foreign requests0 |

这些时间是构建/测试工作耗时，不能充当产品启动、页面就绪或用户退出延迟。受控 Electron fixture 可创建自己的 sandbox 窗口，只使用本轮 disposable 数据及小型本地服务，没有运行产品 GUI或真实外部部署。

本轮重新编译 `payload/owned-runtime/runtime-job.node`，126976字节/SHA `b3875cb777f4890c7ca8340819ef2324a2a384454c0995aab15f75fc8e82e4a9`；不是 native 专项的 `b4f053…` 产物。编译绑定全部 native 源，官方headers/lib/SHASUMS精确pin，NAPI8/x64，实际各命令exit0。依赖仅 KERNEL32.dll和延迟node.exe；[compile原日志](native-compile.log)、[imports](native-imports.log)。Node22和普通Electron loader报告均实际加载此同SHA新文件。

[本轮 frozen gates](windows-gates.json)、[prepared](prepared-build.json)、[payload manifest](payload-source-manifest.json)与[最终校验](validation.json)已归档；payload完整25305文件。逻辑 index SHA仍为 `b36c6d28823e225a3c3daa8e75a74c2956982a21b64b4e8a0093e62cd795f278`，HEAD只读观察仍为 `dd5a356a3afdd67492d82a3b3e0e89dafffe2174`。未stage、commit、push、发布。

## prepare 收尾时的保留资源、清理及下一步

新 staging 及其中 app/payload、Electron dist、构建依赖、Python环境/worker、controlled-gates、native独占编译目录和所有原报告保留供Root package；旧 build-host Node/官方ZIP cache与旧staging保持原样。[自有临时助手](consumed-helpers.json)在实际终态后按精确SHA归档删除；没有清理任何其他worker、用户目录、数据库或凭据。

本轮完成授权的prepare。下一步由Root在当前 source freeze不变时，使用同原builder `--package-only` 重核源/ASAR，再对新安装包普通链路、中文空格安装目录、退出/解析后代及重启不重放验收。这里没有执行或计数这些动作，也不把旧安装包或独立native树实验替代新包验收。macOS/Linux交付未在本轮验证。

## 后续 package：同一冻结的实际 NSIS 与 ASAR 门禁

Root 读取 prepare 原始结果后明确批准继续原 builder `--package-only`。执行前再次审核 [package runner](package-runner.source.txt)、[相同字节 Job 观察器](package-job.source.txt)及[精确绑定](package-runner-binding.json)，SHA分别为 `e77cc49984e0dca7fac9977627fa7df5bb4dda6817c6e7389b16b2d3d8704127`、`8df004abcfe7ab86b13aaaac321fa0b3356cdb12ac467beb77e5181d57cd6e93`、`4c14ba299aa17d6119ed2fe2ae2f072490f1d563838a02e863ced8f2f47952ab`。

[review preflight](package-review-preflight.json) native session46917/chunk16fe2f actual0；正式执行前[再次 preflight](package-package-preflight.json)也实际重核：原 `verify_prepared` 通过、468 源同一冻结、prepared SHA `927b1e59da39b82500f4575f5c2831f2e2058c7a55cc7c580364117f6b6998af`、gates SHA `585cef28b0064031a2af94a0e7ddbc13fcc86664f59e26537381b66f5ac1a9f3` 与归档字节一致，output/release不存在、相关 writer []。没有复用历史 package 绿灯。

唯一正式 child 命令（完整 argv/cwd/time 见[attempt](package-attempt.json)）：

```text
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\home\liuxuedeng\Django-Agent\scripts\build_windows.py --package-only --work-dir "C:\Users\lxd\AppData\Local\Temp\Marlin Owned Runtime Build 20261013" --build-node "C:\Users\lxd\AppData\Local\Temp\Marlin Root Build Host 20261010\node-v22.23.2-win-x64\node.exe" --output-dir "C:\Users\lxd\AppData\Local\Temp\Marlin Owned Runtime Installers 20261013"
```

[实际终态](package-native-terminal.json)：session92899/chunkd06449 actual0，285.7359秒，2026-10-13T04:55:34.651653Z→05:00:20.388985Z。原 root PID12372/FILETIME134363409346552093，原HANDLE前后相同FILETIME、wait0/exit0；原Job accounting active0，全部自有句柄关闭，无timeout。[完整原 stdout](package.log)、[实际回执](package-execution.json)及[原Job回执](package.log.job.json)保留；stdout SHA `f9ca21773e206c47cdeb976cac09624540aab3f2978b178efe02ec66fa1b0073`。观察始终继续同一live session，未重启/重复打包。

原 builder 实际调用 electron-builder `--win nsis --x64 --publish never`，生成 win-unpacked 与 NSIS，随后再次冻结核验、原 `verify_prepared`、实际 `audit-asar.cjs`、再核prepared/源后才复制最终产物。runner 在子进程终态后又实际重核prepared、源清单、安装器stage/output字节及sidecar。新 desktop版本沿用源码0.6.2，Core0.7.0；未改版本、未创建tag、未发布。应用和安装器按既有 `signExecutable` 配置未签名。

新安装包保留于：

```text
C:\Users\lxd\AppData\Local\Temp\Marlin Owned Runtime Installers 20261013\Marlin-Setup-0.6.2-x64.exe
size: 401906433 bytes
SHA256: 869a0401224675d15d1aa515b2a587a657d4caf704044a8ac641a49ab7f896e9
```

[原 SHA sidecar](installer.sha256)与stage/output两个安装器字节实际完全相等；仅核PE的MZ头，没有执行任何安装器。新output还导出完整payload manifest、prepared、gates、native编译、Node loader/IPC、worker/Python、普通Electron loader、Langfuse和ASAR报告；九份输出报告都与本次证据归档的原字节相等，详见[package最终校验](package-validation.json)。

[实际 ASAR审计](asar-audit.json) SHA `5e2937f9ce0ccb71993fd83b23c766b6cad1f69e70879672634871bf588c7814`；`app.asar` SHA `d4d16b42a36b0ec19357c74574217cd7deaa3969a6c61a99404af5e342fcc530`，实际仅12项已审白名单，含owned-runtime/bootstrap；逐文件代码字节等于staged app，package metadata符合upstream cleanup。

实际打包 `resources/runtime` 的全部25305文件与本轮 payload manifest逐字节匹配，没有添加/删除/改动；manifest SHA `2415f718ccde9b2b0506174deafbce88e6cca95a983694bd15c70693c3f963de`，新addon仍 `b3875cb777f4890c7ca8340819ef2324a2a384454c0995aab15f75fc8e82e4a9`，与prepare中的真实Node22/普通Electron44加载相同。468源冻结、prepared和gate原报告保持，逻辑index仍b36c6d…、HEAD只读dd5a356…。

runtime inventory无Django目录或manage.py，manifest的Django/system Node/system Python要求均false；bundled Python报告实际Django import为ModuleNotFoundError。打包资源含编译完成的前端assets和TS Core dist；实际index引用静态assets而非 `/src/`，ASAR/preload/runtime通过已审链路使用这些资源，包的资源布局不需要Vite开发服务器。这是构建/静态资源及prepare真实门禁结论，尚未声称安装版普通启动无需系统运行时的实际操作验收已通过。

[package临时助手](package-consumed-helpers.json)在actual0之后按归档精确SHA删除，finalizer也归档删除。新staging、win-unpacked、NSIS原输出与独占最终installer/output均保留。未改production/tests/dependencies、主验收文档或他人文件，无Git写入、真实用户数据、API Key、付费模型、产品GUI或安装器执行。

本子任务完成授权的prepare与package。下一步由Root对新安装包执行隔离安装/普通启动、中文空格路径、实际业务worker后代、关闭后台/真正退出和重启不重放验收；仍不得以本次编译/受控门禁替代这些交付条件。整个Goal保持未完成。
