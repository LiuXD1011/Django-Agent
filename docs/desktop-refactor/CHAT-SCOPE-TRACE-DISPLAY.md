# 聊天范围与轨迹显示修复

2026-10-12。Goal II.3–5 已授权修复；原 Windows 安装升级 receipt 验证完成后开始本轮。修改后的前端源码与该已安装包存在差异，组件测试不等于安装包或 Orca 验收通过。

## 根因与最小设计

- [ChatInput.vue](../../frontend/src/views/chat/components/ChatInput.vue) 初始未选、`applyState({})` 和显式取消全部选择，最终均提交 `knowledge_base_ids: []`。核心区分“字段未提供”与“显式空数组”：前者可能取保存范围或旧会话/租户范围，后者不回退。当前输入框一直提交字段，故零已选提示应为“未选择知识库：本轮不检索知识库资料”。只改提示，不改发送、记忆、网络搜索或 MCP 行为。
- [TrajectoryPanel.vue](../../frontend/src/views/chat/components/TrajectoryPanel.vue) 将真实 `{ stage, reason }[]` 声明为字符串数组并 `join`，造成 `[object Object]`。逐项渲染阶段与原因；已知阶段提供中文名称，`vector_reindex_required` 说明需要重建向量索引并保留原始代码，未知字段值和历史字符串继续可读。此条件可能来自验收库中有意未生成向量的大文档，不触发重建或付费请求，不据此认定召回逻辑有错。
- 维护生产者发送 `stage` 与 `status` 或 `state`，记忆提取还发送 `graph_state` 和 `warnings`。核心 [journal.ts](../../packages/core/src/jobs/journal.ts) 原只投影 `step/success`，阶段名被丢弃，缺失 `success` 也被默认为成功。根代理负责保留真实字段的最小核心投影与回归，本任务不编辑核心。前端按 `status`、`state`、显式历史 `success: true/false` 顺序显示，不将警告或缺失结果写成完成；无明确结果显示“未明确结果”。维护名称使用真实 `stage` 或历史 `step`，缺失时明确“阶段未记录”。保留错误、图谱状态以及警告的 `code/message`，未知值显示原值。维护事件也可能发生在检索前，标题改为中性的“维护”。

## 验证计划

使用真实 Vue SFC 编译、真实 Vue/图标依赖与隔离 Chromium DOM，API 仅在测试边界提供与实际契约一致的轨迹载荷，不访问验收数据或模型。

1. 输入框真实点击知识库选择、取消最后一项、发送并核对 `[]`，再选择发送核对实际 ID；一个代表性空态足以验证文案，不穷举同义空态。
2. 轨迹真实 API 载荷显示结构化检索降级、未知/历史字符串以及 escaped HTML。
3. 维护载荷覆盖真实 `stage/status/state/graph_state/warnings`、显式历史布尔结果和未知状态，不虚构完成，不隐藏错误。
4. 先观察旧组件的真实断言 RED，再实施最小修改；执行 `npm run test:unit` 的定向命令及用户已要求的完整前端套件。旧 [kb-select.spec.ts](../../frontend/tests/kb-select.spec.ts) 的错误文本期望同步更新，但不声称已执行旧 Django E2E。

独立原始日志、命令耗时、源码 SHA 和清理记录保存到 `docs/refactor-evidence/20261012-chat-scope-trace-display/`。根代理负责真实 Orca 页面复测和后续交付，不预填成功。

## 执行记录

- [首次夹具失败](../refactor-evidence/20261012-chat-scope-trace-display/red.tap)：实际 TDesign 包导入 CSS，内存 esbuild 构建缺少输出路径，0/4，9009.235 ms。它不是产品 RED。核对已安装 esbuild 类型后，仅配置内存 `outdir`，仍为 `write: false`，不落地生成产物。
- [有效产品 RED](../refactor-evidence/20261012-chat-scope-trace-display/red-components.tap)：0/4，9715.732 ms；原组件真实 DOM 分别暴露错误范围文案、`[object Object]`、缺失维护阶段、显式失败被历史布尔成功掩盖。
- [首次修改后运行](../refactor-evidence/20261012-chat-scope-trace-display/green-components.tap)：8/9，40196.310 ms。轨迹三项与既有 Chat 五项通过，新输入框测试假设发送会关选择弹层，后续重新打开实为关闭而超时。真实代码规定点击工具栏按钮不关弹层；夹具改用真实点击 textarea 关闭弹层，再发送和重选，不改变产品行为或内容断言。
- [定向 GREEN](../refactor-evidence/20261012-chat-scope-trace-display/green-components-corrected.tap)：`npm run test:unit -- views/chat/components/ChatScopeTrace.behavior.test.mjs views/Chat.behavior.test.mjs`，9/9，退出 0，9316.166 ms。新四项位于 [ChatScopeTrace.behavior.test.mjs](../../frontend/src/views/chat/components/ChatScopeTrace.behavior.test.mjs)，并核对载荷未被显示逻辑修改、无 DOM 脚本执行或 `pageerror`。
- [完整前端 GREEN](../refactor-evidence/20261012-chat-scope-trace-display/full-frontend.tap)：在 `frontend` 运行 `npm run test:unit`，342/342，退出 0，93203.489 ms；无失败、取消、跳过或 Vue/构建错误诊断。总数和原始日志摘录见 [full-summary.json](../refactor-evidence/20261012-chat-scope-trace-display/full-summary.json)。

这里只更新旧 E2E 中对应提示的测试名称和期望，没有执行该旧 E2E；没有访问 live 数据、模型或可见 GUI，没有改核心/桌面/依赖/配置，构建与实际 Orca 复测由根代理执行。
