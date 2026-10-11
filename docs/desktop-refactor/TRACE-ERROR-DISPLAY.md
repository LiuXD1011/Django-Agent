# 解析轨迹错误显示

## 已授权范围与真实问题

根任务真实 Orca 记录 [672](../refactor-evidence/20261011-browser-model-page/672-root-browser-processing-bad-png-expanded-readonly.json) 中，损坏 PNG 的解析记录已显示“失败”和“文档处理失败”，展开后的轨迹仍显示“文件读取: stage_failed”。本轮只修改实际导入的 [KnowledgeTraceTimeline.vue](../../frontend/src/views/chat/components/KnowledgeTraceTimeline.vue) 及其 [行为测试](../../frontend/src/views/chat/components/KnowledgeTraceTimeline.behavior.test.mjs)，不修改此前解析记录状态修复。

## 设计

在既有 `error_message` 插值处调用一个纯显示函数，精确匹配已经核对的核心文档流水线与模型运行时错误码并显示中文。`stage_failed` 显示“阶段处理失败”；超时、网络、流中断等结果可能未确认的提示保留这一含义。未知人工说明、未知机器码与空值的现有行为保留，不使用正则猜测或通用替换隐藏错误。映射仅查对象自身属性，避免 `constructor`、`__proto__` 等未知文本被对象原型误匹配。

函数不更改原始轨迹数据、`error_code`、阶段状态、错误筛选、历史轨迹分组及当前轨迹选择、轮询或跨文档切换机制。不增加依赖、兼容层或接口。实际 API 的阶段对象已经包含字符串 `error_message`，不需要更改 DTO。

根任务后续真实截图 [680](../refactor-evidence/20261011-browser-model-page/680-root-browser-processing-cancelled-screenshot.png) 显示，取消阶段缺少专用条形样式，15.0 min 的条内白字叠在浅灰背景上看不清。按根任务授权增加取消条的浅灰背景 `#c9cdd4`，仅将它相邻的 `inside` 耗时文字设为既有深色 `#4e5969`；`before`、`after` 和其他状态的条内规则不变。这是局部可逆样式修复，不新增镜像测试，重跑既有相关测试，并用隔离浏览器实际编译的 scoped CSS 检查计算颜色。

## 验证计划

先扩展现有测试：编译真实组件及模板，使用实际 Vue 和隔离的 headless Chromium DOM，仅替换 API 边界。复现已知错误码仍显示英文的 RED，再最小实现。回归同时检查最新轨迹选择、阶段失败样式、原始数据未修改、未知人工说明/机器码原样和 HTML 文本转义。保留并运行已有三项加载、轮询、迟到响应测试，随后运行解析记录及父视图相关测试。

本轮不重复此前已通过的完整前端 331 项及构建；根任务将在所有源码最终冻结后统一执行完整前端测试、构建和真实 Orca 复测。唯一证据文件为 [本轮证据](../refactor-evidence/20261011-review-trace-error-display-evidence.json)，记录真实命令、RED/GREEN、相关验证和最终 SHA。本轮 headless DOM 回归不代表真实 Orca 验收，也不解决同步本地发布仍阻塞核心的性能缺口。

## 实施与结果

错误文本处理只增加 23 个实际已核对错误码的显示映射及纯函数，并替换原始错误文本的一处模板插值。未知文本使用自身属性检查后原样返回，Vue 仍以文本插值渲染，不使用 HTML 渲染。取消样式补充仅增加浅灰条和相邻条内深色耗时两条规则。未修改阶段与任务状态、加载及轮询逻辑、错误筛选或轨迹历史选择。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 真实组件 DOM RED | 4 PASS / 1 FAIL；已知码中文断言失败 | [RED](../refactor-evidence/20261011-review-trace-error-display-red.tap) |
| 定向 GREEN | 5 / 5 PASS | [GREEN](../refactor-evidence/20261011-review-trace-error-display-green.tap) |
| 错误提示相关检查 | 34 / 34 PASS，0 FAIL / cancelled / skipped，TAP 总计 12298.899116 ms | [相关结果](../refactor-evidence/20261011-review-trace-error-display-related-green.tap) |
| 取消样式后最终相关检查 | 34 / 34 PASS，0 FAIL / cancelled / skipped，TAP 总计 12347.149949 ms | [最终相关结果](../refactor-evidence/20261011-review-trace-error-display-cancelled-style-green.tap) |
| 隔离真实模板和 scoped CSS | 取消 inside/before/after 灰条深字；done inside 绿条白字；原始输入未变 | [计算样式](../refactor-evidence/20261011-review-trace-error-display-cancelled-style-dom.json) |

回归覆盖已知错误显示、未知人工文本与未知代码、对象原型同名文本、HTML 文本转义、最新解析轨迹与原始数据、失败阶段样式，以及原有跨文档切换、迟到响应、活动任务轮询和完成后停止。以上 TAP 耗时是隔离测试进程的运行时间，不是产品功能延迟或真实性能结论。

计算样式检查使用临时隔离脚本编译真实组件、模板和 scoped CSS，在 headless Chromium 读取 `getComputedStyle`，未增加永久测试。取消阶段的背景为 `rgb(201, 205, 212)`，inside 耗时为 `rgb(78, 89, 105)`；before/after 仍为既有深色，done inside 仍为绿色背景和白字。临时脚本使用后删除。

最终源码冻结 SHA-256：组件 `6dd6ef04a11246c66f4b869684ae5a10c3a79f6d448f2d20d6b7d1f5afdf6f3f`；现有行为测试 `e6a3b325df28ee552dba77bb9a37709480079933ac919ed97c35abcb34fb2539`。完整前端测试、构建和真实 Orca 显示验收由根任务记录。

根任务随后已完成最终完整前端333/333、0失败/取消/跳过及构建退出0，源码前后一致，见[最终检查](../refactor-evidence/20261011-root-current-frontend-checks/checks.json)。真实Orca已在取消列表检查JSON灰条深字，在失败列表实际展开坏PNG检查中文“阶段处理失败”、failed1/LIVE0，并检查两张稳定截图。模型记录SHA不变、usage98、0活动任务与0新调用，见[681–690实际显示验收](../refactor-evidence/20261011-root-trace-error-display-real.json)。此通过限定页面显示，不代表大文档响应或最终安装版已通过。
