# Startup 与 dormant 后端覆盖补审（2026-10-10）

范围：完整读取当前 Startup 表单、field_support DTO、相关旧路由和 handler，对照 TS application/adapters/AuthService 及前端绑定。未操作 GUI、未发模型或外部服务请求，未改旧 Django、共享 application/routes、依赖或构建产物。原 `db.sqlite3` 仅按本次授权做只读计数/存在性检查；没有查询用户正文、凭据值或解密。

## Startup 提示纠错已完成

后端 [StartupConfiguration](../../packages/core/src/settings/startup.ts) 的 `field_support` 只有 `task_workers/sqlite_timeout/model_timeout/log_level` 为 `applied:true`。debug、allowed_hosts、cors_origins、model_retries、no_proxy、proxy_url 仍可保存，但不作用于当前 native runtime。特别是 model_retries，未知付费结果不会自动重放；allowed_hosts/CORS 不能被误认为 TS HTTP 的安全策略。

[SystemConfiguration](../../frontend/src/views/settings/SystemConfiguration.vue) 保留所有输入项，逐项显示实际 `applied` 状态及后端原始 `reason`；缺失支持 DTO 显示“当前运行时未提供支持状态”。启动保存提示区分“支持字段将在重启后生效”与“当前生效值未改变”，两者都说明保留字段不参与当前运行。没有新增运行支持，其他设置行为未改。

- [回归](../../frontend/src/views/settings/system-fields.test.mjs) 编译真实 SFC script/template 并渲染：改源前新增两项分别因没有 reason、错误“已保存并生效”提示失败，原六项通过，exit 1。
- 改源后两个 Settings 组件相关测试：14/14，exit 0，1.239 秒。
- `frontend/npm run test:unit`：195/195，exit 0，22.386 秒。这是组件/前端单元验证，不是 GUI 或厂商验收。
- 真实 SFC script + inlineTemplate 与实际 API/client 依赖 TypeScript 语义检查：0 diagnostics；临时脚本已删除。限定文件 `git diff --check` 通过。
- B Langfuse 未统一 freeze；本轮没有运行 Vite build 或写 frontend/dist，协调者应在全源冻结后统一构建。
- SystemConfiguration.vue SHA-256：`36de372f25d0021b37e065099e1ad4b011e2039dc6c28390f76c6cf3152deab6`。
- system-fields.test.mjs SHA-256：`e3d1d3bdec11bbbf1855914231ad153550cee2fbd2c81cd8e2e8c328e6019ce5`。

## Dormant 路由逐项分类

`/api/v1/` 前缀省略。依据完整 [accounts URLs](../../accounts/urls.py)、[agent URLs](../../agent/urls.py)、[旧公共 embed URLs](../../personal_knowledge_base/urls.py)、[root URLs](../../config/urls.py)；handler 分开查 [accounts/views](../../accounts/views.py)、[agent/views](../../agent/views.py)、[personal_knowledge_base/views](../../personal_knowledge_base/views.py)。agent URLs 的 generic 来自 agent/views，accounts invitation generic 来自 personal_knowledge_base/views，不能视为同一个安全实现。

TS 对照 [application](../../packages/core/src/application.ts)、[adapters](../../packages/core/src/adapters/agent-routes.ts)、[AuthService](../../packages/core/src/auth/index.ts)。未注册路径进入 application 的确定 `404/not_found` 分支；下面“缺”是源码证明，未启动新服务逐条打 HTTP。当前 [API](../../frontend/src/api/index.ts) 与 [Router](../../frontend/src/router/index.ts) 没有消费下列 dormant 管理/分享/邀请路径；完整 frontend/src 字符串检索也无调用。`auth/me` 的 memberships 与现有认证权限仍真实保留，不等于管理接口已恢复。

| 路径/族 | 旧实现真实程度 | 当前 TS | 现 UI 消费 |
| --- | --- | --- | --- |
| `agents/:id/embed-channels`；`embed-channels`、`embed-channels/:id` | 租户 scoped GenericResource 实际增改查、软删除；前者并未按 agent ID 做数据过滤 | 缺；通用数据导入不提供业务 CRUD endpoint | 无 |
| `embed-channels/:id/rotate-token` | 真实生成并持久化新 token，需要凭据权限 | 缺 | 无 |
| `embed-channels/:id/preview-session` | 真实创建 Session（不是完整渠道公开流程验收） | 缺 | 无 |
| `embed-channels/:id/stats` | 固定 sessions=0/messages=0/last_active_at=null | 缺；旧为占位，不算真实统计丢失 | 无 |
| `embed/:channel/exchange`、`config`、`chunks/:chunk`、`sessions` | 真实签发 channel scoped token，读取配置/真实 Chunk，创建 Session | 缺；旧 exchange/allowed_origins 安全语义还需专项复核，不能盲复制匿名准入 | 无（对外嵌入消费者未核实） |
| `embed/:channel/knowledge-chat/:session`、`agent-chat/:session`、`messages/:session/load`、`sessions/:session/stop` | 真实检查 channel/tenant/session 归属后接聊天、消息和停止业务 | 缺；普通已登录 Chat 路由存在，但不替代渠道 token/范围协议 | 无（对外消费者未核实） |
| `embed/:channel/suggested-questions`、`sessions/:session/events` | 分别固定空 items、空对象 | 缺；旧占位 | 无 |
| `agents/:id/im-channels`；`im-channels`、`im-channels/:id`、`:id/toggle` | 真实配置 CRUD/软删除与启用状态持久化；并非真实 IM 服务收发 | 缺 | 无 |
| `im-channels/wechat/qrcode`、`wechat/qrcode/status`、root `/im/callback/:channel` | QR 通用默认 ok；callback 固定 received，不解析/发送真实消息 | 缺；不能把旧占位当成完整微信接入 | 无 |
| `tenants`、`tenants/all`、`tenants/search`、`tenants/:id` | 真实成员可见范围列表、创建 owner membership、读取/更新/软删除 tenant | 缺；现 Auth 创建个人空间/验证权限/导入租户存在，不替代 legacy 空间管理 | 无 |
| `tenants/:id/members`、`members/:user` | 真实列表、已有用户加入、角色更新、revoked 标记；拒绝个人空间分享 | 缺；AuthAction 有 member.manage 但无公开管理业务 | 无 |
| `tenants/:id/api-key`、`auth/switch-tenant` | 真实授权 key rotation；switch 验证准入后返回 tenant/user | 缺对应路由；trusted transport 的 selectedTenant 仍有真实准入检查，旧成员可读数据隔离未删除 | 无 |
| `tenants/:id/invitations`、`me/invitations` | GenericResource 实际存储 CRUD；没有真正邀请/member 联动业务 | 缺；保留数据与实现完整邀请系统是两件事 | 无 |
| `auth/invitations/lookup`、`me/invitations/pending-count` | 固定 valid=false、count=0 | 缺；旧占位 | 无 |
| `tenants/:id/invite-links`、`me/invitations/:id/accept`、`:id/decline`、`tenants/:id/leave` | generic 默认 ok，无 membership/邀请状态修改 | 缺；旧占位 | 无 |
| `auth/register-by-invite` | 直接调用普通真实 register，没有邀请码验证或加入被邀请空间 | 缺该别名；普通 register 保留，完整邀请注册本来未实现 | 无 |
| `system/admin/promote`、`system/admin/revoke` | 固定 ok，不修改 users.is_system_admin | 缺；旧占位 | 无 |
| `system/admin/list` | 实际查询/CRUD system_admins GenericResource；不是实际 User 管理员列表 | 缺该资源接口；真实管理员鉴权仍有 | 无 |
| `system/admin/settings`、`:id` | 实际 system_settings GenericResource CRUD，agent handler 有管理员动作权限 | 缺任意 generic 设置路由；实际 global application/startup/Neo4j/Langfuse 设置已由 system/config 专用路由保留，不宣称 DTO 等价 | 无 |
| `system/admin/audit-log`、`tenants/:id/audit-log` | accounts handler 真实审计表查询且有租户/system admin 范围 | 缺公开查询路由；表迁移/业务观测不替代审计列表 API | 无 |
| `shares`、`agent-shares`、`join-requests`、`shared-knowledge-bases`、`shared-agents` | 只在 generic_action 的返回空项分支出现；当前旧 urlpatterns 未注册这些 action 的公开 URL | 未发现迁移遗漏的已注册旧路径；不能凭未调用分支推断原有真实分享业务 | 无 |

因此，真实渠道公开聊天、配置存储、legacy tenant/member/key 管理和审计查询的接口缺口已经源码证明；没有现 UI 调用或本次库中资源为零，不构成删除权限。完整邀请、微信 QR/收发、管理员升降级等则原本是占位，不能报作真实已实现/厂商验收，也不应伪造 success 来填 coverage。

## 原始 SQLite 与 Neo4j 的实际适用性

脱敏只读 [JSON 证据](20261010-original-dormant-readonly-parser-worker.json)：workspace 根 db.sqlite3，用 `file:…?mode=ro` + `PRAGMA query_only=ON`；引擎 SQLite，SQLite library 3.46.0，共 51 表。只读取固定表计数/配置存在性；source size/mtime 不变。连接时 WAL/SHM 存在，本轮只证明业务 DB 只读及主文件 size/mtime 不变，不声称 SQLite 内部 sidecar 的绝对无变化。

- `generic_resources=0`，allowlist 中 embed/im/invitation/admin/share 资源 active 行均为 0；这只证明本库没有这些资源行，不证明可删其功能。
- 真实 `tenant_members=4`、`users=4`、`tenants=2`。成员/legacy tenant 管理不是纯空表假设。
- `integration_configs` 有 1 条 Neo4j，启用计数 1，uri/username/password 非空计数各 1；未选出值、未解密、未连接。
- 旧 [GraphRepository](../../personal_knowledge_base/graph_rag.py) 用 `ENTITY<sanitizedKB/document>` label 与 `kg`；新 [templates](../../packages/core/src/graph/templates.ts) 查询 MarlinEntity/MARLIN_REL namespace/generation，SQLite graph_document 原库不存在。现 importLegacy 不导出/转换/发布外部旧图。
- **旧 Neo4j 迁移路径实际适用，不能以“原库未配置图服务”豁免。** 连接可用性、旧图记录数、已删除源/跨租户边界及迁移保真仍未知；未查询外服，不能声称已有图必然丢失或旧图为空。不得通过付费重新抽取冒充无损迁移。
- 原 workspace 引擎确为 SQLite；本轮没有检查其他用户数据目录或部署环境，不能扩展为所有 PostgreSQL 场景已验证。

本补审取代 [上一份覆盖审查](20261010-final-function-coverage-parser-worker.md) 中 Startup 提示“尚待 UI 决策”的状态，并把 Neo4j 配置适用性从未知更新为已存在/启用。其他剩余项维持各 owner 的冻结和真实验收边界，不重复既有厂商测试。
