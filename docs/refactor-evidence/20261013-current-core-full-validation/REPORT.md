# 当前冻结 Core 完整验证

2026-10-13，工作目录 `/home/liuxuedeng/Django-Agent/packages/core`。本轮完成用户授权的 Core 完整类型检查和完整测试，命令均实际执行一次并观察至终态。未修改生产代码、测试、依赖、锁文件或主验收文档，未 stage、commit、push。

## 实际结果

| 命令 | 退出码 | 结果 | 原始输出与执行记录 |
| --- | --- | --- | --- |
| `npm run typecheck` | 0 | `tsc --noEmit` 通过，5.382 秒 | [stdout](typecheck.stdout.log)、[stderr](typecheck.stderr.log)、[记录](typecheck.result.json) |
| `npm test` | 0 | 698 tests：696 pass、0 fail、2 skipped、0 cancelled、0 todo；117.829 秒 | [stdout](test.stdout.log)、[stderr](test.stderr.log)、[记录](test.result.json) |

Node TAP 汇总为 `tests 698`，顶层计划为 `1..688`，其余为嵌套测试；不能把 688 当作总测试数。两个命令的独立 stderr 文件均为 0 字节。测试 stdout 的 MockTimers ExperimentalWarning 是 Node 实验 API 提示，没有失败、取消或未完成测试。[机器汇总](test-summary.json)保留跳过项原文及残留临时缓存清单。

## 每个跳过项与未执行分支

| 测试 | 条件 | 本轮状态 |
| --- | --- | --- |
| `compiled JS owner starts actual native application and bounded streams without a development loader` | `test/core-owner-compiled.test.ts:11`：`process.env.MARLIN_CORE_OWNER_COMPILED_TEST !== '1'` | 环境变量未设置，SKIP，不计 PASS |
| `compiled owner uses actual Python and compiled nested chunk Worker to publish a small document` | `test/core-owner-compiled.test.ts:42`：同上 | 环境变量未设置，SKIP，不计 PASS |

上述测试源文件要求先有 fresh build，并用无 tsx loader 的 plain Node 显式执行；本轮授权范围只有 Core `typecheck` / `npm test`，没有运行 Core build，也没有启用这两个 compiled Owner 测试。

`chunking-workers-compiled.test.ts` 在专属临时目录编译其实际计算依赖图，并通过 Linux plain Node 执行 sibling Worker：Node v22.23.2、parents 1、children 6、started 1、compiled true。编译文件哈希和实际结果位于测试原始 stdout 的 656–657 行。这是隔离临时目录内的编译，没有写入 Core `dist`。其中 Windows 互操作分支仅在 `MARLIN_TEST_WINDOWS_NODE` 设置时执行；本轮未设置，不宣称 Windows 分支通过。

`evaluation.test.ts:317` 的 inherited-pipes 测试仅在 `process.platform === 'win32'` 跳过。本轮 Linux，因此该条件没有造成额外 SKIP。

## 环境、原生依赖与隔离

先核查 `AGENTS.md`、Core package/scripts/tsconfig、测试中的环境与网络入口，以及已安装类型定义。审计索引见 [测试入口](test-environment-network-audit.log)和[已安装类型](installed-types-audit.log)。

- Node v22.23.2，Node module ABI 127，N-API 10；npm 10.9.8。
- Core 实际 `openNativeDatabase` 选择现有 `better-sqlite3/build/Release/better_sqlite3.node`，实际内存库可加载，FTS5 与 vec0 表可创建；SQLite 3.53.4、sqlite-vec v0.1.9。见 [native probe stdout](native-preflight.stdout.log)及[记录](native-preflight.result.json)。
- 预检时直接调用依赖默认构造器会选择发布 prebuild，因宿主缺 `GLIBC_2.33` 报 `ERR_DLOPEN_FAILED`。追溯后确认 Core 已按生产实现显式优先本地 binding，本轮实际路径 probe 和完整测试均通过；这是依赖默认 prebuild 与宿主的兼容性观察，不是本轮 Core 测试失败。没有安装、重建或替换依赖。
- 独立 cryptography Python 已实际检查：`/home/liuxuedeng/anaconda3/bin/python`，Python 3.12.2、cryptography 43.0.0、AESGCM 可用；`MARLIN_CRYPTO_TEST_PYTHON` 设置为该路径。见 [crypto probe](crypto-preflight.stdout.log)。双向 TypeScript/Python AES-GCM 兼容测试实际运行并通过。
- 解析 Python 为已存在的 `/tmp/marlin-parser-isolation-20261010/bin/python`，Python 3.12.2，Pillow 12.3.0、CairoSVG 2.9.1、PyMuPDF 1.28.2、python-docx 1.2.0、openpyxl 3.1.5；没有安装或更改该环境。见 [parser probe](parser-preflight.stdout.log)。
- [已安装依赖输入](installed-dependency-inputs.json)记录实际 package 版本、SQLite binding / vec0 扩展与类型定义 SHA；不是推测 API。

完整测试采用专属 disposable 根 `/tmp/marlin-current-core-full-validation-8pfta2yk`，`TMPDIR` / `TEMP` / `TMP` / `MARLIN_TEST_COMPILED_ROOT` 均指向它。测试自行创建并移除独立数据目录；结束后只剩 tsx / Node compile cache，没有测试数据库或测试账号数据目录。缓存仍保留在 disposable 根，没有清理任何既有用户目录。

测试子进程环境仅继承 PATH 与语言设置，加上报告记录的测试路径和 `PYTHONDONTWRITEBYTECODE=1`；未继承真实模型 Key、数据库地址或 Python 导入覆盖变量。完整显式环境见 [environment.json](environment.json)。测试里的管理员、凭据、设备与资料均来自临时 fixture；没有操作用户真实管理员、Key、设备、资料或 GUI / 现有服务，没有占用 8000 / 5173。

模型与外部协议入口使用 loopback 临时端口或受控 RPC；GLM / DeepSeek 身份策略测试把实际网络路由重定向到 loopback；public dataset 导入测试显式提供 loopback `publicOrigin`。没有外部付费模型调用。Ragas 测试使用已安装独立 Python 与受控 Core RPC / loopback 模型。

## 冻结输入与证据完整性

[执行前 SHA](source_inputs.before.json)与[执行后 SHA](source_inputs.after.json)覆盖 Core src、test、scripts、package.json、package-lock.json、tsconfig.json、AGENTS.md，以及 document worker / fixture 文件；排除 `__pycache__` 和 `.pyc`。315 个文件前后逐项 SHA 相同，新增 / 删除 / 改变项均为零，见 [一致性记录](source-consistency.json)。

本次验证助手源文本保留于 [validation-helper.source.py.txt](validation-helper.source.py.txt)，助手原文件仅在检查预期 SHA、确认保留副本逐字相同后删除。清理结果见 [helper-cleanup.json](helper-cleanup.json)。完整测试 session 20223 已终态，不因等待或超时重复启动。

以上是默认完整测试的独立回执；其两项 SKIP 保持原样。两个 compiled Owner 分支的后续显式验收见下节，Windows 分支仍不属于本轮。

## 后续授权：fresh build 与显式 compiled Owner 验收

Root 后续明确授权独占 Core `dist`，补齐上述两个 conditional compiled Owner 分支。未重复默认完整测试。构建前完整阅读 compiled Owner 测试、Owner / Query / Chunking 实际入口、原生数据库选择与 Python 进程路径；[前置一致性记录](compiled-owner.preflight-consistency.json)确认原 315 个冻结输入及已记录依赖 SHA 一致，现有 Core build writer 为零，然后才执行唯一一次 fresh build。

| 命令 | 实际退出码 | 实际结果 | 原始证据 |
| --- | --- | --- | --- |
| `npm run build` | 0 | `tsc`，7.207 秒 | [stdout](compiled-owner.build.stdout.log)、[stderr](compiled-owner.build.stderr.log)、[记录](compiled-owner.build.result.json) |
| `MARLIN_CORE_OWNER_COMPILED_TEST=1 node --test test/core-owner-compiled.test.ts` | 0 | 2 tests、2 pass、0 fail、0 skipped、0 cancelled、0 todo；5.602 秒 | [stdout](compiled-owner.test.stdout.log)、[stderr](compiled-owner.test.stderr.log)、[记录](compiled-owner.test.result.json) |

没有使用 `--import tsx`：测试文件注释明确要求 plain Node，两个测试开头均断言 `process.execArgv` 等于空数组；Node v22.23.2 直接执行该 erasable TypeScript 测试入口。测试导入 fresh `dist/runtime/owner-client.js`，其 Owner 与 Query Worker 选择 `.js` sibling 并显式设置 `execArgv: []`；compiled Owner worker 的 `.ts` 条件不成立，因此不会注册 tsx。实际 Node 测试子进程 argv 只有 Node 可执行文件与测试路径，没有 loader 选项。见[入口审计](compiled-owner.entrypoint-audit.log)与[归属进程观察](compiled-owner.test.owned-process-observation.json)。这里的 OS 线程名称仅为观察值，不把线程名称当作 Worker 成功断言。

第一个测试实际完成 native application 启动、私有协议 auto-setup、FTS5 / vector extension 状态、精确二进制上传与下载、SSE `message_start` / `done` 与明确模型缺失错误、私有 HTTP transport 身份，以及 Owner 重启后的 serviceId / auth 延续。第二个测试实际通过独立 Python supervisor / document worker、compiled nested Chunk Worker 发布小文档，断言 completed 状态、真实 chunks 含 `compileduniqueterm`、模型调用总数为 0。这两个结果来自未修改的生产与测试文件，未替换协议或 Worker。

测试采用新 disposable 根 `/tmp/marlin-current-core-compiled-owner-bc166owm`。两个测试各自用 `mkdtemp` 创建独立数据目录并在 finally 移除，结束后只剩 Node compile cache；未占用 8000 / 5173，未接触真实管理员、Key、设备或资料，未发起付费模型请求。见[本次环境](compiled-owner.environment.json)。

按测试实际 `spawnSync('python', ...)` 入口核验的 Python 是 `/home/liuxuedeng/anaconda3/bin/python`，Python 3.12.2，而非推测使用首轮解析环境。见[Python preflight](compiled-owner.python-preflight.stdout.log)。旁路观察到 supervisor PID 3852745 及其 worker PID 3852794，实际执行 `/home/liuxuedeng/anaconda3/bin/python3.12` 和真实 `workers/document/worker.py`，两者均为本次 Node 测试子进程的后代。

fresh compiled 数据库入口 probe 退出 0，实际加载现有本地 SQLite binding，SQLite 3.53.4 / vec v0.1.9，FTS5 与 vec0 表创建成功。见[编译后 native probe](compiled-owner.native-preflight.stdout.log)及[执行记录](compiled-owner.native-preflight.result.json)。其内联 probe 本身有 `-e` / `--input-type` 参数；测试子进程的空 `execArgv` 由两个实际测试断言及上述 argv 观察独立证明，不混用这两项证据。

[build 写入范围](compiled-owner.build-write-range.json)显示现有 `packages/core/dist` 的 438 个文件均被 fresh `tsc` 重写，0 新增、0 删除、0 内容 SHA 改变；与此前生成物内容一致，fresh 构建来自当前冻结源码。保留现有 dist，没有删除任何既有文件。完整 manifest 见[构建前](compiled-owner.dist.before.json)、[构建后](compiled-owner.dist.after-build.json)、[测试后](compiled-owner.dist.after-test.json)，测试期间 dist 无变更。

[补充验收汇总](compiled-owner.summary.json)确认：315 个[执行前输入](compiled-owner.source_inputs.before.json)和[执行后输入](compiled-owner.source_inputs.after.json)均与原完整测试输入相同，[依赖前](compiled-owner.dependencies.before.json)与[依赖后](compiled-owner.dependencies.after.json) SHA 相同，bindings 未更换。独立命令 session 26304 已终态 exit 0。自有助手按预期 SHA 与保留副本逐字比较后删除，见[助手源](compiled-owner-helper.source.py.txt)及[清理记录](compiled-owner.helper-cleanup.json)。

因此保留两份明确回执：默认 full suite 为 **698 / 696 pass / 2 skipped**；fresh compiled Owner 独立显式验收为 **2 / 2 pass / 0 skipped**。不改写首轮 SKIP，也不新增 Windows 分支通过声明。
