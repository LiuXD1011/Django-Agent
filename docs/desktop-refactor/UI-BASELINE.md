# 前端功能与点击验收基线

基线日期：2026-10-10。对象是当前工作区的实际代码，包含尚未提交的账号、移动端、PWA、配置管理等修改；没有以 HEAD 代替工作区。此文档用于 Electron + TypeScript 业务核心 + Vue 3 + SQLite 重构的功能对照，不授权删除已有功能。

本次完成静态代码审计，未启动应用或执行以下 GUI 点击场景。下面的“预期”是现有实现的行为契约；执行结果应由 TEST-MATRIX 另行记录，不能把本清单标为已通过。API 响应形状来自前端实际读取字段，并不取代服务端模型、权限及迁移审计。

## 1. 阅读范围与路由

完整分段阅读了 8 个顶层视图、5 个设置组件、11 个聊天组件、知识解析记录组件、ChunkingSettings、PwaStatus，以及 router、api/index、client、auth transport、endpoint、auth/chat store、device store、Langfuse service 和 PWA client/worker。API 对象目前有 105 个导出方法，另有 streamChat、continueStream 和分块配置辅助函数。

主要证据：[路由](../../frontend/src/router/index.ts)、[API](../../frontend/src/api/index.ts)、[认证传输](../../frontend/src/api/auth-transport.mjs)、[端点约束](../../frontend/src/api/endpoint.mjs)。

| 实际地址 | 实际视图/用途 | 入口与状态 |
| --- | --- | --- |
| `/` | 重定向 | `/platform/knowledge-bases` |
| `/login` | Login | 唯一 public 路由；登录、注册、显式自动初始化 |
| `/platform` | Platform 布局 | 空子路径重定向到知识库；子页共享桌面侧栏、移动导航 |
| `/platform/knowledge-bases` | KnowledgeBases | 知识库清单与新建 |
| `/platform/knowledge-bases/:kbId` | KnowledgeDetail | `tab=documents/wiki/graph/processing`；`tab=settings` 打开设置弹窗；`collect=1` 打开采集弹窗 |
| `/platform/knowledge-bases/:kbId/wiki` | Wiki | 独立页，默认 graph；`tab=pages` 为阅读页 |
| `/platform/chat/:chatId` | Chat | 已保存会话、续流、历史、轨迹 |
| `/platform/creatChat` | Chat | 新会话草稿；保留现有 `creatChat` 拼写及深链可达性 |
| `/platform/knowledge-bases/:kbId/creatChat` | Chat | 从知识库创建草稿，初始选中该库 |
| `/platform/settings` | Settings | `section=general/user/neo4j/langfuse/models/vector/websearch/mcp/system` |
| `/platform/settings/devices` | DeviceSessions | 当前/其他登录设备、撤销 |
| `/platform/evaluation` | Evaluation | 从常规设置“评测工作台 → 打开”进入，也支持直达 |

除 public 外的每次导航等待 `auth.restore()`，失败转 `/login`。恢复以 capabilities + me 为准，不自动初始化。当前使用 `createWebHistory()`；桌面自定义协议/静态资源加载必须继续支持深链、刷新、前进后退和懒加载资源。

## 2. 逐页按钮与业务行为

### 登录与共用壳

证据：[Login](../../frontend/src/views/Login.vue)、[Platform](../../frontend/src/views/Platform.vue)、[auth store](../../frontend/src/stores/auth.ts)。

- 登录和注册使用邮箱/密码；注册增加确认密码，前端不一致时不提交。密码框 Enter 可提交；loading 防重复。
- “自动初始化”只由点击发起。返回临时凭据时只放组件内存，用户点击“已保存登录信息，进入工作台”后释放并导航；缺少临时密码则提示并留在页内。busy、disabled、already completed 各有提示。不得写临时密码到日志、URL、storage 或分析事件。
- 桌面主导航只有对话、知识库。“对话”先查询最近 1 个会话，有则打开，空或查询失败进入草稿；“新对话”在聊天侧栏，语义不同。
- 最近访问按当前区域加载最多 5 个知识库/会话，评测区域隐藏最近项。账户头像进入 user；展开菜单提供 general、user 和退出。
- 退出先使本地认证失效并清理 Langfuse 会话，再撤销服务端登录；服务端失败仍到 login，显示“服务器撤销尚未确认”。
- 移动导航是知识库、问答、收集、我的。收集先选知识库，载入失败可重试、空清单可去创建；选中后通过 `collect=1` 深链打开确认流程。

### 知识库清单

证据：[KnowledgeBases](../../frontend/src/views/KnowledgeBases.vue)、[分块表单](../../frontend/src/components/ChunkingSettings.vue)。

- 清单请求 page=1/page_size=100；关键词 Enter、类型选择、刷新触发请求。范围“本空间”发 creator=mine；“收藏”在已加载项上按 is_pinned 筛；“最近”按 updated_at 的近 30 天筛。
- 卡片显示名称、描述、混合检索/Wiki/图谱能力、条目/块/处理数和日期；卡片点击详情。置顶/取消、复制、删除都刷新清单，操作区阻止卡片导航；删除需要确认。
- 新建弹窗含名称、描述、混合检索、Wiki、图谱与分块配置；名称不能为空，至少开一种索引，分块参数通过共享校验。提交 type=document，graph_enabled 同步 extract_config.enabled；图谱模板、wiki_config 也随 payload 保存。
- 分块策略 auto/heading/layout/record/recursive/semantic；父子块可开关，semantic 展示实验标记、窗口及断点百分位。默认 512/80、父 2048、子 384/64、token_limit=0、semantic_window=3、percentile=90。长度、重叠不超过一半、父不小于子等规则不可只依赖 input 属性。

### 知识库详情与解析管理

证据：[KnowledgeDetail](../../frontend/src/views/KnowledgeDetail.vue)、[解析记录](../../frontend/src/views/knowledge/components/KnowledgeProcessingRecords.vue)、[解析阶段时间线](../../frontend/src/views/chat/components/KnowledgeTraceTimeline.vue)。

- 返回知识库、发起对话（立即建会话）、知识库设置、上传文件。文档/Wiki/图谱/解析记录四标签；Wiki、图谱按库能力禁用，关闭能力后当前相应标签回文档。内嵌 Wiki 页面/图谱复用 Wiki 组件。
- 文档按 keyword/tag_id/parse_status/file_type 查询前 100 个；标签侧栏及状态侧栏切换、清空筛选；status_counts/tag_counts 是后端返回的统计，不用当前筛选条目重新计算。切换列表会剔除不可见的 selectedIds。
- 当前列表全选、批量删除确认、移动到目标库；移动提交源库 + 文档 ID + 目标库，目标列表由 move-targets 决定。单文档 Chunk、重解析、取消（非 completed 显示）、删除确认。重解析带当前库默认 process_config。
- 标签“管理”实际仅查看现有标签、新建名称和默认颜色；没有现有标签编辑/删除按钮。
- 文件选择只入待上传列表，按文件名/大小/lastModified 去重；可追加、移除、选择标签、覆盖分块、选择本次图谱抽取。确认“开始解析”后才发送，最多 3 个并行上传；服务端 deduplicated 单列，失败项留队列可重试，成功项移出。HEIC/HEIF 和音视频扩展名有明确前端拒绝提示；当前不是音视频知识库。
- 上传成功确认接收后，后台解析继续；列表 pending/processing/finalizing 或库 processing_count 非零时每 3 秒刷新库/文档，结束停轮询。离开组件也清理轮询。
- Chunk 抽屉每页 50 个，类型筛选 text/image_ocr/image_caption，全部包含 parent_text/image_container；父块和图片容器只读，其他块可编辑 content、启停、保存、删除。脏页禁止翻页/筛选，保存移除 dirty ID；删空末页退上一页。
- 图片 blob 预览按 image_info.image_id 获取并释放 object URL；展示 context_parent_id/media_parent_id/anchor_chunk_id。图片解析失败比例及重解析提示必须保留，图片获取失败不阻断文本编辑。
- Chunk 抽屉和解析记录展开行显示 stages：docreader/chunking/multimodal/embedding/graph/postprocess/wiki。历次 root 分组，优先正在运行、否则最后一次；活动时每 2 秒轮询，不混画不同解析尝试。
- 快速设置保留名称、描述、索引与分块配置，回显 needs_reindex/last_effective_strategy；保存不隐式重解析。直接换 kbId 会清空选择、过滤和抽屉、释放图片并重新载入，防止操作旧库。

### Wiki 阅读与关系图

证据：[Wiki](../../frontend/src/views/Wiki.vue)、[Markdown 与 Wiki 链接](../../frontend/src/utils/markdown-lite.mjs)。

- 独立页可切 graph/pages，并有“新建页面”（标题 + Markdown 正文，标题必填）。详情内嵌页隐藏独立页头，因此没有内嵌新建按钮。
- 阅读页左侧本地搜索 title/summary/content/slug、页面选择、刷新 Wiki；主区渲染 Markdown 与 `[[slug|label]]` 双链；目录提取前 12 个 1–3 级标题，目前目录是文本，不是可点击锚点。
- 图谱请求 mode=overview/ego、limit=500、可选 center/types；节点实际来自 Wiki graph API。单击节点高亮邻居、聚焦和打开详情抽屉，双击或“展开邻域”切 ego；ego 时“全库概览”可回 overview。
- 节点类型选择、图例开关、隐藏/显示箭头、适应屏幕、滚轮缩放、画布平移、节点拖拽固定位置；双向边有双箭头，meta.truncated 有部分展示说明。可见图例是 summary/entity/concept，普通 page 节点仍默认在数据集合中。
- 搜索由 API 返回前 20 项；不在当前图中的选中项先加载 ego。抽屉取 getWikiPage，失败保留本地内容。Wiki 双链若不存在显示提示；graph 中转抽屉、pages 中换选中页，不导航到外部 URL。

### 对话、附件、历史与轨迹

证据：[Chat](../../frontend/src/views/Chat.vue)、[ChatInput](../../frontend/src/views/chat/components/ChatInput.vue)、[SessionSidebar](../../frontend/src/views/chat/components/SessionSidebar.vue)、[AssistantMessage](../../frontend/src/views/chat/components/AssistantMessage.vue)、[TrajectoryPanel](../../frontend/src/views/chat/components/TrajectoryPanel.vue)。

- 草稿有 6 个快捷问题，只填输入，不自动发送。资源同时加载模型/知识库/MCP；等待会话历史、上轮状态及资源完成后启用输入。
- 输入固定智能助手，模型仅选 chat/KnowledgeQA；多选知识库、MCP，联网搜索开关、图片（最多 5）、附件（最多 5）。知识库空选择有“检索全部知识库”提示；幽灵库 ID 从 chip/计数/payload 排除。图片/附件可移除，附件显示大小，图片使用临时 object URL；发送时图片转 data URL、附件转 base64。发送必须有非空 query，附件本身不能单独发送。
- 新草稿首次发送先 createSession，把首消息存 Pinia，再 replace 到保存会话并发流；后续直接提交。last_request_state 回填 model_id/knowledge_base_ids/web_search_enabled/mcp_service_ids。知识库草稿允许用户清空预选或多选，不能在建会话时强行恢复单库。
- request_id 用 UUID/备用随机值，HTTP 同时传 X-Request-ID；正文与 header 应指向同一业务请求。首条本地用户消息显示库引用、图片和附件。
- SSE 接收 answer/references/tool_call/tool_result/actor_*、complete/session_title 以及旧 message_start/message/done 事件；工具按 tool_call_id 关联，多个子 Agent 独立状态。答复有 Markdown/KaTeX、引用折叠、工具结果折叠、子 Agent 展开与复制。
- 中断时按 request_id 查询已有 assistant，只对已有未完成消息 continue-stream，不盲目重新发送；刷新/重开未完成 assistant 也续流。服务端最终消息与已呈现内容、引用、工具、actor 合并。
- 停止先 Abort 本地流；尚无 assistant ID 时最多 30 次、间隔 1 秒找当前 request_id 再 stop；工具/actor running 收敛到停止状态。换会话/卸载也 Abort；历史查询用 Abort + generation 防慢响应串会话。
- 侧栏按置顶/今天/昨天/近7天/近30天/更早分组；新对话、收起/展开、打开、置顶/取消、清空消息确认、删除确认；批量管理、删除所选确认、清空全部历史确认。删当前会话回草稿。
- 历史每次 20 条、before_time、has_more；按钮或滚动顶端加载更早，保持滚动位置；浏览旧消息时不被流强制拉到底，底部按钮可主动回最新。
- 上下文占用按钮显示模型窗口（缺失回退 128K）、会话 used_tokens/percent/compact_threshold；新会话及失败有提示。
- 轨迹页按 turns 呈现 REQUEST/USER/检索/思考/工具/子 Agent/压缩/维护/答案/重试和停止原因；长内容展开，工具 schema 展开，过滤全部/检索/思考/工具/回答，三泳道时间轴切序列/时长/时钟。actor/压缩/维护目前不受上述分类过滤条件隐藏。
- 轨迹中的 Langfuse 链接仅在服务端返回授权 trace_url 且协议有效时显示，再由 Langfuse service 验证目标。轨迹不是 renderer 直接读取日志数据库。
- “加入知识库”按钮目前 disabled，固定智能助手按钮也是 disabled；不能在重构验收中宣称这些是可用提交功能。

### 设置与设备

证据：[Settings](../../frontend/src/views/Settings.vue)、[模型预设](../../frontend/src/views/settings/model-presets.ts)、[思考配置](../../frontend/src/views/settings/ModelThinkingSettings.vue)、[系统字段](../../frontend/src/views/settings/system-fields.ts)、[系统配置组件](../../frontend/src/views/settings/SystemConfiguration.vue)、[Langfuse 设置](../../frontend/src/views/settings/LangfuseSettings.vue)、[追踪凭据](../../frontend/src/views/settings/IntegrationCredentials.vue)、[设备](../../frontend/src/views/settings/DeviceSessions.vue)。

| 设置区 | 实际行为 |
| --- | --- |
| general | 跨会话记忆保存 preferences.enable_memory，Neo4j 不可用时禁用；跳转评测、模型配置；管理员可改 application.name |
| user | 显示邮箱/用户名；聊天历史开关保存 chat-history-config；管理设备；修改密码弹窗逐字段校验、显隐、Enter、取消清空，成功退出所有设备并转 login |
| neo4j | 仅系统管理员展示 enabled/uri/username/password；保存、重载、测试已保存连接、确认清凭据；非管理员说明统一配置 |
| langfuse | 追踪 API 地址/public_key/secret_key/enabled；空密钥保留、加密、无回显、清除后停用；追踪选项、本地服务选项；打开 Langfuse、刷新状态 |
| models | 四类模型标签、数量、7日用量、token/成功率/失败、缓存趋势日/小时/15分钟与用量排行；新增/编辑/默认/清密钥确认/删除确认；内置模型不可删除 |
| vector | sqlite-vec/FTS5 显示；embedding_top_k、vector_threshold、keyword_threshold、rerank_enabled/top_k/threshold 保存 retrieval-config；阈值文案是相对排名归一化 |
| websearch | provider 信息、enabled/notes 保存 web-search-config；当前页面不是完整 provider 凭据编辑器 |
| mcp | 添加/编辑 name/url/description/api_key/enabled，编辑 key 留空沿用，删除确认；卡片显示启用状态 |
| system | 版本/edition/storage/cache/vector/维度显示；管理员 startup 保存、重载、生效值、data_root/database_path/env overrides/restart_required |

模型厂商预设按类型筛选：阿里百炼、DeepSeek、OpenAI、SiliconFlow、智谱、Gemini、Ollama、本地/自定义 OpenAI 兼容；预设自动填地址、model/名称/维度，高级配置可修改。本地无需 key；要求 key 的厂商初次保存必须输入。编辑从不回显 key，留空不提交；已有 key 换 base_url 要求新 key，换 provider 清当前输入 key，不能把旧密钥带到新端点。

思考弹窗按角色列 entries，支持 capability.modes 与 efforts 的动态选项；mode=default/off/on，只有 on 发送 effort。PUT 带 role + revision + policy；dirty/stale 才能保存，editable=false 只读；切角色载入该角色配置，其他角色不改；下一轮生效，当前请求不改。

SystemConfiguration 的 section=application/neo4j/langfuse/local_services/startup；secret 留空从 payload 移除，list 按逗号拆数组；connection test 使用已保存值。startup 需重启且部署环境优先；local_services 文案明确桌面入口不自动启动 Docker。Langfuse 页面本身始终可进入，权限失败显示可重试消息，服务端仍需授权，不能只凭前端 visibility 保护。

设备页显示 id/name/client_type/current/is_revoked/last_seen_at/created_at/expires_at/absolute_expires_at；刷新、撤销确认、撤销当前转 login、撤销他设备后重载；“退出所有设备”有 details 和显式确认按钮。此类操作 skipAuthRefresh，并与 refresh 使用同一个 origin 锁，防止旧 Cookie 响应复活登录。

### RAG 评测

证据：[Evaluation](../../frontend/src/views/Evaluation.vue)。

- 公开固定子集 180 题、全集 3045 题（arxiv-v1），或当前知识库；公开准备任务每 2 秒轮询，ready 后按钮刷新状态，失败提示。租户评估集选择数量、simple/reasoning/multi-context，Judge 可选，生成 entries；auto/manual/sample 审核，sample 优先服务端 review_sampled，否则固定种子约 10%。
- 发布人工选中集合；sample 未选抽样项先 rejected，再 approved + publish，之后“可用问题”取已发布集合。未准备/未发布不能运行。
- 主分块 7 选1、对比策略多选且排除主策略；retrieval=hybrid/vector/keyword、Rerank、Answer/Judge 模型。默认主策略且无对比仍发送既有 chunking_strategies 形状，其他配置发送显式 primary/comparison；这是当前有意保留的过渡形状，不可擅自删掉。
- 运行创建后台 run，再每 2 秒状态轮询；运行时锁配置，启动尚未返回 run_id 的取消意图保留；支持停止/取消、partial/failed/cancelled 继续、重开页面恢复 active run。全集先 estimate，再原生 confirm 展示题数、策略数、时间与模型调用。
- 主策略显示 Hit@10/MRR@10/Recall@20/Context Precision/Faithfulness/Answer Relevancy；对比显示检索/资源指标。缺值 `--`，验证 verified/degraded/unverified/failed 与新鲜度 current/stale/unknown 分开，当前表单改变提示结果属上次配置。
- 进度包含阶段、完成/总题、失败数、覆盖率、耗时、ETA/error；完成报告下载，历史刷新/重试、下载、删除（confirm 含配置），404 刷新并提示不存在；blob JSON 下载后释放 URL，不能直接泄漏私有报告 URL 或跳过授权。

## 3. 实际 API 与前端读取的数据契约

以下路径省略 `/api/v1`；所有普通调用经 client 解包 Axios response 后仍读取业务 envelope `.data`。错误被转换成 `{...业务错误, status}`；不能让 IPC 返回原始 AxiosError 或不一致的 response.data 层级。

| 业务域 | 已用 API/HTTP 形状 | 前端消费数据与关键请求字段 |
| --- | --- | --- |
| 服务身份/认证 | GET capabilities、auth/csrf、auth/me；POST auth/login/register/auto-setup/refresh/logout/logout-all/change-password；PUT auth/me/preferences；GET/DELETE auth/devices[/:id] | capabilities: service_id/client_protocol=1/auth_modes 含 cookie；auth: auth_mode/user/tenant，旧 token/refresh_token；初始化可有 temp_password；登录请求加 auth_mode=cookie/client_type=web；password 三字段；devices.data.items |
| 知识库 | GET/POST knowledge-bases；GET/PUT/DELETE knowledge-bases/:id；PUT :id/pin；POST knowledge-bases/copy；GET :id/move-targets | items（壳/清单部分读取 knowledge_bases 备用）；id/name/description/type/indexing_strategy/capabilities/chunking_config/extract_config/wiki_config/counts/is_pinned/updated_at/needs_reindex/last_effective_strategy；复制 source_id，置顶 is_pinned |
| 文档/上传 | GET knowledge-bases/:id/knowledge；POST :id/knowledge/file；DELETE knowledge/:id；POST :id/reparse、:id/cancel-parse；POST knowledge/batch-delete、knowledge/move | list: items/status_counts/tag_counts/processing_records；doc id/title/file_name/file_size/storage_size/source/type/parse_status/summary_status/error_message/image_count/image_failed_count/updated_at；FormData file/tag_id/process_config(JSON)；响应 deduplicated；批删 ids/kb_id，移动 ids/source_kb_id/target_knowledge_base_id |
| 分块/阶段/标签 | GET chunks/:knowledgeId、knowledge/:id/images/:imageId、knowledge/:id/stages；PUT/DELETE chunks/:knowledgeId/:chunkId；GET/POST knowledge-bases/:id/tags | chunks.items/total/page；chunk id/index/type/content/is_enabled/image_info、context_parent_id/media_parent_id/anchor_chunk_id；保存 content/is_enabled；image=Blob；spans.items: root/stage id/parent_id/name/kind/status/input/output/error_message/times/duration；tag id/name/color |
| 会话/流 | GET/POST sessions；GET/DELETE sessions/:id；POST/DELETE :id/pin；DELETE :id/messages；DELETE sessions/batch；POST :id/stop；GET messages/:id/load；POST knowledge-chat/:id / agent-chat/:id；GET sessions/continue-stream/:id | session id/title/is_pinned/times/last_request_state；建会话 knowledge_base_id/title/agent_config；batch DELETE body ids 或 delete_all；messages.items/has_more；message id/request_id/role/content/is_completed/images/attachments/mentioned_items/knowledge_references/agent_steps/agent_tool_calls/actor_traces/times；stop.message_id；续流 query.message_id |
| 轨迹/上下文 | GET sessions/:id/trajectory、:id/context-usage | trajectory.data.turns 见 TurnRecord；request/steps/tools/actors/retrievals/retries/compactions/maintenance/usage/observability；context_window/used_tokens/percent/compact_threshold |
| 模型/用量 | GET/POST models；PUT/DELETE models/:id；DELETE models/:id/credentials/api_key；GET models/usage；直接 client GET/PUT models/:id/thinking | model id/name/display_name/type/raw_type/role/roles/source/parameters(nonsecret)/credentials_configured/status/is_default/is_builtin/managed_by/context_window；counts_by_type/total；usage total/by_model/by_type/cache/cache_series.buckets/models.points；thinking revision/editable/entries[role,policy,capability,stale] |
| 租户设置/MCP | GET/PUT tenants/kv/:key；GET/POST mcp-services；PUT/DELETE mcp-services/:id；GET system/info、vector-stores/types、web-search-providers/types | KV 响应 data.value，请求 {value}；retrieval-config/chat-history-config/web-search-config；MCP items，id/name/url/description/enabled/status，key 不回显；system info 含 name/version/edition/storage/cache/vector/graph_database_engine/bailian |
| 系统配置/追踪 | client GET/PUT/DELETE system/config/:section；POST :section/test；GET/PUT/DELETE integrations/langfuse/credentials；GET observability/langfuse/status；POST session、session/clear | config values/fields[key].configured/restart_required/active/data_root/database_path/environment_overrides；DELETE body field；追踪配置 enabled/base_url/fields；状态 state/credentials_configured/auto_login/open_url；secret 永不作为 response/日志回显 |
| Wiki | GET/POST knowledge-bases/:id/wiki/pages；GET pages/:slug；GET wiki/search、wiki/graph | pages.items: id/slug/title/content/summary/page_type；search q/limit→pages 或 items；graph mode/limit/center/types→nodes[slug/title/label/page_type/link_count]、edges[source/target]、meta[mode/total/returned/truncated]；slug 按路径段 encode |
| 评测 | rag-eval/open-datasets 与 :id/status、POST :id/prepare；POST testsets；POST datasets/:id/review；POST runs、runs/estimate；GET runs(active=true)、runs/:id；POST :id/cancel/resume；GET history；GET/DELETE reports/:id | datasets id/version/count/documents/ready/status/progress/error；testset id/entries/generated；entry id/question/ground_truth/question_type/status/review_sampled；review entry_ids/status/publish；run run_id/run_status/status/requested_configuration/effective_pipeline/metrics/verification_status/freshness_status/report 与进度/时间；report id/url/available，history provenance/dataset/config，下载 Blob |

API 中还保留了当前页面未直接调用的入口：updateModelCredentials、parserEngines/storageStatus/checkParserEngine/checkStorageEngine、sessionEvents（after_seq/limit）、非流 chat/agentChat、ragEvalRun/questions/add/delete/generate/openRun/status/cancel/datasets/dataset/testsets/retrieval/chunking/ragEvalReportUrl。没有按钮引用不等于可以删除服务端或其他客户端的能力；需与服务端基线、现有调用方核对。`copyValue` 也是 Settings 内现有 helper，目前模板没有复制地址按钮。

## 4. Electron / IPC 与浏览器适配边界

1. renderer 保留 Vue 表单/渲染与用户交互，业务核心通过受限、类型化接口处理持久化、凭据、模型/网络调用、后台任务。现有 UI 依赖的 `.data` envelope、错误 status/code/message、分页、ID、时间、统计与状态含义必须先形成契约；不能把 renderer 任意 SQL/任意文件路径/任意 fetch 当新公共 API。
2. 浏览器/PWA 仍是同源远程服务客户端。EndpointResolver 当前拒绝跨源、用户名密码、hash、非 `/api/v1/` API URL；native 服务切换是单独 adapter，不得用桌面协议替换而破坏浏览器 HTTPS/移动访问。service_id 与用户/tenant 身份变更必须使缓存与会话重新绑定。
3. 远程认证不能简化成“桌面单用户”：HttpOnly Cookie、CSRF、一次 refresh、跨页 Web Locks、epoch、skipAuthRefresh、storage logout/identity 事件、旧 Bearer 兼容均是现有行为。桌面本地身份与远程身份应明确建模，服务端权限/私有空间不能改为仅前端过滤。
4. streamChat 发送 stream=true/channel=web，使用 fetch ReadableStream + TextDecoder，按空行切帧，多行 data 用换行拼接。IPC 需要保留 request_id/assistant_id/tool_call_id/actor_id、增量事件顺序、取消信号、订阅解绑、重新打开后的续流，以及后端已完成内容恢复；close window 与业务取消不能混为同一个状态。
5. 文件上传目前是真正 File/FormData，聊天附件是真正 base64，图片/报告为 Blob/object URL；迁移需明确 renderer↔main 传输用字节或受控句柄、大小/MIME/名称、生命周期和去重。桌面路径不是跨设备业务 ID；不能把绝对路径展示给远程浏览器或作为可任意读取的 IPC 参数。
6. 文件对话框、clipboard、report 保存、外链打开需 platform adapter；保留取消无提交、保存失败可重试。Langfuse 打开先验证 session，禁止先开空窗；配置 UI 地址仅 http/https、无凭据/query/hash 且是项目 traces，traceUrl 只能落在授权同 origin/project。桌面外链必须保留这个约束。
7. 解析/评测为持续任务：3 秒/2 秒轮询、run_id/attempt/root 分组、取消/恢复、失败重试、页面换资源隔离都要继续可用；SQLite 写入与 UI 生命周期分离，不以页面销毁代表后台业务完成。
8. 秘密只写受保护业务侧存储。renderer 获取 configured 状态，留空保留、显式清除、新端点新凭据。Langfuse/Neo4j/MCP/model/初始化密码都不得因 IPC 调试、事件回放或导出报告泄漏。
9. 移动/PWA 已有能力不能误删：底部导航、文档卡片、相机点击后才访问、先确认后上传、软键盘视口、手机 Enter 换行、安装说明、离线提示、延后更新。当前 PWA 只缓存构建清单的公开静态资产；API/media/private uploads/downloads/SSE 不缓存，不承诺完整离线知识库。deviceStore 仅允许显式保存 draft/cursor，按 service/user/space 分区；当前聊天输入并未接入持久草稿，不能声称已有自动草稿恢复。
10. 保留能力门控与权限分层：图谱/Wiki 禁用项、Neo4j 记忆依赖、内置模型删除保护、管理员配置/trace link、思考 editable。截图看得到的按钮不等于每种身份都可执行，IPC/domain 层必须同样执行授权与校验。

## 5. 可合并 TEST-MATRIX 的稳定点击案例

所有案例初始状态为 `未执行`。编号固定；后续变更只补充结果、证据路径及参数，不重排编号。使用隔离临时空间、测试账号/文件/报告，避免在真实资料上点击删除、改密码或撤销。涉及真实模型/Neo4j/Langfuse 时记录依赖准备情况；缺依赖应标阻塞或降级，不伪造通过。桌面和远程浏览器都应覆盖通用案例，UI-MOB 专门验证移动/PWA。

| 编号 | 可实际点击的操作与前置条件 | 判定要点 |
| --- | --- | --- |
| UI-AUTH-001 | 未登录直接打开知识库深链，回 login 后输入有效邮箱密码并点击登录 | 未授权页不展示私有数据；导航到知识库；刷新仍恢复服务端身份 |
| UI-AUTH-002 | 点“创建个人账号”，确认密码先输入不一致，再改为一致点注册 | 不一致不提交；注册后私有空间建立，跨设备同账号可访问 |
| UI-AUTH-003 | 空数据且允许初始化的隔离实例，点自动初始化，再点击已保存凭据按钮 | 只显式点击发请求；凭据只在页内出现一次，确认后清掉并导航 |
| UI-AUTH-004 | 已初始化/禁用/忙状态分别点自动初始化；另模拟成功但无 temp_password | 明确错误/成功提示；无密码不造凭据、不自动跳页 |
| UI-AUTH-005 | 同一浏览器同站点两页签登录，在一个账户菜单点退出；另一浏览器作为独立设备观察 | 当前页及共享storage的页签失效，独立设备保持登录；后到旧 refresh 响应不复活 |
| UI-AUTH-006 | 有保存旧 Bearer 登录的兼容场景打开受保护页，再显式 cookie 登录 | 旧会话可按现有契约恢复；新 cookie 登录清旧 token，不回退泄漏 |
| UI-AUTH-007 | 登录后将服务指向不同 service_id，刷新；另在网络中断时恢复 | 服务改变需重登、缓存不混用；网络错误不删除未提交本地内容 |
| UI-NAV-001 | 有历史点主导航“对话”，再点聊天侧栏“新对话”；空历史重试 | 前者最近会话、后者草稿；空历史进入草稿 |
| UI-NAV-002 | 最近访问在两个知识库详情间切换，再浏览器后退/前进 | 页面、API操作、标签/选择/抽屉都属于当前 kbId |
| UI-NAV-003 | 点账户头像、菜单 general/user；general 打开评测，直达 devices/wiki/chat | section/deep link/懒加载/刷新正确，不丢账号状态 |
| UI-KB-001 | 点新建、填名称描述，分别组合混合/Wiki/图谱与 semantic 父子参数 | 保存实际配置，卡片能力标签正确；空名称/无索引/越界不提交 |
| UI-KB-002 | 输入关键词 Enter、切文档/RAG+Wiki、范围全部/收藏/最近/本空间、刷新 | 请求与客户端筛选符合现有含义，数量/空态正确 |
| UI-KB-003 | 卡片置顶、收藏查看、取消，再点复制 | 行为持久化、清单刷新；操作不意外进入详情 |
| UI-KB-004 | 点卡片进详情；点删除先取消，再确认删除隔离库 | 取消保留，确认删除库/文档/索引/Wiki，清单更新 |
| UI-KB-005 | 知识库设置修改名称/分块/能力并保存，再刷新 | needs_reindex/生效策略按服务端显示；不暗中触发重解析 |
| UI-DOC-001 | 上传选择多个文件，追加重复、移除，改标签/分块，再开始解析 | 选择阶段零上传；队列去重；确认才提交，最多3并发 |
| UI-DOC-002 | 混合成功/服务端 deduplicated/失败文件点击开始解析，再重试失败 | 各项和总数正确；仅失败留队列，不重复提交已成功文件 |
| UI-DOC-003 | 选择 HEIC/HEIF、音视频与有效 JPEG/文本混合 | 明确拒绝不支持项，有效项仍可确认上传 |
| UI-DOC-004 | 点标签管理新建，按标签/状态/文件类型/关键词筛，再清空 | 数据与计数正确、已选隐藏项剔除，不把过滤结果当全库状态 |
| UI-DOC-005 | 对后台解析中文档打开 Chunk/解析记录，取消后再重解析 | 轮询自动启停，展示最新尝试而不是跨 root 混画，状态/error 可见 |
| UI-DOC-006 | 打开有>50块文档，编辑正文/启停，未保存翻页/筛选，再保存 | 脏页被阻止；保存持久化后可翻页；父块/容器只读 |
| UI-DOC-007 | 打开带图文档，看 OCR/描述/关系字段，图片失败场景重解析 | blob 预览正确、失败有比例提示，图片失败不阻断文本编辑 |
| UI-DOC-008 | 选择两文档移动到返回的目标库，再源/目标清单和问答检索 | 文档、chunk/索引迁移一致；无权限目标不可绕过 API 选择 |
| UI-DOC-009 | 单删/批删先取消再确认；删末页唯一可编辑 chunk | 取消无写；删除数据/索引更新；chunk末页退上一页 |
| UI-DOC-010 | 文档/Wiki/图谱/解析记录切换，关能力；直接 `tab=settings` | query与标签同步，能力禁用回文档，settings开弹窗 |
| UI-WIKI-001 | 独立 Wiki 新建含双链/表格/公式的 Markdown，切页面并选择 | 页面保存/读取/安全渲染，空标题不提交；内嵌不误增入口 |
| UI-WIKI-002 | 阅读页搜索并点结果、刷新、点存在/不存在双链 | 本地搜索、选中切换、刷新正确；不存在提示，目录是文本 |
| UI-WIKI-003 | 图谱搜索页、单击节点、双击、抽屉展开邻域、全库概览 | getPage/ego/overview与中心正确，内容回退和邻居高亮 |
| UI-WIKI-004 | 节点类型/图例开关、箭头、适应屏幕、滚轮/拖画布/拖节点 | 类型过滤/空态、双向箭头与视口可用，无重复监听 |
| UI-WIKI-005 | >500节点图显示 truncation，换 kbId 后继续搜索/开详情 | 部分展示有说明；不得读上个库页面或图数据 |
| UI-CHAT-001 | 新对话点快捷问题，选模型/库/MCP/联网后发首消息 | 快捷只填；只创建1会话并发送1请求，首消息及设置保存 |
| UI-CHAT-002 | 知识库草稿清空预选，再多选发送；删库后打开旧会话 | 空代表全部；多选保留；幽灵库无chip/计数/payload |
| UI-CHAT-003 | 添加/删除图片与附件，每类超过5；输入文本后发送 | 限制5，预览/大小/base64正确；未输入query不可发；URL释放 |
| UI-CHAT-004 | 回答期间刷新/断网重连，再重开会话 | 按相同request_id恢复已有assistant/continue-stream，不重复模型请求 |
| UI-CHAT-005 | 请求刚发送、assistant ID尚未返回时点停止；工具/actor运行时再测 | 精确停止当前请求，后到消息不续生成，spinner收敛，按钮状态恢复 |
| UI-CHAT-006 | 慢历史请求中点另一会话；返回上一会话 | 旧请求取消/忽略，消息及last_request_state不串台 |
| UI-CHAT-007 | 展开工具/子Agent/引用，复制完整答案，看 Markdown/数学/错误结果 | 多工具ID/actor独立，失败输出不重复，复制正文，不启用禁用加入知识库 |
| UI-CHAT-008 | 侧栏置顶、清空消息、单删、批删、清空全部，先取消再确认 | 分组/当前会话/导航正确；全部仅当前授权空间 |
| UI-CHAT-009 | 超20历史点加载更早/滚动顶端，流期间停留旧消息，点回底 | history/has_more、滚动位置正确；不强拉底 |
| UI-CHAT-010 | 点上下文窗口；新会话、已有记录、失败三状态 | context_window/used/percent/compact_threshold一致，有空态/错误提示 |
| UI-CHAT-011 | 切轨迹，按过滤、展开长内容/schema、切三种时间轴 | turns数据对应当前会话；零时长记录不消失，actor/压缩/维护保留 |
| UI-SET-001 | general有/无Neo4j两场景点记忆开关，刷新 | 不可用禁用；可用保存用户偏好，失败恢复开关 |
| UI-SET-002 | models点添加各类型和可用厂商、本地、自定义，填测试key并保存 | 预设/维度/类型筛正确、默认持久化，必填/厂商key校验 |
| UI-SET-003 | 编辑已有key模型留空保存，再改端点不填key；填新key保存 | 不回显key，空保留；新端点需新key，厂商切换不带旧key |
| UI-SET-004 | 清密钥/删除模型先取消再确认；内置模型点删除 | 明确清除与删除差异，内置禁用，调用状态更新 |
| UI-SET-005 | 思考弹窗换角色，选default/off/on和允许effort，保存；只读/旧revision | 只改当前角色、下轮生效、capability门控，冲突/readonly不覆盖 |
| UI-SET-006 | 模型用量切日/小时/15分，刷新有/无数据 | 7日统计、缓存率与模型点不混淆，无数据有提示 |
| UI-SET-007 | 检索改五个数值/Rerank开关并保存；websearch启用notes保存 | KV持久化、刷新回填；UI文案与相对排名阈值一致 |
| UI-SET-008 | MCP添加/编辑留空key/禁用/删除，聊天选服务发送 | 配置持久化、不回显密钥、留空沿用；可用服务遵从服务端契约 |
| UI-SET-009 | user改聊天历史；密码弹窗空/不一致/显隐/取消，再成功改密码 | 校验聚焦/取消清字段；成功所有设备退出，新密码可登录 |
| UI-SET-010 | 管理设备刷新，撤销其他设备再撤销当前；另一轮退出所有设备 | 他设备token失效、其他保持；当前/全体退出，旧refresh不复活 |
| UI-SET-011 | 管理员改应用名、Neo4j连接/secret，留空重存、测试与清除 | configured不泄漏值；测试已保存，清除停用，非管理员不能写 |
| UI-SET-012 | 管理员改startup后保存、展开active、重启；有env override场景 | restart_required/data目录/env优先正确，秘密不落startup |
| UI-SET-013 | Langfuse API key保存留空/清除；追踪选项和本地配置保存 | 凭据不回显，采样/内容/trace开关持久化；clear停上报 |
| UI-SET-014 | 打开Langfuse：自动登录开/关/失败；轨迹授权链接点击 | 先验证再开，无失败空窗口；人工登录fallback，同origin/project约束 |
| UI-SET-015 | 故意使一个设置加载API失败，点重新加载 | 其他设置仍可用，错误明确可重试，不用失败空对象覆盖保存值 |
| UI-EVAL-001 | 公开180题选择准备，ready后刷新状态；准备失败再重试 | 后台准备/进度/失败真实，未ready不能运行 |
| UI-EVAL-002 | 知识库生成题，auto/manual/sample分别审核发布 | 已发布子集数量准确、拒绝与批准一致，未发布不可运行 |
| UI-EVAL-003 | 设置主/对比分块、retrieval/Rerank/Answer/Judge，点运行 | 配置快照/实际pipeline可核对，主不重复入对比，运行锁表单 |
| UI-EVAL-004 | 全集3045点运行，先取消估算confirm再确认 | 取消零run创建，确认后后台严格全量；估算信息显示 |
| UI-EVAL-005 | 创建尚未返回run_id点停止、运行后点取消；失败/取消后继续 | 意图保留、run状态准确、已有完成项恢复，任务非页内假进度 |
| UI-EVAL-006 | 运行中离页/刷新再打开；完成后改表单 | active恢复轮询；结果配置/验证/新鲜度独立，变表单有提示 |
| UI-EVAL-007 | 下载统一报告/历史报告，再删除先取消再确认；报告404 | 私有范围/Blob JSON/文件名正确，404刷新提示，删除禁止跨空间 |
| UI-EVAL-008 | history加载失败点重试，查看缺指标、degraded/stale/partial | 缺值--而非0，状态与freshness/覆盖率/error不混淆 |
| UI-MOB-001 | 窄屏底部收集选目标，再主动拍照/选图，先取消后确认上传 | 未点击不访相机、未确认不上传；目标一致，卡片操作可触达 |
| UI-MOB-002 | 手机输入中文IME/Enter/Shift换行，软键盘开关，点显式发送 | IME不发送、手机Enter换行、输入/发送不被底栏遮住 |
| UI-MOB-003 | 手机点会话开关、打开旧会话、管理菜单与表单滚动 | 抽屉导航/触控/弹窗按钮可达，长内容不溢出屏幕 |
| UI-MOB-004 | 设置安装按钮：支持prompt与无prompt的Safari说明两种 | 用户主动安装，已安装隐藏，文案不承诺完整离线 |
| UI-MOB-005 | PWA下载新壳时保留未提交输入/在途上传，断网再进深链 | 仅提示可延后、无自动reload/skipWaiting；离线壳不缓存私有API/SSE/报告 |

## 6. 静态发现的待核实边界

以下是当前工作区代码可见的风险，尚未用 GUI 复现。迁移不能把风险写成已经通过的能力，也不应把缺陷作为必须原样保留的契约；应在相应用例中记录现状与修复决策。

- Wiki 的 kbId watcher 重取 pages/graph，但没有显式清 selectedSlug、drawerPage、搜索和类型状态；UI-WIKI-005 需要覆盖跨库复用及已打开抽屉。
- TrajectoryPanel 的异步 load 没有 Chat.loadMessages 同类的 generation/Abort 保护，慢旧请求可能覆盖新 session；UI-CHAT-006/011 需要覆盖轨迹的快速换会话。
- Settings 的 retrieval/chat-history/web-search 三个 KV 读取失败会回退默认值/空对象，未计入 loadFailures；UI-SET-015 需要区分展示默认值与用户明确保存，验证失败状态不会误覆盖已保存配置。
- ChatInput 的知识库 payload 排除幽灵 ID；MCP payload 仍使用 selectedMcpIds 原集合，mcpOptions 也不在前端按 enabled 过滤。UI-SET-008 需由服务端基线核对禁用/删除服务的实际契约，不能仅凭 chip 显示判断调用权限。

## 7. 文档验证记录

此次只新增本文件，不修改任何业务文件，不提交。文档链接应解析到当前工作区源文件；验收编号应唯一。GUI 结果、远程服务和真实模型结果仍由执行阶段补充。
