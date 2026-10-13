# 869 Windows 包的安装准备与实际 owned 升级

当前结果：固定869包仅执行一次owned升级，安装器与升级harness实际exit0，完整安装资源/保留数据验证通过；外层runner汇总收据的编码错误使原工具整体exit1，原失败保持。独立只读postcheck另实际exit0并重新确认安装和数据。产品GUI/实际普通启动仍未执行，Goal未完成。详见末节，原只读准备报告字节见[历史检查点](readonly-preparation-report.source.md)。

以下为升级之前的只读准备记录：只读 Windows preflight 实际 exit0，准确 owned 注册/目录和旧安装完整字节有效；该只读准备阶段没有执行安装器、产品 GUI、Core、模型或服务，也没有修改历史 staging/output、注册表、QA 数据或源码。固定升级 harness 已完成供 Root 审核，当时升级分支尚未执行，必须在 Root 后续精确授权后使用。完整 Goal 尚未完成。

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

Root后续明确批准前准备的唯一命令（**准备时尚未执行；实际后续执行见末节，禁止重放**）：

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

[准备校验](preparation-validation.json)记录实际readonly0、各版SHA和AST解析。准备时harness默认review-only实际0；当时未执行upgrade。自己state observer最初inline拼写SyntaxError在任何语句前退出1，已单独[保留工具失败](state-observer-initial-syntax-error.json)，修正后的[脚本](state-observer.source.txt)实际0并[精确删除](state-observer-consumed.json)；不是产品/门禁失败。

四个自有tmp review helper按精确SHA保留，因为review binding和下一步具体命令仍引用它们；它们全部已归档，新phase消费后再精确清理。没有删除任何历史/user资料、旧stage、旧output或任何Git文件。当前源观测不同于旧artifact的事实保持；Root现在可审核上述具体upgrade后授权唯一安装阶段，其他开发任务可继续独立推进。

## Root 精确批准后的实际 owned 升级

Root完整审核上述精确版本并写 [ROOT-UPGRADE-REVIEW](ROOT-UPGRADE-REVIEW.md)，明确批准一次固定runner/869安装器升级现owned目录、保留DATA、不启动GUI/模型/服务。执行的是以上同一命令与4ebfac… binding/2424fd… survey，没有改source、binding、安装器、stage/output或旧收据。

[原启动](upgrade-native-session-start.json)为session35809/start5736ae；原 [tool终态](upgrade-native-terminal.json) chunkcc445a **actual overall exit1**。该1不能被下述子阶段0或新只读0覆盖：

| 实际层次 | 结果及原句柄 |
| --- | --- |
| inner NSIS安装器 | actual0，97.6061秒；PID33768/FILETIME134363435971167509，同原HANDLE wait0/exit0，原Job active0、全部句柄关闭，无timeout |
| owned升级harness | actual0；完整安装/registry/data检查完成，并写UTF8原receipt/stdout |
| outer Job的harness child | actual0；PID26168/FILETIME134363435564489501，同原HANDLE wait0/exit0，原Job active0、全部句柄关闭，无timeout |
| 外层汇总runner/工具session35809 | **actual1**；160.9351秒，05:39:16.437759Z→05:41:57.372854Z，子进程0及Job闭合后默认GBK读取UTF8中文receipt发生UnicodeDecodeError |
| 独立只读postcheck | actual0，session83147/chunk24399b，36.1516秒；PID31672/FILETIME134363438870664933，同原HANDLE wait0/exit0、Job active0、所有句柄关闭 |

[固定attempt](upgrade-attempt.json)、[原installer Job](installer.log.job.json)、[原outer Job](native-upgrade.log.job.json)、[installer原日志](installer.log)、[原harness stdout](native-upgrade.log)、[原外层回执](native-upgrade-execution.json)和[原installed receipt](executed-upgrade.json)都保留。没有因quiet日志重启、超时推断或编码失败再调用安装器；installer invocation恰为1。

原installed receipt SHA `0ee5a94b7c2c20d93ae742849149c9cbbb7b53ec85d734a5a9971627a3164b69`，state `verified_owned_immutable_artifact_upgrade_not_launched`；原outer receipt SHA `266eb3e001bd278e58a08029aafef83e8ba69f9e40d3fe84c2e03a8105bfe252`，其中actualExitCode0是owned child结果，另有errorType UnicodeDecodeError，installerExecuted null是汇总尚未读出的状态。它不是工具整体0，也不把null解释为未执行安装器；原installed receipt实际installerExecuted true。原工具终态1另有明确记录。

### 安装和数据的实际结论

启动前immutable artifact、8条registry、marker、进程缺失、旧uninstaller与869安装器SHA再次核对。按末尾unquoted `/D=` 在 `Marlin 安装验收 20261010\应用` 完成中文空格目录升级；独立 `验收数据 二次` 持DB deny-write/delete guard。

升级harness实际完整比较25380安装文件（唯一额外uninstaller另核）与新win-unpacked，25305 runtime文件与manifest，12项ASAR资产与audit，新native `b3875cb…` 与当轮资源；全部相等。uninstaller SHA仍 `08edb13f97f88cbb542bc03c74c19f9c7d602c0a6041a096df234067ef253f7e`。HKCU/HKLM双view注册范围/值与原survey相等，没有正式/foreign安装覆盖；NSIS自身对owned安装注册的正常操作不称“未写注册表”，harness未直接写注册。

12表、94数据文件及凭据材料哈希全部前后相等，完整retainedState规范JSON digest均为 `3711d469ee990e0bfeb3e16d8296217798df46120b500f014e26d2c76ddbff53`。models/model_usage/jobs/tasks仍0，没有启动Core、解密/输出Key、改密码或设备。实际相关旁实例0、保护计数0；PID25268仍open87，历史死因不推断，旧53956 overall1保持。

### 编码工具失败的定位与独立复核

我写的外层runner第16行用 `.read_text()`，在此Windows解释器默认GBK下读入由已审utility显式UTF8写出的中文scope。给owned child设置PYTHONUTF8不会改变当前outer解释器；错误发生在所有安装/数据检查已完成、owned child和原Job已退出之后。按 systematic-debugging 先读原组件边界与完整trace，再用原receipt bytes最小只读复现：GBK在同position338失败、UTF8成功，见[编码诊断](wrapper-encoding-diagnosis.json)。没有修原runner、重写失败收据、重跑安装或改生产源码。

为完成授权的安装验证，另建仅显式UTF8读原报告和重新hash当前资源/数据的[只读observer](independent-postcheck.source.txt)与[固定私有Job runner](independent-postcheck-runner.source.txt)。它固定原升级receipt SHA、outer receipt SHA、原approved harness SHA/4ebfac binding，再次核immutable artifact、8条registry、全部25380安装文件/25305 runtime/12项ASAR/native、readonly12表/94文件/凭据hash及原related HANDLE，未调用installer/产品/Core/服务。

[新actual0终态](independent-postcheck-native-terminal.json)、[新执行回执](independent-postcheck-execution.json)、[新原stdout](independent-postcheck.log)、[新Job回执](independent-postcheck.log.job.json)均保留。独立 [installed postcheck](independent-installed-postcheck.json) SHA `bfbe73937e4aca423b5b973769239524c4dca573fd10f4df6848054dcecd6c12`，确认所有安装资源、registry和retainedState仍匹配，并明确携带 originalOuterToolExitCode1、originalOwnedHarnessExitCode0、originalInstallerExitCode0、originalWrapperFailurePreserved true。这是新只读验证0，原工具overall1仍保持。

[最终分层校验](upgrade-final-validation.json)记录这些真实层次、单次安装以及无GUI/模型限制。该包已安装并静态全量/数据复验，普通产品GUI、实际native main生命周期、IPC/worker后代、托盘关闭/退出和重启不重放仍由Root后续授权及验收，未计为通过。包仍绑定旧468，而非后续变动sidebar/detail/autostart源码。

### 清理与只读Git观察

[独立postcheck的两个自有临时脚本](independent-postcheck-consumed.json)在其真实terminal0后按归档精确SHA删除；诊断/收尾临时助手也归档后消费。原四个review临时helper暂保留：当前不可变review binding的inputs仍引用它们，后续Root GUI准备可能调用harness/privateJob；readonly/upgrade runner已经消费，不得重放安装。等下阶段将必要只读能力与binding分离后可再按SHA精确删除这些剩余helper，不修改当前binding或原证据。

另发现 [Git只读观察变化](post-upgrade-git-observation.json)：当前 `git ls-files --stage` 字节SHA为 `eaabee877042616f848ff8e58d98ca117e7183ac4be310baad46e6ca6691ddf2`，此前b36c6d…；HEAD仍dd5a356…。本worker没有执行任何Git写命令，不推断作者/原因，不将逻辑stage变化混成stat-cache刷新，也未回滚或触碰无关改动。旧artifact/source/registry/data证据不受该Git观察改写。
