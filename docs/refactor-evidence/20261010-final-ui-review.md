# 2026-10-10 前端集成独立只读复核

## 范围与基线

复核 Wiki.vue 的 reader/drawer 编辑、删除、目录与来源，KnowledgeDetail.vue 的 document-only 来源分支及必要引用/路由状态，api/index.ts 的 Wiki 两个写入绑定，markdown-lite.mjs 的图片与数学属性处理，CitationList.vue 的有限分数显示。

完整阅读当前受影响组件/实现；使用 `/home/liuxuedeng/.local/share/marlin-refactor/20261010-baseline/source/` 的对应文件执行 `diff -u`，没有将 HEAD 差异冒充本轮差异。当前初始文件与 [Wiki 程序验证冻结记录](20261010-wiki-page-program-verification.json) 及 [图片解析验证记录](../evidence/20261010-markdown-image-parser-worker.json) 的源 SHA 相符。KnowledgeDetail 的历史上传/摘要等额外差异不作为本轮新实现归属。

已阅读 AGENTS.md、SPEC.md、PLAN.md、requesting-code-review 的 SKILL.md/评审模板；核对实际安装 Vue compiler、VNodeRef、Vue Router push/replace、TDesign Select search/loading 与 Dialog 类型及必要实现。仅新增本报告；未编辑生产源码、既有测试、index、HEAD、分支或其他代理文件。

## 已复现的问题

### 1. 已修复 Minor/P3：取消来源读取后加载状态残留

- 原位置：`frontend/src/views/KnowledgeDetail.vue:495-527`；当前修复点为 `openCitationFromRoute`、`openChunks`、KB 参数重置。
- 触发：document-only 来源的真实编译 Vue/router 正在等受控 deferred fetch 响应，随后清空 document 查询、切到无来源的新 KB，或改成无效来源标识。
- 原因：新读取递增 `citationReadGeneration` 后提前返回，没有清除 `citationLoading`；旧读取 finally 因 generation 不一致也不清除。全部请求结束后仍显示“正在读取引用来源…”。旧来源内容被正确隔离；问题影响加载提示准确性，未观察到权限越界或内容串库。
- 最小修复：开始新的读取/手动打开文档/重置 KB 时明确清除旧来源的 loading，保留响应 generation fence。根代理实施源码及正式回归；本评审不修改这些文件。

原独立复现输出（三条均 0 pageerror、0 displayedChunks、0 pendingRequests）：

```json
{"scenario":"clear-query","query":{},"kb":"kb-a","loadingStatus":["正在读取引用来源…"]}
{"scenario":"switch-kb-no-source","query":{},"kb":"kb-b","loadingStatus":["正在读取引用来源…"]}
{"scenario":"replace-invalid-source","query":{"document":"invalid:doc"},"kb":"kb-a","loadingStatus":["正在读取引用来源…"]}
```

相同独立脚本在修复后重跑 3/3：三条 `loadingStatus=[]`，0 displayedChunks、0 pageerror。KnowledgeDetail 修复后源 SHA：`a0c6e2da04b3fa3062fe6c6b6ba8c7fb6f63a0ef1f7ae16e4b6364b5196fa4cc`。

### 2. 已修复 Minor/P3：清空正在读取的 Wiki 搜索后加载状态残留

- 位置：`frontend/src/views/Wiki.vue:289-291`。
- 触发：真实安装的 TDesign Select 已发出 Wiki 搜索且响应 pending 时，清空输入，等空查询的真实 search 事件发生后再释放旧响应。
- 原因：空查询同样递增 `searchRequest` 后提前返回，却未清除 `searchLoading`；旧 finally 被 request fence 阻止清除。此 fence 正确阻止旧搜索结果覆盖图谱选项，但遗留的 loading 使弹层始终显示“加载中”。
- 最小修复：空查询分支增加 `searchLoading.value = false`，保留 request/scope fence。

独立受控 HTTP、实际 SFC/Vue/router/installed Select 输出：

```json
{"scenario":"installed-Select-clear-pending-Wiki-search","pendingRequests":0,"input":"","loadingElements":1,"selectLoadingProp":true,"loadingText":[],"body":["加载中Wiki AlphaWiki Beta"],"errors":[]}
```

根代理在空查询分支增加 loading 复位；相同独立脚本重跑通过：

```json
{"scenario":"installed-Select-clear-pending-Wiki-search","pendingRequests":0,"input":"","loadingElements":0,"selectLoadingProp":false,"loadingText":[],"body":["Wiki AlphaWiki Beta"],"errors":[]}
```

当前修复点为 `frontend/src/views/Wiki.vue:290`。迟到响应不覆盖本地图谱选项，实际 installed Select 的 spinner 已消失。

### 3. 已修复 Minor/P3：清空正在读取的 Wiki 图谱类型后加载状态残留

- 原位置：`frontend/src/views/Wiki.vue:404-408` 的无类型分支。
- 触发：实际安装的节点类型 Select 选“概念”，过滤图谱 GET pending 时再点 legend“概念”取消唯一类型。
- 原因：`++graphRequest` 正确阻止旧响应重新展示取消的节点，随后清空图谱并提前返回，却没有清 `loading`；旧请求 finally 被 request fence 阻止清除，空图持续显示“加载图谱中...”。
- 最小修复：无类型分支明确 `loading.value = false`，保留 request fence。

独立实际 Select/legend 点击、受控 HTTP 与实际编译组件输出：

```json
{"scenario":"clear-types-pending-Wiki-graph","pendingRequests":0,"emptyState":[" 加载图谱中..."],"legendClass":"disabled","nodes":0,"errors":[]}
```

根代理在空类型分支增加 loading 复位；相同独立脚本重跑通过：

```json
{"scenario":"clear-types-pending-Wiki-graph","pendingRequests":0,"emptyState":["暂无图谱关系创建 Wiki 页面并建立链接后会显示关系图。"],"legendClass":"disabled","nodes":0,"errors":[]}
```

当前修复点为 `frontend/src/views/Wiki.vue:407`。迟到响应没有复活已取消的节点；页面显示空图状态。两项 Wiki 独立复测读取的源 SHA 为 `4b03188dd9f6ed4286c1dcd1fecffa79bf3fc33d469343d31b1d1338859ef743`。此后停止新增探查，仅完成以上复测与资源清理。

## 独立正向核查

### 新 SQLite、真实 Core DTO 与前端组合：5/5

新建独立 CoreApplication 数据根、受控 owner/outsider，使用真实 Core 注册业务路由及 SQLite，由仅绑定 loopback 的 HTTP fixture 转发到 `CoreApplication.dispatch`。浏览器读取真实 Wiki、Knowledge、Chunk DTO；私有 fixture binding 留在测试进程中，没有传入浏览器或写入报告。

1. Wiki source_refs 提供文档 A，却只有属于文档 B 的全局 chunk_refs：前端忽略不可靠全局配对，导航仅带 `document=A`，按 `page=1&page_size=50` 读取 A；没有请求任何猜测的 exact chunk。
2. `metadata.contributions[A].chunks[0]` 指定 `1152921504606846976`：真实 Core 返回及 router query 保持该 60 位 ID 的原始字符串，准确展示对应 chunk；没有按 chunk_index 9876 猜分页。
3. Unicode slug `concept/审查 空间😀` 编辑后刷新 GET 返回 503：真实 SQLite 内容已变为 `# Confirmed content`、version=2、slug 未变；前端显示“页面已保存，刷新失败”，关闭编辑框。
4. 删除后刷新 GET 返回 503：真实 SQLite deleted_at 已写入；reader 已清空，并显示“页面已删除，刷新失败”。
5. 外 tenant 读取来源文档以及用文档 B 路径读取 A 的 exact chunk，真实 Core 均返回 404。

5 项全部通过，0 pageerror，0 model_usage。这里只使用新 fixtures，没有真实用户、厂商或 GUI 调用。HTTP fixture 保留 Core API envelope/DTO，前端 API 替身保留该 envelope，与当前 client 的 `response.data` 拦截行为一致；它不是完整 cookie/CSRF HTTP adapter 验收。

### Markdown 图片/属性/数学：16/16

独立 headless Chromium 运行当前 renderer，所有图片请求由受控 handler 接收；核查实际 DOM 的节点与属性。覆盖平衡括号 HTTP URL、中文/空格/查询参数路径、百分号文件名、alt/src 中引号与伪事件属性、图片属性数学加邻近正文数学、占位符形状文本、data/javascript/blob/file、百分号/实体编码双斜杠、编码反斜杠、原始 C0、编码 CR、行内及 fenced code。

安全图片仅有固定 `src/alt/style/loading/decoding/referrerpolicy` 六个属性；没有注入事件属性或 script/iframe/object/embed。图片属性中的数学保持文字，邻近正文公式正常生成 KaTeX；禁止 URL 不生成 img。16 项全部通过，0 pageerror。此独立检查验证 DOM/属性，不扩充为真实远端图片加载验收。

### CitationList 有限分数：12/12

实际编译组件核查 `0`、`0.82`、字符串 `0.75`、`-1` 显示为有限两位小数；null、undefined、空串、空白、非数字串、NaN、正负 Infinity 均不显示相关度。12 种输入全部通过，0 pageerror。

## 源哈希

| 文件 | 本评审读取的 SHA-256 |
| --- | --- |
| Wiki.vue（搜索问题复现时） | e3a94281239a06cc96ee22ac01916b54af2b6e4e47a853ced91bbe8c5268e48c |
| Wiki.vue（两项加载修复复测） | 4b03188dd9f6ed4286c1dcd1fecffa79bf3fc33d469343d31b1d1338859ef743 |
| KnowledgeDetail.vue（初始） | 559132854d07676305f45d12d04b230030cfe647e4027ba73c09a929ef80218a |
| KnowledgeDetail.vue（来源加载修复复测） | a0c6e2da04b3fa3062fe6c6b6ba8c7fb6f63a0ef1f7ae16e4b6364b5196fa4cc |
| api/index.ts | 47af6ce12b39b10afe8a1b4ad0800c7ba7fffbc89ebd893f8c6cfda2e2382096 |
| markdown-lite.mjs | 78014db046a8541c39105f40535195931f69be604b60367344fa4f00dfd777e9 |
| CitationList.vue | b51789e77da5f6172f52a8e4d91413628c5b0211e33428c471ad2c3588877e21 |

浏览器版本：149.0.7827.55。独立测试只写 `/tmp/marlin-final-ui-review-*` 及新 `/tmp/marlin-final-ui-core-*`，本人临时脚本、日志、服务器、浏览器与数据根已全部清除；持久证据为本报告中的实际输出与哈希。

## 结论与边界

确认的三处 Minor/P3 加载状态问题均已由根代理修复，并通过本人原独立脚本复测；本范围内无未解决的已证实问题。没有确认 Critical/Important 问题，也没有观察到实际 Core 来源合法 ID 被本轮来源按钮错误拒绝、跨 tenant 内容读取、错文档定位、保存事实误报、属性执行或旧 KB 内容覆盖。

未重复主代理完整前端/核心套件、semantic 检查或 build；本报告只声明上述独立检查结果。不把 headless fixtures 等同于 Windows/Orca/nativewindow/安装程序的人工验收，不声明 Goal、GUI、安装或发布完成。未接触当前 Windows QA 数据、真实设备、模型厂商、真实用户/Key，未提交、push、打 tag 或发布。
