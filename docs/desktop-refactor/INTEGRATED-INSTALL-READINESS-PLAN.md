# 最新集成包安装与页面就绪验收准备

**Goal:** 为已冻结的最新源码准备默认review_only的固定Windows安装/启动harness，根代理全读后显式执行；本准备不运行安装器、应用、GUI、模型或Windows进程调查。

**Architecture:** 新harness从SHA锁定的541行升级归档和最终688行启动归档加载真实函数，复用JobObject、SQLite只读锁、12表/完整文件/凭据摘要、ASAR及随包Node/Python/IPC检查。新的身份绑定和Win32进程前置检查替换旧来源/旧数据基线；原档案及失败收据不修改。

**Tech Stack:** Windows x64 Python3.13、ctypes Win32、SQLite immutable readonly、SHA256；不新增产品模块或依赖。

## 固定范围与方案

已知修复前freeze为`20261012-integrated-readiness-generation-source-freeze.json`，SHA256 `04384889060e32a1249c151c83ea04ee1a772a02f4799b831ab976ac87c9b6fc`，451构建输入/5额外测试/520本地编译产物。随后真实仅分块遇image barrier 422，另代理修复中；该旧freeze不再作为最终交付身份。新harness绑定时要求根代理提供实际新freeze路径/64hex SHA及成功build收据，路径仅能在固定公开`docs/refactor-evidence/20261012-*`范围，且经根SHA审阅的request文件锁定。每轮iteration使用独立收据/WORK/SMOKE_DATA，失败不覆盖或重试。stage仍为`C:\Users\lxd\AppData\Local\Temp\Marlin TS Cancel Worker Build 20261012`；新产物目录固定`Marlin TS Readiness Generation Installers 20261012`。安装范围仅既有`.marlin-install-qa-owned`中文空格目录`Marlin 安装验收 20261010\应用`及`验收数据 二次`，沿用原专用GUID，不覆盖其他安装。

选择复用已审函数的薄适配器，保留原完整安装验证和拥有进程树退出。直接复制两套脚本会增加重复审核；不经新绑定直接复用旧脚本会错用350/435、旧installerSHA及旧90文件摘要，因此不可采用。新artifact SHA/size尚未产出，只有根代理从真实文件取得后才能显式绑定；不填写猜测值。

旧visible PID27784/FILETIME134362309196213069须由根代理正常托盘退出，所属树归零后再采集当前数据基线。所有候选由Toolhelp枚举，再用Win32 OpenProcess、QueryFullProcessImageName、GetProcessTimes和WaitForSingleObject核真实身份/存活，不读取CommandLine，不用CIM字符串创建时间绕过。保护原四模型QA25268/FILETIME134361236166333286及精确外部electron.exe路径；只持有只读句柄，不向它发送退出/终止。执行时拒绝任意活跃Marlin.exe或安装目录下的core/辅助进程。

用户1/KB1/设备2及其余业务表0是当前旧安装观察；Chromium profile/日志可在正常运行中改变。新baseline必须在自然退出后取得当前完整数据文件、12业务表和凭据摘要，再与升级前后比较。不得强求启动前的旧90文件仍同一SHA，也不得因此忽略业务/凭据变化。旧hidden失败收据及旧WORK/SMOKE_DATA不覆盖。

## 准备和根代理执行顺序

- [x] 完整阅读已审升级/最终启动归档、正式builder与desktop实际flags/结果字段；保存复用归档SHA。
- [x] 新harness完成本地无产品guard检查：default review_only、未知/重复/equals参数拒绝、执行缺绑定拒绝、真实request解析/归档/hash核对；最终24/24，只使用本地fixture，不使用Windows活进程或真实数据。Windows SDK字段/函数原型已核，实际Windows行为仍未执行。
- [ ] 根代理等待本轮prepare/package全部真实exit0，以真实installer大小/SHA、prepare/package日志收据SHA显式执行`bind-artifact`。绑定调用正式只读`verify_prepared`一次，核来源、prepared/gates/ASAR、runtime及真实installer/sidecar/导出报告；只生成公开新绑定收据，不安装。
- [ ] 根代理正常trayQuit旧27784且owned树归零后，执行`baseline`：核保护进程精确代次、原安装receipt身份/GUID、offline deny-write/delete DB锁及零WAL；采当前完整文件/12表/凭据摘要，二次相等后冻结。
- [ ] 根代理显式`upgrade`：复用原NSIS私有JobObject树等待/900秒边界，当前baseline及保护句柄不变，完整installed/runtime/ASAR匹配新绑定，升级前后所有当前数据/12表/key相同。失败写新failed收据，不自动重试、不启动旧core。
- [ ] 根代理显式`hidden-smoke`：新WORK和独立中文空格空数据目录，PATH仅System32；用正式Marlin.exe实际`--smoke-test --data-dir`，要求mounted和pageReady均true、kind=login、Node隔离/preload IPC真实、startup_interval精确为`runtime_start_to_renderer_readiness_result`。记录mounted/page_ready/renderer_wait/startup各区间；实际截图需根代理阅读，不将文件存在当人工画面通过。复用随包Node/Python真实SQLite/FTS/vec>2^53、私有fork/新schema/无Django及拥有树退出。旧blank3231.9168ms绝不改成ready。
- [ ] 根代理显式`visible-retained`：只使用新upgrade/hidden成功收据和installed身份；启动既有保留数据，由新私有Job持有到真实托盘退出，7200秒、有每5秒owned状态输出。标题关闭hidden不算退出，helper不能因短工具yield结束。根代理实际验证登录/工作台/业务，再正常托盘退出，最终核所属树全0、业务变更实列、key相同、保护25268仍活。真实GUI操作导致profile/设备等变化不可改称完整文件不变。

精确命令、harness SHA和待绑定项见[准备目录README](../refactor-evidence/20261012-integrated-install-preparation/README.md)。本次准备无产品/依赖/源freeze改动，无提交或发布；新installer大小/SHA、build完成、offline新baseline、实际安装/就绪/GUI生命周期仍由根代理后续绑定和执行。
