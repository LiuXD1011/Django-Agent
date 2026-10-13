# Langfuse 开发自动启动迁移：独立审查

2026-10-13。审查范围是本次 TS CoreOwner 开发入口迁移及显式 `discardOutput` 扩展。已阅读根 AGENTS.md、[设计计划](../20261013-local-services-autostart/DESIGN-PLAN.md)、[原迁移合同](../20261013-legacy-retirement-prepare/AUTOSTART-GAP.md)、[实现报告](../20261013-local-services-autostart/REPORT.md)、完整 14 文件差异、受影响文件全文，以及现有配置、凭据、数据库、supervisor、worker 和桌面入口依赖。没有修改生产代码或原证据，没有提交、操作真实 Docker、用户数据、浏览器或安装包。

## 两项独立结论

- **Spec compliance：尚未完全符合。** 可信 Owner 接线、默认关闭、环境优先、loopback、跨进程 OS 锁、固定 CLI、健康检查、非致命业务启动和桌面排除均有对应实现与原验证证据；但执行文件解析阶段没有持续遵守同一截止时间/取消信号，且超时解析仍缩小了旧 `float()` 的有效有限输入集合。
- **Code quality：建议修改后重新审查以下两处。** 服务生命周期与私有入口边界清晰，复用了真实进程监管机制，默认输出捕获没有被删除；新增解析循环缺少工作阶段的预算/取消检查，新增解析正则缺少完整兼容回归。没有提出与本任务无关的整理要求。

## 问题

### R1：Docker PATH 遍历会在截止时间或取消后继续工作

位置：`packages/core/src/integrations/local-services.ts:36–48`，调用点 `:113`。

触发条件：绝对 PATH 候选较多，或者候选所在文件系统的 stat/access 较慢，且最终没有可用 Docker。`dockerExecutable(env)` 不接收截止时间或 signal，循环中的每次 stat/access 之间也不调用 `remaining()`。调用方只在正常返回后检查剩余预算，解析器最终抛出 `docker_unavailable` 或 `startup_failed` 时跳过此检查。因此启动可以超过配置预算后继续遍历，最终诊断也未反映已耗尽预算；取消或 service.close 也必须等待所有剩余候选完成后才能结束。

独立回归在 10 个候选的 Docker stat 上各注入 160ms 延迟和 ENOENT，其他 source 配置、SQLite OS 锁和状态写入保持真实。配置 1 秒预算，实际遍历 10 次、耗时 1611.8ms，返回 `docker_unavailable`，期望 `startup_timeout`；40ms 发出取消，仍遍历全部 10 次至 1611.4ms 才返回 `cancelled`。这证明的是受控慢文件系统下的遍历与分类问题，不是一次真实 Docker 启动或 native Windows 结果。

建议让执行文件解析使用同一 `remaining()`/signal，在候选和 stat/access 之间检查；处理解析器抛错时也先判定取消和原截止时间，避免在预算耗尽后把结果分类为缺 Docker。单个不可取消的文件系统请求可以说明限制，但不能在它完成后继续整个 PATH。

### R2：合法旧 float 环境值被静默替换成 45 秒

位置：`packages/core/src/integrations/local-services.ts:24`。

触发条件：部署环境 `LANGFUSE_STARTUP_TIMEOUT_SECONDS` 使用旧 Python float 合法的有限十进制表示，例如 `1_0`、`1_2.5` 或 `١.٢٥`。独立回归直接执行当前 Python 的 `float()` 得到 10、12.5、1.25；新解析器均得到 45。下划线数字和 Unicode 十进制数字不属于本次已明确拒绝的 JS 十六进制语法；环境优先仍成立，但原明确设置的工作预算发生变化。普通 ASCII 小数和 UI 保存的 number 不受此问题影响。

建议保留旧合法有限十进制输入的解析/夹取语义，并增加有效下划线、Unicode 十进制数字和非法下划线位置回归，继续拒绝十六进制、非法/非有限值并按合同回退 45。

## 其余合同核对

| 项目 | 审查结果与依据 |
| --- | --- |
| 默认关闭 / 外部 API 零副作用 | service 在目录创建前 early return；env false 压过保存 true。 |
| 配置来源与 API/UI 区分 | CoreApplication 同 Owner 同步读取一次 snapshot；BASE_URL > 保存 base_url > HOST > localhost；只传 startup 三字段，UI/tracing 开关未作为 gate。 |
| 超时与 CLI/health | 锁 grant 不重置 deadline；config/up 用真实剩余；health GET 仅 200、direct native agent、无 redirect、每次 min(2s, remaining)。R1 是解析阶段例外。 |
| 同 dataRoot 互斥 / 释放 | 独立 `.cache/langfuse/startup-lock.sqlite3`、timeout:0、BEGIN IMMEDIATE 持有至 finally rollback/close；原证据含真实第二进程等待、释放和杀 holder 恢复，无业务 DB 跨 await 事务。 |
| 固定命令 / 自产进程 | 固定 shell-free compose config/up，sourceRoot cwd；只由 OwnedProcessRegistry 管理本次 CLI 和后代，没有 down/卷删除/按端口名杀进程。 |
| 非致命与关闭 | 常规服务失败返回固定状态并让 HTTP 启动；signal guard 在可选 startup 前安装；close 等待 pending 和 owned registry。原 occupied-port 用例保留 exit1。 |
| 私有可信边界 | OwnerCall 只有 operation/sourceRoot；client 和 host 均拒绝多余 argv，HTTP transport/renderer invoke 没有启动路由；原测试包含 404/400/403。 |
| 桌面排除 | 桌面工具与 Electron 未添加调用；唯一生产调用是 dev-server；原实际 desktop subprocess 在保存 true/env true 时零 CLI、零 startup cache。 |
| discardOutput | 仅 local-services 显式 true；默认 capture、输出上限、decoder、超时/取消和 supervisor 均保留；原用例覆盖大 stdout/stderr drain 与默认超限拒绝。 |
| 实际已安装 API | 核查 better-sqlite3 13.0.3 实现、@types/better-sqlite3 9.6.0 的 timeout/inTransaction/close 和 @types/node 22.19.15 的 HTTP agent/signal；未新增依赖/锁文件。 |

## 证据与后续检查

新增最小独立回归 actual exit1，0/3，3 个失败分别对应 R2、R1 deadline 和 R1 cancellation：[完整输出](independent-regressions.log)、[actual exit](independent-regressions.exit)、[归档源码](independent-regressions.source.mjs.txt)。临时执行脚本及各自 synthetic 数据目录在运行后删除；原失败证据未被覆盖。

原日志与 machine results 已读取核对：focused62/62、最终 service/Owner/output18/18、typecheck/build exit0、plain compiled2/2。这里引用历史验证结果，不声称本次重新运行，也不累计为不重复测试数量；没有无理由重跑这些用例。`lock-grant-green` 在实现报告中被明确排除，未用其 metadata 作为成功证据。

修复 R1/R2 后需重跑新增针对性回归、相关 local-services 服务/Owner/dev/output 用例与 Core typecheck；若再修改生产源，应完成新的 Core build/compiled 验证并更新来源绑定。真实 Docker/Langfuse、Orca 管理员保存/重启、native Windows 锁/Job/新打包来源仍是 Root 的后续门禁，本审查没有代替它们，也没有解除旧域退役暂停。

本次 14 文件来源 SHA、证据链接和临时清理检查见 [独立核对](review-checks.json)。

独立核对首次执行因检查尚未写出的自引用 `review-checks.json` 链接返回 actual1，14 来源 SHA 和其他链接均正确；已保留 [首次检查失败](review-checks-initial-failure.json)，完成自有证据文件后复查 actual0。此检查顺序错误不属于生产问题；[检查源码](review-checks.source.py.txt)也已归档。
