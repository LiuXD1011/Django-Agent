# 正常安装版GUI launcher独立审查：d1版本

2026-10-13。结论：**request_changes，两个阻塞项R1/R2**。此结论只针对不可变 binding `d1b09d0c1bb5ac907ea250a472c5f22a6b1fb08b152b32e8e2f994b622d84beb` 所绑定七份 helper，不把随后拟议v2修订或已完成的native只读precondition计入本结论。Windows worker已明确赞同两项并准备另版修订；旧binding/收据保持，普通GUI与sentinel尚未由本审查执行。

完整读取[PLAN副本](reviewed-PLAN.md.source.txt)、独立owner/utils、clone、launcher、control、supervisor、sentinel源码。原schema大对象仅用于读取/摘要比对，未重新扫描历史安装/业务证据。审查只写本目录，没有修改生产、主四文档、worker文件、Git或QA数据，没有克隆、启动任何pending harness/GUI/sentinel或操作Orca。

## R1 — failure cleanup的capture再次失败会跳过强制终态观察（P1）

[owner源码第76–87行](reviewed-d1-owner.source.txt)，关键是第82行：`self.capture(); ... TerminateJobObject(...)`。若原异常来自成员枚举、OpenProcess或身份查询，cleanup再次执行capture可以复发；随后直接进入第87行finally关闭全部句柄。显式TerminateJobObject、第83–86行Job accounting和原root/已保留成员等待均未执行。

本审查只从归档AST抽取cleanup_failure/close_handles两个方法，注入明确fake Win32 API和抛错capture，未导入或执行pending harness。实际探针exit0，调用序列只有关闭job/member/thread/main四个句柄，显式TerminateJobObject和WaitForSingleObject调用均0；原错误保留、closed=true。见[原探针与精确清理](isolated-review-probe.source.py.txt)、[实际结果](isolated-review-results.json)。这是对失败分支的RED证据，探针本身exit0表示复现断言成立，不是GUI清理通过。

Job设置KILL_ON_JOB_CLOSE仍提供最后句柄关闭时的终止fallback，因此本发现**不声称实际遗留存活进程**；问题是关闭原句柄前没有取得承诺的五秒有界终态观察，不能再证明原树已空。官方[Job限制合同](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information)确认该flag触发关闭时终止；[TerminateJobObject合同](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)说明显式终止涵盖该Job及嵌套子Job。

此函数还被[launcher第76–79行](reviewed-d1-launcher.source.txt)和[supervisor第25–27行](reviewed-d1-supervisor.source.txt)复用。应把capture作为补充成员的best-effort观察、独立保留其错误，仍尝试仅自产原Job终止并核原root/既有retained/Jobactive0；任何终态读取失败继续明确失败，不能以关HANDLE补推成功。无需按名字或端口kill。

## R2 — outside原句柄保护仅包含Electron，遗漏已核的Node/Python（P2）

[owner第98–117行](reviewed-d1-owner.source.txt)枚举Marlin/Electron/Node/Python/Pythonw候选，非owned活进程已完成image与FILETIME读取；但第114–115行只在名称为electron.exe时append原HANDLE。非owned node.exe/python.exe/pythonw.exe直接走第117行关闭HANDLE。因此例如仅有一个安装目录外Node旁实例时，outsideProtectedCount=0，没有该实例的跨GUI生命周期原句柄保留断言。

[PLAN第三阶段第1项](reviewed-PLAN.md.source.txt)要求真正present的outside handles持至终态；原范围没有明确限定为Electron。Windows worker已确认范围更窄是实现遗漏。应按Root指定相关候选范围保留真实活的非ownedElectron/Node/Python原HANDLE、image和完整FILETIME，按种类准确记录数量；安装目录内Marlin/Core/worker仍必须先拒绝并由Root自然退出，不能改为强停。实际outside=0只表示无匹配旁实例，不能计保护PASS。历史25268缺失也不在本次补成保留通过。

本项是源码分支/合同对照，不声称在真实Windows新造或观察了任何旁实例；本审查没有运行Toolhelp/OpenProcess。

## 其余已核边界

- [精确binding副本](reviewed-d1-binding.source.json)固定installed0ee5a94b…/postcheckbfbe7393…、旧468/dd5来源/869安装器，原outer1保持；clone receipt SHA `54fe8df748ab873a9835648782691e4e4311d3baa66ef3041c3712db5a1451c7`实际77表/25材料，与绑定及JSON计数相同。launcher第15–24行先核全部输入SHA、全安装inventory/12ASAR/注册/clone marker及DB/行/材料，固定命令仅installed `Marlin.exe --data-dir <新DATA>`，没有smoke/inspect/GPU/devserver参数。
- owner第18–22行CreateProcess suspended→原image→Assign自产Job→Resume；成员须IsProcessInJob才pin HANDLE，原root从CreateProcess保留，不依赖后来按裸PID重开。完整FILETIME为64位字符串。[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)、[IsProcessInJob](https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob)文档确认QueryLimited权限适用这些只读调用；不把成员query权限误认为可TerminateProcess。
- sentinel是GUI Job的兄弟Job，位于supervisor的外层生命周期Job之下；因此可检查GUI Job自然退出或main77 crash不影响sentinel，不宣称它在supervisor自身崩溃之后继续存活。sentinel固定bundledNode/脚本、session32十六进制、无网络/Core/数据库，只认精确stop协议。
- control固定目录/marker、互斥controller HANDLE、原子临时帧rename、最多256帧、无任意PID/path/argv/port；nonce/sequence/有限action约束有独立纯函数验证，foreign path、bool sequence、foreign nonce、seq gap、unknown action五种均拒绝。另非阻塞观察：protocol=True被`==1`接受；正常controller只发整数1，可在修订中严格type处理，本项未提升为执行阻塞。
- natural-exit仅打印Root托盘指引，不发WM_CLOSE/Terminate；force-crash-main只向保留原mainHANDLE发77，必须由Root另行明确授权；second-instance仍相同exe/DATA及独立短Job。默认14400秒、仅一次7200扩展、硬上限21600与outer21690分层；main早退而Job仍活不算正常，45秒拒绝，crash观察30秒后才异常自产Job清理。Root未发natural-exit但程序自然exit0时收据仍awaiting_root_ui_verdict/actualRootTrayClickVerified=false，不冒充真实托盘点击。
- stdout/stderr到NUL、最小OS环境/PATH System32、不继承Key或数据库地址。报告只含进程身份/状态与表/文件摘要；RuntimeError/Refusal为固定代码，其余异常details_withheld，未读取private-auth或解密材料。后置changedTables/changedInitialMaterials明列，正常认证/profile变化不要求全DB字节相等，calls不从进程状态推测。

## 验证与边界

六份Python helper的AST解析、sentinel仅stdin语法检查、binding/clone SHA与77/25计数、上述纯替身方法/控制检查均actual0。没有执行未交付harness默认模式、native precondition、安装器、模型、服务、克隆或GUI；此前worker自己的native只读0是独立事实，不能覆盖本次R1/R2。明确的两处阻塞外未发现新增阻塞问题；新v2须按新SHA完整复审及对应隔离回归后才能关闭本结论。

本次绑定、链接、差异和自有探针归档删除见validation.json与cleanup.json。原d1七源码和binding的逐字副本保留在本目录；计划prose后续变化按时点记录，不以当前PLAN重写旧审查。Goal与全部Windows GUI验收仍未完成。
