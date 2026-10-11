# 正式 Windows TS 构建检查实施计划

日期：2026-10-10。设计与实施已由 Goal/root 批准；初始实现阶段不执行 NSIS。统一冻结后 root 已授权本地 NSIS 与审计；不安装、发布或操作 QA 窗口。

## 设计和范围

保留 `scripts/build_windows.py` 的干净构建与现有参数，将已验证的 C 流程参数化落库。新增受控 `--refresh`、`--verify-only`、`--package-only`：只复用带构建所有权标记、锁文件相同且完整 payload 清单一致的目录；新增、删除、改写文件均拒绝复用。源码实际输入在复制前、验证后及 NSIS 后重新核验，审计成功后才复制安装器到输出目录。

- `scripts/build_windows.py`：源输入/产物清单、版本检查、复用、构建顺序和结果发布。
- `scripts/desktop/windows-gates.py`：参数化核心 HTTP/IPC 6 文件（原 24 用例）、生产 Runtime 原 6 用例、实际 Electron/NextAuth 与 Python helper 检查；任何失败不生成 verified 报告。
- `scripts/desktop/windows-job.py`：仅构建夹具使用的 Win32 JobObject 子进程控制；挂起创建、先归属后启动、超时/退出清理自己的后代，失败不降级为泛化 PID 清理。
- `scripts/desktop/audit-asar.cjs`：现有 10 项明确资产、打包字节、清理后的 package metadata 和完整 runtime inventory 比对。
- `scripts/test_build_windows.py`：合成打包单测及实际平台夹具回归。原 Runtime 测试断言全部保留，仅固定、计数核验的测试路径/TS 启动适配。
- `scripts/desktop/build-python-runtime.py`：后续真实 NSIS 审计定位的 native utility shim 仅增加 `-B`，避免其在受控生产树内生成被现有资源过滤排除的派生 bytecode；不改变锁、模块或许可证。

不修改原生 DLL utility、Python pin/锁、Electron 业务、前端、QA 数据或根启动器。`bundle_windows_native.py` 仍是受控 Python builder 的必要 Cairo/许可证步骤。root 已把前端原静态夹具改为 `packages/core/src/settings/startup.ts`；构建工作目录按相同相对路径复制该文件，不再依赖或复制 `config/settings.py`，不导入 Django。

## 版本和启动约束

产品 Node 固定官方 SHA 校验的 22.23.2；本轮构建主机使用同版本。构建主机版本检查严格遵循当前 `node-gyp`：`^22.22.2 || ^24.15.0 || >=26`，拒绝 Node 23/25 和过早 Node 24。Electron 44.7.0、builder 26.15.3、Python 3.13.16 及五个锁文件不变。

将 app 的 `npm ci` 移至 `--prepare-only` 返回前，并显式执行锁定 Electron 包自带的 `install.js`，使准备结果同时包含 Electron 开发壳和 payload。Electron 44.7.0 的实际 npm 包没有 postinstall；官方脚本会使用本包 `checksums.json` 校验缓存与新下载的 ZIP。构建环境不转发 mirror、override、remote-checksum 或 force 选项。干净构建和源码 refresh 均在 gate 前执行这个固定脚本、检查真实 executable，再核验完整分发清单。root 的新 Node 启动器使用 `<work>/app/node_modules/electron/dist/electron.exe <work>/app --data-dir ...`；成品通过 `Marlin.exe` 启动，不依赖系统 Node/Python或开发服务器。

准备状态还绑定 Electron 开发分发的完整 SHA/inventory（exe、DLL、resources、version、package metadata 和 path.txt），新增文件也失败。builder 与启动器共同解析 gate 的正式 schema、测试计数及固定 native/Python/Langfuse 报告的哈希和实际字段；未知状态、部分报告、artifact-only、失败或跳过用例不能授权启动或打包。

## 实施与验收

- [x] 写源码新增/变化、payload 新增/删改、版本区间、prepare-only 壳就绪、NSIS 后变化拒绝输出的回归；先运行并确认 RED。
- [x] 最小实现输入清单、严格复用与顺序；运行同一单测得到 GREEN。
- [x] 为固定 fixture 路径适配、JobObject 归属/超时/无关子进程保留与 ASAR 字节/额外文件写 RED，再实现并得到 GREEN。
- [x] 运行相关打包单测和语法检查；真实 Windows 使用独立构建 fixture 运行核心/Runtime/Python/Electron 协议边界，不操作 QA。
- [x] 保存非敏感结果、命令、源哈希和未执行 NSIS/安装/GUI/厂商验收的范围；检查五锁无变化并通知 root 冻结。

仓库根打包单测命令为 `python -m unittest scripts.test_build_windows`；Windows 原生 probe 必须指向已准备的 Windows production 模块及固定 Node，不能用 WSL/Linux node_modules 或 skip 替代。最终 NSIS 必须等待 root 的前端/核心统一冻结后另行执行，`--publish never` 不变。

Windows 单测使用可信构建目录的 `MARLIN_TEST_NODE`、`MARLIN_TEST_CORE_DIRECTORY`、`MARLIN_TEST_APP_DIRECTORY`、`MARLIN_TEST_ASAR_DIRECTORY`。POSIX symlink/shebang 测试保留为对应平台单测；Windows 的实际 JobObject、SQLite/FTS/vector/IPC/ASAR 均执行。正式 gate 的核心和 Runtime TAP 不允许任何 skip。

干净准备命令：`C:\\Python313\\python.exe scripts/build_windows.py --work-dir C:\\MarlinBuild --build-node C:\\BuildNode\\node.exe --prepare-only`。依赖未改变时用 `--refresh --prepare-only` 更新当前冻结源码；已准备且源码完全相同可用 `--verify-only` 重新验证，最后 `--package-only --output-dir C:\\MarlinInstallers` 运行 NSIS 和完整 ASAR/runtime 审计。默认无模式参数仍为干净构建后打包。

独立 `windows-gates.py --artifact-only` 只检查现有候选产物，报告 `scope=artifact_only`；正式 builder 只接受 `scope=frozen_source`，旧 C 或独立回归不能授权最终包。所有 gate 使用私有 JobObject；挂起进程必须先归属后启动，失败不降级为名称、端口或 PID 搜索清理。清理同时等待保留的 owned process 句柄，避免 job 活跃数为零而实际退出事件尚未完成的竞态。[Windows JobObject 契约](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)

2026-10-10 冻结实现后的限定单测：Linux 35 项中 33 通过、2 项 Windows 专用跳过，5.442 秒；原生 Windows 35 项中 31 通过、4 项 POSIX 专用跳过，零失败。Windows 的真实 owned Job 超时/父先退出后代清理、无关进程保留、junction 拒绝、SQLite/FTS/vector/IPC 和实际 ASAR 均执行。原生证据保存于独立构建目录 `C:\Users\lxd\AppData\Local\Temp\Marlin TS Formal Build 20261010\repository-checks\windows-build-unit.{json,log}`，Linux 输出为同目录的 `linux-build-unit.log`。这些限定单测不替代正式 frozen_source gate、NSIS 或 GUI/厂商验收。

第一轮正式 `--refresh --prepare-only` exit 0：360 个实际源码输入、73 个 Electron 分发文件、25,280 个 payload 文件；Windows 前端 238/238（0 skip，228,907.4419 ms）、Vite build、Core tsc、核心 24/24、生产 Runtime 6/6、Python 11 文件夹具/110 依赖及受控 Electron/NextAuth 均通过。原始报告和日志已逐字节核对保存为 [`20261010-windows-repository-*`](../refactor-evidence/20261010-windows-repository-gates.json)，不算可见 GUI 或厂商验收。

随后真实 NSIS 已生成内部 exe，但 `--package-only` exit 1，完整 runtime 审计拒绝输出：原 payload 包含 `zstandard/__pycache__/__init__.cpython-313.pyc`，桌面已有生产过滤规则排除该派生缓存。已确认它来自 Python builder 的 native utility shim 使用 `-I -S` 而未带 `-B`；没有删除文件、改写旧 manifest 或放宽 audit。原始 RED [日志](../refactor-evidence/20261010-windows-repository-nsis-red.log)和生成但未交付的 [artifact 事实](../refactor-evidence/20261010-windows-repository-nsis-red.json)已保留。root 已批准仅修 shim `-B`，保留原过滤；另 root 的实际源码 CLI smoke 发现 CRLF marker 与启动器 LF 比较不一致，启动器 owner 已修复并重新冻结。

producer 回归使用真正的 `make_runtime` native shim/隔离 Python 进程导入临时受控包，网络、archive 与 wheel 安装有明确 unit 替身。旧实现 Linux/Windows 均生成 bytecode 而 RED；仅增加 `-B` 后两平台 GREEN，并使用已安装 FileMatcher/copyFiles 与真实 ASAR 验证完整 fixture，保留正常模块改写、许可证删除和额外 pyc 的拒绝。全相关回归 Linux 36 项中 34 通过、2 Windows 专用跳过（6.489 秒），Windows 36 项中 32 通过、4 POSIX 专用跳过（18.737 秒）。[原始证据与范围](../refactor-evidence/20261010-windows-repository-python-producer.json)。后续 root 要求从新的空 `Marlin TS Final Build 20261010` 完整 clean 构建，可只读校验并复用压缩缓存；不复制旧已展开 Python runtime、不修改旧 stage 或 manifest。新的正式 producer 与资源审计通过前，不称最终产物就绪。

新的空工作目录已实际 clean 构建：缓存只复用 SHA 验证的 Python ZIP、110 wheel、25 Cairo 归档及官方 Node ZIP；前端原生 238/238、Vite/Core 编译、全新 Python 11 夹具/110 依赖、原生 SQLite/FTS/vector/IPC 均通过，新 Python bytecode 文件为 0。随后 app `npm ci` 成功但缺少 Electron exe，正式 prepare 在 gate 前停止，未运行 NSIS。[失败原始日志和实际范围](../refactor-evidence/20261010-windows-repository-final-clean-red.json)已保存；临时 outer runner 把 CompletedProcess 当数值序列化的错误单独记录，没有 verified 状态报告。

修复官方 Electron 安装顺序的 orchestration 回归在 Linux/Windows 均先 RED，再仅修固定脚本调用后 GREEN；现有完整相关单测 Linux 37 项中 35 通过、2 Windows 专用跳过（6.568 秒），原生 Windows 37 项中 33 通过、4 POSIX 专用跳过（23.758 秒），零失败，语法和 diff 检查通过。[日志、源码哈希及范围](../refactor-evidence/20261010-windows-repository-electron-install.json)明确区分合成 orchestration 单测与随后仍待执行的实际官方 installer/formal gate。root 同步验证 RagasBridge 运行时 bytecode 问题；双方共同冻结后使用正式 refresh 重建源码、重新绑定清单和 gates，再执行 NSIS，不手动修 payload 或旧 manifest。

共同冻结官方 Electron 安装步骤与 RagasBridge `-B` 后，新的 Final Build 已实际 `--refresh --prepare-only` exit 0，777.715 秒：361 个源码输入、73 个 Electron 分发文件和 25,279 个 payload 文件，派生 bytecode 为 0。Windows 前端 238/238、Vite/Core 编译、核心 24/24、生产 Runtime 6/6、Python 11 夹具/110 依赖、SQLite/FTS/vector/IPC 以及受控 Electron/NextAuth 全部通过。原始 14 份日志/报告逐字节归档，root/LICENSE、Node/Python 许可证和 MT19937 许可证均绑定 SHA；五锁未变化。[本次正式准备证据](../refactor-evidence/20261010-windows-repository-final-refresh-proof.json)保留独立历史快照，没有覆盖此前 C 或失败记录。

该准备快照随后由 root 实际运行源码 CLI smoke，exit 1、3,564.781 ms，未创建数据或启动窗口：启动器要求 `better-sqlite3/build/Release/better_sqlite3.node`，而已通过真实 native gate 的 production 包使用其它实际布局。启动器 owner 正在修复该检查；本次 prepared/gates/payload 原样保留，NSIS 暂停。后续须按正式 builder refresh 重新绑定新源码和报告，不手改 inventory，也不把已通过构建门禁等同源码启动成功、安装或可见 GUI/厂商验收。

启动器 owner 已根据锁定 `better-sqlite3@13.0.3` 的实际官方 loader，把唯一必需路径修为 `prebuilds/win32-x64.node`，并完成 Linux 26/26、原生 Windows 14/14 回归。共同冻结后，正式 refresh 再次 exit 0（784.857 秒）；前端 238/238、Vite/Core 编译、Core 24/24、Runtime 6/6、原生数据库/IPC/Python 和 Electron 夹具均通过。与上一历史快照相比恰 2 个源码输入变化（launcher 及其测试），25,279 个 payload 文件 SHA 和 73 个 Electron 分发文件 SHA 全部相同，没有改写 payload 来满足启动器。本轮 14 份原始报告另存为 [`final-launcher-refresh-*`](../refactor-evidence/20261010-windows-repository-final-launcher-refresh-proof.json)。root 正独立核验新来源并执行实际源码 CLI smoke；在其通过并授权之前，继续不运行 NSIS。

root 对该新准备来源的实际 Windows 源码 CLI smoke 已 exit 0，mounted=true、Node 未暴露、真实 TS IPC 且无 HTTP listener，两个无关 QA 的保留句柄均仍存活，prepared/gates/payload 三个 SHA 独立匹配且执行前后不变。命令全程 107,553.7582 ms 含源码和资源哈希；应用内部 startup_ms=1,604.8697 仅是当前环境单次样本，不称冷机性能。PNG 仅背景，因此没有可见 UI ready 承诺。[源码 CLI 原始 JSON](../refactor-evidence/20261010-windows-repository-source-cli.json)、raw log 与 PNG 已按字节保存，与此前两次实际失败分开。root 随后授权正式 `--package-only`：NSIS、完整 ASAR/runtime 和执行后源码围栏通过后才复制到 Final Installers；不运行安装器、不操作 QA。

当前冻结源码的候选 NSIS 已正式 `--package-only` exit 0，835.498 秒，`--publish never`。10 个 ASAR 固定资产与全部 25,279 个 runtime 文件的精确审计通过，打包后完整源码围栏通过；prepared/gates/payload manifest 三个 SHA 前后不变，派生 bytecode 为 0。专用输出目录 `C:\Users\lxd\AppData\Local\Temp\Marlin TS Final Installers 20261010` 内恰有安装器、SHA 文本及 7 份 sidecar 报告，共 9 文件；原生复算确认 sidecar 与 stage 字节一致，内部/外部 exe 一致。

候选文件 `Marlin-Setup-0.6.2-x64.exe` 为 401,778,413 字节，SHA256 `1a9f6ccec8d154d9ed7019ab8b05416dc038e4c51ee23f4d816ca541268950bc`。11 份本轮 raw 证据和 [候选构建 proof](../refactor-evidence/20261010-windows-repository-final-nsis-proof.json)已逐字节归档；既有 build evidence 只追加 `repository_final_candidate`，旧基线、C 和每轮失败保留原值。没有安装、升级、卸载、运行安装器或操作 QA，未声称可见 GUI、真实外部厂商或核心评测通过；root 的真实评测仍需独立收尾，因此该包仍为候选。
