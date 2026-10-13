# 已安装正常 GUI：可审准备，尚未启动

本阶段只准备正常installed GUI与有限控制。Root已单独批准并执行唯一SQLite backup复制，副本实际77表/25必要材料；本agent未执行复制。产品GUI、sentinel、模型、安装器和服务尚未启动。本阶段不修改生产/测试/依赖/旧binding/旧回执/index，也未stage/commit。

## 原artifact事实与当前范围

- 安装器固定 `869a0401224675d15d1aa515b2a587a657d4caf704044a8ac641a49ab7f896e9`，401906433字节，源freeze `dd5b9d2f6a59fe3365177a3d35743fe4884e0e369ce15f54e6c6433ffc6cbccb` 的468输入。
- installed receipt `0ee5a94b7c2c20d93ae742849149c9cbbb7b53ec85d734a5a9971627a3164b69`，独立只读proof `bfbe73937e4aca423b5b973769239524c4dca573fd10f4df6848054dcecd6c12`；此前NSIS0/owned harness0/Job0与外wrapper GBK聚合overall1分别保留。本阶段不把原工具1改写为0。
- 当前后续sidebar/detail/autostart源码不属于869包，GUI结果只绑定旧artifact，不用于声称最终新版源码交付。
- 原安装验收的12表/94材料是旧DATA历史范围。新完整业务副本为77表/25材料，不混用。
- 历史25268原HANDLE缺失事实保持。现态outside0只记真实计数，不虚构保护PASS或伪建实例。

实际ASAR五文件已全文读：[main](installed-main.cjs.source.txt)、[runtime](installed-runtime.cjs.source.txt)、[owned](installed-owned-runtime.cjs.source.txt)、[bootstrap](installed-runtime-bootstrap.cjs.source.txt)、[preload](installed-preload.cjs.source.txt)，SHA见[installed source binding](installed-source-bindings.json)。正常main设置新DATA/desktop-profile与单实例锁、show:true、close转tray、tray Exit走finishDesktopQuit/runtime.stop；resources/runtime固定bundled Node/Python/privateIPC，没有system dev runtime或Vite依赖。API/类型核对见[Electron types](electron-types.source.txt)、[Node types](child_process-types.source.txt)、[类型绑定](dependency-types-binding.json)。

## Source只读与已由Root执行的复制

[初始只读观测](source-readonly-observation.json)、[物理路径与关联](source-portability.json)核schema1、FK0、queued/running0、相对media路径和文档/图片/tenant/KB/session/user关联；没有输出row/secret值、读取private-auth或解密。Source有非零WAL，禁止rawcopy主DB。首次未加载vec的observer错误actual1保存在[module RED](source-observer-module-red.json)，加载实际已核vec0.1.9之后只读actual0，未放宽schema。

[独立clone审查](CLONE-REVIEW.md)、[clone helper](clone-helper.source.txt)、[clone binding](clone-reviewed-binding.json)固定schema与25材料path/size/SHA；数据库全表hash/count在只读事务第一次schema查询建立当前快照，然后backup并逐表比较，没有将Source正常业务变化伪装为旧hash。专用QA UUID SHA `cba6980f446f99647ab03db2c3da397b0d1cf26dfb703005a4fc3cd915b826aa` 要求active/nondeleted恰好1；不读取口令/邮件/明文UUID。25材料变更拒绝，需要新观察与复审。

Root唯一复制session91220，首chunk b89434、末c665a4 actual0，输出verified_owned_clone_not_launched；[clone receipt](clone-receipt.json) SHA `54fe8df748ab873a9835648782691e4e4311d3baa66ef3041c3712db5a1451c7`，77实际表、25材料，productStarted=false。Root完整复制工具回执在其专有协调目录；本agent没有重试。新DATA固定 `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\业务验收 20261013`；旧DATA `验收数据 二次`保持。

## Windows真实只读preflight

唯一session14376首ee8780、末d62d66 actual0，8.0207213秒。[只读actual结果](native-readonly-preparation.json)、[原HANDLE/Job终态](native-readonly-preparation-execution.json)与[绑定](preparation-readonly-binding.json)保留：原CsysPython PID21948/FILETIME134363465628563183 Wait0/Exit0/Jobactive0，原conhost13584/FILETIME134363465628629601同样Wait0/Exit0，所有原保留HANDLE关闭。此检查发生在Root复制之前，新DATA/CONTROL确切不存在；它不是复制后的前置核查。

实际核25380 installed/25305 runtime/12 ASAR与新native addon `b3875cb777f4890c7ca8340819ef2324a2a384454c0995aab15f75fc8e82e4a9`、HKLM/HKCU双view精确owned安装位置/uninstaller、parent marker/reparse和actual outside0。未启动GUI/sentinel，未读Key/private-auth。CsysPython3.13.3 SHA `d87063e5597f257004c731b66c59c56c91038861c6877b1a3dca6b8c4e919125` 是核查工具；product自身使用打包runtime。

## 正常GUI待Root/reviewer完整审核

历史v1 [GUI binding](reviewed-binding.json) SHA `d1b09d0c1bb5ac907ea250a472c5f22a6b1fb08b152b32e8e2f994b622d84beb` 固定helper+archive+installed proof+clone receipt/schema/QA/marker。七份可审源码：

| 文件 | SHA256 |
| --- | --- |
| [utility](utils-helper.source.txt) | 8e98334e5031efd3228c8c0180f84b69da7e1e9fd10ad6fa0492e1bd344c63ab |
| [owner](owner-helper.source.txt) | 108a3d79ca800e586babed3ad85bfc0ee8316fff9149683cacafd82316a750e4 |
| [clone只读audit](clone-helper.source.txt) | d0f79323fddb2a3d26e8477379cbc0076987aff2b3fed743005ae809ea8ba6fe |
| [launcher](launcher-helper.source.txt) | 1f9cce49903ef767ad80000168f8aa0659dbc6d205ecdc318ef2e6a77639ada6 |
| [control](control-helper.source.txt) | f4565becc77822725e32377416645896ce6ceae34b1a89c17f7a5f86114f3538 |
| [supervisor](supervisor-helper.source.txt) | 41c35ec7ce4cdacf0ff21875103f0f2caf0ef8b96ae95e667b3b9e20c9cc43bd |
| [sentinel](sentinel-helper.source.txt) | 564fb1e98c1557cb8e86ac29e77f2d025aab757b3a645c4c9244e69de64d4f0a |

GUI argv仅固定installed Marlin.exe与`--data-dir`新DATA，无hidden smoke/auth绕过/inspect/no-sandbox。最小OS env/PATH System32；bundled runtime由产品本身启动。Root负责真实正常QA登录、多页/关闭后台/tray恢复/退出，helper只声明原main resumed，不推断auth/UI ready。没有旁实例时不声明保护通过；现态related Marlin或installed runtime存在就要求Root自然退出。

每个工具/GUI/独立sentinel均CREATE_SUSPENDED→private Job→Assign→Resume，保存原HANDLE/image/FILETIME与经IsProcessInJob证明的后代HANDLE，按同HANDLE Wait/GetExitCode和Jobactive0确定终态。不按PID/image/port广泛kill。Job中快速消失且无法完整identity的进程记录真实竞态，不声称所有瞬时进程都被采样；Jobactive0仍保证整树终态。

GUI默认14400秒，唯一extend-once追加7200，supervisor总21690秒；安静输出不代表终态，不因观察timeout重复启动。main退出后后代45秒内必须结束，受控crash30秒观察product自有Core/worker清理，否则只清自身Job并保留失败。sentinel是另一个Job、无Core/network/DB，只在GUI树终态后核仍alive，再经自身stop标志退出0。

有限control只有固定目录、session nonce、严格连续sequence、4个字段、5个动作；每条先写自身临时文件再atomic rename为6位编号json，sender独占controller lock，避免半条命令。snapshot只观察；natural-exit只要求Root点击此应用tray Exit，不发WM_CLOSE/kill；second-instance仅固定同exe/data新短Job；force-crash-main只对本次原main HANDLE code77，须Root明确特定case授权；extend仅一次。

后置只读表hash/count与材料变化明列，credentials.key哈希必须保持；认证/session/profile正常变化不声称全DB不变。crash后pending job计数保留供恢复验收，不强洗0；普通退出要求queued/running0。固定desktop-shutdown-error诊断字段核实际installed main；存在时normalQuitWithoutDiagnostic=false，不能作为clean quit绿灯。GUI/tray/UI结论留给Root。

### 历史v1精确命令及唯一只读已执行记录

以下v1正常launch未执行，不应执行；新正常待审命令见[V2-REVIEW](V2-REVIEW.md)。

先实际只读复制后native前置核查（180秒自有Job，installed全资源/registry/77表/25材料/Windows vecDLL/QA/marker/outside）:

```text
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-installed-gui-supervisor-20261013.py --verify-reviewed-preconditions --binding-sha d1b09d0c1bb5ac907ea250a472c5f22a6b1fb08b152b32e8e2f994b622d84beb
```

Root具体授权正常GUI后，仅一次：

```text
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-installed-gui-supervisor-20261013.py --execute-reviewed-launch --binding-sha d1b09d0c1bb5ac907ea250a472c5f22a6b1fb08b152b32e8e2f994b622d84beb
```

有限动作例如snapshot；其他action要由Root按实际阶段指定单值，不接受自由argv/PID/path：

```text
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-installed-gui-control-20261013.py --send snapshot --binding-sha d1b09d0c1bb5ac907ea250a472c5f22a6b1fb08b152b32e8e2f994b622d84beb
```

## 静态验证与资源消费

[静态字段拒绝验证](gui-static-review-validation.json)、[最终默认review](gui-review-default-validation.json)：AST解析0，拒绝foreign path/boolean序号/foreign session/序号缺口/未知action；launcher/control/supervisor默认review actual0，零GUI/sentinel/control写入。Root随后精确批准唯一复制后native前置命令，session91102首1cd33b/末e97eb7 actual0，12.0142658秒。原Python35580/FILETIME134363470314357700 Wait0/Exit0/Jobactive0，原conhost32100/134363470314429597同样0，全部保留HANDLE关闭；[native前置结果](gui-native-preconditions.json)、[supervisor终态](gui-preconditions-supervisor-terminal.json)已实际核installed/77表/25材料/Windows vecDLL/QA1/outside0，零GUI/sentinel。该结果只绑定d1版本。独立review指出owner清理若capture失败可能跳过bounded等待；正常GUI仍未批准，下一修订须保留d1源码/binding/actual0事实并新建版本复审，不从前置0推断cleanup负路径或GUI通过。

[临时资源ledger](temporary-resource-ledger.json)：6个已消费自有extract/source observer/portability/utility generator/native readonly helpers已逐字归档核SHA并精确删除；7个未来GUI/只读audit helper继续保留。新的代码无4个旧安装tmp相互引用；旧4helper已消费，可在Root确认没有活跃旧review消费者后按原ledger精确SHA删除，不改旧binding/失败收据。安装目录、新副本、旧DATA、原stage/output全部保留。无Git写入。

[PLAN](PLAN.md)仍列明真正UI验收/自然退出/crash/recovery为后续授权与验收范围，整个最终源码Goal尚未完成。

## v2独立review修订

Root认可R1/R2，并仅授权修helper。新[v2审查与精确命令](V2-REVIEW.md)与[binding](reviewed-binding-v2.json)固定新代码/哈希；[纯替身验证](v2-guards-validation.json)、[默认review](v2-review-default-validation.json)actual0，尚未native/GUI/sentinel执行。d1原helper/archive/binding/前置actual0完全保留。Root要求review关闭后一次正常launch自带当前validation，不额外重复v2只读整轮。
