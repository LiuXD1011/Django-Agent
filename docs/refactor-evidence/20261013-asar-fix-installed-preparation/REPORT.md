# 新 ASAR-fix 安装与正常生命周期验收

正式新安装器唯一绑定、既有隔离目录升级、正常启动→Root真实托盘退出→重开→再次真实退出均完成。安装／两次controller实际exit0；原Main／Core及captured成员均保留原HANDLE确认wait0、exit0、privateJob active0，没有force kill、shutdown-error或identityRace。Root单独负责真实登录、问答、引用导航、历史恢复与UI注销证据；本controller的生命周期结果不代替完整UI验收。

固定安装目录 `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用`，固定独立数据 `业务验收 20261013`、既有desktop-profile保持。新installer SHA `4edc4d970ccf383b9dd48a6ef38bce1b192e071a1c450a186c0bd63c54abc52e`，binding `8643e557…562c2`。25,381安装文件与正式新manifest匹配；升级前后DB／WAL／SHM和opaqueKey hash相等，两次GUI后Key仍相同。没有读Keyplaintext、私有auth／token／password值，没有改密码、配置或别的space数据。

关键收据：[最终汇总](FINAL-RECEIPT.json)、[实际binding](reviewed-artifact-binding.json)、[升级receipt](installed-receipt.json)、[非GUI执行](execution-non-gui.json)、[第一次原生命周期](launch-1-lifecycle-check.json)、[第二次原生命周期](launch-2-lifecycle-check.json)。原Main1 PID36052／FILETIME134363572936733190，Main2 PID22820／FILETIME134363584175021276；各captured8成员全0，包括真实bundledNode／Core。

仅一次小Native SQLite只读核查与一个页面scope纠正：全库180模型记录，相比copy基线174新增6条全部成功、6241tokens，重开未重复调用；desktop_jobs／task_records active0，专用QA未撤销设备0。固定chat保留两completed消息、assistant五引用、林青128000、预期document／chunk及真实RID `617950a6-80be-453e-af64-0a20115be125`。按实际Core用户空间／页面过滤，QA tenant2的普通知识库2个、文档16份；[首RO原结果](final-sqlite-readonly.json)、[正确scope结果](final-sqlite-scoped.json)、[实际schema](final-sqlite-schema.json)。两次query_only／mode=ro、totalChanges0，没有新增API登录或模型调用。

模型表duration_ms是本条上游调用记录：Embedding292ms、ReRank139ms、agent_chat两条9297／13214ms，memory_extraction6448ms、memory_keywords1318ms；未测精确产品TTFT／P95，不把这些duration相加或将CLI运行时间当产品延迟。此安装验收不扩大为每类模型／每页的新全量回归。

两次helper问题的实际失败完整保留：首次bind actual1是固定owner marker的CRLF被新helper仅LF判断拒绝，单行修订仅认可已知LF／CRLF（[原字节与修订](marker-crlf-fix.json)）；首次最终RO actual1是把当前页2KB16docs误当全库，真实全库6KB18docs保持不改，追加scoped actual0关闭错误断言。旧869正常启动FAIL证据未动，未重放旧wrapper。

Root已审3个准备helper源码均归档：[main](marlin-asar-fix-installed-20261013.py.source.txt)、[owner](marlin-asar-fix-installed-owner-20261013.py.source.txt)、[utils](marlin-asar-fix-installed-utils-20261013.py.source.txt)。仅只读提供任务栏句柄／相关UIA入口，不操作GUI（[Win32](tray-observe.json)、[UIA](taskbar-uia.json)）。两controller终态后，3prep与本次tinyRO／observer临时helper按精确archive／执行binding SHA删除，见[清理](consumed-helper-cleanup.json)；没有第三slot，未碰Root私有auth／UIhelper、production、Git、安装器或用户数据。
