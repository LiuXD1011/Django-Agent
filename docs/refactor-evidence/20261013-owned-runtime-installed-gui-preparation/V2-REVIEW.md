# 正常GUI v2修订：等待Root与独立review

v1/d1已批准的只读前置actual0与原代码/binding保留。v2没有执行native前置、产品、sentinel；Root决定独立review关闭后正常启动内执行完整validation，无需额外重复一轮v2只读。

[完整diff](v1-to-v2.diff.txt)、[owner v2](owner-helper-v2.source.txt)、[launcher v2](launcher-helper-v2.source.txt)、[control v2](control-helper-v2.source.txt)、[supervisor v2](supervisor-helper-v2.source.txt)、[binding v2](reviewed-binding-v2.json)固定SHA。binding `6f14a152f15256d774e936fb1884d88e445715224449c3e64fbd8858768dfd9e`。

R1：cleanup先尝试capture，失败作为独立captureErrors保存，不阻止TerminateJobObject。随后对原root/已有retained HANDLE做有界等待并核Jobactive，accounting不可用仍观察原HANDLE并拒绝whole-tree绿灯。构造失败、GUI/supervisor cleanup失败均携带原层次证据；只终止自产Job或未Assign的自产suspended原root。

R2：actual非自有Electron/Node/Python当前活进程的原HANDLE/FILETIME/image保留至终态；installed路径候选/Marlin存在仍要求Root自然退出。本次supervisor在固定context文件记录自己的真实原PID/FILETIME/image；launcher核自身身份及Toolhelp父PID关系，排除必须PID/FILETIME/image相等，不用名称或宽泛祖先排除。context路径/role/binding固定，不向controller新增任意PID或argv接口。已经退出的candidate race记录同HANDLE真实Wait/Exit或OpenProcess87身份缺失，不伪造身份。

protocol也严格整数，bool不接受；atomic固定序号文件接口与正常GUI动作范围保持。

[纯替身回归证据](v2-guards-validation.json)与[已消费验证源码](v2-guards-consumed-helper.source.txt)：old capture失败确实绕过Terminate RED；新capture失败仍Terminate+原root/retained Wait0+Jobactive0；accounting未知仍Terminate/Wait且拒绝绿灯。自身匹配/foreign不排除/FILETIME或image或parent不匹配拒绝、protocol/sequence bool拒绝均actual0。未导入native owner或启动产品。三项[默认review模式](v2-review-default-validation.json)actual0，AST0。

Root具体批准后唯一正常命令：

```text
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-installed-gui-supervisor-20261013-v2.py --execute-reviewed-launch --binding-sha 6f14a152f15256d774e936fb1884d88e445715224449c3e64fbd8858768dfd9e
```

有限controller例如snapshot：

```text
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-installed-gui-control-20261013-v2.py --send snapshot --binding-sha 6f14a152f15256d774e936fb1884d88e445715224449c3e64fbd8858768dfd9e
```

force-crash-main仍需Root明确特定case授权。正常main/单实例/Key/paid model/UI结论尚未执行，不从pure guards或d1只读0推断。

后续事实：Root完整审核与独立review关闭后已执行唯一v2正常launch，本次用户原图判定STARTUP FAIL（Core代码1），tree/native工具0只属收尾；详见[REPORT](REPORT.md)。本文件上文保留执行前review范围与精确命令，不作为再次执行授权。
