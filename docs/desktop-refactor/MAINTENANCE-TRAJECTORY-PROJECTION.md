# 维护轨迹投影修复计划

目标：让轨迹页面显示后台实际维护阶段、结果和警告；没有明确结果的记录不得显示为完成。此修复属于已批准 Goal 的真实轨迹一致性要求。

实际 Orca 操作 `1154`–`1160` 发现“后置维护 · ：完成”。`SessionEventJournal.fold` 只投影旧字段 `step/success`，而当前生产者使用 `stage/status` 或 `stage/state/graph_state/warnings`。原始数据库事件仍完整，错误发生在读取投影，无需数据迁移或重新运行付费请求。

## 文件与契约

- root 修改 `packages/core/src/jobs/journal.ts`，新增直接集成回归 `packages/core/test/maintenance-trajectory.test.ts`。
- 前端代理负责实际轨迹组件、知识库范围提示和直接组件测试，双方不编辑对方文件。
- 保留旧 `step/duration_ms/error`，追加 `stage/status/state/graph_state/warnings`；字符串按现有投影方式限制长度，警告保持 JSON 数组。
- `success` 仅接受实际布尔值，否则为 `null`；不根据字段缺失推断完成，也不改原始事件或任务状态。
- 前端按真实状态显示结果，兼容旧 `step/success`，保留警告和未知状态原值。
- 不修改依赖、锁文件、API 路径、数据库、付费请求执行或自动重放规则。当前已安装取消 worker 包是修复前冻结版本，后续安装构建需纳入本次变化。

## 执行与验证

- [x] 在真实临时 SQLite 中写入现有生产者格式的事件，读取及折叠；断言阶段、状态、警告保持且缺少 `success` 为未知。
- [x] 覆盖旧式明确成功/失败与仅有阶段的记录，记录预期 RED。
- [x] 只修改维护事件折叠分支，记录 GREEN。
- [x] 用 Node 22 执行维护、jobs、chat、memory 相关测试及核心类型检查和构建；核对实际退出码。
- [x] 重启拥有的浏览器测试核心，在同一已完成会话重开轨迹，核对原始阶段/警告，无新增模型请求。
- [ ] 将后续 Windows 包与本次源代码对应，正式 IPC 复核单独记录，不把旧包算为已修复。

核心测试命令：`node --import tsx --test test/maintenance-trajectory.test.ts test/jobs.test.ts test/chat.test.ts test/memory.test.ts`。类型和构建分别为 `npm run typecheck`、`npm run build`（在 `packages/core`）。证据保存在 `docs/refactor-evidence/20261012-root-maintenance-trajectory/`。

## 方案选择

采用修复折叠投影并正确渲染的方案。仅修改前端会继续缺失阶段；额外拉取整个会话原始事件会增加网络读取和两套折叠逻辑。当前纯投影修复可直接读取既有完整事件，保留原历史事实。

## 已执行事实

核心有效 RED 为 0/2，修复后相关测试 61/61（32,799.675399ms）；类型检查与构建退出 0。原始 [RED](../refactor-evidence/20261012-root-maintenance-trajectory/red.tap)、[相关 GREEN](../refactor-evidence/20261012-root-maintenance-trajectory/related-green.tap)、[类型日志](../refactor-evidence/20261012-root-maintenance-trajectory/typecheck.log)、[构建日志](../refactor-evidence/20261012-root-maintenance-trajectory/build.log) 分别保留。前端独立验证见 [显示修复记录](CHAT-SCOPE-TRACE-DISPLAY.md)。

2026-10-12 05:47（北京时间）精确核对旧测试进程 PID245516 的启动时间、可执行文件、参数和工作目录后，以 pidfd 发送 SIGTERM；观察退出用时 200.392ms，仅为停止观察，不计应用冷启动。新 PID823067 的参数与数据目录相同，service_id 保持；[重启前](../refactor-evidence/20261012-root-maintenance-trajectory/live-before.json) 与 [重启后](../refactor-evidence/20261012-root-maintenance-trajectory/live-after.json) 六张业务表全行哈希、真实四模型与密钥材料哈希相等。重启前后无活动任务，用量记录仍为 110；没有模型重放。首次停止辅助脚本缺少 Python pidfd 方法，未发送信号，属于已保留的工具环境错误。

Orca 刷新原已完成会话并点击轨迹，[1175 实际页面](../refactor-evidence/20261011-browser-model-page/1175-maintenance-fixed-real-trace.json) 显示记忆检索“未明确结果”、记忆提取“已保存”、图谱“无权限”、原警告及回合后处理“完成”。读取原事件即可修复历史显示；正式安装版仍须更新和独立复核。
