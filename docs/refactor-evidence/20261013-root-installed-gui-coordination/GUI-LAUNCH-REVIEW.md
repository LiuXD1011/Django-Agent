# Root 对固定安装版正常启动的具体审核

2026-10-13。依据 Goal 第二节第 3 项及 J 节，批准 Windows worker 恰一次正常启动固定安装版。Root 已完整读取 v2 owner/launcher/control/supervisor 全文、[v2 说明](../20261013-owned-runtime-installed-gui-preparation/V2-REVIEW.md)，重新核验四份归档及 binding SHA，并读取[独立复验 actual0](../20261013-owned-runtime-installed-gui-review/iteration-2/isolated-v2-review-results.json)。独立 reviewer 已确认 R1/R2 在稳定 v2 范围可关闭，无新增阻塞。原 d1 request_changes 与只读前置 actual0 分别保留。

v2 binding SHA `6f14a152f15256d774e936fb1884d88e445715224449c3e64fbd8858768dfd9e`。owner `052d7d1f634491cdfceea40bdcb1aaa6394f7886595b86b5d7b035fb2504f95e`；launcher `7133144c785e2d6d1a9465b22f17e6482756017ea0dac236da35212ed8782695`；control `ad57736a5e5d475b5bab6550ccb03b3f62988881f8b148b67e3e342cea466441`；supervisor `71937442e9188d7087d3a852b50674d35da740698a6693c1c08ad5d8a50b6325`。

具体唯一命令：

```text
C:\Python313\python.exe -B \\wsl.localhost\Ubuntu-20.04\tmp\marlin-installed-gui-supervisor-20261013-v2.py --execute-reviewed-launch --binding-sha 6f14a152f15256d774e936fb1884d88e445715224449c3e64fbd8858768dfd9e
```

它在启动内部执行完整当前验证，无需再重复只读 precondition。固定程序仅 `C:\Users\lxd\AppData\Local\Temp\Marlin 安装验收 20261010\应用\Marlin.exe --data-dir <同父目录\业务验收 20261013>`；Root 恰一次创建的副本为 77 表、25 材料，收据 SHA `54fe8df748ab873a9835648782691e4e4311d3baa66ef3041c3712db5a1451c7`。不启动 smoke 或开发服务器，不注入认证。

批准本次自产独立 sentinel、原 GUI/supervisor HANDLE 与私有 Job 的既定有界观察。默认 GUI14400 秒，仅一次延长7200 秒，上限21600，外层21690；任何失败保持原实际回执，不自动重放。实际非自产 Electron/Node/Python 的已 pin HANDLE 保留，按精确 PID/FILETIME/image 与父关系排除自有工具；实际零不能计旁实例保护通过。捕获成员再失败不能跳过自产 Job 终止和原 HANDLE/Jobactive 的有界终态观察。

Root 会独占正常桌面 UI，使用专用 QA 账号经原登录页面输入，随后验证业务、单实例与托盘。有限 controller 的 snapshot、natural-exit、second-instance、extend-once 可在本次明确用例中使用；natural-exit 只表达观察意图，真正退出由 Root 点击自有托盘。`force-crash-main` 尚未授权，待独立具体崩溃用例；不按名称/端口终止任何进程。

安装包仍属旧468/dd5源码与869a安装器，包含 Runtime 修复，不含后续 sidebar/detail/autostart；原升级 outer1 保留。启动 helper 活着、纯替身通过或正常窗口出现都不能冒充全部安装版/Goal 通过。真正结论据 Root 实际 UI 步骤、所属树终态、数据审计与最后交付源码分别记录。
