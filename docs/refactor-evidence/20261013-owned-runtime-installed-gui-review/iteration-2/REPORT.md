# 正常安装版GUI v2独立复审

2026-10-13。**Spec compliance：accept。Code quality：accept。新增阻塞finding：0。** 原R1/R2在本次绑定v2源码/隔离回归范围闭合，protocol bool建议也已收紧。审查对象 binding SHA `6f14a152f15256d774e936fb1884d88e445715224449c3e64fbd8858768dfd9e`，完整读取owner052d7d1f…、launcher7133144c…、controlad57736a…、supervisor71937442…、v1→v2完整diff与V2-REVIEW。旧d1 [request_changes](../REPORT.md)、RED结果和冻结全部原字节保留，不覆盖旧结论或把其native只读0外推到v2。

本轮只写独占iteration-2目录。没有运行pending harness/default模式、v2 native只读、GUI/sentinel、clone、服务、模型或Orca，也没有改生产/主四文档/worker文件/Git。正常启动内validation、真实GUI、second-instance、关闭后台/托盘退出及Core业务页面结论由Root另行执行。

## R1闭合：capture失败不阻断原Job终止与有界原句柄观察

[owner v2第78–104行](reviewed-owner-helper-v2.source.txt)：记录独立captureErrors后仍调用原Job的TerminateJobObject，第89–99行分别观察Job accounting、原root HANDLE与既有retained HANDLE；共用原5秒单调deadline，每项等待只取剩余预算。capture是补充成员观察，不是强制清理的前置条件。accounting异常独立写terminalErrors；原root/member不为Wait0时wholeOwnedTreeTerminalProved=false并明确拒绝，不凭最后关句柄推算成功。API终止结果字段与终态证明分层保留，不能把字段false抹成API成功。

构造失败保留原异常并携带ownedCleanup；[launcher第52–54、77–81行](reviewed-launcher-helper-v2.source.txt)的第二实例/GUI/sentinel失败以及[supervisor第25–28行](reviewed-supervisor-helper-v2.source.txt)都归档lastCleanup，避免只有错误类型而丢失终态层次。正常结束依旧要求原root/Job/保留成员终态；没有扩大名称、端口或外部PID清理。

独立纯AST回放5个case均actual0：capture失败仍Terminate+Job0+原root/retained Wait0并成功；accounting未知、root258超时、member258超时、root WAIT_FAILED分别拒绝终态通过，同时仍完成其他原句柄观察、关闭自产句柄。所有fake Wait预算在0–5000ms，未调用真实OS等待。本审查另原样抽取d1方法，仍复现只关句柄、不调用显式终止的旧RED。[探针来源](isolated-v2-review-probe.source.py.txt)、[完整结果](isolated-v2-review-results.json)。这些case是明确fake Win32方法验证，不是Windows实际Job清理或实际PID复用实验。

## R2闭合：实际候选保留与精确自产祖先排除

[supervisor第13行](reviewed-supervisor-helper-v2.source.txt)在创建launcher之前以write_new记录本次自身真实PID/完整FILETIME/image；固定context按normal/readonly role及v2 binding分开。[launcher第18、28行](reviewed-launcher-helper-v2.source.txt)核固定context精确字段，另独立读取自身身份，附Toolhelp必须匹配的expectedParentPid，传入只有本次launcher与supervisor两项排除身份。

[owner第112–115、127–154行](reviewed-owner-helper-v2.source.txt)：排除先匹配PID，再要求FILETIME/image精确匹配；launcher额外核父PID。并分别核实supervisor本代身份，因此不是仅凭同名Python或任意祖先PID排除。预期自产身份未实际观察到会拒绝，不把自己祖先悄悄算旁业务。其他真实活的Electron/Node/Python/pythonw候选一律pin原HANDLE/image/FILETIME；安装目录候选与Marlin存在仍拒绝并交Root自然退出。

本审查不仅回放is_own_tool，还把完整outside_handles函数抽入fake Toolhelp/OpenProcess/GetTimes实现。正常枚举里恰好排除自产101/102，保留四项103/104/105/106；其中外部Python105的image与自产完全相同，仍保留，证明没有宽泛image/名称排除。installed runtime候选和缺失expected self两项失败case均拒绝，并关闭该次所有已打开观察句柄；另PID不同不排除，FILETIME/image/父关系三种不匹配拒绝。三枚举case及三个身份guard实际检查均exit0；没有真实枚举Windows或创建旁实例。outside0仍不是保护PASS，历史25268缺失不补成通过。

## 绑定、有限协议与保留边界

- [v2 binding副本](reviewed-reviewed-binding-v2.json)继续pin clone54fe8…实际77表/25材料、installed0ee5…/postcheckbfbe…及旧468/dd5/869来源，schema逐字段与d1相同；旧outer工具1保留。utils/clone/sentinel未变，四v2 helper走新文件和新binding，旧d1正常命令不能替代新v2交付。
- [launcher第12–13行](reviewed-launcher-helper-v2.source.txt)和[control第16行](reviewed-control-helper-v2.source.txt)对protocol使用type is int，与sequence同样拒绝bool。独立纯函数确认有效snapshot及六拒绝：protocol bool、sequence bool、foreign path、foreign nonce、sequence gap、unknown action。原固定目录/marker/nonce/原子序号/256上限与有限action保持，不加入任意PID/argv/path入口。
- 正常命令仍只有固定installed Marlin.exe和--data-dir；多页14400秒/一次7200扩展/硬21600与outer21690保持。natural-exit只提示Root点击本窗口自己的tray Exit；main77 force crash必须另获Root特定case授权，不能继承正常launch授权。sentinel仍是GUI Job兄弟、外层supervisor Job成员，无网络/Core/数据库。
- stdout/stderr NUL、最小OS环境/系统PATH、secret不回显、固定错误代码、changedTables/changedInitialMaterials和正常认证/profile变化边界保持。过程alive、sameHANDLE终态或纯guards不代替Root GUI就绪、托盘/单实例、Core页面、付费模型或全部Goal判定。

worker [V2-REVIEW副本](reviewed-V2-REVIEW.md)、[worker原guards](reviewed-v2-guards-validation.json)和[完整diff](reviewed-v1-to-v2.diff.txt)已核读，不把worker检查冒称审查者执行。本审查独立来源、结果、输入SHA/链接及精确清理记录另见validation.json/cleanup.json/freeze.json。源与旧d1 artifact前后SHA未变；没有重复旧大规模业务/安装审计。

首轮本审查probe实际exit1是夹具catch类型错误：launcher.need抛RuntimeError，review probe误只catch Refusal；发生于protocol拒绝测试，未运行任何native或harness。原版本与失败保留：[原源码](isolated-v2-review-probe.initial.source.py.txt)、[actual1记录](probe-initial.actual1.json)。只修夹具catch后上述完整纯检查actual0，v2产品/worker源码没有修改。

本结论允许Root以所审v2具体命令继续其已授权的正常验收准备，不构成执行或native通过记录；不要求额外重跑v2RO。Goal、普通GUI、最新完整源码Windows包及实际业务验收仍未完成。
