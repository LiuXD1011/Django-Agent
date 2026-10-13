# 侧栏属性修复：实际 Windows 阶段包

本文件接续本目录此前的准备性 README。唯一 copy、prepare、package 均已实际完成，未执行安装或应用启动。这是来源 6e37 的侧栏阶段历史包；Root 后续真实发现的库类型筛选问题尚未纳入，不能称最终交付或 Goal 完成。

| 实际阶段 | 原生会话 / 终态 | 耗时 | 回执 |
| --- | --- | --- | --- |
| copy | 81499 / exit 0 / 671f5e | 809.733 s | [copy-execution.json](copy-execution.json) |
| prepare | 30038 / exit 0 / d530ff | 1293.909 s | [prepare-execution.json](prepare-execution.json) |
| package | 60561 / exit 0 / 6c38ab | 959.903 s | [package-execution.json](package-execution.json) |

三阶段实际私有 Job 进程树均已闭合，无重试。prepare 结束后已明确交回全部 GUI 租约给 Root。package 仅正式 `--publish never`，未打开业务窗口。上述耗时为构建阶段耗时，不能当作产品延迟。

[实际 prepare 核验](prepare-native-terminal.json)：Windows 前端 361/361（504302.9742 ms，fail/skip/cancel/todo 全 0）、核心定向 24/24、正式编译运行时 6/6、Python 11 个真实解析夹具、精确 64 位 FTS/vec ID `1152921504606847297`、无 Django 的隔离 Python、实际受控 Electron/NextAuth 边界全部通过，零模型调用。它们不替代完整核心套件或真实外部 Langfuse 服务验收。

[实际 package 核验](package-native-terminal.json)：10 项 ASAR 资产白名单、清理后的实际 package metadata、25304 个运行资源全部匹配正式清单；七份导出报告与 stage 完全相同。ASAR SHA 895f93 与旧包相同，因为本轮 desktop 无变；runtime manifest 更新为 36b2bc，包含新前端。来源 457 / 额外测试 5 / 本地产物 438 core + 85 frontend 与 6e37 冻结相同。旧 99ba 安装器、旧 stage 六个关键文件与原 sidecar 全部重新核验相同。

新安装器固定路径为 `C:\Users\lxd\AppData\Local\Temp\Marlin TS Sidebar A11y Installers 20261012\Marlin-Setup-0.6.2-x64.exe`，401841335 字节，SHA256 `aabd44bc71a7a36b3d583720f8292b4035efe1c69159740db513931293568556`。桌面版本 0.6.2，核心版本 0.7.0，二者分别记录。

[唯一 iteration 1 审阅请求](../20261012-sidebar-a11y-install-preparation/reviewed-binding-request-1.json) SHA256 `eb522f4ad914dd53d6c497d66687fdf26556742cc84c27a3a7ba0ae7d1785fc9`。生成请求的[完整 81 行校验源](artifact-request-validator.source.txt) SHA256 `af06d80870f9309fd5bcb7f909f6f29de22d10e2d9849e719c9597e5b16b1ef2`，仅本地读取实际成功回执和公开构建文件，未调用 Windows/native、artifact_binding 或资料操作。真实消费检查 52056 / exit 0 / 1780ce 后归档清理。

Root 下一步亲读请求及 [95a8 安装 harness](../20261012-sidebar-a11y-install-preparation/reviewed-harness.source.txt) 后再执行 binding；本次交接没有创建 iteration-1 或 artifact-binding.json。安装/隐藏 smoke/1024 侧栏实际 GUI 回归仍待执行；原 UnknownVizError 与可见诊断整体 exit 1 历史保留，没有声称修复或重放。
