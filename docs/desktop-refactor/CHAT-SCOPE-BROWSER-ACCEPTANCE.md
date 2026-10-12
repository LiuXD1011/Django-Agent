# 对话范围与轨迹真实浏览器验收

本轮使用 Orca 实际页面操作与同一 TypeScript 核心，版本 0.7.0。不是旧 Django 或 mock 后端。数据目录 `/home/liuxuedeng/.local/share/marlin-refactor/20261010-browser-qa`；专用账户 `orca-page-qa-20261010`、空间 2；页面 ID `4fc18a4f-051f-4326-bffd-878f8150d912`，会话 `6ca71cb8-76b0-4261-9a9a-5469d29adf6c`。起止时间保存在各操作原始 receipt；浏览器工具命令耗时不作为产品延迟。

本轮对话使用已配置 GLM `glm-5.3-flash`，记忆开启、联网和 MCP 未选择。未修改四个真实模型及密钥。以下子项通过不代表对话整组、四模型整组或最终 Windows 安装版通过。

| 子项 | 实际操作与结果 | 原始证据 |
| --- | --- | --- |
| 库入口与显式空范围 | 从标准答案知识库点击发起对话，实际移除预选库并发送 17×19。答案为“结果：323”、零引用；配置、主任务和维护任务均为显式空数组，无检索或工具事件 | [空范围后置核查](../refactor-evidence/20261012-root-chat-scope-empty-confirmed.json)、[发送](../refactor-evidence/20261011-browser-model-page/1118-explicit-empty-send-click.json)、[答案](../refactor-evidence/20261011-browser-model-page/1119-explicit-empty-answer-snapshot.json) |
| 多库范围与事实 | 在选择弹层先选格式库再选标准答案库，实际发送负责人/预算问题；保存两个 ID，答案为林青、128000 元及两条手册引用。工具两次检索均保持所选范围 | [选择](../refactor-evidence/20261011-browser-model-page/1125-chat-multi-scope-picker-current.json)、[答案](../refactor-evidence/20261011-browser-model-page/1131-multi-scope-stream-snapshot.json)、[后置核查](../refactor-evidence/20261012-root-chat-scope-multi.json) |
| 引用来源 | 实际展开两条引用，并聚焦来源按钮按 Enter，打开正确知识库、手册与片段 #6，正文含负责人和预算 | [正确来源](../refactor-evidence/20261011-browser-model-page/1138-multi-scope-source-detail-snapshot.json) |
| 返回与持久化 | 点击主导航“对话”返回最近会话；刷新恢复四条消息、两库选择与模型，不重发问题 | [返回](../refactor-evidence/20261011-browser-model-page/1140-chat-returned-history-snapshot.json)、[刷新](../refactor-evidence/20261011-browser-model-page/1145-chat-reloaded-multi-history-snapshot.json)、[核查](../refactor-evidence/20261012-root-chat-scope-reloaded.json) |
| 置顶与取消置顶 | 实际点击管理菜单置顶，出现置顶分组，数据库 is_pinned=1；再取消置顶回“今天”，最终 is_pinned=0 | [置顶](../refactor-evidence/20261012-root-chat-scope-pinned.json)、[取消后页面](../refactor-evidence/20261011-browser-model-page/1153-chat-unpinned-current-snapshot.json)、[最终核查](../refactor-evidence/20261012-root-chat-scope-fixed-reloaded.json) |
| 已有会话上下文 | 点击 128K 控件，实际显示窗口 128000、已用估算 482、0%、压缩阈值 120000 | [已有记录占用](../refactor-evidence/20261011-browser-model-page/1142-chat-context-window-state.json) |
| 轨迹、工具与 Schema | 点击轨迹和工具过滤，两次同名工具记录分别显示；聚焦 Schema 按 Enter，实际展开调用时 query/top_k 定义；返回全部过滤 | [工具过滤](../refactor-evidence/20261011-browser-model-page/1157-chat-trace-tools-filtered.json)、[Schema](../refactor-evidence/20261011-browser-model-page/1160-chat-trace-schema-snapshot.json) |
| 三种时间轴 | 稳定修复后从“序列·7条”实际按 Enter 切“时长·12.4s”，再切“时钟·29.5s” | [序列](../refactor-evidence/20261011-browser-model-page/1175-maintenance-fixed-real-trace.json)、[时长](../refactor-evidence/20261011-browser-model-page/1178-fixed-timeline-duration-snapshot.json)、[时钟](../refactor-evidence/20261011-browser-model-page/1181-fixed-timeline-third-mode-snapshot.json) |
| 显示问题回归 | 重启新核心、刷新并点击原对话轨迹后，维护阶段、状态、警告及图谱权限均显示；检索降级为可读中文和原代码。实际移除两库、打开弹层，0 已选提示“本轮不检索知识库资料”；随后刷新恢复持久化两库草稿 | [真实轨迹](../refactor-evidence/20261011-browser-model-page/1175-maintenance-fixed-real-trace.json)、[空提示](../refactor-evidence/20261011-browser-model-page/1187-fixed-empty-scope-hint-snapshot.json)、[可见截图](../refactor-evidence/20261011-browser-model-page/1188-fixed-empty-scope-visible.png.png)、[恢复](../refactor-evidence/20261011-browser-model-page/1190-fixed-scope-restored-two-chips.json) |

空范围回合主任务耗时 7.072s，多库回合 29.554s，来自各自 job.started_at/finished_at；不作为首段延迟或 P95。空范围有 3 次真实模型调用（记忆关键词、Agent 回复、记忆提取），1453 tokens；多库回合 4 次、4791 tokens，总计 7 次/6244 tokens。记忆维护可能在主回复结束后继续，不把主任务耗时当作全部后台完成时间。

多库问题仅命中标准答案库的手册，模型已明确说明第二库没有对应事实；这证明范围保留，不能称跨库联合答案已通过。格式库的大文档未建立向量，实际 `vector_reindex_required` 导致关键词降级。本轮没有新的 Embedding/ReRank 调用，不计四角色成功；历史四模型调用另有证据。显示修复保留该降级原因，没有自动运行付费重建。

发现并修复三处问题：空范围提示与实际行为矛盾、结构化检索降级显示 `[object Object]`、核心投影丢失维护阶段且缺少结果误标完成。前端定向 9/9、完整 342/342，核心相关 61/61、类型与构建退出 0；见 [前端记录](CHAT-SCOPE-TRACE-DISPLAY.md) 和 [核心投影记录](MAINTENANCE-TRAJECTORY-PROJECTION.md)。重启六表及密钥/模型哈希完整保留；刷新后仍四消息、四任务、36 事件、7 用量记录，无付费重放。

工具限制保留：1134 来源鼠标点击、1161 全部过滤点击没有产生预期页面变化，后续实际键盘聚焦/Enter 验证；1169–1171 恰逢开发 HMR，不能计入第三时间轴通过，后来稳定 1179–1181 才计入。早期 empty receipt 的任务查询取错 JSON 层级，未覆写；empty-confirmed 使用真实 `payload.input.session_id` 核查。

剩余：默认未指定范围、删除后幽灵选择、加载期间快速发送、早停/网络恢复、清空/删除/批量、图片附件、上下文空与错误、模型切换、长历史、子 Agent 与记忆开关仍需分别验收。当前会话保留供正式链路复核。已安装 cancel 版本属于本次显示修复前冻结来源，最终必须重打包并用正式 IPC 复核；Goal 保持执行中。
