# 侧栏属性修复：Windows准备交接

本目录目前只有准备性证据，尚未复制Windows stage、构建、安装或启动GUI。[计划](../../desktop-refactor/SIDEBAR-A11Y-WINDOWS-REFRESH-PLAN.md)已获Root审阅；执行仍等待Root最终“源码已冻结可构建”口令和prepare时的GUI租约释放。

[新的完整来源冻结](../20261012-sidebar-a11y-integrated-source-freeze.json)SHA256为`6e37bc4f7e94dbc4714f322ee32c56d32da084a5a039f231603290466ce1b7d8`。457源文件仅Platform.vue变化，额外5个测试不变。总523本地产物实测为438 core与85 frontend：core全部与旧5cab相同，frontend绑定本次Vite输出，10个内容hash路径增加/删除、index.html与sw.js变化单列；没有凑数或冒称前端编译字节未变。新前端检查绑定Root实际361/361及build成功收据，原核心109文件/693通过及compiled2检查仅因核心摘要完全一致保留。实际1024侧栏GUI尚未复验。

初次writer将旧523全视作不变的core输出，在旧Chat hash路径缺失处实际退出1。`source-freeze-writer-initial-failure.json`保留原工具chunk/退出码/原因；旧冻结未改写。调查确认438/85实际范围后，修正的writer实际退出0，归档并删除。中途`/tmp/marlin-agent-sidebar-a11y-stage-copy-20261012.py`候选SHAae0c48…仍原字节保留，未填的binding常量使其不可执行；它不是本次执行入口。

审阅入口为以下完整源码与暂存脚本，Root读后才执行：

| 文件 | SHA256 | 状态 |
| --- | --- | --- |
| `reviewed-stage-copy.source.txt`；`/tmp/marlin-agent-sidebar-a11y-stage-copy-ready-20261012.py` | 6059070aea8c0c7263eaca1beef50b763312108a8f5323384fffccc6b142fe95 | 默认review_only；固定旧/新stage，不接收任意路径 |
| `reviewed-runner.source.txt`；`/tmp/marlin-agent-sidebar-a11y-windows-build-20261012.py` | b8578b1ba0361145e0d95c7a0a97a2e205034ea980f4a7835330675b71ca3348 | 默认review_only；copy/prepare/package三阶段、前阶段实际SHA、唯一回执 |

`preparation-checks.json`实际61项通过：跨POSIX/Windows PurePath复制allowlist、真实Python临时假目录的存在/重叠/symlink/无效payload拒绝、两个默认review_only、Linux不能执行Windowsphase、新来源/编译/额外摘要、零真实Windows回执等。只检验准备性文件守卫，不算完整stage复制、Windows native或产品通过；假目录与检查脚本已精确归档清理，两个执行入口保留供Root审阅。

Root最终授权后首步在原生Windows Python运行新runner `copy --execute-reviewed --reviewed-script-sha b857… --source-freeze-sha 6e37…`，参数须使用上表完整SHA。copy只读核旧stage、复制到新的`Marlin TS Sidebar A11y Final Build 20261012`并正式verify_reusable；旧release/验证结果不作为新门禁复制。prepare需新copy-execution.json实际SHA作`--preceding-execution-sha`并显式`--gui-lease-released`，因为正式Electron/NextAuth门禁会创建自有窗口；package需新prepare执行SHA，NSIS只本地`--publish never`。

新OUTPUT为`C:\Users\lxd\AppData\Local\Temp\Marlin TS Sidebar A11y Installers 20261012`；旧Search Result stage/output/99ba历史全部保留。每阶段沿用正式私有Job timeout3600秒，实际失败/清理事实如实记录，无重试。尚无copy/prepare/package任何attempt/execution，新stage/output尚不存在；新版本、安装器SHA、侧栏GUI通过或隐藏smoke修复均未预填。桌面仍0.6.2/core0.7.0。
