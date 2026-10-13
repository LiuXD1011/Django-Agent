# Langfuse 开发入口自动启动的迁移缺口

2026-10-13。Root 重新检查已审10项第一批删除前，确认当前UI仍提供的真实能力尚无TS落点。Root 已明确 **暂缓整个10项group**，不是只留其中3项；全部301候选仍存在，`entrypoints_retired=false`、`full_retirement_executed=false`。本专项只调查与设计，不改产品、测试、依赖、Docker资源或用户配置。

问题不是缺少Docker或配置导致一次运行失败：旧 `manage.py runserver` 的入口确实调用自动启动代码，当前 TS `dev-server.ts` 则没有这条调用，而UI仍声明保存后在下次开发启动生效。原静态退役计划未覆盖这条能力，需要更正，不能以删除旧入口掩盖。

## 精确来源与旧行为

当前SHA和关键行见[源码绑定](entrypoints-execution/autostart-source-bindings.json)。全部10受影响文件已完整读取并与301快照逐字节重核；[删除前15项检查](entrypoints-execution/before-verification.json)实际exit0，10路径不在 `build_windows.source_inputs(ROOT)` 的468项中，来源与 Windows `dd5b9d2f…` 冻结完全一致。这证明删除不改变该包来源，不能证明能力已经迁移。

| 触发/分支 | 当前旧实现的真实语义 |
| --- | --- |
| 唯一开发触发 | `manage.py:23–29`：首参数严格等于 `runserver` 且 `RUN_MAIN != "true"` 时，外层进程调用 `django.setup()` 然后 `ensure_langfuse`；reload子进程不重复自动启动。调用或setup异常只输出固定 `startup_failed; application continues`，仍交给Django启动。 |
| `start_local.py` | 设置 `DJANGO_DEBUG=true`（仅setdefault），`execv`同一解释器运行manage runserver，没有自己的其他服务实现。 |
| 桌面排除 | `start_desktop.py:194–204`强制 `LANGFUSE_AUTOSTART=false`，即使DB配置开启也不自动启动Docker。旧desktop不会调用ensure；新Electron也不得因为此迁移新增自动启动Docker。 |
| 配置来源 | `local_env`先复制部署环境；仅在 `django.apps.apps.ready` 时查询数据库配置；`integration_config.stored_configuration`读取失败回退默认值。数据库的API/UI地址、project、timeout、auto_login及登录信息只填环境空值，非空环境优先。`LANGFUSE_AUTOSTART`非空环境优先，否则由保存的布尔开关决定。 |
| 默认/布尔 | 保存默认autostart=false、timeout45秒、auto_login=false。布尔接受true/1/yes/on（忽略大小写及首尾空格）。追踪enabled与Docker autostart是独立开关，不能因Langfuse tracing未启用而假设不需要起服务。 |
| API地址 | helper按BASE_URL > HOST > `http://localhost:3000`取值、去末尾slash；apps-ready默认配置本身按BASE_URL/HOST解析且可被保存base_url覆盖，所以非空BASE_URL优先于保存值，保存base_url优先于旧HOST别名。UI地址不决定compose启动或health目标。 |
| disabled/external | autostart=false立即 `disabled`，不创建目录、不调用Docker；API hostname不在127.0.0.1/localhost/::1则 `external`，也不调用Docker。只限loopback，并非新远程部署功能。 |
| 数据和源码 | 状态/锁在显式APP_DATA_DIR的 `.cache/langfuse`；旧未设置/空APP_DATA_DIR时回退源码根。compose文件和 `.env.langfuse`始终在源码根；不会把它们改写到数据库。新dev入口已要求显式 `--data-root`，状态应放该独立数据目录，不重新引入源码写入回退。 |
| 超时/锁 | float timeout夹到1–120秒；无法解析回退45。一次 `time.monotonic()`截止时刻覆盖FileLock等待、config、up、health；获得锁后不能重置预算，剩余≤0时不得执行下一步。FileLock的OS锁退出/崩溃释放，不是“marker文件存在就视为活跃锁”。 |
| 实际命令 | 固定list argv、无shell：`docker compose --env-file <source>/.env.langfuse -f <source>/docker-compose.langfuse.yml config --quiet`，成功后同前缀 `up -d`；cwd为源码根。每条命令timeout用原截止时刻剩余。stdout/stderr丢弃，不打印配置/凭据。 |
| health | `ProxyHandler({})`禁系统代理；GET API-base `/api/public/health`，请求timeout=min(2秒,剩余)，HTTP200才 `healthy`。失败轮询最多0.5秒且不超过剩余；不能用固定sleep或进程存在冒充就绪。 |
| 非致命结果 | `.env.langfuse`不存在→missing_server_configuration；Docker执行文件缺失→docker_unavailable；任何compose非零→compose_failed；锁/子进程/health预算用尽→startup_timeout；其他异常→startup_failed。所有失败后开发业务仍启动。 |
| 状态与清理 | 非早退分支将state/checked_at原子写startup.json，只打印固定state。finally释放锁。`up -d`创建的是持久服务；旧应用退出不运行compose down、不删除卷，也不按进程名/端口结束Docker或外部服务。 |

参考旧回归断言：`test_runtime_lock_portability.LangfuseStartupLockTests` 的跨进程锁等待/释放、预算不重置、锁grant已耗时不运行Docker、首条config耗尽预算不运行up、health仅使用真实剩余；`test_runtime_paths.LangfuseDataRootTests` 的状态目录；`test_langfuse_access_regressions.test_startup_uses_api_base_for_selection_and_health` 的API/UI分离。未执行这些Django测试，更没有运行旧启动器或读取原数据库。

## 当前TS/UI与Neo4j边界

`frontend/src/views/settings/system-fields.ts:29–31`仍有autostart和timeout字段，明确提示下次开发入口生效；`SettingsService`保留default、bool/number类型和1–120有限数校验、加密保存/管理员权限，`getIntegration`对local_services返回restart_required。当前 `packages/core/src/tools/dev-server.ts` 仅启动CoreOwner和HTTP，没有Docker/compose/local-service启动；`integrations/README.md:160–163`也明确Docker autostart需要owner lifecycle adapter。配置保存通过不能证明启动已应用。

旧 `scripts/local_services.py` 只启动Langfuse compose，没有Neo4j分支。tracked根仅有 `docker-compose.langfuse.yml`，没有Neo4j compose入口。旧 `neo4j_connection.py` 是保存配置变化后重建官方driver/按enabled连接，并不安装或启动Neo4j。此次需迁移的autostart缺口仅限开发入口Langfuse；保持现有Neo4j可选外部连接、driver重建/超时/错误，不扩大成自动启动Neo4j。

仍保留的旧 `personal_knowledge_base/langfuse_access.py` 及旧Django测试导入 `scripts.local_services`；它们不在当前默认TS suite/正式builder中，后续整个旧域退役时统一处理。当前正常新入口没有引用旧脚本，但旧业务存在真实opt-in能力，因此Root暂缓删除，不能凭“新入口没引用”推定可删。

## 三种落点与建议

1. **推荐：TS CoreOwner内的开发启动服务。** 只由dev CLI的可信入口调用，读取同一个owner的全局integration配置/选定dataRoot，固定源资源和命令，生命周期登记在app.close；HTTP/IPC业务路由不能发任意命令。无Django，不增加Python主业务，不改变桌面默认行为。
2. 独立TS启动器先打开第二业务DB读取设置，再启动CoreOwner：结构较短，但增加第二业务连接/凭据读取和配置竞态，不符合单owner设计，故不推荐。
3. 继续保留旧Python启动器或隐藏/禁用UI选项：前者仍依赖Django且不迁移正常TS行为，后者删产品能力。这里只作为当前暂缓保留，不是最终解决方案。

建议新文件 `packages/core/src/integrations/local-services.ts`，由 `CoreApplication`管理owned服务与close；接线涉及 `runtime/owner-contracts.ts` 的一个可信私有call、`owner-client.ts` 的可信方法、`owner-host.ts` 的分支、`tools/dev-server.ts` 调用。保持普通HTTP/renderer无命令参数入口，不改业务schema或公有API。Root协调这些共享文件，本准备者不实施。

建议采用如下具体接口（均为新设计、尚未存在，不假称现API）：

```ts
type LocalServicesStartupState = 'disabled' | 'external' | 'healthy'
  | 'missing_server_configuration' | 'docker_unavailable' | 'compose_failed'
  | 'startup_timeout' | 'startup_failed' | 'cancelled';
interface LocalServicesStartupResult { state: LocalServicesStartupState; checked_at: number }
// CoreOwner 的可信Node调用；sourceRoot来自dev CLI，不来自HTTP/IPC body。
startDevelopmentLocalServices(input: { sourceRoot: string }, signal?: AbortSignal): Promise<LocalServicesStartupResult>;
// 增加到既有 OwnerCall 私有union，owner-host调用app持有的startup服务。
type DevelopmentLocalServicesCall = { operation: 'development-local-services'; sourceRoot: string };
// CoreApplication持有；environ只可由可信启动/测试配置提供。
class LocalServicesStartupService {
  start(input: { sourceRoot: string; environ?: NodeJS.ProcessEnv; signal?: AbortSignal }): Promise<LocalServicesStartupResult>;
  close(): Promise<void>;
}
```

owner/bootstrap/registry不得把result与secret配置拼接发送renderer。测试可给服务构造器一个可信CLI可执行夹具选项，实际执行自有进程；它不进入OwnerCall/HTTP或生产默认参数。

### 启动顺序和已有API限制

先完成 `CoreOwner.start`，再由dev CLI调用可信开发startup方法，完成可选启动后才HTTP listen；缺服务/失败只是记录固定state，仍启动HTTP。不能在owner ready之前await最长120秒：当前owner-client连接只有30秒启动超时，直接把autostart塞在owner-worker构造前会产生新的启动失败。dev CLI的SIGINT/SIGTERM guard须在可选长等待之前安装，close/取消打断当前startup并等待自有helper终态。

从owner持有的 `integration_configs`读取一次snapshot，只提取autostart/timeout/API URL；不返回密码或API Key，不让renderer用body覆盖sourceRoot/env/argv。非空部署LANGFUSE_AUTOSTART、TIMEOUT、BASE_URL及历史HOST别名按上表解析；不得调用被保留的Django配置模块。auto_login仍使用现有Langfuse cookie桥，不混入Docker runner。

新服务复用 `OwnedProcessRegistry.spawn(file,args,signal,{cwd,timeoutMs,maxOutputBytes})` 及其真实supervisor/Job；固定shell=false、两步真实命令，退出/超时只结束自己的CLI/后代，关闭应用不down长期容器。现registry把spawn错误降为 `child_start_failed`，未保留ENOENT；要区分docker_unavailable必须增加安全枚举/受控可执行文件解析并测试，不把权限错误/隔离失败一律冒称“未安装Docker”。不回显原始stderr/config或父进程环境。

锁建议复用现有SQLite native能力建立专门非业务锁库（dataRoot `.cache/langfuse/startup-lock.sqlite3`），独立连接 `timeout:0`、尝试BEGIN IMMEDIATE，异步按真实剩余预算重试；成功持有SQLite OS锁直到全部启动工作结束，finally rollback/close。进程崩溃OS释放锁，拒绝简单O_EXCL遗留marker方案，也不把business DB transaction跨await持有。现 `openNativeDatabase(path,options)` 和已安装 `@types/better-sqlite3`明确支持 `Options.timeout`/inTransaction/close；但此锁方案尚未实现或实测，Root必须先验证Windows与Linux跨进程锁/崩溃释放，才能宣称等价。它不需要新增业务表或依赖。

一个 `performance.now()`截止时刻覆盖锁等待→compose config→up→真实health；获得锁后只用剩余，既有Integration CallScope单次上限60秒不能直接代表总120秒预算，health probe每次≤2秒可用单次受控网络scope。工作预算耗尽后必须停止下一步；实际自有进程清理的有界等待单独记录，不把清理时间伪装为已扩大工作预算。首次默认off/remote时零spawn/零数据写入；开发state保存到选定dataRoot，保留旧fixed statuses并加取消诊断，不能将副作用失败阻断Core主业务。

## 必要回归与实际验收方案

以下是Root后续实现者的门禁，没有本轮PASS声明：

- RED：新空隔离Core数据 + 经正常管理员设置保存autostart=true，实际dev入口不发compose调用且无startup state；用真实可执行测试CLI与真实loopback health观测“缺调用”，不能仅mock函数未被调用来当真实迁移失败。保留当前源SHA/工具码。
- 解析/权限：default false、env明确false压过保存true、BASE_URL/保存base_url/HOST解析、浮点/非法/0/大timeout、UI地址不作为health、remote早退。保存仍要求system_admin，renderer调用新私有startup路径返回404/非法ownercall拒绝。
- 真锁/真进程：同dataRoot两独立Node进程；第一持锁，第二全预算耗尽时零Docker调用；释放后第二能继续；杀本测试持锁进程后锁恢复。新dataRoot状态不写源码根。Linux和native Windows单独记录，不能用仿真锁冒充OS互斥。
- 真实子进程/网络夹具：隔离测试CLI记录两个固定argv与cwd，config非零不执行up，config烧尽预算不执行up，health只返回200才healthy，含中文/空格的sourceRoot和dataRoot。明确它是CLI协议夹具，不宣称真实Docker或Langfuse通过。
- 缺Docker/配置/失败：missing env、ENOENT、compose非零、health拒绝/超时，均固定state、Core HTTP仍真实可达；既有凭据/错误输出不进state/log。禁用与desktop入口测试零CLI执行；关闭服务只终止该次受控CLI、等待终态，旁实例和长期容器保留。
- 正常真实Docker：Root用新的验收project、复制公开固定compose到独立目录并生成独立私有合成env，不复制真实 `.env.langfuse`。实际启动 pinned Langfuse stack、健康API与应用保存开关→重新启动→记录真实CLI/状态/health；检查不会重建现有正式project或删除卷。首次pull超过预算应如实报告timeout，允许明确重试，不制造成功。测试项目退出/清理由Root准确project管理，不泛化停止Docker。
- Orca：验收管理员在本地Langfuse设置实际保存开关/timeout，退出自有开发实例并重新启动；实际状态/HTTP/health验证保存语义。desktop仍不autostart的Linux/Win源码和正式安装链分别核；旧Win dd5包不包含新功能，必须形成新来源迭代，不能改原manifest。
- 检查：相关Core类型与新增focused local-service/owner/dev-entry测试、必要前端local-services设置测试、现有startup与退出回归；改源后按scope执行构建和新的source_inputs/Windows门禁。已由另一代理跑过的698项Core结果不重复或冒作新实现验证。

## 退役恢复条件

Root确认上述能力有真实TS落点和相应证据后，再核新source_inputs迭代、301来源/归档SHA与新能力保留清单，再授权精确10项group。当前阶段全部10项继续存在，其他291也未动；没有再次请求用户批准正常迁移。原Windows468项/dd5冻结、原prepare e8冻结、历史失败与归档字节不改；本文件和计划/REPORT的新事实作为后续addendum，原两份准备文档字节已独立保存供旧freeze复核。

收尾时的13项文档/归档/保留核对全部actual0：[真实结果](entrypoints-execution/autostart-gap-final-verification.json)。当前构建来源已观察到另一个新迭代：新增 `Platform.recent-sync.test.mjs`，修改 `api/index.ts`、`Platform.vue`；Root此前已通知其独立界面修复任务。此处只记录差异，不推断作者；[当前来源观察](entrypoints-execution/current-source-inputs-observation.json)如实标记与原468不相同，原dd5冻结文件保持不动，本准备者没有修改这三条来源。
