# 桌面迁移：数据、权限与后台任务基线

本报告记录 2026-10-10 当前工作区的实现，供 TypeScript + Electron + SQLite 全量迁移使用。Python 的目标职责限于文档解析、OCR 和 Ragas 辅助；身份、权限、模型调度、检索、图谱、Wiki、任务、评测编排及所有数据库写入迁入 TypeScript。保留当前有效功能与用户数据，不把历史删除迁移重新执行为数据导入步骤。

本次只阅读源码并新增此报告，没有访问实际业务数据库、用户缓存、上传文件或 `.secrets` 内容，没有启动 Django、运行业务任务、修改数据或提交。工作区已有大量改动，本报告反映工作区文件，不能当作某个已发布版本的状态。

## 1. 覆盖范围与证据等级

完整阅读的主要实现：

- [PKB models](../../personal_knowledge_base/models.py)、[accounts models](../../accounts/models.py)，PKB `0001`—`0026` 中现存的 25 个迁移文件及 accounts 的 1 个迁移文件。迁移编号缺 `0006`，不是本次遗漏。
- [凭据字段](../../personal_knowledge_base/credential_fields.py)、[运行路径](../../config/runtime_paths.py)、[settings](../../config/settings.py)、[bootstrap](../../config/bootstrap.py)、[数据库工具](../../personal_knowledge_base/db_utils.py)。
- [账户接口](../../accounts/views.py)、[设备会话](../../accounts/device_sessions.py)、[认证](../../personal_knowledge_base/authentication.py)、[权限](../../personal_knowledge_base/permissions.py)、[个人空间](../../personal_knowledge_base/personal_spaces.py)、[接口安全](../../personal_knowledge_base/view_security.py)。
- [任务](../../personal_knowledge_base/tasks.py)、[任务恢复](../../personal_knowledge_base/task_recovery.py)、[文档处理](../../personal_knowledge_base/document_processing.py)、[文档接口](../../knowledge/views.py)、[清理](../../personal_knowledge_base/knowledge_cleanup.py)。
- [会话事件日志](../../personal_knowledge_base/event_log.py)、[处理 span](../../personal_knowledge_base/span_tracker.py)、[持久化流](../../personal_knowledge_base/stream_manager.py)、[流终态](../../personal_knowledge_base/stream_protocol.py)。
- [检索](../../personal_knowledge_base/search.py)、[图检索](../../personal_knowledge_base/graph_rag.py)、[Neo4j 连接](../../personal_knowledge_base/neo4j_connection.py)、[集成配置](../../personal_knowledge_base/integration_config.py)。
- [Wiki ingest](../../personal_knowledge_base/wiki_ingest.py)、[页面生成](../../personal_knowledge_base/wiki_page_generator.py)、[Wiki 接口](../../wiki/views.py)。
- [评测接口](../../personal_knowledge_base/eval_views.py)、[报告](../../personal_knowledge_base/eval_reports.py)、[RAG 评测](../../personal_knowledge_base/rag_eval.py)、[检索评测](../../personal_knowledge_base/retrieval_eval.py)、[Ragas 适配](../../personal_knowledge_base/ragas_adapter.py)、[数据集注册表](../../personal_knowledge_base/eval_dataset_registry.py)。
- 根 URL 及 accounts、models_config、knowledge、wiki、PKB、chat、agent 的 URL 文件。
- 四份回归测试全文：[发布边界](../../personal_knowledge_base/test_business_publish_fencing.py)、[检索正确性](../../personal_knowledge_base/test_search_correctness.py)、[事件竞争](../../personal_knowledge_base/test_event_log_contention.py)、[span attempt](../../personal_knowledge_base/test_span_tracker_attempts.py)。其他测试仅核查类名、测试名称或局部实现，见第 11 节。

部分阅读：`open_rag_benchmark.py` 全文件结构及第 1—310、565—832 行，包括注册状态、完整性检查、embedding 断点 SQLite、索引准备和下载锁；`parent_context.py` 全文件结构及第 390—580 行；`chunking_eval.py` 全文件结构及第 924—1013 行。没有完整审计解析器、分块内部实现、通道/MCP/agent 执行器、所有视图或全部测试。

以下是源代码基线，不是实际数据库盘点：未确认用户数据库迁移执行到哪一版、数据规模、历史异常行、扩展实际可加载性、实际 PostgreSQL 使用情况或凭据密文是否可解。没有运行后端/前端测试；新增文档只进行链接和差异检查。

## 2. 数据库清单及关系

### 2.1 主业务模型：31 张实体表

统计为 PKB 29 个具体模型 + accounts 2 个具体模型；抽象 `TimeStampedModel` 不计。普通 PKB UUID 主键多为带连字符的 `CharField`，`Tenant` 等为 Django 隐式整数主键；accounts 的 `UUIDField` 在 SQLite 上的实际存储编码不能直接等同于字符串 UUID。

| 表 / 模型 | 主键与关联 | 必须保留的内容、约束和语义 |
| --- | --- | --- |
| `tenants` / Tenant | 隐式整数 PK；personal_owner → User，PROTECT | 空间名称、状态、配额、API key、各类配置；legacy 要求 owner=NULL，personal 要求 owner 非 NULL；每用户仅一个 active、未软删个人空间。API key 唯一。 |
| `users` / User | UUID 文本 PK；primary tenant → Tenant，SET_NULL | username/email 唯一；原 password_hash、激活/管理员/跨空间标志、preferences；primary tenant 不是完整成员关系。 |
| `auth_tokens` / AuthToken | UUID 文本 PK；user CASCADE | 原始 token 唯一，类型、期限、撤销状态；历史 bearer/refresh 仍为现行能力，当前字段不是 digest。 |
| `tenant_members` / TenantMember | 隐式整数 PK；user、tenant CASCADE | unique(user,tenant)，role/status/inviter/join time；撤销行不能删除后退回旧 primary tenant 权限。 |
| `models` / ModelConfig | 文本 PK，最长 64；tenant CASCADE | type/source/parameters、default/builtin/managed_by、fallback_priority、context_window、状态；parameters 为加密 JSON。 |
| `model_usage` / ModelUsage | UUID 文本 PK；tenant 可空 | request_id、scenario、provider/model 标识、prompt/completion/cached/reasoning/total tokens、duration、success/metadata；tenant+时间/type/model/scenario 索引。 |
| `knowledge_bases` / KnowledgeBase | UUID 文本 PK；tenant CASCADE | 分块、图片、embedding、摘要、图、Wiki、存储等配置，pin/temp/creator；模型配置 ID 多为普通字符串，不能自行改成强 FK 后丢失历史值。 |
| `knowledges` / Knowledge | UUID 文本 PK；tenant、KB CASCADE | 文件 hash/name/path/size、解析/启用/摘要状态、metadata/error、软删除；活跃 file 的 KB+hash+name 条件唯一。 |
| `knowledge_images` / KnowledgeImage | UUID 文本 PK；tenant、KB、knowledge CASCADE | 原图、storage_owned/path/hash、mime/尺寸、page/block、OCR/caption/status/metadata；文件删除要检查共享引用和所有权。 |
| `chunks` / Chunk | UUID 文本 PK；tenant、KB、knowledge CASCADE | 内容及编辑状态、类型、索引/偏移、prev/next、context_header、context_parent/media_parent/anchor、relation_chunks/image_info、enable/soft delete、seq_id。三类 parent/anchor 是不同概念。 |
| `semantic_chunk_cache` / SemanticChunkCache | 隐式整数 PK；无 tenant FK | 内容 hash+模型 signature+algorithm+window+percentile 唯一；JSON vectors/window inputs。语义分块缓存，不是检索向量表。 |
| `stream_states` / StreamState | message_id 普通文本 PK；session_id 普通文本索引 | complete/error、最终内容、refs/steps/duration、时间；没有 Message/Session FK 自动级联。 |
| `stream_events` / StreamEventRecord | 隐式整数 PK；message/session 普通文本 | unique(message_id,offset)，event/data、时间；断线续传有序事件，不可用内存流代替。 |
| `sessions` / Session | UUID 文本 PK；tenant CASCADE | user_id/agent_id/KB id 为普通文本；标题、pin、agent/context/retrieval 配置和 event_seq。 |
| `session_events` / SessionEvent | 隐式整数 PK；tenant、session CASCADE | unique(session,seq)，request_id/type/data；session+seq 和 session+request+seq 索引。用于轨迹回放和修复。 |
| `context_snapshots` / ContextSnapshot | UUID 文本 PK；session CASCADE | 模式、历史边界、内容/关键事实/摘要及 token 数；每 session+mode 仅一条 is_active=true 的条件唯一约束。 |
| `messages` / Message | UUID 文本 PK；session CASCADE | request_id、role/content/rendered、引用/步骤/图片/附件/提及、完成状态、fallback/channel/knowledge、actor/可见性/duration。 |
| `agent_actors` / AgentActor | UUID 文本 PK；session CASCADE | unique(session,actor_id)；parent actor/message 普通 ID、foreground/background、工具白名单、输入/输出、状态/error/metadata/times。 |
| `knowledge_tags` / KnowledgeTag | UUID 文本 PK；tenant、KB CASCADE | unique(tenant,KB,name)，color/order/seq；文档 tag 关联部分在 JSON，需保持原格式。 |
| `generic_resources` / GenericResource | 文本 PK，最长 64；tenant 可空 | type/name/status/data；data 为加密 JSON；承担 agent、channel、MCP、连接器、配置及评测资源等，不能只导入已知少数 type。 |
| `audit_logs` / AuditLog | 隐式整数 PK；tenant CASCADE | actor/role/action/target/path/method/outcome/details、时间；保留审计历史。 |
| `task_records` / TaskRecord | UUID 文本 PK；无 tenant FK | task_type/status/progress/payload/result/error、queue/lease/attempt/claim/cancel；权限依赖 payload/result 归属，不能只凭任务 ID 访问。 |
| `model_rate_limit_state` / ModelRateLimitState | 255 字符 key PK | provider/model、token bucket/capacity/refill/time/block；provider+model 索引；限流跨调用持久化。 |
| `wiki_pages` / WikiPage | UUID 文本 PK；tenant、KB CASCADE | unique(KB,slug)，包括软删除页；内容/summary、source/chunk refs、aliases/in/out links、contributions/page_metadata、类型/状态/版本、目录/父 slug/path/depth/order。 |
| `wiki_folders` / WikiFolder | UUID 文本 PK；tenant、KB CASCADE | parent_id 为普通字符串；名称/path/depth/order；KB+parent 索引。 |
| `wiki_pending_ops` / WikiPendingOp | 隐式整数 PK；tenant FK | task_type/scope/id/op/dedup_key/payload、enqueue/claim/fail/error；dedup_key 有索引但无唯一约束。 |
| `wiki_log_entries` / WikiLogEntry | UUID 文本 PK；tenant、KB CASCADE | 原 knowledge_id 普通字符串、action/title/summary/pages/details/time；保留文档删除后的历史日志。 |
| `knowledge_processing_spans` / KnowledgeProcessingSpan | 隐式整数 PK；knowledge CASCADE | span_id 唯一，parent_span_id 普通字符串；attempt、name/kind/status、输入输出/metadata/error/times/duration；knowledge+attempt 索引。 |
| `integration_configs` / IntegrationConfig | name 文本 PK，最长 64；无 tenant FK | 全局 application/neo4j/langfuse/local services 等；parameters 为加密 JSON，不能误改为每用户仅一份。 |
| `device_sessions` / DeviceSession | UUIDField PK；user CASCADE | access_digest 唯一；设备名/client type、access/idle/absolute expiry、seen/revoke reason；user+revoked 索引。 |
| `device_refresh_tokens` / DeviceRefreshToken | sha256 digest 文本 PK；device session CASCADE | expiry/consumed_at；已消费摘要保留至 family 到期，支撑 replay 检测。 |

依据：[模型及约束](../../personal_knowledge_base/models.py)、[设备模型](../../accounts/models.py)、[个人空间迁移](../../personal_knowledge_base/migrations/0026_personal_spaces.py)、[设备迁移](../../accounts/migrations/0001_initial.py)。

跨表一致性不能仅靠现有 FK：Chunk、KnowledgeImage、WikiPage/Folder 等重复存有 tenant 和 KB，FK 本身未约束组合一致；Session user_id、actor parents、Wiki parents、chunk hierarchy、TaskRecord payload 归属多为逻辑关联。迁移需保留原 ID，并检查子表 tenant、文档 tenant、KB tenant 和 KB id 的一致性；不能把可疑行悄悄丢弃。

### 2.2 非 ORM 数据与持久化资源

| 位置 | 当前结构与用途 | 迁移要求 |
| --- | --- | --- |
| 主 SQLite `chunks_fts` | FTS5；chunk_id、tenant_id、KB id、knowledge id、title/content，其中 knowledge_id UNINDEXED | 当前检索索引；FTS5 扩展与 tokenizer/排序语义需验证，不能把普通表复制当作索引可用。 |
| 主 SQLite `chunk_embeddings_vec` | sqlite-vec `vec0`，按 rowid 定位，仅 embedding float[dimension] | 保留向量与原 rowid 对应；原有表可能维度 384，运行设置默认 1024；维度和模型空间不兼容不能标 ready。 |
| 主 SQLite `search_index_meta` | key/value；status/signature/reason 等 | 保留 ready/needs_rebuild 的区别；转换需新版本标识，禁止未完成重建就显示可用。 |
| 评测 `index.sqlite3` | sections、metadata、FTS5 section_fts、可选 vec0 section_vectors | 钉住上游 revision/manifest 的公共语料索引，独立于 tenant 文档；TypeScript 接管准备、校验、SQLite 写入。 |
| 评测 `embedding-checkpoint.sqlite3` | embeddings；PK(model_signature,content_hash)，dimension/vector/updated_at | 已计费的公共语料 embedding 断点缓存；模型/内容校验后复用，不能无条件删掉重算。 |
| 主 SQLite 的 FTS/vec shadow 表、Django 元数据表 | SQLite 扩展内部表；django_migrations 及可能存在的框架表 | 不计入 31 个实体表；应从实际 schema 盘点，扩展内部表避免逐行盲拷贝。 |
| Neo4j | 每 KB 的实体 label、每文档 kg 属性、node/edge/chunk provenance 和权重 | 原完整图不在主 SQLite；SQLite 图迁移需导出实体、边、属性及 provenance。只搬 relation_chunks 会丢图能力。 |
| 上传媒体与缓存 | 原始文件、所有权明确的图片，公共 corpus/json、报告、评测 checkpoint、配置文件 | 与 DB 一致快照并验证引用，不把缓存一律归为可删除。 |

主检索来源：[search](../../personal_knowledge_base/search.py)、[初始迁移](../../personal_knowledge_base/migrations/0001_initial.py)。公共索引来源：[Open RAG benchmark](../../personal_knowledge_base/open_rag_benchmark.py)。图来源：[graph_rag](../../personal_knowledge_base/graph_rag.py)。

### 2.3 历史迁移的破坏性步骤

| 迁移 | 已有实现 | 新导入必须避免的行为 |
| --- | --- | --- |
| [0004](../../personal_knowledge_base/migrations/0004_remove_manual_url_knowledge.py) | 删除 manual/url 文档、chunk、索引和图；反向 no-op | 不在读取现存数据时再次清理。当前业务已移除的历史类型与当前有效功能要分别识别。 |
| [0007](../../personal_knowledge_base/migrations/0007_deduplicate_active_file_knowledge.py) | 按 KB+hash+name 去重，保留排序第一份，其他 soft delete/cancel、删除 chunk | 不用新脚本重跑旧去重规则；保留用户现存状态，异常单独报告。 |
| [0012](../../personal_knowledge_base/migrations/0012_remove_audio_video_support.py) | 清理 audio/video 文件及记录、ASR 模型/用量，删除 videoInfo；atomic=false | 新迁移不能重放文件删除；不得为了转换方便删除现有有效多模态文档/图片。 |
| [0013](../../personal_knowledge_base/migrations/0013_multimodal_document_images.py) | 清空既有 knowledge/chunks/FTS/vector/Wiki/process tasks，并处理旧图；反向显式不可逆 | 这是最高风险历史迁移。TypeScript 初始化 schema 必须与业务导入分开，绝不可直接重放 Django RunPython。 |
| [0015](../../personal_knowledge_base/migrations/0015_chunk_hierarchy.py) | parent_chunk_id 重命名 media_parent_id，另加 context_parent/anchor/header/version | 不把历史兼容 property 与文本父块关联混用。 |
| [0025](../../personal_knowledge_base/migrations/0025_encrypted_credentials.py) | 加密现存凭据 JSON；反向需要原密钥解密 | 导入保留密文和原安装密钥，跨语言校验后再按新策略轮换；不能生成新 key 后宣称导入成功。 |
| [0026](../../personal_knowledge_base/migrations/0026_personal_spaces.py) | 个人空间 owner 约束与 active 条件唯一；accounts 0001 依赖此迁移 | 原 legacy 空间不能一律改成个人空间；用户身份和所有权必须逐项保留。 |

迁移源文件共 26 个，不等于用户数据库已执行 26 个，也不等于 26 个可安全重放的步骤。

## 3. 运行路径与加密材料机制

### 3.1 数据根及源代码资源

`app_data_root()` 优先使用非空 `APP_DATA_DIR`，expanduser 后 resolve；否则运行时获取 settings.BASE_DIR。相对 APP_DATA_DIR 的解释与启动 cwd 有关，Electron 应在启动前规范成稳定绝对路径。路径 helper 本身不创建目录、搬迁或 chdir。

主库：有 `DATABASE_URL` 时走 PostgreSQL；否则 `DJANGO_DB_PATH` 优先，默认 `<dataRoot>/db.sqlite3`。SQLite 当前设置 WAL/busy timeout/synchronous NORMAL。目标 SQLite 是收敛后的实现，仍需给实际 PostgreSQL 用户提供独立只读导出流程，不能假设每用户都只有一份 db.sqlite3。

| 资源 | 源码推导路径 / 规则 |
| --- | --- |
| 持久数据与媒体 | `<dataRoot>` 下的 DB、media、staticfiles 与 cache；实际媒体根以 settings 配置为准。 |
| 前端构建、模板、manifests | 保持在源码/安装资源根，不能随 APP_DATA_DIR 改为用户可写资源。 |
| 启动配置 | `<dataRoot>/.settings/startup.json`；原子写入，环境变量优先；代理校验禁止内嵌用户凭据。 |
| 评测资源 | `<dataRoot>/.cache/eval-datasets/open_rag_benchmark/<version>/`，含 state.json、.prepare.lock、corpus、core JSON、两个 SQLite 文件；subset/full 共用底层 artifacts。 |
| 评测任务断点 | `<dataRoot>/.cache/open-rag-runs/<tenant>/<task>.json`。 |
| 评测报告文件 | `<dataRoot>/.cache/eval-reports/<tenant>/<report>.json`。 |

来源：[runtime_paths](../../config/runtime_paths.py)、[settings](../../config/settings.py)、[bootstrap](../../config/bootstrap.py)、[数据集 registry](../../personal_knowledge_base/eval_dataset_registry.py)、[评测 views](../../personal_knowledge_base/eval_views.py)、[eval reports](../../personal_knowledge_base/eval_reports.py)。以上没有读取对应用户文件。

### 3.2 CredentialJSONField 精确兼容点

当前加密覆盖 Tenant 的 web_search_config/parser_engine_config/storage_engine_config/credentials，ModelConfig.parameters、GenericResource.data 和 IntegrationConfig.parameters；其他 JSON 字段不能默认都已加密。

- 密钥材料位置：`<dataRoot>/.secrets/credentials.key`，32 字节 AES-256 key；目录创建权限 0700、文件 0600，`credentials.lock` 文件锁，O_EXCL 创建、fsync。报告只记录机制，没有读取密钥。
- 每 secret 字符串用 12 字节随机 nonce；格式 `enc:v1:` + URL-safe Base64(nonce + ciphertext + 16 字节 GCM tag)。AAD 是 **原始字典键名的 UTF-8 字节**，不是 lower-case 后的键名，也不是 JSON path。
- key 检测不区分大小写，覆盖 api_key/apikey/secret_key/app_secret/access_key/access_token/token/password/private_key/client_secret/secret/webhook_secret/public_key/authorization，或 `_api_key`、`_token`、`_secret` 后缀；递归 dict/list，仅非空字符串做密封。
- ORM 入库时加密、出库时解密；已有 `enc:v1:` 会先验证密文。缺失、长度错误的 key 或认证失败必须显式报错，不能静默生成替代 key。明文历史字段仍可读取，未来导入要区分状态。
- `public_parameters` 是递归删除 secret key，不是返回密文；renderer、IPC、日志及导出不应默认获得解密后的完整配置。
- `.secrets/django.key` 是独立 Django SECRET_KEY，配套 django.lock，并支持 DJANGO_SECRET_KEY 环境覆盖；与 credentials.key 不可互换。
- Tenant.api_key 和 AuthToken.token 当前是原值；device 的访问/刷新 token 当前只存 SHA-256 digest。这三种机制不能在导入中混为同一列含义。

来源：[credential_fields](../../personal_knowledge_base/credential_fields.py)、[models](../../personal_knowledge_base/models.py)、[settings](../../config/settings.py)。TS 兼容测试必须用临时生成 key 与固定密文样例双向验证，不得拿真实 key 做日志或测试 fixture。目标 OS keychain 方案若采用，必须先解开原密文并完成可恢复的轮换；仅改变路径会使既有安装无法解密。

## 4. 身份、空间与权限行为

当前存在三条认证通道：历史 bearer、Tenant API key、设备 cookie。解析优先级是明确 Authorization，其次 API key，无这类 header 时才使用 cookie；错误显式 tenant selector 不回退为其他身份。OAuth/OIDC 和 invitation lookup 路由中有占位实现，不能仅凭 URL 声称已经具备完整 OIDC 登录。

| 行为 | 当前要求与迁移保留点 |
| --- | --- |
| 注册/个人空间 | 原子创建 User→personal Tenant→owner membership→primary tenant；一人一个活跃个人空间。任何中间失败都回滚。 |
| legacy 空间准入 | active 用户+未删除 active tenant；admin/can_access_all 的历史能力保留；明确 membership revoked 时拒绝，只有不存在 membership 时才使用 primary tenant 兼容。 |
| 个人空间准入 | 必须 true owner + active、未删除 membership；系统管理员和 can_access_all 也不能跨入别人的私有空间。 |
| 角色 | owner/admin 可读、导出和编辑，另可 KB 删除/凭据/成员/空间管理；editor 可业务编辑但无这些管理权限；viewer 只读；API-key service 可读/导出；需要真实 user 的个人会话写操作不得用 service 代替。 |
| 历史 token | access 8 小时、refresh 30 天；disabled/revoked/user/tenant/membership 状态即时生效。 |
| 设备 cookie | access 10 分钟、idle 30 天、absolute 90 天；生产 Secure、HttpOnly、SameSite=Lax；refresh 路径 `/api/v1/auth`，token 不写原文到 DB。 |
| refresh rotation | 单次 CAS 消费旧 digest，轮换 access/refresh；旧 refresh 重放撤销该 family，其他设备仍有效；保留 consumed token 记录直至到期。 |
| logout/password | logout 当前设备、logout-all 所有设备和历史凭据；修改密码同样撤销全部凭据。 |
| CSRF | Cookie 请求即使接口 csrf_exempt、附带 arbitrary/mixed Authorization 或 multipart 仍须 CSRF/Origin 校验；不能因 Electron 渲染环境而泄露旧 HTTP cookie 接口权限。 |
| 流权限 | 绑定稳定 device family/user/tenant；约每 30 秒在下一块输出前复验；正常 refresh 不打断流，撤销/禁用/换归属会停止并关闭源。provider 卡住时当前不能在没有新块的期间立刻取消。 |
| 并发账户变更 | SQLite device_gate 跨进程文件锁+事务、10 秒有界超时；PG 用 row locks；嵌套通过 contextvar 避免递归锁。双并发 refresh 只签发一次，重放 family 撤销。 |
| 首次 setup | ALLOW_AUTO_SETUP 明确开启时才允许；同一 gate/transaction 创建唯一首个管理员；失败/超时不能留下半用户或重复管理员。 |

来源：[permissions](../../personal_knowledge_base/permissions.py)、[authentication](../../personal_knowledge_base/authentication.py)、[device_sessions](../../accounts/device_sessions.py)、[accounts views](../../accounts/views.py)、[personal_spaces](../../personal_knowledge_base/personal_spaces.py)。原 password_hash 由 Django make/check_password 使用；未加载安装环境核对具体 hasher/迭代数，TS 应按编码中的算法参数解析并用跨语言 fixture 验证，不能重新设定用户密码规避导入。

跨空间拒绝有部分接口返回 404 以隐藏资源存在性，另有 action 403；兼容测试要按具体接口固定，不把所有拒绝统一改成一种响应。

## 5. 文档生命周期、任务恢复与取消

### 5.1 持久任务契约

当前任务模式支持 local/api/worker/all-in-one。文档队列含 process_knowledge/rebuild_vector_index；评测队列含 prepare_open_rag_dataset/open_rag_evaluation，两队列独立顺序处理。API 进程只入队，评测由持久 worker 执行。`cleanup_knowledge_artifacts` 是独立持久补偿清单，不应作为未知普通任务标失败。

| 边界 | 当前实现 |
| --- | --- |
| 入队 | 先创建 pending TaskRecord，transaction.on_commit 分发；回滚后不能产生悬空执行。进程内 task ID 去重不替代持久 claim。 |
| claim | pending→running 条件更新；worker token 同时写 claimed_by 和 payload._worker_token；attempt_count 增加，lease 默认 90 秒；调用上下文保存原 token，不能从后来 DB owner“借”身份。 |
| heartbeat | 默认 15 秒，只更新仍 running、自己 owner、未取消的任务；临时 DB 错误可重试；不得给新 owner 续约。 |
| 恢复循环 | 默认 30 秒，启动首轮约 0.1 秒；常驻单例，退出 join 有界；启动索引检查仅一次。 |
| 文档恢复 | 文档有效、未软删且未 cancelled；process_knowledge 分支按 updated_at 的 90 秒 stale 判断，非统一 lease 判断；同文档只保留稳定的活跃 running 或最早 pending。 |
| 通用恢复 | 已过期 lease 完整快照 CAS（含 attempt 等）重置 pending；抵御 heartbeat/new owner/ABA 竞态；queue filter 限定扫描范围。 |
| 不可恢复类型 | 明确 failed，保存错误；cleanup manifest 排除；不能把 Python 旧 callable 名直接视为 TS 可执行函数。 |
| 调用重试 | 仅 SQLite locked 类失败做有限重试，休眠前后再校验原身份；最新 partial runtime 应保存，不能被旧初始化 result 覆盖。 |
| 业务发布 | 短事务中的条件 UPDATE 校验原 owner、running、cancel_time=NULL 和 lease 尚有效，再执行业务写入；网络/模型工作尽量在外。过期 owner 不得写 DB、checkpoint、cache 或终态。 |
| 完成 | 普通成功 completed；评测 verified=false 可保持 partial、可继续；CAS 丢失后停止，不能覆盖新任务 owner 的完成/取消结果。 |

来源：[tasks](../../personal_knowledge_base/tasks.py)、[task_recovery](../../personal_knowledge_base/task_recovery.py)。目标可以调整内部队列实现，但并发身份、持久状态、恢复和取消的可见效果是必须保留的契约。

### 5.2 文档与清理

文档处理包括读取、分块、多模态、embedding、图、postprocess、Wiki；原始图片 OCR/caption 可产生可检索图片 chunk。图/Wiki 作为可选阶段存在独立警告/降级，不应为了 Python 辅助缩小而删除它们。metadata 含 effective chunk config、diagnostics、生成问题/摘要/提取字段、图数量和 Wiki 状态。

- 上传按文件 SHA-256+原名+KB 活跃条件去重；重复上传返回成功，task_id 为空；存储写入与 DB 入队失败需回收文件。不能把“没有 task_id”误报失败。
- reparse 原子重置状态、保存 processing overrides、清理 pending Wiki op 再 enqueue；新 parsing job 要隔离旧尝试的结果。
- 用户取消把文档 parse_status 置 cancelled，并取消对应 pending/running TaskRecord；应阻止迟到 model/provider 结果发布。
- 普通删除先 retire/soft delete，停止处理，清 chunk/index/image/Wiki/graph 及任务缓存；原文件清理需按现有不同路径区分，不统一声称每种删除都物理删除原文件。
- duplicate cleanup 是另一规则：按 tenant+KB+规范化 SHA-256 分组，排序偏好未删、completed、创建早的记录，**不依赖同名**；执行时重新验证计划快照。事务内 Wiki retract/graph 清理后创建 artifact manifest、删除 DB，on_commit 清扩展索引和文件；失败 manifest 可重试，共享图片/原文件仍被引用时不删。
- KB copy 当前复制配置，不复制内容，task_id 为空。文档 move 同 tenant，重绑文档及其 chunk/image 后更新索引、图与 Wiki；图不可用时不能静默完成需要严格清理的 live move。

来源：[knowledge views](../../knowledge/views.py)、[document_processing](../../personal_knowledge_base/document_processing.py)、[knowledge_cleanup](../../personal_knowledge_base/knowledge_cleanup.py)。文件补偿必须迁入 TS；Python parser/OCR 只返回输出 artifact 清单，不自行决定删除业务文件或写任务状态。

### 5.3 当前待核实的发布缝隙

这些是源码阅读发现的风险，不是本次证明已经发生的数据损坏：

- index_chunk 有删除旧 FTS/vector、写 FTS、远程 embedding、写向量和 chunk seq 的多个步骤；文档 workflow 的 progress/ensure_active 不等于每一步都处于 owner fence 内。
- graph save、Wiki 部分写操作与外部副作用不在同一 owner 条件更新内；不能因为当前任务最终态有 CAS，就宣称所有中间结果都已 fenced。
- move/cleanup/Wiki reducer 部分流程会在事务中调用 Neo4j 或 fallback LLM，SQLite 锁持有时间不可预测；目标将外部计算与短事务发布分开，同时保存可恢复补偿状态。
- DB 与 filesystem atomic rename 不是分布式原子提交；需要通过 version/hash/manifest 和恢复校验处理 crash window。

目标验收必须直接制造 owner transfer/cancel/crash 时序，不能仅覆盖“任务正常完成”。

## 6. 事件、消息、流和 span

### 6.1 SessionEvent 与 Message

事件类型白名单共 18 类：session/started、turn/user-message、turn/assistant-created、turn/completed、turn/error、retrieval/search、retrieval/result、agent/iteration、agent/thinking、agent/actor、tool/call、tool/result、llm/call、llm/retry、context/compacted、request/header、maintenance/step、observability/trace-linked。未知类型不记录；payload 先序列化冻结。

追加事件以 session.event_seq CAS 增量和 SessionEvent 插入同事务，最多有限次 SQLite busy 重试；失败时 seq 与行一并回滚，记录失败不阻塞主营业务。`fold_events` 当前 FOLD_VERSION=3，按 request/actor/tool 还原轨迹及 token；已有成功 llm/call token 时不再重复加入 thinking fallback 的 token。trace linked 是本地声明状态，不代表远端 trace 已验证。

`rebuild_session_messages` 只重建存在 user event 的终态 turn，逐 turn 原子替换；不完整或旧无轨迹消息需保留。Message 当前仍保存业务事实，不能把事件日志注释理解成可以丢掉所有 Message 再任意重建。重建会创建新 Message ID，可能影响普通 ID 引用；导入优先原样保留两者。

### 6.2 Stream 与终态

`StreamManager` 有内存缓存，但 StreamState/StreamEventRecord 支撑重启 hydrate 和按 offset 续传。append 在事务内计算 DB event count 为 offset 并利用 unique(message,offset)；新事件与 completed/error 终态同步更新，然后更新内存。取流会从 DB 刷新。最终内容、refs/steps/duration 单独持久化。

终态更新 Message 采用 is_completed=false 条件，迟到失败不得改写成功内容。error payload 带 assistant_message_id/content/done，若已完成则返回已完成 message。

当前 TTL 默认 1 小时，5 分钟清理按 created_at 淘汰，包括长运行流；这是现有长任务风险，需测试明确预期后调整，不能把所有 streams 视作永不需要导入的缓存。StreamState、StreamEvent 的普通 session/message 字段也需要显式删除策略。

### 6.3 Processing span

本地 KnowledgeProcessingSpan 是处理可观测数据，Langfuse 是可选 mirror；默认外发隐私策略不带真实标题/完整文档。root/span 状态、开始结束、duration、输入输出/metadata、错误和父关系必须迁移。

当前 tracker 的 root attempt 有复用 attempt=1 的行为，已有回归检查 reparse 关闭自己的新 root，并保留首个已完成 root 的 finished_at；stage update_or_create 依赖 knowledge+attempt+name+kind，DB 没有对应唯一约束，部分子 span 使用默认 attempt。迁移不能自行把全部 attempt 归并成“最新一次”而丢掉历史。

来源：[event_log](../../personal_knowledge_base/event_log.py)、[stream_manager](../../personal_knowledge_base/stream_manager.py)、[stream_protocol](../../personal_knowledge_base/stream_protocol.py)、[span_tracker](../../personal_knowledge_base/span_tracker.py)。

## 7. 检索、向量维度与图谱

### 7.1 检索契约

| 阶段 | 当前行为与迁移条件 |
| --- | --- |
| searchable scope | text/image_ocr/image_caption，chunk enabled/未删、doc enabled/未删、KB 未删；tenant/KB/doc 重复字段必须一致。parent_text 不直接作为普通向量候选。 |
| keyword | FTS5 BM25，tenant/KB scope 在 LIMIT 前限制；必要时 LIKE 降级。不能先取全局 top-N 再过滤。 |
| vector | sqlite-vec L2；扩大候选窗口，初始 max(limit*8,64)，按 4 倍扩展直到 scoped 候选足够或扫完；禁止外空间高排名吞掉本空间候选。 |
| fusion | RRF k=60；得分约为 1/(k+rank)，排序含稳定 tie-break；不是简单相加 BM25 原始负分与 distance。 |
| rerank | 保持最终 rerank 顺序与 provenance；模型缺失/失败有显式降级标记，不能报告“实际启用”而走 keyword。 |
| parent context | text context_parent_id 与 media_parent_id 区分；同 tenant/KB/doc 父子校验、源 offset 有效、合并同父命中、处理已编辑 siblings、限制上下文字符，保留命中与排序来源。 |
| chat retrieval | keyword expansion、graph 独立 cohort、短块窗口扩展、parent context、MMR 多样性与 graph/document 交错；不按 graph=1 与低 RRF score 全局混排。 |
| repeated provenance | graph 命中已有文档 chunk 时给文档结果附加 graph provenance，保留文档最终排序，不重复塞满上下文。 |
| model space | KB/document embedding override 要在本次 query 内 coherent；混合模型空间不可比较时应明确降级；模型或 dimension 变化使索引 needs_rebuild。 |

搜索 `_rowid(chunk_id)` 是 SHA-1 前 **15 个十六进制字符**转整数，最多 60 bit，超过 JS Number 精确范围。TS DB adapter、JSON/IPC、导入映射须使用 bigint 或十进制 string；不能通过 Number 往返后改变向量定位。碰撞处理现有机制也应在新 schema 验证，不能假定 hash 就天然唯一。

rebuild 以 batch=32 按 tenant+有效 embedding 模型分组，清 stale FTS/vector；未全成功不应 ready，全失败抛错，取消不应该发布 ready。当前全局 search_index_meta signature 从单个配置推导，vec 表未对每向量保存独立模型空间；推荐目标索引显式带 tenant/KB/doc/model signature/dimension/algorithm version 的一致版本，不把不同模型仅因维度相同就混检。

来源：[search](../../personal_knowledge_base/search.py)、[parent context](../../personal_knowledge_base/parent_context.py)。parent_context 的渲染窗口辅助函数仅结构核查，当前文本编辑/Unicode offset 算法需要后续完整阅读与 fixture 锁定。

### 7.2 Graph

Neo4j 为可选服务，由全局 IntegrationConfig 动态配置，signature 改变时关闭并重建 driver；driver 可创建不等于已证明服务连通。当前节点 label 基于 KB id、节点唯一性基于 name+文档 kg，边类型 sanitize，chunk provenance 合并用 APOC。

实体与关系由 LLM JSON 批量抽取，归一化/去重；关系强度和 PMI 等参与图耦合。Chunk.relation_chunks 保存 direct/indirect，间接关联按乘积折减，只是图派生摘要。graph query 的完整图数据需额外导出，目标建议 SQLite graph_nodes/graph_edges/graph_node_chunk_refs，保留 tenant+KB+knowledge namespace、方向、类型、属性、权重和来源；TypeScript 编排图抽取、查询与删除。

当前 graph 查询主路径会 hydrate 检查 scope；`expand_relation_context` 检查较弱（tenant/enabled），与完整 deleted/KB/doc 验证不完全一致。live delete/move 的图删除需严格失败；retired 文档可容忍 ServiceUnavailable/SessionExpired，但其他错误不能全部吞掉。目标先锁定用户可见行为，再补一致权限校验，不以关图方式避开移植。

来源：[graph_rag](../../personal_knowledge_base/graph_rag.py)、[neo4j_connection](../../personal_knowledge_base/neo4j_connection.py)。没有连接实际 Neo4j 或读取用户图数据。

## 8. Wiki

Wiki 启用与图启用是独立配置。每 tenant+KB scope 的 WikiPendingOp 为持久 ingest/retract 操作，默认批处理 5，dedup_key 合并最新操作，关闭 Wiki 时仍需处理 retract。当前没有独立可恢复的 Wiki TaskRecord worker；它随文档 workflow/接口调用运行，pending op 的 claimed_at/fail_count 字段不代表已经实现完整 owner lease claim。

内容 map 阶段按 focused/standard/exhaustive 限候选，slug 允许中文；页面类型、别名、source/chunk 引用、每文档 contributions、版本、目录及 soft-delete tombstone 保留。生成/merge 可 LLM 批处理和 template fallback。删除或重解析文档撤回该文档贡献，空页清理；软删 tombstone 防自动重建同 slug。

`[[slug|label]]` 关系有自动 crosslink/backlink 与死链清理；最长标题/别名优先，保护已有 Markdown/code/images/links/headings。目录 slash slug 必须按 Wiki 约定解析。索引页会自动生成，但在 visible list/stat/graph 中排除。

页面、目录、统计、最近日志、connectivity 排序图和 ego graph 都是有效能力：overview 默认 limit=500、最多 2000；ego depth 1—3；日志最多 100。lint/issues 目前部分返回空/已解决占位，不把占位当成完善审核能力。

当前 Wiki folder collection POST 没有与 folder detail 相同的 WIKI_WRITE action 检查，是源码发现的潜在权限缝隙。目标须统一域权限，并将旧测试矩阵补到 folder create；这不是已证明生产被越权的结论。

Wiki reducer/index/cleanup 与 delete op 部分在同事务；fallback LLM 可能仍进入事务，日志写入在另一个边界。目标以 scope revision 和 task fence 做短事务发布，保持 contribution 撤销和链接一致性。

来源：[wiki_ingest](../../personal_knowledge_base/wiki_ingest.py)、[wiki_page_generator](../../personal_knowledge_base/wiki_page_generator.py)、[wiki views](../../wiki/views.py)。

## 9. 评测、断点与报告

### 9.1 数据集与运行配置

GenericResource 的 rag_eval_questions/datasets/testsets/runs 是 tenant 资源。evaluation_v2 候选包含 question/reference answer/ground truth、source evidence、文档版本和审核状态。人工审核仅改状态，自动审核验证证据，sample 约 10% 且固定 seed。发布只能包含有效 approved 候选、同 KB，增加版本并对标准化内容 hash；发布后不可原位修改或再审核。

运行来源既有 published tenant dataset（版本/hash/文档指纹），也有公共 Open RAG immutable registry。公共 full 为 3045，subset 为 **180**；原 `_100` alias 仍映射 180，subset/full 共用固定 revision 的 downloads/index。不能把旧 alias 的数字当作实际题量或删掉兼容入口。注册表校验 subset query ID 数量、唯一性与 digest。

运行要独立保存 answer/judge 模型、keyword/vector/hybrid、rerank flag、primary/comparison chunking strategy。现有策略包含 fixed_window、recursive、auto_parent_child、semantic_parent_child、heading、layout、record；不能因目标 Python 仅 parser/OCR/Ragas 就把 semantic chunking 编排留在 Python。

前置校验是实质契约：向量/混合/语义策略缺 embedding、开启 rerank 缺模型、缺 answer/judge 等返回 422；坏 JSON 返回 400。effective pipeline 应记录实际模型/维度/L2/RRF/index version、运行配置与 source fingerprint；请求设置和实际降级必须不同字段。

### 9.2 状态不能压成一个 success 布尔

| 维度 | 当前意义 |
| --- | --- |
| task run status | pending 对外可 queued；running/completed/partial/failed/cancelled，决定是否运行/恢复。 |
| verification status | verified/degraded/unverified/failed，表示评测证据、阶段和得分质量，和 task 已结束不是同一个概念。 |
| freshness | current/stale/unknown，按 dataset/document hash/version 比较；不能以文件年龄决定。 |
| progress | question processed/usable/invalid、coverage、phase/stage、ETA；部分结果不能假装完整题量。 |
| identities | task_run_id 与 artifact report_id 是不同 ID；dataset requested alias 与 normalized/effective id 也分开。 |

来源：[eval views](../../personal_knowledge_base/eval_views.py)、[eval reports](../../personal_knowledge_base/eval_reports.py)、[registry](../../personal_knowledge_base/eval_dataset_registry.py)。

### 9.3 恢复与持久化

retrieval→chunking→answer generation→Ragas 按 stage/per-question 保存 checkpoint，配置指纹、dataset/document、judge identity 匹配后复用。不合法 answer、空 answer、NaN/非法 score、degraded retrieval/chunking 的相关下游需要重新打开，不能因为 stage 曾 completed 就跳过。

checkpoint 保留 ID/provenance/阶段信息与生成答案，但去掉 query/question/source contexts 等；生成答案仍可能包含源事实，不能因“不存 context”就把文件标成完全无敏感内容。isolated strategy index 不在 checkpoint 中保存真实 context，继续时需要再 hydrate/retrieve。

checkpoint 使用唯一临时文件、0600 和 atomic rename，在 DB owner publish fence 内操作，但这不构成 DB+文件两阶段提交；crash 恢复需重新校验 hash/version。过期清理默认 7 天，只清终态、过期且 mtime/DB 状态仍符合的文件；active/未知任务文件保留。resume 仅 partial/failed/cancelled，重用原任务 ID、重置 cancellation/error/claim/lease，保留可用 checkpoint。

公共 prepare 还有 `.prepare.lock` 跨进程互斥：state.json、core JSON hash、corpus git blob OID、index PRAGMA integrity_check、metadata revision/manifest/model signature 均参与 ready 校验。index 写 `.sqlite3.part`，成功后 replace；embedding 以 model_signature+content_hash 断点 reuse。下载/索引准备当前直接写 SQLite，必须迁入 TS，不能归为 Ragas Python helper。

### 9.4 指标与报告

Ragas 正式指标为 faithfulness、answer_relevancy、context_precision（有无参考答案走不同 precision metric）。若旧结果含 context_recall/correctness 默认 0，不表示当前实际运行了对应指标。无效输入不调用 Ragas；非有限得分记 invalid；API/模型失败明确暴露且保留 partial，不用简单字符串指标伪装正式 Ragas。

确定性检索/分块评测使用 source evidence span、document hash 的 Hit@10/MRR@10/Recall@20 等；模板/未验证样例返回 metric=null/unverified，不能靠旧 chunk ID 当真实标注。原 baseline 有自己的简单分数融合路径，比较时必须保留定义差异，不能悄悄让 baseline 和新算法变成同一实现。release gate 涉及相对提升与 recall 非回退，需后续完整阅读 chunking_eval 的具体阈值实现。

每 tenant 的 DB GenericResource 报告与文件报告合计仅保留最新 **50** 份。报告 sanitizer 剥离 context/question/query/path/answer 等源文本并删除/redact 凭据键，保留 git commit/time、dataset/model/pipeline provenance、指标。report download tenant scoped；删除历史 report 时保留 TaskRecord，但 pointer 标 unavailable、download URL 置空。

当前 `_attach_task_report_pointer` 另行写 task result，未体现相同 owner fence，需真实竞态测试。不能只验证报告文件原子写就宣称所有 task pointer 更新安全。

来源：[rag_eval](../../personal_knowledge_base/rag_eval.py)、[retrieval_eval](../../personal_knowledge_base/retrieval_eval.py)、[ragas_adapter](../../personal_knowledge_base/ragas_adapter.py)、[eval_reports](../../personal_knowledge_base/eval_reports.py)、[open_rag_benchmark](../../personal_knowledge_base/open_rag_benchmark.py)。

## 10. 业务入口到 TypeScript 模块的建议契约

### 10.1 路由盘点的边界

URL 文件源码声明数：accounts 37、models_config 11、knowledge 29、wiki 12、PKB 43、chat 17、agent 82，共 **231 条应用 routing declaration**；config 另有 24 条根声明（含 include/静态资源等）。这是源码 path/re_path 声明数，不是唯一 API 数、HTTP 方法数或已完整实现功能数。

| 路由来源 | 此报告识别的能力 | 目标 owner |
| --- | --- | --- |
| [accounts](../../accounts/urls.py) | register/login/refresh/logout、设备、profile/preference/password、用户/空间/成员、setup及认证兼容入口 | identity + access-policy |
| [models_config](../../models_config/urls.py) | 模型管理、default/fallback/context window、credentials、model usage | model-registry + model-runtime + credential-vault |
| [knowledge](../../knowledge/urls.py) | KB/文档 upload/parse/cancel/download/delete/move/copy、chunk/image/processing 数据 | knowledge + processing + artifacts |
| [wiki](../../wiki/urls.py) | 页面/目录、链接/图、状态/stat/log、部分检查占位 | wiki |
| [PKB](../../personal_knowledge_base/urls.py) | 检索、graph、评测数据集/运行/报告、任务状态与其他平台资源 | retrieval + graph + evaluation + jobs |
| [chat](../../chat/urls.py) | 会话/消息/流/上下文与轨迹相关入口 | conversation + event-journal + stream |
| [agent](../../agent/urls.py) | agent/tool/channel/MCP/配置等多类入口 | agent-runtime 等；细节由 agent 域专项基线审计，本报告未读完整 views |

现有 HTTP response DTO、错误码、SSE response_type/offset 与模型引用格式需要在边界冻结。Electron IPC 可以使用明确 command/query/event，但不能在迁移中删掉已用入口、输出或配置类型。

### 10.2 建议的模块输入输出

以下是待实现的契约建议，不是声称仓库已有这些 TypeScript 类型或选定某个 SQLite 驱动 API。安装依赖类型、Electron/native addon 打包及扩展加载接口需由实施阶段核对实际版本。

| 模块 | 推荐输入与输出 | 持久化和边界 |
| --- | --- | --- |
| data-owner / repository | 初始化/transaction/read snapshot/schema version/import manifest；typed rows 与 JSON opaque extras | 唯一 SQLite 写 owner 在 Electron main 或其明确管理的 TS service；renderer/Python 无 DB handle；foreign_keys/busy/WAL 策略统一。 |
| runtime-paths | sourceRoot/dataRoot 配置→稳定绝对 DB/media/cache/secret/artifact 路径 | 启动前解析，区分安装资源与用户数据；路径与复制状态可审查，不自动删除旧目录。 |
| credential-vault | secret field read/write、decrypt legacy、public-config projection；配置引用/脱敏 DTO | 保留原 enc:v1/AAD；只在主进程解析密钥，IPC 不发原 key/解密全量对象；失钥显式阻断。 |
| identity | register/login/refresh/revoke/change-password→principal、device DTO、token response | digest rotation/family revoke 原子；导入旧 hash/token；个人空间创建同事务；HTTP兼容与IPC身份分开。 |
| access-policy | principal + target scope + action→allow/deny reason/visibility | 所有域共享 owner/membership/private policy；task/report/artifact也 scope；不依赖 renderer 隐藏按钮。 |
| jobs | enqueue/claim/heartbeat/cancel/resume/recover；Claim(taskId,ownerToken,attempt,leaseUntil) | publish(claim,write) 必须 DB 条件原子；所有进度/终态/派生索引/checkpoint pointer 使用原 claim；两队列独立。 |
| processing | document+effective config+claim→parsed blocks/chunk plans/画像/summary与阶段状态 | parser/OCR 辅助 JSON 接口只接 task input path/options，返回 blocks/artifact refs/errors；业务分块、embedding、publish和文件归属由 TS 控制。 |
| artifacts / cleanup | ownership manifest、expected hashes、path refs→validated artifacts/cleanup outcome | 可恢复 file publication/delete manifest；共享引用不删，DB commit 后执行补偿；不允许 Python 对主 DB 写。 |
| event-journal | append(session,request,event type,payload)→seq；fold(request)→versioned trajectory | seq CAS 与 event 同事务；保留 message facts，异常 logger 不阻断业务；命名/版本兼容。 |
| stream | message+session+principal、append(event)、read(afterOffset)、finish(result/error) | DB事件/offset可恢复；终态不可覆写；refresh稳定、revocation止流；session cleanup显式级联。 |
| spans | knowledge+attempt+parent/span state→local span DTO | 本地权威、外部 observability 可选；输出脱敏、禁止把旧 attempt 覆盖为最新。 |
| retrieval | query+tenant/KB/doc scope+model space+strategy/rerank→ordered hits+matched child/provenance+effective pipeline/degradation | scope在候选阶段限制；L2/RRF/MMR与顺序可比较；60-bit rowid用bigint/string；index ready以一致generation确认。 |
| graph | extract/query/expand/delete(scope,claim)、nodes/edges/provenance DTO | SQLite完整节点边及namespace；graph/relations及派生chunk refs短事务发布；支持图离线与严格删除语义。 |
| wiki | enqueue/reduce/retract/edit/folder/link/graph(scope,revision,claim) | contributions/tombstone/link/index一致发布；LLM在事务外；pending op持久claim或等效唯一owner。 |
| evaluation | dataset review/publish/version、prepare、run/cancel/resume；阶段结果与verification/freshness | 公共和tenant数据隔离；checkpoint/version可恢复；评分辅助仅DTO；报告与任务identity分开。 |
| ragas-helper | ephemeral judge/embedding config + question/answer/context/reference rows→progress、finite metric rows、invalid/error metadata | Python只做Ragas计算，不import Django业务model、不读写SQLite、不保存真实源语料或credentials；TS负责发布状态/文件/日志。 |
| reporting | report schema/provenance+tenant→sanitized artifact+report id/download pointer | 50份保留策略、tenant scope、hash/freshness、pointer撤销；late owner无法覆盖新report。 |

推荐公共 DTO 中保留 `schemaVersion`、`tenantId`、`requestId`、`taskId`、`attempt`、`ownerToken`（仅服务内部）、`modelSignature`、`indexGeneration`、`sourceVersion` 和有效配置。IPC仅公开允许的数据投影；给 Python helper 的凭据可短期内存传入，但不得落日志、checkpoint 或持久配置文件。

## 11. 必要真实回归与迁移验收

现有测试是迁移需求证据，不是本报告运行通过的证明。四个全文读取测试还包含 mock 场景；其断言应迁入目标测试，但不能替代真实 SQLite、跨进程和 Electron 验证。

| 优先级 / 用例 | 必须制造的真实情境与断言 | 现有证据 / 后续扩展 |
| --- | --- | --- |
| P0 导入完整性 | 临时已迁移 SQLite fixture 包含31表、soft-delete、opaque resource、所有逻辑IDs/UTC/null/JSON/大整数；导入后逐表数量/hash/约束、文件引用和密码登录一致；首次/二次导入幂等，原文件未变 | [迁移图完整性](../../tests/test_migration_graph_integrity.py)、[凭据迁移](../../models_config/test_credential_migration.py)；需增加跨语言export/import fixture。 |
| P0 破坏性旧migration | 从current fixture导入TS，强制含文档/Wiki/任务；确保不会调用0004/12/13 purge、不会重复dedup或删除文件 | 历史migration源码；必须专门检查import执行路径。 |
| P0 加密跨语言 | 临时32-byte key，嵌套dict/list、大小写key、非secret/空值、已有ciphertext、坏tag/缺key；Python加密→TS解密与反向；不会错用django key，日志/IPC不含秘密 | [凭据迁移测试](../../models_config/test_credential_migration.py)仅名称/结构核查；真实key未访问。 |
| P0 个人空间隔离 | 两用户、legacy空间、personal owner、system admin/can-all、revoked membership；读/写/搜索/graph/wiki/report/task/artifact均不能跨私有空间；管理员也不可绕过 | [个人空间](../../personal_knowledge_base/test_personal_spaces.py)、[权限矩阵](../../personal_knowledge_base/test_permission_matrix.py)、[Wiki子行租户](../../wiki/test_tenant_child_rows.py)。 |
| P0 refresh并发与撤销 | 同一临时DB，两进程同时refresh同旧digest；仅一次签发，重放只撤family；其他设备有效；revoke/password/logout-all与gate wait竞态、真实cookie CSRF/Origin | [device sessions](../../accounts/test_device_sessions.py)。后续保留真实HTTP兼容及Electron隔离IPC。 |
| P0 owner抢占与迟到发布 | 真实SQLite两个worker：A网络返回前停heartbeat、B恢复claim；放行A，A不能写chunk/FTS/vector/wiki/graph/report/checkpoint/result/cache、续lease或终态；B仍可完成 | [task ownership](../../personal_knowledge_base/test_task_ownership.py)、[business publish](../../personal_knowledge_base/test_business_publish_fencing.py)、[task recovery](../../personal_knowledge_base/test_task_recovery.py)。 |
| P0 cancel全边界 | 在parse、embedding、graph、Wiki、answer/Ragas等待期间cancel；task/doc/stream终态一致，迟到response不发布；reparse/resume新attempt不被旧attempt删除 | [任务恢复](../../personal_knowledge_base/test_task_recovery.py)与[任务归属](../../personal_knowledge_base/test_task_ownership.py)。 |
| P0 crash恢复 | 真正终止TS service进程，在claim后、FTS前后、artifact rename后、DB提交前后、report pointer前后重启；lease恢复/补偿、索引generation、checkpoint hash正确，无幽灵completed | [worker lifecycle](../../personal_knowledge_base/test_task_worker_lifecycle.py)。增加SIGKILL/重启测试而非仅mock时间。 |
| P0 native索引 | 在Electron目标平台真正加载FTS5和sqlite-vec；384/1024与模型dimension切换、向量已存在、坏维度；FTS和L2实际可查询；60-bit rowid>2^53往返不丢精度 | [search correctness](../../personal_knowledge_base/test_search_correctness.py)、[索引实现](../../personal_knowledge_base/search.py)。具体平台依赖与版本需实施核对。 |
| P0 scoped候选正确 | 大量外tenant/外KB高分候选占满初始窗口；本scope仍得正确topK；deleted/disabled/错tenant或KB的child拒绝；rerank顺序、graph provenance、RRF稳定 | [search correctness](../../personal_knowledge_base/test_search_correctness.py)。BM25、vector必须真实扩展执行。 |
| P0 Python不写业务DB | 启动parser/OCR/Ragas helpers时不提供DB路径/handle；覆盖成功、失败、超时、取消，监控其SQLite open/write与Django imports为零；TS记录结果 | 目标新增架构验收；当前Python评测index写入是需移出的确定代码路径。 |
| P1 parent编辑与Unicode | Chinese/emoji/组合字符、同父多child、edit重叠/删除、无效source offset、media parent、cap窗口；provenance与rerank顺序不丢失 | [parent context](../../personal_knowledge_base/test_parent_context.py)、[chunking eval](../../personal_knowledge_base/test_chunking_eval.py)。需完整读取offset算法后固定fixture。 |
| P1 原始图迁移 | 从临时Neo4j或导出fixture迁nodes/edges/属性/方向/refs到SQLite；entity/ego/expand/strength可比，rename/delete/move只作用本scope；断网退化与live严格删除可见 | [graph availability](../../personal_knowledge_base/test_graph_availability.py)；原Neo4j数据未读取。 |
| P1 Wiki贡献与权限 | 两文档共享一页，reparse/delete其一只撤其贡献；tombstone阻止regen、slash slug/别名/Markdown保护、index排除、backlink/图/stat正确；folder POST权限矩阵 | [Wiki links](../../personal_knowledge_base/test_wiki_links.py)、[Wiki tenant child](../../wiki/test_tenant_child_rows.py)。 |
| P1 文件补偿 | 删除重复文档时注入file/index失败保留manifest，重启重试；共享路径不删；计划后文档变动不删除；普通删除/move与originalfile语义各自验证 | [knowledge cleanup](../../personal_knowledge_base/test_knowledge_cleanup.py)；本次完整读取cleanup实现，测试仅发现未全文核对。 |
| P1 Event CAS竞争 | 真实SQLite两个connection抢event_seq，插入失败不增seq；turn fold3字段/token不双计；repair失败保留Message，旧无轨迹/未完消息不丢 | [event contention](../../personal_knowledge_base/test_event_log_contention.py)、[轨迹测试](../../tests/test_session_trajectory.py)。 |
| P1 SSE续流 | 真服务断线重连与重启hydrate，offset有序无重复，终态Message不被迟到错误覆写，device revoke在下一块停止并close；长于TTL流预期明确 | [device stream guards](../../accounts/test_device_sessions.py)、[stream persistence](../../personal_knowledge_base/test_stream_persistence.py)。 |
| P1 Span尝试隔离 | attempt A关闭发生在B开始后，不改B；root/stage/subspan关系、失败和时长保留、Langfuse停用仍本地可用 | [span attempts](../../personal_knowledge_base/test_span_tracker_attempts.py)。 |
| P1 评测状态/继续 | 真实小fixture检索→chunking→answer→Ragas helper，制造空answer/非法score/断线，partial仍可resume；model/dataset变动拒旧checkpoint或重开相应阶段；task/verification/freshness不混 | [ragas loop](../../personal_knowledge_base/test_ragas_evaluation_loop.py)、[task recovery](../../personal_knowledge_base/test_task_recovery.py)、[dataset sources](../../personal_knowledge_base/test_eval_dataset_sources.py)。 |
| P1 公共准备与不重计费 | 钉manifest最小fixture，下载hash/OID错误不ready；两个prepare互斥；embedding batch crash后复用合法cache；subset/full/100alias身份/题数正确；corruptindex检测 | [open benchmark](../../personal_knowledge_base/test_open_rag_benchmark.py)，此测试未全文读取。 |
| P1 报告历史/隐私 | 同tenant DB+文件混合超过50，保留准确；另一tenant不影响；reportid/taskid不同、删除pointer失效、freshness按hash；报告/log无源文/secret | [eval reports](../../personal_knowledge_base/test_eval_reports.py)。 |

至少一组 small golden dataset 应同时通过旧实现与 TS 的真实检索/分块/graph/Wiki/评测，比较结果集合、最终顺序、引用、范围、分数容差、状态与用户可见输出。确定性阶段固定 seed/模型响应；模型外部调用通过真实受控协议端点返回延迟/错误，而不是把整个 domain service mock 成成功。Ragas 如使用真实远程模型，配置与费用应独立于默认回归；本报告未发起任何调用。

## 12. 数据迁移交付门槛与未决事项

1. 以实际安装的 schema/version 做只读 manifest，记录实体、逻辑关联、扩展定义/维度、SQLite/PG来源、Neo4j与文件清单。不得查询或输出 secret明文；密码/token类字段只计数量与结构校验。
2. 从一致快照导出；运行中的SQLite不能只拷贝db主文件而漏WAL。原路径/DB/密钥/媒体/持久缓存保持可恢复，不覆盖旧安装。
3. TS创建新schema并导入保留ID的实体，恢复循环在导入验证完成前不执行；不可恢复旧任务要明确记录，不能将未知任务静默标为 completed。
4. 主SQLite一写owner，导入、任务、模型usage/rate-limit、graph/Wiki/eval索引及report pointer同属TS。Python helper不读写主库或副索引库。
5. 原密文跨语言解密成功；原passwordHash、token/digest、personal owner、legacy membership行为校验通过；UI/IPC仅允许公开投影。
6. 实体/文件/图/索引/报告数量与摘要校验，所有丢失/异常必须具体列出；需要重建的索引在完成前保持needs_rebuild，不能用“缓存可重算”掩盖收费向量或历史报告的消失。
7. 第11节P0真实回归通过，再允许切换；用户未要求提交，本次不进行git commit。发布/升级/删除旧数据另按明确授权执行。

未决：实际数据规模和旧异常、SQLite addon/vec平台二进制与打包支持、Django password hasher真实配置、Python parser/OCR协议细节、完整chunking/parent Unicodeoffset实现、所有agent/channel/MCP资源的业务格式、现有StreamManager长TTL风险、Neo4j导出兼容及PostgreSQL导出实现。它们需要后续源码/依赖与fixture验证，不能由这份只读基线推定已经解决。
