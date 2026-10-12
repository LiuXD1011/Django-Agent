# 核心只读 Query Worker 第二阶段设计

日期：2026-10-12。范围：Goal II.5 已授权的独立设计审查；仅新增本设计及[调查证据](../refactor-evidence/20261012-core-read-worker-design-review.json)。没有实现 Query Worker、运行测试、访问运行中数据库或操作 GUI。依据[发布响应性评审](LOCAL-PUBLICATION-RESPONSIVENESS-REVIEW.md)与[owner 实施计划](CORE-OWNER-WORKER-PLAN.md)，并重新核对当前源码和已安装类型。root 告知 owner 第1阶段已接入 HTTP/fork，相关29项/typecheck/build通过；这是 root 的既有验证，本轮未重复。旧计划末尾“尚未实施”描述不代表本次源码状态。

## 目标和仍存在的限制

在唯一业务写 owner 同步发布时，明确允许的页面 GET 应由第二条真正只读 WAL 连接返回上一版完整已提交数据。读请求的认证、membership、权限、范围与 DTO 在同一个同步 deferred 快照内完成；回复还必须通过协调线程的认证与空间 epoch fence。保留原发布事务、默认值、完整来源正文、字段投影和单写者，不能以分批提交、删除功能或授权后置实现响应性。

这不会让 owner 内聊天流、模型回调、写操作或业务取消同时变得可响应。下载与图片暂留 owner，也仍可能等待发布结束。同步发布本身及真正取消属于后续阶段；仅 Query GET/health 可用不能宣称完整性能通过。

## 实查的构造与类型边界

| 当前入口 | 核实结果 | 阶段2处理 |
| --- | --- | --- |
| `runtime/owner-client.ts` / `owner-worker.ts` | 前者仅代理；后者唯一构造完整 Application/IPC。ready 目前只有 serviceId。外层128 pending；owner64执行+64等待。 | 保留 owner；扩展可信 bootstrap/session 生命周期消息，新增独立 Query client/worker。 |
| `storage/database.ts` | CoreDatabase 构造 mkdir、可写连接、WAL、vec、migration、drizzle；transaction 使用 immediate，拒绝 Promise。 | Query 不能实例化；抽取无初始化的读 codec/接口，新连接使用原 openNativeDatabase API。 |
| `auth/index.ts` | 构造本身没有写，但类依赖完整 CoreDatabase，既含认证/断言，也含会话/密码写入。 | 抽取共同 AuthReader，由 owner AuthService 与 Query 使用同一逻辑；禁止假 cast。 |
| `knowledge/domain.ts` / `knowledge/index.ts` | 未传 index 会创建 SearchIndex；当前 GET 需要 state/DTO/聚合等，写服务也依赖 jobs。 | 抽取真实 KnowledgeReadDomain/Queries，写服务复用，读端仅接收纯 IndexStateReader。 |
| `retrieval/search-index.ts` | 构造创建 registry/sequence/vector/build 表；state 方法本身只有 SELECT，已有 namespace/active/deleted join。 | 提取纯 state 查询，不能在 Query 构造整个 SearchIndex。首批不做 FTS/vector 搜索。 |
| `settings/model-configuration.ts` / `settings/settings.ts` | 构造 StartupConfiguration 会读配置文件、冻结当前环境；公开设置通常需 decrypt 后剔除秘密。 | 抽取 Queries，不构造这两个完整服务；设置解密单独列为第二批。 |
| `storage/credentials.ts` | Vault 构造只保存 keyPath；decrypt 只读既有 key，缺失不创建；encrypt 才可能创建。 | 显式 DecryptOnly 能力；不把 encrypt/create 暴露给读端。不能把这类设置读说成严格 DB-only。 |
| `documents/workflow.ts` / `document-routes.ts` | stages 为授权后的纯 DB 投影；路由同时要求 parser 已配置，返回 items 与 spans 同义字段。完整 workflow 拥有恢复/写 hooks。 | 单独提取 stages 查询，镜像 parserEnabled，保留原503和 DTO；不构造 workflow。 |

当前知识库计数已改成受作用域约束的聚合。本设计复用它，保留 disabled/parent 等既有计数语义；不再次提出已落地的统计优化。

真实依赖：better-sqlite313.0.3、types9.6.0、Node types22.19.15。Options 实际提供 readonly/fileMustExist/nativeBinding，Transaction 提供 deferred，Statement 提供 readonly/reader；没有已安装公开 interrupt/progress API。依赖附带 SQLite 源码宏为3.53.4；它不是实际 Windows/Node native 加载版本证明。

## 精确 allowlist 与分批范围

分类使用经过 validateCoreRequest 和同一 URL/path matcher 规范化的 method+模板，解析后的 pathname 决定路由，保留原 query/编码/请求体校验。GET 前缀、类似路径、任意 SQL/函数/模块名不能进入 Query。未知请求走既有 owner。静态路径与参数路径的优先次序必须与现有注册顺序一致；不是“匹配其中一个正则即可”。

### A：严格数据库页与账户，第一交付批次

以下均为 GET；每项仍重新认证、assertCan(read)，并执行当前各领域断言。只读函数同步返回现有 JSON DTO，不是预授权缓存。

| 精确路径模板 | 实际读行为 |
| --- | --- |
| `/api/v1/knowledge-bases` | KB 列表、作用域和现有计数/配置投影 |
| `/api/v1/knowledge-bases/:id` | KB 详情、配置、index state |
| `/api/v1/knowledge-bases/:id/move-targets` | 同一身份允许的移动目标 |
| `/api/v1/knowledge-bases/:id/knowledge` | 文档列表，保留状态/标签/关键词/分页 |
| `/api/v1/knowledge-bases/:id/knowledge/stats` | 现有解析工作流状态与块计数 |
| `/api/v1/knowledge/batch` | 现有 ids 解析与最多900项限制 |
| `/api/v1/knowledge/search` | 文档元数据列表搜索；不是模型/向量检索 |
| `/api/v1/knowledge/:id` | 文档详情、完整正文、metadata |
| `/api/v1/chunks/by-id/:chunk` | 分块详情，必须先于 chunks 参数路径 |
| `/api/v1/chunks/:id` | 文档分块列表 |
| `/api/v1/chunks/:id/:chunk` | 指定文档的分块详情 |
| `/api/v1/knowledge-bases/:id/tags` | 标签列表 |
| `/api/v1/knowledge-bases/:id/tags/:tag` | 标签详情 |
| `/api/v1/knowledge/:id/stages` | 经纯函数抽取后的解析轨迹；parserEnabled=false仍返回503 |
| `/api/v1/auth/me` | 当前用户/设备/选定空间的安全身份投影 |
| `/api/v1/auth/devices` | 当前用户设备清单，保持现有权限和排序 |

`knowledge/batch`、`knowledge/search` 优先于 `knowledge/:id`。所有 ID/JSON/boolean/null/排序和64位 seq 字符串使用共享 codec。跨 tenant、KB、文档、membership 撤销标记及有效工作流状态语义完全保留；列表、计数和 hydration 不得来自不同连接或事务。

### B：设置页，独立审计后启用

下表中的纯枚举可随 A 注册，仍认证。其余需要显式的只读已有密钥解密能力，属于“DB+DecryptOnly”，不是纯 DB 批次。先完成 B 的真实权限/投影回归再启用，不能用 ModelRuntime/configuration/provider test 替代查询。

| 精确 GET 模板 | 约束 |
| --- | --- |
| `/api/v1/models/providers` | 已有静态供应商枚举 |
| `/api/v1/models/usage` | 当前 tenant 的 DB 用量聚合 |
| `/api/v1/models`、`/api/v1/models/:id` | 公共模型投影，保留 unsupported imported rows、type 过滤 |
| `/api/v1/models/:id/thinking` | 当前配置与 admin_editable/revision 投影 |
| `/api/v1/models/:id/credentials` | 仅 configured 状态，不返回明文或密文 |
| `/api/v1/tenants/kv/:key` | 仅现有代码认可的 key 字段映射，不允许任意表/列 |
| `/api/v1/system/config/:section` | 参数值仅 application/neo4j/langfuse/local_services；startup 继续 owner |
| `/api/v1/integrations/langfuse/credentials` | 原公开配置/秘密是否已配置投影 |
| `/api/v1/vector-stores/types`、`/api/v1/web-search-providers/types` | 已有静态枚举，须先于参数 id |
| `/api/v1/mcp-services`、`/api/v1/mcp-services/:id`、`/api/v1/mcp-services/:id/credentials` | 同一 snapshot 的 provider 读投影 |
| `/api/v1/web-search-providers`、`/api/v1/web-search-providers/:id`、`/api/v1/web-search-providers/:id/credentials` | 同上 |
| `/api/v1/vector-stores`、`/api/v1/vector-stores/:id`、`/api/v1/vector-stores/:id/credentials` | 同上 |
| `/api/v1/system-settings`、`/api/v1/system-settings/:id`、`/api/v1/system-settings/:id/credentials` | 同上，fresh真实系统管理员检查 |

providers/usage 在 models/:id 前匹配。未知 section 留 owner处理原错误；不把它默认纳入 Query。解密缺失/损坏 key 时返回已有安全错误，不生成新 key、不迁移旧明文、不把 secrets 纳入 Worker 回复或日志。Vault 是核心内部能力，renderer 只得到既有公开 JSON。

### 明确留在 owner

- `knowledge/:id/download`、`knowledge/:id/images/:image`：DB 快照不能 pin 已退役的外部文件；保留受控文件/哈希生命周期。
- `sessions/continue-stream/:id` 等流 GET：ensure/reconcile 可写并有专属 ACK/恢复语义。
- `observability/langfuse/status`、`mcp-services/:id/tools`：远程网络/连接状态。
- system parser engines/storage/info、startup 配置：可能启动辅助进程、读文件或反映 owner 自身连接状态。
- capabilities/CSRF/public embed、Wiki/Graph/chat/agents/evaluation/legacy tenants/audit GET：本批未提取其全部能力与副作用，走原 owner；CSRF/health保留外层已有特殊处理。
- 任何非 GET、上传预检、模型请求、provider tests、NativeLangfuse、stream/ACK、业务取消均 owner。

## 只读连接与一次请求快照

Query 等 owner bootstrap 完成 migrations、业务 DDL 和服务身份后再启动。可信 bootstrap 提供实际 databasePath/dataRoot、serviceId、runtimeGeneration、schema readiness、parserEnabled、ownerStartupActive；renderer 无权指定路径或 Worker 选项。

新 ReadDatabase 仅实现 `get<T extends Row>(sql,...BindValue[]): T|undefined`、`all<T extends Row>(sql,...BindValue[]): T[]`、`read(table,id): Row|undefined`、readonly path/dataRoot。SQL 是经过审查的核心内部函数代码，不能出现在 Query IPC 请求中。使用原生 openNativeDatabase 的 readonly:true、fileMustExist:true，启用 defaultSafeIntegers，读 journal_mode 确认 WAL；不 mkdir、不 migrate、不设置 WAL/NORMAL、不构造 drizzle/ORM、不恢复 jobs、不生成 CSRF/identity/vault key，不 checkpoint/backup/cleanup。connection-local query_only 可作为第二层防护，不能宣称它是文件系统隔离。

提取 normalized、表定义校验、read 主键验证和 JSON/boolean decode 到共同无副作用模块。CoreDatabase 通过结构类型真实满足 ReadDatabase，不改其 insert/default/transaction 语义；Query wrapper 不暴露 sqlite/run/insert/update/delete。必要时校验内部 prepared statement 为 reader+readonly，仍以 native readonly 为最终约束。首次 allowlist 不查询 vec 虚拟表；native SQLite 对已存在 vec schema 的只读读取须真实验证，如需扩展加载，只加载驱动已有代码，不运行任何 vec DDL。

每请求：

1. 验证私有协议、期限、route ID 和 GET；共享 matcher 再核对 request，不能接受任意 route/params 替换。
2. 在 Query 的同步 `sqlite.transaction(work).deferred()` 内解析 access/bearer/apiKey，并查询设备、用户、tenant、membership。
3. 同一事务内 assertCan(read)、领域授权、ID 查询、hydration、计数与 DTO 构造。没有 await、网络、函数调用消息或异步事务。
4. 返回 JSON 前结束读事务；协调线程做最终 fence 后才把 response 交 HTTP/IPC。快照不跨请求存活。

BEGIN deferred 本身尚未读取数据；第一条认证 SELECT 固定快照。不能在事务外预认证，再于事务内读文档；也不能按 ID 和详情分别开事务。GET 与正在发布的事务重叠可返回旧的完整已提交版本；提交 ACK 后发出的新 GET 必须开始新快照，读到该提交或更新版本。[SQLite 隔离文档](https://www.sqlite.org/isolation.html)支持这个可见性约定。

WAL 允许读写并行，但不是所有场景都保证没有 BUSY；长读也会阻止 WAL 回收。readonly 连接可能仍需要已有/可创建 WAL/shm，不能对实时 DB 使用 immutable。[WAL 文档](https://www.sqlite.org/wal.html)是这两个运行条件的依据。owner 唯一写者，Query 不执行 checkpoint；读事务限时、每次结束并留 reader gaps。实际目标平台加载版本和关闭行为另验。

## 私有认证、epoch 与回复 fence

### 协调线程的可信状态

继续由 owner CoreIpcAdapter 独占持久化 `ipc.session`、access+refresh 和一切认证写。新增核心内部生命周期接口，在恢复成功、save/clear 和认证操作终态后发出带 correlation/version 的当前 session 状态。协调线程只保存私有 access 镜像；refresh 不离开 owner，不给 renderer 新增秘密字段。Query 接收 private binding 的 access/bearer/apiKey/origin/selectedTenant 必要子集，不接收 refresh、upload、localSession、AuthContext/role/userId/管理员结论或 SQL。

每个 Query 记录 requestId、runtimeGeneration、queryGeneration、authEpoch、authorizationEpoch、scopeEpoch、原 selectedTenant、abort/deadline。回复必须全部对应当前可信状态、owner 存活且没有相关认证变更 pending。迟到/过期结果只丢弃并返回安全409/503，不把原正文泄漏到 renderer、日志或错误信息。

当前 IPC 只对7种 POST auth 操作增加本地 epoch，而且按原始 input.path regex 判断；Application 却用解析 pathname。必须共同规范化分类，包含带 query 的路径，不能留下绕过窗口。新增外层 fence 是可信私有状态，不能接受 renderer 提供 epoch 来提升资格。

### 哪些操作提前立 fence

外层接收并验证以下意图后、发给 owner 前就增加 fence；不能等 owner 在长发布后处理消息才阻止旧回复：

- POST auth/login、register、auto-setup、refresh、logout、logout-all、change-password。
- DELETE auth/devices/:id、PUT auth/me/preferences。
- POST auth/switch-tenant：空间切换 fence，保留现有权限检查。
- 改变授权的 owner 路由：POST tenants；PUT/PATCH/DELETE tenants/:id；POST tenants/:id/members；PUT/PATCH/DELETE tenants/:id/members/:user；POST tenants/:id/api-key。

先采用保守的全局 authorization epoch，避免只按当前 IPC 用户隔离后漏掉其他 HTTP 会话/成员撤权。代价是无关用户的一次在途读也可能被409拦截；后续可按可信设备/身份细化，不能缓存权威权限。上传/普通知识库编辑/解析状态写不增加全局认证 pending，页面必须仍能读旧快照。

pending 使用有界、按调用 ID 的 ticket 集合，不能一个 boolean 被早完成的操作清除。相关新 Query 在 pending 时快速返回 auth_pending，而不是无限等待或携旧镜像认证。成功或失败都必须收到 owner 当前权威 session/epoch ACK 才开放；失败登录不凭空清掉原有效 session。auth/preferences 不轮换凭据，也须防止旧 me/preferences 回复覆盖新偏好。

### owner 忙时认证并发

仅异步 session 消息和 owner 本地 #epoch 不够：外层已接收 B 意图，但 owner 的同步发布期间还没收到 B，随后 A 的 authChange 可能先保存。建议由协调线程维护私有 SharedArrayBuffer 原子 epoch，owner 在认证入场、产生 issue 后及保存/发布 authChange 的边界同步读取；消息携可信 captured epoch。SAB 只在核心 Node 内部两个 Worker/协调线程间使用，不经过 JSON fork，不关联阶段3取消槽。

保留现有过期新 issue 由 owner logout 撤销的行为。不能只丢外层回复，留下无人知晓的有效新设备。已提交的密码修改/退出安全副作用不能假称撤销；认证意图和数据库提交的线性化点要写进测试。

SAB 与 SQLite COMMIT 不是一个原子操作，读一次 epoch 不能关闭“最后检查后又收到 B”的窗口。实现必须覆盖保存前、保存后但回复前的竞态：若已签发/保存结果成为过期结果，唯一 owner 做受当前 session/version 条件约束的撤销/必要私有 session 修复，不覆盖新的 B；协调线程保持 pending，直到当前版本已确认。尚不能证明这一点时不得开放读镜像，也不得以读 desktop_meta 的旧快照替代确认。建议先用确定性 barrier 测试这个微小窗口再实现，不扩大为第二认证写者。

### selectedTenant 的精确语义

现有 PrivateBinding.selectedTenant 来自可信 HTTP header/IPC tenantId，但它只是请求选定范围，不是权限。LegacyTenantService.switch 检查权限后返回 user/tenant，不更新用户主空间或 session。保留这些行为：没有 selectedTenant 的请求仍按原主空间规则，不能强制全部请求使用一个全局新默认空间。

显式 switch-tenant 意图增加 scope fence，成功/失败均有权威结论；新请求仍使用自己的原始 tenant binding。不要因两个合法并发请求携不同 tenantId 就擅自切换全局 session。若 UI 仅改变选定空间并不调用此 API，则需要独立、不含凭据的 scope intent 通知或页面现有加载代数 guard；无法观察的本地切换不能声称由核心 fence 自动保证。服务端仍严格重新查 membership 并以捕获的 selectedTenant 完成整次查询。

## startup 生效环境镜像

owner 的 StartupConfiguration.active 在构造时冻结 task_workers/sqlite_timeout/model_timeout/log_level，environmentOverrides 也固定；GET projection 每次重新读取 startup.json 的 saved values。Query 后启动时若重新构造 StartupConfiguration，可能把 owner 启动后保存的配置或新环境误报为已生效。

bootstrap 镜像仅这4个 active 值、已公开的 override 名字、owner 实际路径/服务身份及必要 parserEnabled；不发送整个 process.env。Query 用它判断自己的运行上下文，不 applyDatabase 到 owner、不改变 task_workers/model timeout。Query busy timeout/admission deadline 是另一个显式预算，不能把它伪装成 owner 设置投影。

startup GET 初版继续 owner，保留文件被修改后 saved/restart_required 的现有行为；startup update 后 active 镜像仍不变。若以后移到独立纯投影，必须同时提供最新 saved 文件读能力和 owner frozen active，另行审计；不能仅缓存 projection。system/storage/info 的 PRAGMA 应反映 owner 连接，因此本批也保留 owner。

## Query 协议、界限与生命周期

新增 query-contracts/client/worker；沿用外部 CoreRequest/CoreResponse，内部消息是固定 discriminated union。示意字段：

```ts
// 仅可信 CoreOwner -> Query；不是 renderer/fork 的新增 API。
type QueryCall = {
  protocol: 1; type: 'read'; id: string;
  request: CoreRequest; routeId: ReadRouteId;
  binding: ReadPrivateBinding;
  runtimeGeneration: string; queryGeneration: string;
  authEpoch: string; authorizationEpoch: string; scopeEpoch: string;
  deadline: number;
};
type QueryReply =
  | { protocol: 1; type: 'read-response'; id: string;
      runtimeGeneration: string; queryGeneration: string;
      authEpoch: string; authorizationEpoch: string; scopeEpoch: string;
      response: CoreResponse }
  | { protocol: 1; type: 'read-error'; id: string; error: OwnerFailure }
  | { protocol: 1; type: 'ready' }
  | { protocol: 1; type: 'closed' };
```

ReadRouteId 来自编译时固定 manifest，不是动态模块/任意 SQL。ReadPrivateBinding 是 PrivateBinding 允许字段的窄化结构；用实际 AuthReader 重认证，不能携 AuthContext。 epoch 字符串避免 JSON/64位精度歧义；SAB计数设计须定义溢出/重启 generation，不复用旧 epoch。Worker reply 字段严格验证，error 不包含 SQL/native path/秘密。

初始建议一条 Query Worker、一条只读连接、同一时刻至多一个在途执行，协调线程至多32个验证后等待请求，并纳入现有总 pending128/fork64限制。这些数值是实施提案而非已存在产品行为。不要一次把队列全部 postMessage 到同步 Query，否则 Worker 内部消息队列无界。队列满429，未 ready/worker fault/owner closed503；期限从协调线程接受时计，排队也计入。不得在 read故障时静默转 owner造成“已通过响应性”的假象；未知路由原本走 owner 不属于 fallback。

沿用现有2MiB请求限制。响应不能简单套2MiB上限并截断合法完整正文/900项 batch；一个全文读取许可、排队字节预算和 clone/JSON 序列化耗时须测量，不能假称 count bound 等于内存 bound。优化投影只能依原 API 的 list/detail契约，不能删除正文。

排队 abort 移除；在途 abort/timeout 由协调线程立即拒绝并 fence回复。Query 不能在同步 SQLite 执行中处理 abort 消息，当前依赖也没有 interrupt；不要宣称停止了 SQL。函数边界可读共享 abort/deadline，SQL 返回后释放快照。超限只读 Worker 可经有界关停后终止隔离，但不能用同样方式取消业务 owner。

Query 异常使旧 generation 的 pending 全部失败、关闭队列；owner 健康且配置一致时最多一次受控 readonly 重启，失败显示明确降级状态。owner 异常立即封闭 Query，避免死核心仍返回陈旧页面。关闭先停接收、递增fence、拒绝队列/回复，结束 Query 快照并 close native连接，再完成 owner原应用close；若 Query SQL未退出采用明确期限和最后终止隔离，owner正常业务取消/恢复规则不变。查询读连接关闭不得成为新迁移/恢复入口。

## 最小实施文件与抽取顺序

不建议一次重写全部 service。下面是依赖要求，不是本轮实际改动：

| 现有文件 / 新边界 | 必要修改 |
| --- | --- |
| runtime/owner-contracts.ts、owner-client.ts、owner-worker.ts；新增 query 三文件 | 私有 bootstrap、认证生命周期/epoch、精确分流、队列、reply fence、故障和关闭 |
| adapters/ipc.ts | 只给可信 runtime 提供 access 快照/状态 hook；保持 encrypted session 写和 refresh/秘密在 owner，规范化 auth分类 |
| application.ts；新增共享 route/protocol 纯模块 | 共享验证、规范化 matcher、授权 binding优先级、成功/错误和IPC auth_mode投影；不把整个 Application 导入为读服务构造 |
| storage/database.ts；新增 read-database/row-codec | 共享安全整数/表/JSON/boolean解码，真正 readonly wrapper + deferred snapshot；写 API语义不改 |
| auth/index.ts；新增 auth-reader | 单一认证/断言/身份投影代码，AuthService写操作继续 owner |
| knowledge/domain.ts、index.ts、knowledge-bases.ts；adapters/knowledge-routes.ts | 抽取/复用纯 Queries/ReadDomain 与现有DTO/过滤，写方法原依赖保留 |
| retrieval/search-index.ts 或独立 index-state 纯模块 | state查询独立共享，ReadDomain不构造SearchIndex；FTS/vec实现不改 |
| documents/workflow.ts、adapters/document-routes.ts；纯 stages查询 | 仅提取已读 stages，保持parser503及items/spans |
| settings/model-configuration.ts、settings/settings.ts、settings/usage.ts、adapters/settings-routes.ts | B批次Queries/DecryptOnly/纯用量签名，startup服务仍owner |
| settings/startup.ts（可能无需改） | 优先直接复用owner既有active getter；只增加类型明确的bootstrap投影时才改 |
| adapters/http.ts、tools/desktop-process.ts | 理想保持外部facade不变；CoreOwner dispatch/invoke内分流，无renderer新凭据API |

构造一个轻量 ReadDispatcher 而非 `CoreApplication as ...`；用小型 ReadRouteRegistrar 接收同步处理器，owner路由复用同一读 manifest/函数。不要复制完整 AuthService 或到处强转 Pick；写服务依赖读取接口时保持类型真实，写方法仍接收实际 CoreDatabase。先 A 的 codec/AuthReader/KnowledgeQueries/协议，再 B 的显式解密，分别冻结源码与证据。

## 必须先实际 RED 的回归设计

所有数据库只在隔离临时 dataRoot；使用真正 Native SQLite、真实 Query/owner Worker和正式facade。测试fixture可以先初始化数据库后关闭初始化连接，随后唯一 owner打开RW、Query打开RO；不在发布期间另开测试RW写者，不运行模型或重复40K入库。barrier仅测试入口，不能给产品协议新增任意SQL/函数。

建议新增 `packages/core/test/core-read-worker.test.ts`、`core-read-auth-fence.test.ts` 及测试专属 Worker fixture。owner消息泵的可信构造可抽取为共享内部函数，fixture直接构造真实Application/IPC并在固定fixture发布回调插入SAB barrier；生产入口不注册测试路由、不接受fixture路径或SQL。不能为了测试把任意handler/worker URL加到renderer或普通CoreOwnerConfig。测试使用真实运行时消息泵与HTTP/fork facade，不用mock假装同步发布阻塞。

实际执行路径：先写上述因果断言，在 `packages/core` 运行 `node --import tsx --test test/core-read-worker.test.ts test/core-read-auth-fence.test.ts` 记录RED；失败必须是读请求不能在barrier释放前完成/旧回复未被fence，不能把缺模块、漏fixture、挂起进程当业务RED。实现后同命令GREEN，再 `npm run typecheck`、owner/HTTP/IPC/knowledge/settings相关测试和 `npm run build`，编译.js入口另验。本轮没有创建或运行这些测试。

1. **同步发布时页面读。** owner在真实immediate发布事务退役旧块/插入新块、metadata、FTS后，通过私有测试SAB barrier阻塞直到协调线程释放。GET KB/detail/docs/chunks/tags/stats/me/devices必须在释放前终态返回，HTTP健康与fork IPC处理仍活跃。验证旧完整body/source generation/父子/邻接/计数/索引状态；release+COMMIT ACK后的GET验证新完整版本；故障rollback仍旧版。RED目标是当前所有GET排队等owner，而不是只看health200或设置宽松秒数。
2. **认证与hydration同快照。** 读worker首条认证SELECT后/ID查询后停barrier，owner提交新正文/状态，继续hydration必须全部旧版本，下一请求全部新版本。事务外认证、逐阶段autocommit或不同连接会产生确定性RED。混合版本不能靠字段删减规避。
3. **撤权期间迟到回复。** Query已验证旧membership且产生旧快照，协调线程接收logout/device revoke/member remove/password/refresh/API-key rotation意图，然后才交付旧Query回复。它必须被fence；相关新GET在pending中立即拒绝。释放owner发布，再由唯一owner提交撤权，freshGET401/403，跨KB/tenant查404。不能把旧快照本来有效视为撤权后仍可放行的理由。
4. **A/B认证和保存微窗口。** 认证A queued或已签发，owner正忙时外层收到B，测试入场/issue后/save前/save后-reply前各barrier。过期A不能成为查询镜像；已签发过期设备须真实撤销，不能覆盖B。覆盖失败login、refresh replay、logout-all、change-password、新旧device删除、preferences和scope切换，失败操作恢复已确认session而不是编造匿名/新身份；检查持久化与公开结果一致。SAB/SQLite窗口未通过时A批次不能启用。
5. **作用域与伪造。** personal owner/member撤销标记、inactive/deleted user/tenant/member、普通owner与真实系统admin、api-key只能legacy、Bearer access优先/fallback均用真实行测试。request/options伪造AuthContext/role/sql/unknownfields不能被接受；不同合法selectedTenant并发和无tenant参数保留原行为，显式switch失败不强行换空间。
6. **只读初始化与DTO。** 启动/读/异常/close不写schema_version、identity、jobs、desktop_meta、key或日志；native RO实际拒绝INSERT。断言没有Application/SearchIndex/Workflow恢复构造。已有codec的>2^53/64bit seq、JSON/boolean/null、Unicode来源范围、完整正文、disabled/parent计数、空集和900项batch保持等价。不是给读模块mock出一条假结果。
7. **精确路由与副作用。** 每个manifest路由、static-vs-id冲突、带query auth分类、非法编码/路径/section/key同原status；download/media/remote/streams/startup/未审查GET实际进入owner；不能通过通配GET绕过已有副作用。
8. **设置与环境。** B批次真实加密fixture：公开投影没有明/密文，configured嵌套字段一致，缺失/坏key不创建替代key。owner启动后保存startup文件、改变测试environ，再启动Query，其active仍等于owner；startupGET读取最新saved/restart_required仍owner，不把新保存值假报已生效。
9. **有界与关闭。** 一次执行+32等待/全局128/fork64互相兼容；overflow、排队期限、abort、错误协议、Query exit、owner exit、受控restart和close都不遗留pending/原生连接/旧generation回复。持有读快照时关闭最终释放WAL；期限不冒充SQLiteinterrupt。
10. **源码/编译与平台。** A/B分别related tests+core typecheck/build，真实Node22编译.js Worker/native binding同样跑；桌面生命周期相关回归、最终前端检查、真实Orca发布期间读页/撤权/延迟以及Windows正式安装由root统一验收。隔离barrier证明并发因果，实际性能另记录队列/SQL/hydration/clone/HTTP/IPC耗时与样本条件，不能用一条小fixture推断P95或完整响应性通过。

## 本轮交付与未验证项

本轮只提供可实施接口、安全边界和RED设计；没有上述测试结果，没有 Query性能改善结论。调查证据记录源码哈希、真实类型/依赖、allowlist数量、文档链接和差异检查。实施前建议先冻结认证生命周期/SAB保存窗口及共享读接口，再拆A/B并行任务；owner runtime、Auth/IPC和route分流有共同状态，不能由两个协作者同时编辑。
