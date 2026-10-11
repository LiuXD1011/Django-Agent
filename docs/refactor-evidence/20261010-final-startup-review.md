# 最终启动入口独立复核

2026-10-10，parser_worker，只读生产源码。检查 root `package.json`、Node launcher 与完整 startup tests、Windows builder/prepared/gates 契约，以及 `desktop/runtime.cjs` 的真实环境与进程接口。未修改生产文件、测试或根命令；未操作 GUI、QA 数据、密钥或厂商服务。

复核发现两项启动预检完整性缺口，以及一项已证明的 POSIX owned cancellation 缺口。现有启动测试 44/44 通过，不能覆盖这些额外场景。以下“允许 spawn”指生产 `main()` 的预检通过，随后可信测试依赖启动真实受控 Node 子进程；并非 Windows Electron 启动通过。

| 优先级 | 已证明问题 | 触发与影响 | 最小修复方向 |
|---|---|---|---|
| P1 | gate 报告只核 SHA，不验证语义 | 未知 format/failed state，或 artifact_only/failed tests，只要 prepared 绑定对应报告 SHA，仍进入 spawn。不能把未知或失败报告作为正式 launch 许可。 | 与 builder 单一正式 schema 对齐；拒绝未知、failed、artifact_only，核对所有事实与实际文件绑定。 |
| P1 | 实际 Electron 执行分发未绑定 SHA | 仅修改 `app/node_modules/electron/dist/electron.exe`，其他清单和报告完全不变，仍进入 spawn。该目录在 payload 外，不在 prepared.desktop_sha256 内。 | prepare 记录整个 Electron dist 精确文件集合及 SHA；launch 再核实际集合、父子链接、全部字节，不能只检查 package version 或只哈希 exe。 |
| P2 | POSIX 取消后主进程退出使 force cleanup 消失 | 同 owned group 后代忽略 SIGTERM，父进程退出；launcher 4 ms 返回 143，2.3 s 后后代仍存活，无关进程保留。 | 取消后持有 owned tree 的可靠身份并执行有限清理，不因主 exit 清除唯一 force cleanup。Windows 必须独立原生验证，避免按已退出父 PID 猜测/复用杀进程。 |

问题一对应 [start-desktop.cjs](../../scripts/desktop/start-desktop.cjs#L132)：只比较 `prepared.gates_sha256 === digest(windows-gates.json)`，未读取报告 JSON。正常测试 fixture 本身写入 `format: controlled-fixture`、`state: not-real-electron-verification`，故现有成功用例没有证明正式 gate schema。builder 的 `run_windows_gates` 检查 format/state/scope 和部分事实，`verify_prepared` 再使用只绑定哈希的契约；建议共用同一严格验证，避免 packaging 与 launch 漂移。哈希提供字节一致性，不提供报告真实性或签名；本结论不声称能抵御有权限同时重写所有本地清单的攻击者。

问题二对应 [start-desktop.cjs](../../scripts/desktop/start-desktop.cjs#L121)：Electron.exe 仅文件存在、Electron package 版本匹配；`inventory(app)` 会拒绝链接，但没有绑定 dist 内容。`verifyHashMap(payload, ...)` 完整覆盖 payload；`prepared.desktop_sha256` 仅覆盖十个应用顶层文件。这不能检测实际外部执行分发的字节变化。

问题三对应 [start-desktop.cjs](../../scripts/desktop/start-desktop.cjs#L159)：`terminate` 在主 child.exitCode/signalCode 已设置后直接返回；`close` cleanup 又清掉 2 s force timer。已有取消测试仅创建一个 owned child，没有拒绝 SIGTERM 的后代。复现是 Linux 实际 Node group 行为；正常 CLI 明确拒绝 Linux，不能据此直接判定 Windows 产品存在相同后代存活结果。Windows taskkill 的主 exit/后代/系统调用失败路径需要实际原生测试；建议持有 private JobObject 或可靠 owned handles，而不是在主退出后搜索名称、端口或复用 PID。

## 实际验证

命令 `npm run test:startup`：exit 0，44 tests、44 pass、0 fail、0 skipped，2794.994143 ms。只运行本任务相关启动测试，未重跑产品完整 suite。

独立 `/tmp/marlin-final-startup-review.cjs` 调用真实 launcher `main()`，复用完整已读 startup fixture 的文件构造器；用可信测试依赖声明 win32/x64，将实际执行目标替换为当前 Node。参数、环境、预检与取消代码均为生产实现。每个 fixture 在 finally 删除，进程均明确清理。

| 额外受控用例 | spawn 次数 / 状态 | 实际结果 |
|---|---|---|
| gate `{format:'unknown-format',state:'failed'}`，prepared 同步对应 gate SHA | 1 / code 7 | 错误允许预检通过 |
| 正式 format，但 scope=artifact_only、core failed=1/pass=0，prepared 同步 gate SHA | 1 / code 7 | 错误允许预检通过 |
| gate 文件丢失 | 0 / reject | 正确拒绝，缺必要文件 |
| gate 字节修改但 prepared SHA 不同步 | 0 / reject | 正确拒绝，验证报告已变化 |
| 仅 Electron.exe 字节修改，所有清单/报告不动 | 1 / code 7 | 未检测实际执行文件篡改 |
| owned 后代忽略 SIGTERM，主进程退出 | code 143 / settle 4 ms | 2.3 s 后 owned 后代 alive、主 dead、无关 child alive；随后测试显式清掉自己 owned group |

最小重现材料（仅临时脚本，不编辑 startup tests）：

```js
const original = path.join(root, 'scripts/desktop/startup.test.cjs');
const prefix = fs.readFileSync(original, 'utf8').split("\ntest('root scripts")[0];
const harness = new Module(original, module);
harness.filename = original;
harness.paths = Module._nodeModulePaths(path.dirname(original));
harness._compile(prefix + '\nmodule.exports={fixture,options,launcher,sha,put};', original);
const {fixture,options,launcher,sha,put} = harness.exports;
const f = fixture('process.exitCode=7;');
// Gate 用例：写报告，并只同步 prepared.gates_sha256。
put(path.join(f.work,'windows-gates.json'), JSON.stringify({format:'unknown-format',state:'failed'}));
const preparedFile = path.join(f.work,'prepared-build.json');
const prepared = JSON.parse(fs.readFileSync(preparedFile));
prepared.gates_sha256 = sha(path.join(f.work,'windows-gates.json'));
put(preparedFile, JSON.stringify(prepared));
const code = await launcher.main(['--work-dir',f.work], options({
  spawn: (_exe, argv, settings) => spawn(process.execPath, argv, {...settings, stdio:'ignore'})
})); // code 7；finally f.close()
```

Electron 用例在新的 fixture 中只执行 `put(path.join(f.app,'node_modules/electron/dist/electron.exe'),'ALTERED executable bytes')`，不改其他清单，再调用相同 main：仍 code 7。该 fake exe 没有被真正执行；证据针对预检接受，不是有效 Windows PE 执行结果。

取消用例：fixture 的主 Node 启动同组 `spawn(process.execPath,['-e',"process.on('SIGTERM',()=>{});process.send('ready');setInterval(()=>{},1000)"],{stdio:['ignore','ignore','ignore','ipc']})`；等后代 IPC ready 后，主 stdout 发 PID/READY。另启独立 unrelated Node。launcher 的真实 spawn 使用生产 `detached` 设置，测试捕获 stdout 只为握手。AbortController.abort 后 await main，再等待 2300 ms，用 `process.kill(pid,0)` 查询存活。最后仅清自己的 owned group 与 unrelated fixture。未按端口或进程名杀进程。

## 正式 gate 契约建议，交接 root / parser_baseline / builder owner

1. `format=marlin-windows-build-gates-v1`、`state=verified`、`scope=frozen_source`、`source_before_after_equal=true`；拒绝缺失、未知、失败、artifact_only。不是只测试报告 JSON 能解析。
2. 报告 source_sha256 与 manifest/prepared/current source 精确集合一致；desktop_sha256、core_entry_sha256、frontend_index_sha256 对应实际 staged 文件。
3. core_tests 至少 24、runtime_tests 至少 6；计数为有限非负整数、passed=tests、failed=skipped=0，duration 有限；不能只检查 passed 下限。
4. 验证现 windows-gates 输出的 native SQLite/FTS/vector/IPC 事实、隔离 Python fixture 数/Ragas 版本及 python_report_sha256，和 `validate_window_report` 的完整 Langfuse 原生事实；paid_model_calls=0。为所有实际引用报告拒绝丢失或篡改。
5. 与 builder owner 协调正式字段/版本，使用一个共同契约；控制 fixture 也提供合法正式形状，同时单独保留 unknown/failed/omitted/artifact_only/mismatched/tampered 拒绝回归。实际 test fixture 不能伪称 native gates 已运行。
6. Electron dist 新的全量 SHA 字段也需共同写入/校验；不要把 launcher 和 builder 独立手写出的近似 schemas 当一致。

## 其余核查与边界

- 根 start:local 直接进入编译 TS entry；start:desktop 使用 Node launcher；build/typecheck/test 核心命令不依赖 Django。build:desktop 使用 Python 打包脚本，仅构建辅助，未将 Django 当运行依赖。
- 当前平台与架构拒绝、未知/重复/缺值参数、UNC 和控制符参数、smoke 显式空隔离数据目录、构建/数据目录重叠围栏均有相关 GREEN 回归。
- `checkedStat`、父目录遍历和递归 inventory 覆盖 work/app/payload/Electron/data-parent/marker 的 symlink 拒绝。现 6 项路径测试在 Linux 实际 symlink 上通过；Windows junction 的实际目标平台行为未在此复核中验证。
- payload 的实际文件集合及逐文件 SHA 完整比较；未知/新增/缺失/修改 payload 字节均有原回归。manifest 路径拒绝 traversal、盘符、反斜杠、路径别名，使用大小写去重和 Windows 保留名围栏。
- builder source_inputs 和 launcher sourceNames 均收集实际 source 文件集合（包括 scripts/desktop 和新 frontend/core/worker 源）；精确集合阻止旧 snapshot 静默遗漏新文件。原回归实际证明省略现有 frontend/src/main.ts 被拒绝。此轮没有往真实源目录造新增文件。
- runtimeEnv 仅传 OS/profile/temp 字段。真实受控 Node child 证明 shell=false、中文/空格/shell 字符参数按原样传入，NODE_OPTIONS、ELECTRON_RUN_AS_NODE、模型 Key、Python 路径与 ambient PATH 不继承。未读取真实环境 Key。
- Windows gates 的 `windows-job.py` 使用 CREATE_SUSPENDED→private JobObject→ResumeThread，KILL_ON_JOB_CLOSE、retained handles 与 finite cleanup；这是源码核查，不是本轮 Windows 实测。普通 build.run 的 subprocess 行为与 launcher cancellation 不应因该 gate helper 已存在而被计为相同 owned-tree 验收。
- 独立 windows-gates execute 先 Path.resolve，再做部分 reject_links；直接 CLI 传 junction alias 可能在校验前被归一化。builder 上游 guard_workspace 已拒绝链接，但 standalone gate 的原生 alias 情况仍是待验证疑点，本轮不列为已证明缺陷。

复核快照 SHA256：

| 文件 | SHA256 |
|---|---|
| package.json | 7ebaa45c538eb88b4222bd53372116a53a7333fd6077e290960150061856baca |
| scripts/desktop/start-desktop.cjs | ec5b2356842ebdfbf66ab45726837e12b9645da3ac0674c1e29c992fc34f0cd5 |
| scripts/desktop/startup.test.cjs | c6a036d5fc74bc92ef429e3d113035588e76689b62febccf87f4eb7bf5fb456c |
| scripts/build_windows.py | 299ba51bc5b0c8ef402e1bcd47721b3de598e18780f270922b0e1f4faf2458e3 |
| scripts/desktop/windows-gates.py | 7678636c701825fbc01622e3450a5238099fc9985d2369c2dcfb5ba3fd77638b |
| desktop/runtime.cjs | 6fc4f3999e6362f4d07fbd253226d35e4f65e0ed4db299f29fd605c79575e834 |

结论不包含 Windows Electron GUI、真实厂商、安装器交付通过。临时复现脚本/结果/测试 TAP 在提取上述无秘密事实后删除；没有常驻 fixture 或生产改动。
