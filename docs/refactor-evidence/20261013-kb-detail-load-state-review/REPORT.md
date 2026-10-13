# KB-DETAIL-LOAD-002 独立源码与行为审查

2026-10-13。审查对象限于本次详情加载状态修复，不审查或宣称其他 Goal、Core、Native 打包及 Root 正在进行的真实 Orca 复验完成。

## 两项结论

- **Spec compliance：通过。** 指定的持久加载/不可用/可重试主区域、安全返回、错误安全文案、真实重试、路由复用/同 ID 新加载/卸载保护、错误后停止与成功后恢复处理状态轮询，均与批准的计划及本次需求一致。
- **Code quality：通过。** 未发现本次差异中的阻塞或应修复 finding。改动集中于现有详情组件，复用原读取和轮询路径，无正常功能删除、新兼容层或依赖改动；新增测试实际编译并挂载生产 SFC，断言渲染与事件行为。

上述通过为本次代码与受控行为审查结论，不能替代真实网络、认证、TDesign 布局及 Orca 验收。

## 审查范围与逐项证据

已完整阅读仓库 AGENTS.md、[批准计划](../20261013-kb-detail-load-state-fix/PLAN.md)、[实施报告](../20261013-kb-detail-load-state-fix/REPORT.md)、[最终差异](../20261013-kb-detail-load-state-fix/code-complete.diff)、生产 KnowledgeDetail.vue 与新增 KnowledgeDetail.load-state.test.mjs。生产文件 SHA-256 为 `84ee651d2f62d5407a09ca9531bbfb8bbaa1310aa1bdb804788a933d3cab73bf`，新增测试为 `c456d80965ac9a88af8e6160dd23dfcbd53487baae70bb7eec103fc6df336078`，与指定终态一致。

| 要求或疑点 | 源码位置与审查结果 |
| --- | --- |
| 原缺陷确为已删 ID GET 404 后 main 缺失 | [125 原操作结果](../20261013-root-browser-business/125-stale-recent-result.json)为失败 toast；[127 原资源证据](../20261013-root-browser-business/127-stale-resource-confirm.json)记录最后 GET 404 和 mainText=null。没有将侧栏修复作为详情加载状态修复证据。 |
| 持久状态与安全返回 | KnowledgeDetail.vue:982–998 保留 main、加载 role=status、错误 role=alert；990/1000 指向 `/platform/knowledge-bases`。错误页不依赖短暂 toast。 |
| 401/403/404/410 不泄露服务详情 | KnowledgeDetail.vue:266–267 只分类 status；987 只输出两种固定文案。新增正式测试:120–138 覆盖四种状态；本次补充检查还覆盖文档阶段已读取到 KB 名称后失败，最终错误主区域不显示已有名称或服务消息。 |
| 网络、500、503 真实 retry pending | KnowledgeDetail.vue:245–271 与991 的重试使用原 load；正式测试:140–167 控制 deferred 读取并调用实际渲染按钮。补充检查验证再次重试也失败时仍有持久错误及重试入口，无成功 toast。 |
| 部分 KB 成功后 docs 失败再重试 | 257 提前保存 KB，997–998 在重试 pending 时保留正文与加载标识，符合计划“正文数据仍读取时保留加载提示”；不显示空库结论，实际重发 listKnowledge。补充检查控制第二次文档读取 pending，再拒绝后确认错误页及停止轮询。 |
| A→B、同 ID 新 load 与卸载晚响应 | KnowledgeDetail.vue:248–251 请求代次与路由/卸载判定，249 立即废弃旧 docs；256/261/265/270 保护发布、错误与 finally；282 保护 docs 发布；895–909 清空旧库及统计/标签，971–974 废弃卸载实例。正式测试:190–250、269–292；补充检查覆盖卸载时已在文档读取阶段。 |
| 加载/错误停止轮询，成功 retry 恢复 | KnowledgeDetail.vue:268 显式停止，921–927 将加载和错误纳入 isProcessing，960–963 复用原启动/停止机制。正式测试:252–266 验证失败无 timer、恢复处理中 KB 后存在 timer、卸载清理。 |
| 正常功能保留 | 最终生产差异没有删除文档、Wiki、图谱、解析记录、Chunk、引用或设置实现；正式测试:163 验证正常按钮存在。引用仍走原 openCitationFromRoute 和独立 citationError/citationLoading；其完整真实浏览器行为不在本次补充复现中声称验证。 |

核查了实际 `frontend/src/api/client.ts` 与 `frontend/src/api/index.ts:248/254/274`：读取失败由 client 拒绝为带 status 的对象，组件现有分类能处理该真实形态。核查已安装 TDesign `es/button/type.d.ts` 的 outline variant、onClick，及 Vue runtime-core 的 watch/生命周期类型；未猜测新 API。

## 验证及 finding

**Finding：0。** 没有发现本次修改中的可复现需求违反或需修复质量问题。

审阅了实施者已经归档的原始终态 stdout 与独立 actualexit：正式 GREEN 19/19、frontend unit 408/408、build 成功且退出码 0；构建存在既有大 chunk 提示。本审查未重跑完整 suite 或 build，也未将上述日志称为审查者独立执行结果。

审查者仅对具体补充疑点执行了生产 SFC 受控行为 helper：`node --test frontend/src/views/.kb-detail-load-review-helper.mjs`，**4/4 pass，0 fail，实际退出码 0**。见 [edge.stdout](edge.stdout)、[edge.actualexit](edge.actualexit)与[实际 helper 源码](edge-helper.source.mjs.txt)。helper 复用正式测试的编译/真实 Vue renderer 边界，在外部 IO 上控制异步；未修改生产组件或正式测试。

## 无法验证的边界与清理

没有操作 GUI、启动/停止服务、写入 QA 或外部资料，没有 Git 写操作、提交或暂存，没有触碰锁文件及任务范围外源码。未执行或评判 Root 正在进行的 Orca 复验、Native 后台包与其他 Goal 验证。

实际 helper、构造 helper 和归档清理 helper 的源码及 SHA-256 已归档；按 [temporary-cleanup.json](temporary-cleanup.json) 的明确自有路径核对后删除原临时文件。源文件和日志 SHA 见 [source.sha256](source.sha256)，清理不会删除或覆盖其他工作区改动。
