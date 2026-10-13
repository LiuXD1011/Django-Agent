# 869 Windows 包的只读安装准备

当前结论：只读 Windows preflight 实际 exit0，准确 owned 注册/目录和旧安装完整字节有效；本次没有执行安装器、产品 GUI、Core、模型或服务，也没有修改历史 staging/output、注册表、QA 数据或源码。固定升级 harness 已完成供 Root 审核，升级分支尚未执行，必须在 Root 后续精确授权后使用。完整 Goal 尚未完成。

本项计划先安装/验收包含新 NAPI/Runtime 的既有 `869a0401…` 包；它不含随后 sidebar/detail/autostart 修改。最终源码稳定后仍需再生成新版包，不能把这里的结果宣称为这些后续修改的安装验收。

## 不可变 artifact 与变动源码分别绑定

固定安装器：`C:\Users\lxd\AppData\Local\Temp\Marlin Owned Runtime Installers 20261013\Marlin-Setup-0.6.2-x64.exe`，401906433字节/SHA `869a0401224675d15d1aa515b2a587a657d4caf704044a8ac641a49ab7f896e9`，sidecar一致。固定 source stage 为 `C:\Users\lxd\AppData\Local\Temp\Marlin Owned Runtime Build 20261013`；二者全程只读。

[本次 artifact-binding](artifact-binding.json)重新实际核验原 [prepare/package事实](../20261013-owned-runtime-windows-build/REPORT.md)：旧468源冻结 `dd5b9d2f6a59fe3365177a3d35743fe4884e0e369ce15f54e6c6433ffc6cbccb`；prepare/package真实exit0、原Job active0、原stdout SHA；prepared/gates/raw导出报告和stage字节一致；全部payload及win-unpacked资源重新哈希。

- 本次绑定 SHA `e03d77180601b09cfee12011187e8d62e338e6ade99aeba81c1ef76d2c5b443c`。
- prepared SHA `927b1e59da39b82500f4575f5c2831f2e2058c7a55cc7c580364117f6b6998af`，gates SHA `585cef28b0064031a2af94a0e7ddbc13fcc86664f59e26537381b66f5ac1a9f3`。
- payload manifest SHA `2415f718ccde9b2b0506174deafbce88e6cca95a983694bd15c70693c3f963de`，完整25305 runtime文件，实际native SHA `b3875cb777f4890c7ca8340819ef2324a2a384454c0995aab15f75fc8e82e4a9`。
- 实际ASAR仅12项白名单，SHA `d4d16b42a36b0ec19357c74574217cd7deaa3969a6c61a99404af5e342fcc530`，审计SHA `5e2937f9ce0ccb71993fd83b23c766b6cad1f69e70879672634871bf588c7814`；ASAR各资产原字节重新读取核验。

本次使用旧artifact自带的source清单与成功收据、全资源SHA授权它的安装，不调用要求 `current source_inputs==旧468` 的 `verify_prepared(ROOT, stage)`。复核门禁仍执行原validator的payload inventory、native/loader/gate报告、desktop与Electron完整分发绑定；validator源码自身SHA也受旧artifact和本次review绑定约束。

[当前源码首次观察](current-source-observation.json)在05:26:24Z为478项，比旧artifact修改9文件、增加10文件；[第二次观察](current-source-observation-after.json)在05:32:36Z为479项，期间还发生detail/local-services相关变化并新增layout测试。两次都不等旧468，均只称mutable observation，没有声明当前最终freeze，也没有修改旧manifest或收据。当前main已完整读取，它的正常链路使用resources/runtime及private IPC；本次未运行任何main/GUI。

## 实际只读 Windows 工具与终态

[外层只读 runner](readonly-runner.source.txt)固定 native `C:\Python313\python.exe` 3.13/SHA `d87063e5597f257004c731b66c59c56c91038861c6877b1a3dca6b8c4e919125`，在 private Job 内 suspended→Assign→resume执行只读helper。原root HANDLE/FILETIME保存至终态；没有按image/PID/port终止其他进程。

[native terminal](native-readonly-terminal.json)：session91851/start6a682b/terminal1e1f88，actual0，67.7438秒。PID33144、FILETIME134363429862620873，同原HANDLE wait0/exit0，Job activeProcesses0，所有自有句柄关闭、无timeout。[原stdout](native-readonly.log)、[执行回执](native-readonly-execution.json)、[原Job回执](native-readonly.log.job.json)均保留。

[readonly-preflight](readonly-preflight.json) SHA `2424fd782e1203979bfcc8bf7111fa904322c4805edbad6ff495531d40c7d2cc`。数据读取方法是原 reviewed utility 的Win32 deny-write/delete数据库HANDLE、零WAL检查、SQLite `mode=ro&immutable=1`/query_only；只输出表计数、行SHA与文件SHA，没有初始化Core、解密/输出明文密钥或凭据、创建WAL或数据库写入。

## 注册表、owned旧安装与数据

实际owned根：`C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010`；应用 `应用`，数据 `验收数据 二次`。marker `.marlin-install-qa-owned` 精确内容为 `marlin-ts-install-qa-20261010\n`，SHA `b2cb9ca9786497d3470f6882b26811d8d388d25978c987cabd913ad6bb14be9a`。已有成功 [安装收据](../20261012-sidebar-a11y-install-preparation/iteration-1/executed-upgrade.json) SHA `718bd256951d4321862bab5158b5334770161e288e4cc57337d64e5b05039ab8` 对同目录、marker、数据及GUID有效。

GUID `5eeaa2c6-7620-5547-ba48-efe96f6ebb0b`，键为 `Software\<GUID>` 和 `Software\Microsoft\Windows\CurrentVersion\Uninstall\<GUID>`。真实winreg只读检查四组hive/view、共8行：

| hive/view | install key | uninstall key |
| --- | --- | --- |
| HKLM/64 | 缺失 | 缺失 |
| HKLM/32 | 缺失 | 缺失 |
| HKCU/64 | 精确owned `应用` | 精确owned `Uninstall Marlin.exe` `/currentuser`；quiet再加`/S` |
| HKCU/32 | 精确owned `应用` | 同上 |

未发现formal/foreign注册。未来任何machine注册或位置/卸载命令不同都会在创建安装器之前拒绝，不恢复或覆盖这些注册。

旧安装25379文件实际完整核验；除uninstaller外的完整inventory SHA `7061b381f3243de245713c84342fd76ba6a6718fc456189d0dd4072e6b0dd161`，uninstaller SHA `08edb13f97f88cbb542bc03c74c19f9c7d602c0a6041a096df234067ef253f7e`，旧ASAR `895f93…`、runtime25304文件与旧成功收据/manifest完全一致。

94个数据文件、`.secrets`材料哈希、12个业务表在只读前后精确相等。计数为user1、KB1、device_sessions2，documents/chunks/sessions/messages/models/model_usage/wiki/jobs/tasks0；integrity与foreign keys检查通过。这些是验收数据，不是原始用户资料；未改变密码、Key、设备或任何业务记录。

## 当前实际进程与历史限制

Toolhelp native snapshot只枚举候选进程名字；相关候选由真实OpenProcess查询image、FILETIME、同HANDLE liveness，现存相关旁实例若有则持其原HANDLE至preflight/未来升级结束再检查。没有读CommandLine，没有停止任何候选。

本次实际relatedAlive=0、installed/foreign Marlin候选0、protectedObservedLiveProcessCount=0、identityRaces空。PID25268再次OpenProcess返回87，原generation未观察到存活；其历史退出码/时间/死因仍未知。没有新建一个进程去冒充旧保护，也没有将0计数写成“旁实例保留通过”。未来native生命周期测试若要证明旁实例不受影响，应由Root在对应授权阶段创建明确自有sentinel并持原HANDLE，当前尚未执行。

原严格launcher session53956 actual1，以及其owned树实际exit0/active0，继续分别保留；[原审查](../20261013-root-sidebar-native-gui/root-evidence-review.json)和[PID历史观察](../20261013-sidebar-postclose-audit/process-observation.json)未修改。本次新只读成功不覆盖或洗成该旧launcher整体通过。

## 具体待审升级 harness

已完整读旧sidebar [95a harness](../20261012-sidebar-a11y-install-preparation/reviewed-harness.source.txt)、其安装utility [102b archive](../20261012-root-cancel-install-preparation/reviewed-harness.source.txt)和启动/ASAR utility [8cf0 archive](../20261012-root-cancel-installed-launch-preparation/reviewed-harness-final2.source.txt)。只复用其只读inventory/DB guard/registry/native结构/ASAR读法，未调用要求25268存活的旧launch/guard，也未重做全历史链审计。

推荐升级现owned `应用`，保留独立 `验收数据 二次`。同appId的NSIS可能调用已注册的旧uninstaller，另选新 `/D` 不能保证避开它；改变appId需要修改正式源码/包。本次所有注册和旧uninstaller都准确owned，所以固定升级此目录更便于核对数据保留与完整资源替换，且不触达formal安装。

[当前待审 harness](reviewed-harness.source.txt) SHA `d307c0de52548ea1df9150ff6ae466b30ffedea16997d47ec0d6bca7617ddb40`；[私有Job](reviewed-private-job.source.txt) SHA `823014d210855849e43f1daf85b52636a439c405e815e0ca551bbe9b273a36c7`；[固定升级runner](reviewed-upgrade-runner.source.txt) SHA `5b9cf61f52dca119439e82ff81ab11550db3486cabddd893cb075f87b47866a3`；[review绑定](reviewed-binding.json) SHA `4ebfac55400742bcd68f9ba2311fa9d3db7b889ce62a3478cc97ae54f746c56f`。

只读实际执行的前版完整字节保留在 [executed harness](readonly-executed-harness.source.txt) / [executed binding](readonly-executed-binding.json)，后者SHA `75a67fae50ead0d15d23c0d3c65c3de1737ce62423bb7fa6bf6efe3a2779f6cf`；随后只对未执行的upgrade分支加强启动边界检查、native host SHA、attempt/实际执行flag区分，并增加外层固定upgrade runner。[逐行差异](upgrade-only-review-refinements.diff)可审；readonly函数与其实际事实未被修改或重写。不能把前版实际只读0当作新版upgrade已执行/通过。

Root后续明确批准后的唯一命令（**尚未执行**）：

```text
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-owned-runtime-install-upgrade-runner-20261013.py 4ebfac55400742bcd68f9ba2311fa9d3db7b889ce62a3478cc97ae54f746c56f 2424fd782e1203979bfcc8bf7111fa904322c4805edbad6ff495531d40c7d2cc
```

outer runner仅固定该harness `upgrade`/binding/survey，私有Job1200秒；harness在原数据deny-write/delete锁下再次核immutable artifact、8条注册、marker、旧完整安装、12表/94文件及实际related身份，在CreateProcess边界再次检查进程缺失、exact旧uninstaller/安装器SHA。真正NSIS命令固定为：

```text
"C:\Users\lxd\AppData\Local\Temp\Marlin Owned Runtime Installers 20261013\Marlin-Setup-0.6.2-x64.exe" /S /currentuser --no-desktop-shortcut /D=C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用
```

保留NSIS最后、不加引号的 `/D=` 规则，支持中文/空格；不传delete-app-data、run-after、任意命令/路径/PID。inner private NSIS Job suspended→Assign→resume，先观察整树active0（900秒预算）再等待原bootstrap HANDLE最多30秒，保留原FILETIME/实际exit；失败只处理自己原Job/悬挂child、5秒完整reap，不泛化kill。安装完成后重新核registry、完整安装文件、25305 runtime文件、12项ASAR、新native SHA，并逐项要求12表/全部数据文件/凭据哈希前后相等及现存旁实例原HANDLE仍live；产出实际installed receipt，不启动产品。

包中既有NSIS配置 `runAfterFinish:false`、`deleteAppDataOnUninstall:false`、`allowElevation:false`；同desktop0.6.2代码升级不冒充版本迁移。后续hidden/普通产品GUI、IPC/worker后代、托盘关闭与真正退出、重启不重放须分别明确授权并写新的同包绑定harness；旧8cf0 NODE_PROBE缺新的owned/bootstrap副本，不直接重放。

## 验证、保留和下一步

[准备校验](preparation-validation.json)记录实际readonly0、各版SHA和AST解析。当前harness默认review-only实际0；未执行upgrade。自己state observer最初inline拼写SyntaxError在任何语句前退出1，已单独[保留工具失败](state-observer-initial-syntax-error.json)，修正后的[脚本](state-observer.source.txt)实际0并[精确删除](state-observer-consumed.json)；不是产品/门禁失败。

四个自有tmp review helper按精确SHA保留，因为review binding和下一步具体命令仍引用它们；它们全部已归档，新phase消费后再精确清理。没有删除任何历史/user资料、旧stage、旧output或任何Git文件。当前源观测不同于旧artifact的事实保持；Root现在可审核上述具体upgrade后授权唯一安装阶段，其他开发任务可继续独立推进。
