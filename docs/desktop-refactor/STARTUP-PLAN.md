# 源码启动入口替换计划

日期：2026-10-10。root 已批准本设计与限定文件归属。本轮不提交、不改子包版本/依赖/锁、不启动真实 Windows 窗口、不接触 QA 数据或付费厂商。

目标是让常用根命令启动已编译的 TypeScript 主业务；桌面启动仅使用既有 Windows x64 builder 准备的 Electron 应用。Python 只用于构建和独立解析/评测 helper。

文件范围：根 `package.json`；新增 `scripts/desktop/start-desktop.cjs` 与 `scripts/desktop/startup.test.cjs`；本计划。

## 已确认的契约

- `packages/core/dist/tools/dev-server.js` 是实际编译入口，接受现有 `--data-root`、`--port`、`--ui-origin`、parser/Ragas 成对参数。`start:local` 直接运行该文件，使用前先 `npm run build`；npm 的 `--` 后参数原样转发。
- 根 `test` 聚合真实 core/frontend/desktop/startup 命令；`build` 仅 core build + frontend build；`typecheck` 仅 core typecheck。frontend 没有 typecheck，desktop 没有 build/typecheck，不虚构子包命令。`build:desktop=python scripts/build_windows.py` 是构建入口。
- builder-owned 工作目录标记为 `.marlin-build`，仅接受完整 `marlin-electron-build-v1\n` 或 Windows 官方 writer 的 `marlin-electron-build-v1\r\n`；应用位于 `app`，实际开发 Electron 位于 `app/node_modules/electron/dist/electron.exe`。
- 现应用文件白名单：main/runtime/ipc/preload/protocol/langfuse.cjs、loading.html、package.json、LICENSE、icon.png；另有 builder 的 package-lock、payload、node_modules、NSIS release。
- payload `source-manifest.json` 的 format 为 `marlin-electron-payload-v1`、platform 为 `win32-x64`；files 保存所有 payload 文件的 SHA256（不含自身），包括编译 core、frontend、Node、独立 Python、workers、tokenizer cache/native modules。
- main 实际接受 `--data-dir` 和 `--smoke-test`。普通 data-dir 可选；smoke 必须提供 payload/work-dir 之外的独立空目录。launcher 不创建账号、不删除数据。
- runtimeEnv 仅保留必要 Windows OS 环境，不继承 PATH/NODE_OPTIONS/ELECTRON_RUN_AS_NODE/API Key/Python 路径等开发环境。

## 实施与验证

- [x] 写 RED：旧根启动/test/build/typecheck 命令与新契约不符。
- [x] 写 RED：严格参数、平台、完整预检、路径链接/manifest/文件清单与 hash 不满足时必须在 spawn 前拒绝。
- [x] 写 RED：真实受控 Node 子进程接受中文空格及 shell 字符原文、退出码保真，取消只清理所属进程且无关子进程仍活。
- [x] 实现 `main(argv, trustedDependencies?)`；依赖注入仅供程序测试，CLI 无 arbitrary command/path/平台绕过选项。生产使用固定 Electron 路径、shell:false argv 与 runtimeEnv。
- [x] 实现目录父链/子树链接检查、精确应用白名单与 manifest 文件 SHA/inventory 验证；所有拒绝给安全中文原因及既有 `python scripts/build_windows.py --work-dir ... --prepare-only` 指令。
- [x] 修改根 scripts，保留原 dev、private 及其它已有字段。新增独立子包测试别名。
- [x] 运行 startup 专项 GREEN、真实 npm 参数转发 fixture、脚本语法、JSON/差异与 SHA；不重复全产品套件。
- [x] 冻结源码并交给 root；本轮受控 Node 结果不计 Windows GUI/Electron 通过。
- [ ] root 用 fresh prepare 的 Windows 目录执行真实 Electron smoke。

生产命令：

```text
npm run build
npm run start:local -- --data-root <独立数据目录> --port 8000
python scripts/build_windows.py --work-dir C:\MarlinBuild --prepare-only
npm run start:desktop -- --work-dir C:\MarlinBuild
npm run start:desktop -- --work-dir C:\MarlinBuild --data-dir C:\MarlinSmokeEmpty --smoke-test
node --test scripts/desktop/startup.test.cjs
```

## 实测结果与证据边界

- 初始专项 RED：39/39 失败，确认旧根脚本与缺失 launcher；旧 Python 命令只在独立临时 npm fixture 中尝试不存在的脚本，没有运行 Django 业务。日志 [20261010-startup-red.tap](../refactor-evidence/20261010-startup-red.tap)。
- 加入实际 builder 的 prepared-build 契约后，marker 链接回归发现漏验；原实现真实进入 spawn，修复后在 spawn 前拒绝。source snapshot 漏掉 `frontend/src/main.ts` 同样先真实 RED，再补当前全量 build input inventory，不能以现有条目的哈希代替完整清单。额外 RED 日志 [20261010-startup-source-red.tap](../refactor-evidence/20261010-startup-source-red.tap)。
- 最终实际根 `npm run test:startup`：44/44 GREEN，0 skipped，2.708 秒；包含真实 npm-cli.js 转发与受控 Node 子进程。日志 [20261010-startup-green.tap](../refactor-evidence/20261010-startup-green.tap)。没有重复完整产品测试。
- `node --check scripts/desktop/start-desktop.cjs` 与 `node --check scripts/desktop/startup.test.cjs` 均 exit 0；根 JSON 和差异检查通过。
- 本机 Linux 上实际 `npm run start:desktop -- --work-dir /tmp/marlin-not-prepared --data-dir /tmp/marlin-not-created --smoke-test` exit 1，清楚提示仅交付 Windows x64 及构建准备命令，未创建这两个目录。日志 [20261010-startup-platform-refusal.log](../refactor-evidence/20261010-startup-platform-refusal.log)。
- 程序测试的 `platform/spawn/signal` 注入只能从 trusted Node 调用提供；CLI 只有 work-dir/data-dir/smoke-test。测试实际运行的是隔离 Node fixture，不是假称 Electron、Windows 图形界面或真实业务 Core 启动通过。临时 fixture 脚本/目录在 finally 删除。
- 预检完整读 hash/inventory 的耗时尚未在真实大 Windows payload 测量；2.708 秒是本机专项 suite 时间，不能当产品桌面启动延迟。
- 根 `typecheck` scope 仅 core 的现有 TypeScript 检查。frontend Vite build 不宣称语义类型检查；desktop 没有新增不存在的 build/typecheck 脚本。三个子包版本、依赖与锁文件未由本轮修改。

## 源码冻结 SHA256

| 文件 | SHA256 |
| --- | --- |
| `package.json` | `7ebaa45c538eb88b4222bd53372116a53a7333fd6077e290960150061856baca` |
| `scripts/desktop/start-desktop.cjs` | `ec5b2356842ebdfbf66ab45726837e12b9645da3ac0674c1e29c992fc34f0cd5` |
| `scripts/desktop/startup.test.cjs` | `c6a036d5fc74bc92ef429e3d113035588e76689b62febccf87f4eb7bf5fb456c` |

稳定汇总：[启动入口验证与哈希](../refactor-evidence/20261010-startup-summary.json)。四份原始日志逐字节复制并校验 SHA256 后，已删除对应精确临时日志路径；源码冻结 SHA 未变化。

## 独立复核修订与最终冻结

初始 44 项证明范围不完整。独立复核实际发现：只绑定 gate SHA 会接受未知/失败/artifact_only 报告；Electron dist 不在原 manifest 内，执行字节修改仍可通过；POSIX 主进程提前退出会清掉唯一 force cleanup，抗 SIGTERM 后代仍活。该 POSIX 实证不当作旧 Windows taskkill 缺陷证明。Root 已批准本轮修复和新增固定 `scripts/desktop/windows-launch-supervisor.ps1`。

本轮保留根 package 命令与版本/依赖/锁。launcher 对齐 builder 的正式 `marlin-windows-build-gates-v1`：必须 verified、frozen_source、source_before_after_equal；核对测试整数计数与有限非负 duration、当前完整 source/desktop/core/frontend、实际引用 core/Python/Langfuse 报告 SHA 与事实。独立 Python 的版本/隔离/Django 禁止/Ragas/fixture canonical SHA/依赖完整集合和两锁 pins 同时核对。`artifact_only` 仍只能作构建独立检查，不能授权启动。

`prepared.electron_distribution` 和 gate 同字段必须等于实际 `marlin-electron-distribution-v1`：package 与 dist/version 匹配固定版本、path.txt 精确为 electron.exe、package/path SHA 和 dist 全部文件及 SHA。增加、删除、修改或链接均拒绝。

Windows 固定 supervisor 用 stdin 私有 JSON 接受已预检的唯一 Electron 路径与应用 argv、cwd、OS 环境白名单，不增加任意命令 CLI。使用 [CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw) 的 CREATE_SUSPENDED，先 [AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject) 再 Resume；private Job 设 [KILL_ON_JOB_CLOSE](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。取消/所属 Node 的 stdin EOF/主进程早退后清理同一 Job，保留 process handle、等待 Job active=0；没有按名称、端口或主进程已退出的 PID 查杀。失败不 resume 未受控进程，输出安全的阶段/Win32 数字错误；超时不当成功。helper 不执行业务或 Python/Django，也没有新增依赖。

本轮实际结果：

- [36 项实际 RED](../refactor-evidence/20261010-startup-review-fix-red.tap)：27 个 report semantics + 8 个 Electron dist + 1 个实际 POSIX 后代取消；[对应 GREEN](../refactor-evidence/20261010-startup-review-fix-gate-green.tap)。无效事实用例会同步更新对应报告和 gate 的 SHA，避免仅证明未同步哈希被拒绝。
- [32 个正式报告事实用例](../refactor-evidence/20261010-startup-review-fix-facts-green.tap)：另补 5 个隔离 Python/锁/fixture/scope 检查。fixture 提供合约形状，明确属于 synthetic validator 数据，不假称真实 native gate 已执行。
- 最终 [Linux npm run test:startup](../refactor-evidence/20261010-startup-review-fix-linux-green.tap)：90 tests、85 pass、0 fail、5 Windows-only skips、9.804 秒。实际 POSIX 后代在主进程早退后由保留的强制清理结束；正常非 Windows CLI 仍拒绝。
- Windows 专项 [首次 RED](../refactor-evidence/20261010-startup-review-fix-windows-red.tap) 的 5 项因固定 supervisor 尚不存在而失败，不证明旧 taskkill 的 Win 行为。最终 [真实 Windows GREEN](../refactor-evidence/20261010-startup-review-fix-windows-green.tap)：5/5 pass、0 skipped、9.755 秒。官方 Node22.23.2 副本在唯一 Electron 路径充当受控 fixture，真实 Windows private Job 清理抗 TERM 后代、parent early exit7、无关子进程保持；stdout/stderr/code 与中文/空格/shell/quote argv 及环境白名单均真实检查。只在独立 helper 副本向真实 Win32 API 注入非法 Job 名/无效 assign handle，typed 错误为 create private job (3)/assign suspended child (6)，suspended child 未执行 marker。
- Windows 原生 PID 与存活事实及 6 份逐字节原始日志 SHA 保存在 [稳定汇总](../refactor-evidence/20261010-startup-review-fix-summary.json)。不同平台结果覆盖同一套 90 个 distinct cases，不能把 90+5 当 95 个独立用例。
- 41ms cancellation/26ms early-exit cleanup 只是本次受控 Node fixture 的观测，不是产品 Electron GUI 的启动/关闭延迟。没有 Windows GUI、厂商、真实 Core 业务或安装器验收；未修改 QA payload 或用户数据。
- 脚本语法和本轮差异检查 exit0。正式 native 专项命令为 `node.exe --test --test-name-pattern="Windows private JobObject" scripts/desktop/startup.test.cjs`，在独立 source 副本执行；Linux 为 `npm run test:startup`。相关检查完成，没有重复全产品 suite。
- 六份精确临时日志在 hash 一致后删除，独立 Windows source/Node fixture 在 marker 与冻结 source SHA 核对后删除；不清理未知目录。

本轮最终冻结 SHA256（上表为初始阶段历史 SHA，保留其原始证据）：

| 文件 | SHA256 |
| --- | --- |
| `package.json`（本修订未改） | `7ebaa45c538eb88b4222bd53372116a53a7333fd6077e290960150061856baca` |
| `scripts/desktop/start-desktop.cjs` | `ee576cb58d9385fadb1600f183164f8e541b9284d8a3aed17ff4c6cc919c7078` |
| `scripts/desktop/startup.test.cjs` | `69c5d09ce3ee2c9d370c49a10e2b79190851732ac6fcf92e6a988e08e34f6da1` |
| `scripts/desktop/windows-launch-supervisor.ps1` | `f647757e1310962feb1a89879433989a1ba03cf03ee7c88e5490169c49f0084e` |

Root 和 builder 已收到 freeze 通知。新 helper 位于 builder 现有 source_inputs 目录，正式 fresh prepare 应纳入该 hash；后续真实 Electron smoke 仍由 root 单独验收。


## 官方 Windows marker 换行修复

Root 在正式 Windows stage 实际 Node CLI 验收发现：Python `marker.write_text(..., encoding="utf-8")` 默认生成 26-byte 完整 `marlin-electron-build-v1\r\n`，自身 `read_text` 将换行读为 LF，builder gates 因而通过。Node `readFileSync(..., 'utf8')` 保留 CRLF，原 launcher 的 LF 精确比较导致 exit1，未启动 Electron 或业务数据。这个 Windows 观测由 root 提供，不计本轮 subagent 的 Windows 重跑。

本轮生产只修改 marker 常量与完整比较两行：仅接受 25-byte LF 或 26-byte CRLF；不 trim、不规范化输入、不改 builder 或正式 stage 标记。链接/owner/source/gate/artifact/进程围栏保持原路径。缺换行、CR-only、多换行、前后空格、BOM、NUL、混合尾巴及未知版本共十种均在 spawn 前拒绝，并保持原文件字节。

新增 [12 项 marker RED](../refactor-evidence/20261010-startup-marker-red.tap) 只有官方 CRLF 用例真实失败（原“目录不属于当前 Electron 构建”）；LF 与非法标记行为符合既有预期。修复后 [选择回归 20/20 GREEN](../refactor-evidence/20261010-startup-marker-green.tap)，0 skipped，1.505 秒；两种正式标记进入真实受控 Node 后返回其 code7，未重写 marker。选择范围包含原 marker link、source snapshot、unknown/artifact_only gate、Electron exe SHA 和 shell/argv 围栏。没有重跑完整 startup/产品 suite，也没有重复未变的 Windows private Job5项。

[独立汇总与原始日志 SHA](../refactor-evidence/20261010-startup-marker-summary.json) 记录精确选择命令与范围。两份原始 TAP 逐字节持久化并校验后删除对应精确临时日志，所属 fixture 由 finally 清理。本轮不启动 GUI、访问 QA 或用户数据、调用厂商；正式 Windows CLI 重试由 root 在 fresh source refresh 后执行。

本次替代前两项启动源码冻结 SHA：

| 文件 | SHA256 |
| --- | --- |
| `scripts/desktop/start-desktop.cjs` | `f4409c66da6a78ab721c790bb9e595c12671f80fd53752c5538ae586c2a49d8a` |
| `scripts/desktop/startup.test.cjs` | `40b8b282ab61fb8e61f8d69fc14b646f44af5ae711b8bc92a87dd7848c229f19` |

`windows-launch-supervisor.ps1` 与根 package SHA 保持上一轮值不变。Root 与 builder 已收到新 source freeze 通知。
