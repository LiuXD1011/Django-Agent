# 文档工作流状态与自动刷新修复计划

**Goal:** 文档已有发布结果时仍正确展示本次处理、取消、失败和中断，任务完成后自动更新列表、统计及打开的分块；空来源不误导用户反复重试摘要。

**Architecture:** `KnowledgeDetail.vue` 统一读取当前工作流状态，保持已发布正文和摘要可见。轮询只允许一个定时刷新在途；手动刷新和列表请求使用序号及知识库加载代次防止陈旧响应覆盖新数据。分块刷新同时识别工作流结束与来源代次变化，保留未保存编辑和精确引用。

**Tech Stack:** Vue 3.5 的现有 ref/computed/watch、实际 SFC 编译组件、Node 测试、现有 Vite 构建；不新增依赖。

## 已确认根因

- `summaryText` 优先读取旧 description 和 summary_status，取消/失败状态靠后，导致实际取消显示“摘要模型未配置”，或旧摘要隐藏本次失败。空来源也显示“可重解析重试”。
- docs watcher 只比较 `parse_status==='processing'`。为保留旧发布内容，重解析可以一直 `completed→completed`，因此打开的 Chunk 不更新，trace 不轮询。
- 页面已有 `processing_count` 判定，不是单纯只看 parse_status。实际缺陷是每 3000ms 无条件刷新，而 API 超时为 30000ms；多个同库响应可交错，较旧的处理中统计和摘要能覆盖完成响应。必须通过可控真实 Vue 组件响应顺序验证，不能仅凭实际页面陈旧推定其全部成因。
- 核心列表 DTO 原本不含 metadata，前端无法获知工作流状态。主任务负责轻量投影：`workflow_status: string`、`processing_warning_codes: string[]`、`source_generation: string`，旧数据默认空字符串/空数组。前端使用顶层投影，详情读取保留 metadata 回退，不为状态增加整篇正文读取或逐文档请求。

## 方案与边界

推荐保留三秒轮询，限制定时刷新在途数量，并以序号拒绝较旧的手动刷新/列表响应。统一拒绝每三秒之前的响应会使慢请求永远无法发布；持续无条件轮询又会扩大并发并允许陈旧覆盖，两者均不采用。

当前工作流取消、失败或中断优先提示，并在提示后保留已有摘要。状态标签、取消按钮和 trace 活跃状态按当前工作流判断；全库历史解析计数的协议不由本补丁改写。`postprocess_source_empty` 显示“未提取到可用于摘要的内容，请检查原文件”，不承诺重试可生成摘要。保留引用来源、未保存编辑、正常上传和既有筛选行为。没有对应 issue 编号。

Goal II.3/II.4 已授权记录设计后继续实现；主任务确认字段与方案。本任务不提交，不编辑核心/worker/根报告，也不操作实际 GUI、数据、API、模型或凭据。

## 执行步骤

- [x] 扩充真实编译 SFC 的行为/轮询回归：取消/失败优先、空来源、completed→completed、来源变化、保留编辑与引用、重叠定时器、较旧回复。
- [x] 运行定向回归观察预期 RED，保存命令、退出码、耗时和源码哈希。
- [x] 实现最小工作流状态读取与提示、分块刷新及轮询/列表请求保护。
- [x] 定向 GREEN 后执行 `frontend/npm run test:unit` 与 `npm run build`，保留完整结果。
- [x] 验证文档链接/差异，删除已消费临时脚本，向主任务提供独立证据和实际 UI 复测边界。

## 验证结果

以下命令均从 `frontend` 执行，独立收据包含退出码、墙钟耗时及受影响前端文件的 SHA-256；夹具修复后的收据额外记录 Wiki 测试文件哈希，原始失败日志保留。

| 检查 | 实际结果 | 墙钟耗时 | 证据 |
| --- | --- | --- | --- |
| `node --test src/views/KnowledgeDetail.behavior.test.mjs src/views/KnowledgeDetail.polling.test.mjs`，修改实现前 | RED：21 项中 9 个预期断言失败，12 通过 | 1399.500 ms | [收据](../refactor-evidence/20261011-document-status-red.json)、[TAP](../refactor-evidence/20261011-document-status-red.tap) |
| 同上，第一轮实现后 | GREEN：21/21 | 1402.640 ms | [收据](../refactor-evidence/20261011-document-status-green.json)、[TAP](../refactor-evidence/20261011-document-status-green.tap) |
| `node --test --test-name-pattern='explicit empty list projections' src/views/KnowledgeDetail.behavior.test.mjs` | RED：1 个预期断言失败，证明空顶层投影不能回退旧详情状态 | 1205.346 ms | [收据](../refactor-evidence/20261011-document-status-projection-reset-red.json)、[TAP](../refactor-evidence/20261011-document-status-projection-reset-red.tap) |
| 定向两文件，最终实现 | GREEN：23/23，0 跳过 | 1367.236 ms | [收据](../refactor-evidence/20261011-document-status-green-final.json)、[TAP](../refactor-evidence/20261011-document-status-green-final.tap) |
| `npm run test:unit`，首次完整运行 | 320 通过 / 1 失败 / 0 跳过；失败为已有 Wiki 长文本测试 fixture 的 UTF-8 分片解码 | 89893.142 ms | [收据](../refactor-evidence/20261011-document-status-unit.json)、[TAP](../refactor-evidence/20261011-document-status-unit.tap) |
| `npm run build` | 退出 0；Vite 3977 模块，已有大 chunk 提示未阻断构建 | 52074.649 ms | [收据](../refactor-evidence/20261011-document-status-build.json)、[日志](../refactor-evidence/20261011-document-status-build.log) |
| `node --test --test-name-pattern='long Markdown Wiki editor' src/views/Wiki.page-actions.test.mjs`，独立复测 | 2/2，通过不等于随机分片缺陷已修复 | 10484.823 ms | [收据](../refactor-evidence/20261011-document-status-wiki-long-input-recheck.json)、[TAP](../refactor-evidence/20261011-document-status-wiki-long-input-recheck.tap) |
| 实际 Wiki fixture decoder，受控字节分片诊断 | 原 decoder 确定性失败 1 项；拼接字节后单次解码对照通过 1 项 | 314.999 ms | [收据](../refactor-evidence/20261011-document-status-wiki-utf8-diagnostic.json)、[TAP](../refactor-evidence/20261011-document-status-wiki-utf8-diagnostic.tap) |
| `node --test --test-name-pattern='Wiki HTTP fixture keeps UTF-8' src/views/Wiki.page-actions.test.mjs`，新增永久回归后、修复前 | RED：5 个预期断言失败，覆盖中文两处分片、emoji 三处分片 | 1822.295 ms | [收据](../refactor-evidence/20261011-document-status-wiki-fixture-red.json)、[TAP](../refactor-evidence/20261011-document-status-wiki-fixture-red.tap) |
| `node --test --test-name-pattern='Wiki HTTP fixture keeps UTF-8\|long Markdown Wiki editor' src/views/Wiki.page-actions.test.mjs`，夹具修复后 | GREEN：7/7，保留全部正文严格相等断言 | 9266.461 ms | [收据](../refactor-evidence/20261011-document-status-wiki-fixture-green.json)、[TAP](../refactor-evidence/20261011-document-status-wiki-fixture-green.tap) |
| `npm run test:unit`，夹具修复后最终完整复测 | GREEN：326/326，0 失败/取消/跳过/待办 | 82278.648 ms | [收据](../refactor-evidence/20261011-document-status-unit-final.json)、[TAP](../refactor-evidence/20261011-document-status-unit-final.tap) |

## 测试边界：Wiki HTTP 验证夹具

完整运行失败的根因在 `Wiki.page-actions.test.mjs:46`：测试服务端将每个请求 Buffer 单独隐式转成字符串再拼接。与应用 UI 的中文输入路径无关；同一请求正文在字节 2896 将“第66行”的“行”分成两片时，实际既有 decoder 稳定得到完全相同的“第66��”。拼接 Buffer 后一次 UTF-8 解码可保留全部输入。这是验证夹具缺陷，未据此认定 Wiki 产品缺陷，原产品与全部内容断言保持不变。

主任务已明确扩展归属至该测试文件的 HTTP 解码及必要分片回归。最小实现：提取夹具原解码函数供服务器和受控 Readable 分片共用，跨中文及 emoji 字节边界的永久回归先得到 5 个预期失败，再在遍历前调用 Node 现有 `req.setEncoding('utf8')`，由 StringDecoder 保留跨片字节，随后 5 个分片回归与原两个长文本 DOM 回归均通过；不修改 Wiki.vue，不放宽正文相等断言，不新增依赖。已核查 `packages/core/node_modules/@types/node/stream.d.ts` 的 `Readable.from`、`setEncoding`、`http.d.ts` 的 IncomingMessage 继承，以及 Node 22.23.2 实际 setEncoding 使用 StringDecoder。夹具修复只改测试，构建对应的产品源码未变化，无需重复构建。

修复前 Wiki 测试 SHA-256 为 `b34544ac8801bbd650ff85a390c9e51d9e7132135d06b5a664df7a48ea73dde4`；最终为 `4a4da3c0cb192725aef714bb347cf08cb509f69bec08499f9331e1437bbfcb08`。完整套件已在新路径复测为 326/326 通过，没有覆盖原失败证据。最终复测期间协调性能任务暂缓 40K CPU 采样，避免影响 DOM 时序；终态后已通知主任务及性能任务恢复。

最终 `KnowledgeDetail.vue` SHA-256 为 `1a937837ca62778da476ca8abc108bf6775df22b91938bada1d7e6edf8bedd02`。顶层空字符串和空数组代表权威状态，不能被旧详情 metadata 覆盖；仅字段缺失时回退详情 metadata。原布局测试中通过字符串搜索断言 startPolling 不包含 refreshAll 已替换为真实组件断言“定时器触发前只有初始一次知识库请求”，保留原行为要求。

真实桌面/Orca 页面复测及最终 Windows 包由主任务执行，组件测试不等同于实际页面验收。桌面列表提示 selector 为 `.document-table tbody tr .doc-title-cell p`，同行状态标签为 `.status-stack`；移动列表提示为 `.document-card-subtitle`。已发布坏图再次失败应显示“本次处理失败：文档处理失败”和“失败”，取消应优先显示“处理已取消”，空 TXT 应提示检查原文件。重解析完成后应自动更新摘要、统计和已打开且没有未保存编辑的分块。

独立收据汇总、最终文件哈希及临时脚本清理记录见[复核记录](../refactor-evidence/20261011-document-status-review.json)。
