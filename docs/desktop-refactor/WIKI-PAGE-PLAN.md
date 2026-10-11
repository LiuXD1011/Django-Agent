# Wiki 页面操作与来源定位计划

日期：2026-10-10。范围由 Goal F 与 root 的具体设计批准；本计划不表示 GUI 验收已通过。不提交，不修改 core、共用 Markdown renderer 或其他工作区改动。

**目标：** 独立 Wiki 页面能真实编辑、删除、打开有权限的来源文档与分块，并通过本页目录定位正文；知识库内嵌 Wiki 保持只读。

**架构：** 使用已有 WikiService 的 PUT/DELETE 与版本冲突检查。Vue 页面复用新建 Markdown 对话框；来源只使用当前知识库内的真实标识与认证 client，文件读取由现有 KnowledgeDetail 完成。所有异步 UI 发布检查知识库、页面与请求代际，避免旧响应覆盖新页面。

**技术：** 已安装 Vue 3、vue-router 4.6.4、TDesign Vue Next、esbuild、Vue SFC compiler、Node test、Playwright。没有依赖变更。

## 已核查的事实

- 私有基线 Wiki.vue 与当前文件相同；旧页面一直没有编辑、删除、来源控件，目录是文本 span。
- 旧 `wiki/views.py` 已支持页面更新与删除；旧 serializer 提供 source_refs、chunk_refs、metadata、version。
- 当前 `packages/core/src/adapters/wiki-routes.ts` 已注册 authenticated PUT/PATCH/DELETE；WikiService 更新检查可选 version，删除后刷新双链。
- 当前 KnowledgeDetail 的引用入口要求 document 与 chunk 同时存在。Wiki 的真实 source_refs 可能只有文档 ID，不能猜分块或伪装为准确引用。
- Markdown renderer 已提供双链、表格、公式、安全转义；本轮不改 renderer。

## 文件范围

| 文件 | 修改责任 |
| --- | --- |
| `frontend/src/views/Wiki.vue` | 独立 reader/drawer 操作、复用表单、真实来源、局部目录、异步范围围栏 |
| `frontend/src/api/index.ts` | 仅新增 updateWikiPage 与 deleteWikiPage 两方法 |
| `frontend/src/views/KnowledgeDetail.vue` | document-only 来源的受控读取与正常分页；保留准确引用路径 |
| `frontend/src/views/Wiki.page-actions.test.mjs` | 实际编译 Vue/Router 的受控 HTTP 行为回归 |
| `frontend/src/api/wiki-page-actions.test.mjs` | 现认证 client 与路径段编码回归 |
| `frontend/src/views/KnowledgeDetail.citation.test.mjs` | 文档来源分页、错误范围、迟到响应、未保存编辑回归 |

## 执行步骤

### 1. 客户端绑定

- [x] 先写 RED：调用 updateWikiPage/deleteWikiPage，断言 PUT/DELETE 与 UTF-8、斜线 slug 的逐段编码。
- [x] 使用已有 client：`updateWikiPage(kbId, slug, data)`、`deleteWikiPage(kbId, slug)`。不新增 host、tenant 或任意 URL 参数。
- [x] 运行新 API 回归到 GREEN，其他 API 契约不变。

### 2. Wiki 页面操作

- [x] 先写 RED：reader/drawer 的实际按钮打开编辑表单、保持固定 slug/version，真实请求成功后刷新；403/409 保存失败保留草稿。
- [x] 编辑复用 title/content 表单；新建、编辑均阻止重复提交。删除使用具名确认对话框，取消不写，成功重取 pages/graph，并清除失效 selectedSlug/drawer。
- [x] embedded 模式不渲染新建/编辑/删除入口，也拒绝程序式写入口。来源与目录导航属于读取行为。
- [x] RED→GREEN 验证旧请求完成时 KB 已变化不会发布到新 KB；切换 KB 会关闭旧编辑与删除目标、清空旧抽屉/搜索/选择。
- [x] API 失败显示安全业务提示，保留输入；不将部分刷新失败表述为未发生写入。

### 3. 来源与目录

- [x] 先写 RED：无有效 source_refs 不产生链接；来源 getKnowledge 必须返回请求文档与当前 KB；跨 KB、403/404 均不导航。
- [x] 文档/分块配对只来自真实 source_ref.chunk_id 或该文档 contributions.chunks；准确来源沿现 `?document=...&chunk=...`。没有可靠配对则使用 document-only 来源，清楚展示普通分页而非伪造片段。
- [x] KnowledgeDetail 文档-only 分支先 getKnowledge 并检查 KB，再按现 page_size=50 读取分块，复用既有 source/dirty-edit/request-generation 围栏。CitationList 缺 chunk 禁用 guard 不变。
- [x] 本页目录绑定实际渲染出的 h2–h4；只在当前 Wiki 正文容器内创建锚点。目录按钮滚动并聚焦实际标题，不修改共用 renderer。
- [x] 实际 DOM 回归目录定位、双链、表格/公式/代码与恶意 HTML/URL 安全渲染。

### 4. 验证与冻结

- [x] 新专项测试真实观察 RED 后运行 GREEN；原 Wiki、KnowledgeDetail 与 citation API 回归组合通过。
- [x] 在 frontend 执行 `npm run test:unit` 与 `npm run build`，并对受影响 SFC/API 执行语义 TypeScript 检查。
- [x] 检查本轮文件差异与 SHA，向 root 发源码冻结通知；未授权不改 QA payload/Windows 数据。
- [ ] Orca 独立 page 固定 `--page`，实际 click/fill/save/搜索/来源跳转后核查 UI 与只读 SQLite。API 仅用于明确标记的 fixture 准备，不能代替 GUI PASS。

## 验收证据边界

现有 Orca 建页两次超时；root 分配的页导航 receipt 成功但 snapshot 为空，DOM eval 最终 runtime_unavailable。本轮至此 GUI PASS=0，未创建 fixture。原记录见 [Orca Wiki 证据](../refactor-evidence/20261010-orca-wiki-parser-baseline.json)。程序回归与真实 GUI 验收分别记录；缺 Neo4j/模型不调用厂商，也不宣称图谱生成成功。

## 已观察的程序回归

- 首轮专项真实 RED：30 项中 16 项失败；追加范围与写入事实 5 项均先失败。实现后新旧相关组合 42/42 通过（35.982 秒）。
- 实际安装的 TDesign Dialog 使用显式 300 ms Transition。两个新增关闭测试原先在两帧后检查可见性过早；加入实际 hidden 状态等待后保留原 false 断言，未修改生产时限或组件关闭行为。
- 程序测试使用实际编译 Vue/Router、真实受控 HTTP、安装的 Dialog 与 Chromium；HTTP fixture 没有宣称真实服务权限已通过，错误响应与范围围栏均独立验证。
- 前端完整 `npm run test:unit`：232/232 通过，44.320 秒（含已冻结的 Markdown 图片专项）；SFC/API 语义 TypeScript 6.0.3：0 diagnostics。生产构建 exit 0，48.81 秒；保留现有超过 500 kB 的 bundle 提示。
- 临时语义检查只在内存生成 SFC virtual TS，与真实 API/client/安装类型共同 strict 检查；脚本已按规则删除，没有加入生产配置。
- GUI 验收仍未执行成功；程序回归不计 Orca PASS。

证据：[首次 RED](../refactor-evidence/20261010-wiki-page-red.tap)、[追加 RED](../refactor-evidence/20261010-wiki-page-red-extra.tap)、[相关 GREEN](../refactor-evidence/20261010-wiki-page-green.tap)、[完整单元测试](../refactor-evidence/20261010-wiki-frontend-full.tap)、[语义检查](../refactor-evidence/20261010-wiki-semantic.log)。

最终程序证据：[结果与源码 SHA](../refactor-evidence/20261010-wiki-page-program-verification.json)、[构建日志](../refactor-evidence/20261010-wiki-frontend-build.log)。GUI 验收步骤保持未勾选。
