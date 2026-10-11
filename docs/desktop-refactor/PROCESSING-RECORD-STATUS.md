# 解析记录统一当前工作流状态

2026-10-11，Goal II.3/4/5 的最小前端修复。真实证据：[607-root-corrupt-attempt-stage-history.json](../refactor-evidence/20261011-browser-model-page/607-root-corrupt-attempt-stage-history.json)。已发布过的损坏 PNG 在新任务失败后仍显示“已完成”；取消重解析的文档也沿用旧解析状态。

已完整阅读 `KnowledgeDetail.vue`、实际子组件 `KnowledgeProcessingRecords.vue`、七个 KnowledgeDetail 测试、轨迹组件及其测试、当前 DTO/筛选语义和已安装 Vue/TDesign 类型。基线 SHA：父页 `1a937837ca62778da476ca8abc108bf6775df22b91938bada1d7e6edf8bedd02`，子组件 `73f2bc888b9ca02ac4f8a1fc4ab5505d1ed2617d6f5c2c92443b711638239570`。

## 设计

子组件的 filter、badge 文本/样式和 timeline.active 均使用父页已有 `documentStatus`/`documentStatusLabel`，通过必需的函数 prop 复用，不改写 DTO 或原始 parse_status。父页已有的顶层 workflow 投影优先、显式空投影清除旧 metadata 与历史解析 fallback 语义保持一致。失败筛选同时包含 interrupted，但徽标仍显示“已中断”，使用失败色彩。将父页已有三条中文错误映射提取为 `documentErrorMessage`，继续用于原摘要与解析记录错误，未知人工错误文本原样保留；不改 timeline 文件或核心代码。

记录列表继续来自同一个有界 collection payload，过滤不增加网络请求。展开完成/失败/取消记录仍读取真实轨迹；当前 processing 记录开启现有轨迹轮询，终态关闭轮询并读取最终结果，历史 root/stages 不删除。切换知识库时与 docs 一起清空 processingRecords，旧请求仍受已有 generation/KB 检查约束，避免新库加载中短暂展示旧库记录。

## 验证

先运行真实编译父/子组件的离线 DOM 与加载回归保存 RED，再做最小修复。覆盖 workflow failed/cancelled/processing/interrupted 优先于保留 parse completed；失败筛选归类、徽标文本/class、active→terminal 轨迹加载、保留旧摘要/解析数据与历次 root、晚到 list 与切换 KB 清空记录、历史无 workflow fallback 与显式空投影。运行相关前端测试、Goal 授权的完整 `npm run test:unit` 与 `npm run build`，最后冻结源码 SHA、检查差异和文档链接。

不操作 live 页面/GUI、数据库或模型。离线浏览器 fixture 仅用于实际 Vue 编译/DOM 和隔离协议行为。主任务负责 Orca 真实重测。唯一汇总：[20261011-review-processing-record-status-evidence.json](../refactor-evidence/20261011-review-processing-record-status-evidence.json)。

## 实际验证结果

- [状态与加载 RED](../refactor-evidence/20261011-review-processing-record-status-red.tap)：4/4 实际失败、0 取消，覆盖错误徽标、失败筛选、当前任务轨迹轮询、跨库旧记录残留；[错误文案 RED](../refactor-evidence/20261011-review-processing-record-errors-red.tap)：1/1 实际失败，原代码直接显示英文错误码。
- [相关 GREEN](../refactor-evidence/20261011-review-processing-record-status-related-green.tap)：32/32 通过，0 失败/取消/跳过；TAP 总命令耗时 11569.361332 ms。5 项新增测试真实编译父页/子组件/轨迹组件，使用隔离 Chromium DOM；API 与无关控件为 fixture。
- [完整前端 GREEN](../refactor-evidence/20261011-review-processing-record-status-full-green.tap)：`npm run test:unit` 331/331 通过，0 失败/取消/跳过；TAP 总命令耗时 90808.207551 ms。
- [生产构建](../refactor-evidence/20261011-review-processing-record-status-build.txt)：`npm run build` 退出 0，Vite 报告 40.13 s。记录了大于 500 kB 的包体提示；本轮未改构建配置或依赖。
- 最终源码 SHA：父页 `2a9083bc37d6bd69475872d42bea2a2ea41eb8918f4b128fce01ca7fd7b94805`，子组件 `5d4f4edc7c941f6a20d14524afbcc5737419037c8bff961d91ec18f20051ba36`。相关、完整单测和构建期间产品源码一致；`KnowledgeTraceTimeline.vue` 保持 `f2b7d45341304df4212e12bb0677c5040320d8a0ac2e613364b96c96578ada69`，未编辑。

实现：[KnowledgeDetail.vue](../../frontend/src/views/KnowledgeDetail.vue)、[KnowledgeProcessingRecords.vue](../../frontend/src/views/knowledge/components/KnowledgeProcessingRecords.vue)；回归：[KnowledgeDetail.processing-records.test.mjs](../../frontend/src/views/KnowledgeDetail.processing-records.test.mjs)。完整命令、最终 SHA、差异及链接检查见唯一汇总。

父页进入本任务前已包含主任务的文档列表/轮询修复；本轮只添加复用的错误映射、记录函数 props 和跨库记录清空，不认领其他既有变更。本轮未操作 Orca/live GUI、数据库、模型、core、worker、desktop 或主验收报告；真实页面再次点击与任务耗时由主任务确认。轨迹中的 `stage_failed` 文案保持原行为，未扩大到该文件。
