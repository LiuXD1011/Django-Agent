# 重构阶段执行记录（W00–W05 切片；W06–W09 待实施）

> 代码复核与收尾结果见 [CLOSEOUT.md](CLOSEOUT.md)。下文保留 Zcode 的阶段记录，
> 其历史测试数量不代表当前完整方案已验收。
> 原始阶段日志已从文档目录移入本机 `.cache/docs-cleanup/originals/docs/refactor-evidence/`；
> 下文日志文件名仅作历史溯源，日志不随仓库分发。

执行环境：WSL2 (Ubuntu)，Python 3.12.2，Django 5.2.15，Node v22.23.2。
工作区包含大量既有未提交改动（Langfuse 集成配置、系统集成 UI 等），全部保留并在其上工作。
审计基线 commit `2223838` 的审计证据目录未随仓库分发，因此按方案纪律对本机代码逐项重新取证，
而非沿用历史结论。

## 一、基线重建（W00）

`python manage.py test` 全量套件初始状态：**853 项测试，22 失败 + 11 错误**（基线日志
`W00-full-suite.log`，完整失败清单见该日志）。归因与修复：

| 根因 | 涉及测试（约数） | 处置 |
|---|---|---|
| `scripts/local_services.py local_env` 无条件查库读取集成配置，无库环境（SimpleTestCase/引导期）抛 `DatabaseOperationForbidden` | 启动锁 7 项 + LocalStartup 3 项等 | `stored_configuration` 回退语义加宽（任何 DB 不可用→settings 默认）；`local_env` 优先级修正为**进程 env 优先、DB 配置补缺**（既有测试钉定的 12-factor 契约） |
| `config/bootstrap.py persistent_secret` 无超时文件锁：fcntl 被屏蔽的软锁环境永久阻塞 settings 导入 | fcntl 导入契约、生产密钥、启动锁等 | 锁加 10s 超时 + O_EXCL 原子创建兜底（密钥稳定性契约保留） |
| 产品已移除 env 直连模型（`env_models`→`[]`），思考配置回归测试仍依赖它 | ThinkingPersistence 9 项 | 夹具改为租户内 `ModelConfig` 行；env 专属契约（指纹失配、env 并发胜者）随功能下线移除/改写为“env 模型 id 一律 404” |
| 模型列表契约变化：服务端生成 id、凭据彻底剔除而非掩码 | tests.py 4 项 | 断言适配新契约且保持保护力（密钥零回显、configured 布尔） |
| `/api/v1/system/info` 迁至 `models_config.system_config` | 路由契约 1 项 | 期望更新 |
| 仓库 `.cache` 残留真实运行数据导致绝对断言失败 | eval-reports、rate-limits 3 项 | 测试改为“不新增仓库侧写入”的快照对比；eval 报告测试隔离 `APP_DATA_DIR` |
| `get_langfuse()` 签名缓存重构后，bench 脚本旧注入契约失效 | BenchmarkScenario 1 项 | 脚本经 `patch(obs.get_langfuse)` 注入受控客户端（门面开销测量与传输验证断言原样保留） |
| 生产密钥契约：工作区有意引入“无环境密钥自动持久化（桌面 D2）”，与基线 fail-closed 探针冲突 | 2 项（互斥） | 保留工作区设计（`persistent_secret` 稳定/私有/与凭据密钥分离）；fail-closed 探针改写为“持久化+复用+0600 权限”契约。**注意：这是一次安全契约变更，见“待确认事项”** |

修复后全量套件全绿（`W00-full-suite-after-fixes.log` 883→见下）。

## 二、W01 统一授权与凭据生命周期（F01/F02，P0）

代码取证（含路由勘察）确认审计结论且**更严重**：knowledge/wiki/chat/agent/eval 约 100+ 条路由
零角色检查；`role_for(None)`→"owner"；`system/admin/settings` 匿名可写（tenant 兜底 `first()`）；
登录/刷新不查 `is_active`。

新增 `personal_knowledge_base/permissions.py`：动作枚举（kb.write/kb.delete/document.*、
chunk.write、wiki.write、agent.write、eval.write、task.write、credentials.manage、
member.manage、tenant.admin/tenant.create）+ 角色矩阵（owner/admin 全量、editor 业务写、
viewer/service 只读+导出，默认拒绝）。

- **F01**：knowledge 13 个写分支、wiki 页面/目录、agent 通用资源写（`system_settings` 提权至
  tenant.admin、匿名兜底移除、rotate-token→credentials.manage）、accounts tenant_kv/建租户、
  eval 13 个写端点、chat 写路径（要求真实用户主体；embed 签名主体放行）全部接入动作检查。
- **F02**：Bearer 认证谓词加入 `user__is_active`、租户 status/deleted_at；X-Tenant-ID 切换校验
  目标租户启用；`auth_login`/`auth_refresh` 拒绝禁用账号（防枚举同错误码）；`role_for(None)`→
  `service`；`can_administer_tenant` 的 API-key 分支关闭。
- 测试：`test_permission_matrix.py`（角色×资源×方法矩阵 11 项）+ 凭据生命周期（禁用即 401、
  刷新/登录拒绝、租户停用、跨租户 404 保持）。

证据：`W01-full-suite-final.log`（863 项全绿）。

## 三、W02 任务 fencing（F08，P0）

取证确认：`process_knowledge` 的业务写（删建 chunk、终态发布）完全无租约保护。

- `tasks.py` 新增 `assert_task_ownership()`（复用既有 `_WORKER_IDENTITY`/`_owned_task_records`
  谓词）与 `TaskOwnershipLost`。
- `document_processing.process_knowledge`：chunk 替换前、终态发布前强制校验；失败标记亦不覆写
  新 owner 状态；graph/wiki 阶段显式重抛失主异常。
- 测试：`test_business_publish_fencing.py` 6 项（接管后禁止替换 chunk/翻转终态/写失败标记；
  持有者正常完成）。
- **剩余范围**：DocumentRevision/staging/outbox 的完整版本化发布协议（见“未完成项”）。

## 四、W03 检索正确性与投影（F03–F07）

逐项取证并修复：

- **F03** `_vector_ranked`：vec0 全局 KNN 后过滤 → 按倍率扩展扫描窗口，窗口覆盖全表时范围内
  结果为精确近邻。回归：70 个跨租户更近候选不再挤掉范围内目标。
- **F04** `_vector_recall`：单知识库（或同模型多库）检索透传该库 `embedding_model_id`，查询与
  索引共用同一空间；混合空间显式降级 `mixed_embedding_spaces`，绝不跨空间比较距离。
- **F05** `rebuild_vector_index`：部分批次失败 → 维持 `needs_rebuild(partial_batch_failures)`，
  绝不冒充 ready；全部失败照旧抛错；全量成功才 `ready`。
- **F06** `event_log.rebuild_projection`：仅终结事件（completed/error）允许投影切换；每组切换
  在短事务内先删后建；未终结轨迹跳过计数；注入失败保留原消息。
- **F07** `chunk_mutations.update_chunk`：索引（含 embedding 模型 HTTP）移出 `select_for_update`
  事务；取最新行后索引。外层事务与索引并发覆盖仍需版本发布协议，
  不能仅凭一次“最新行”读取断言最终一致。
- 测试：`test_search_correctness.py` 9 项。

证据：`W03-full-suite.log`（878 项全绿）。

## 五、W04 运行模式与健康语义（F10/F11/F13）

- `APP_MODE`（local 默认 / api / worker / all-in-one）：非法值启动即失败；`api` 模式不启动任务
  执行与恢复线程（F13）；bench 脚本以 api 模式运行。
- `/livez`（零依赖活性）、`/readyz`（数据库+迁移+向量索引组件明细，失败 503）、
  `/health/components`（永远 200、degraded 区分）（F10）。
- F11（类型化启动配置+校验+脱敏）由工作区既有 `config/bootstrap.py` 承载，`models_config/
  test_system_config.py` 已覆盖；本会话补齐其与测试套件的兼容。
- 测试：`test_runtime_health.py` 7 项（含 livez 零数据库访问断言）。

证据：`W04-full-suite.log`（885 项全绿）。

## 六、W05 切片：真实 PostgreSQL 迁移审计

- 新增 `DATABASE_URL` 支持（仅 postgres；设置层最小解析器，非法值启动失败）+ `psycopg[binary]`
  依赖登记。
- 真实 PG 16（docker `django-agent-pg`，端口 5433）上执行全量迁移：
  - 发现并修复第一处硬耦合：`0001_initial` 的 `RunSQL`（FTS5/vec0 DDL）→ 厂商感知
    `RunPython`（SQLite 才建表；已有 SQLite 库不受影响，已验证全新 SQLite 安装路径完好）。
  - 修复后 **26 个迁移全部在 PostgreSQL 通过**；ORM 冒烟（Tenant 查询）通过。
  - 检索后端诚实化：非 SQLite 底座 `get_vector_index_state()` 返回 `unsupported`，绝不虚报
    ready；FTS/向量在 PG 上的完整适配器（pgvector/中文全文）是 W05 剩余工作。
- Redis 7 容器已就绪（端口 6380）但缓存/限流适配未在本切片实现。

## 七、测试证据汇总

| 证据文件 | 内容 |
|---|---|
| `W00-full-suite.log` | 基线：853 项，22F+11E（未修改前） |
| `W00-full-suite-after-fixes.log` | W00 修复中段（含中途改动，非干净证据） |
| `W01-full-suite-final.log` | W01 收口：863 项全绿 |
| `W03-full-suite.log` | W02+W03 收口：878 项全绿 |
| `W04-full-suite.log` | W04 收口：885 项全绿 |
| `FINAL-full-suite.log` / `FINAL-frontend.log` | Zcode 阶段收口（后端 885 项、跳过 3 项；前端 63 项） |

前端单元测试：63/63 通过（`FINAL-frontend.log`）。

## 八、部署说明（新增配置）

| 变量 | 取值 | 说明 |
|---|---|---|
| `APP_MODE` | `local`(默认)/`api`/`worker`/`all-in-one` | 非 local 值为团队/分层部署准备；`api` 不启动后台线程。非法值拒绝启动 |
| `DATABASE_URL` | `postgres://user:pass@host:port/name` | 设置即切换 ORM 数据库，非完整团队底座；**检索（FTS/向量）在 PG 上当前显式 unsupported** |
| 其余 | 不变 | `DJANGO_DEBUG`/`DJANGO_SECRET_KEY`/`ALLOW_AUTO_SETUP`/`APP_DATA_DIR` 等保持既有语义 |

- 全新 SQLite 安装：`migrate` 后即用；存量 SQLite 升级：直接 `migrate`（0001 已应用的库不重跑）。
- 桌面/本地入口（start_desktop/start_local/runserver）行为不变。

## 九、回退说明

- 未提交不等于可以从 Git HEAD 逐文件恢复；本工作区在重构开始前已有改动，
  对单个文件执行 Git 还原也会一并丢失其早先改动。
- 本次代码复核为实际修改的 15 个路径保存了逐文件原始 SHA256 和副本，
  回退演练只在独立工作区副本执行。文件清单、命令和结果见
  [CLOSEOUT.md](CLOSEOUT.md) 及本机 .cache/refactor-closeout/VERIFICATION.txt。
- P0 授权修复采用前向修复；隔离副本还原仅证明源码恢复能力，不是生产降级方案。
  本次没有业务 schema 新迁移，也不恢复或覆盖业务数据库与密钥。
- 历史记录中的 PG/Redis 容器保持原状；清理容器及其数据应另行核对使用者和数据状态，
  不根据“临时资源”的名称直接删除。

## 十、未验证项与剩余范围（如实声明）

1. **W02 完整协议**：DocumentRevision/staging/outbox 版本化发布、幂等键、expected_revision
   发布事务（方案 6.2/7.1 全量）未实现；收尾增加了初始状态、chunk 替换和终态的短事务 CAS 保护，
   但图片、索引、图谱、Wiki 的外部/长阶段尚无完整版本 fencing，不承诺所有业务写失主免疫。
2. **W05 完整底座**：PG 上的检索适配器（pgvector + 中文全文/分词质量门禁 oracle）、Redis 缓存/
   共享限流、对象存储适配、数据迁移导入校验（dry-run/checkpoint/哈希核对）未实现。PG 迁移通过
   ≠ 检索功能在 PG 可用。
3. **W06**：SKIP LOCKED 领取、按租户公平调度、死信、Neo4j versioned projection/tombstone/
   对账——未实现（需真实 Neo4j 集群与产品降级路线确认）。
4. **W07**：同步 SSE 未改造为真正 async（F09 实测前提是 Waitress 4 线程；本会话未做 100 路并
   行验证）。现有流恢复/落库机制保留。
5. **W08**：三平台签名安装包未开始（需签名证书等付费资源与产品确认 Tauri/Electron 选型）。
6. **W09**：1000 在线/100 并行生成的容量验收**未执行**（需独立负载机、受控模型 stub 与真实
   硬件）；任何“已支持千人”的结论都被本证据禁止。
7. **安全契约变更待确认**：生产无环境密钥时自动持久化密钥（工作区既有设计，本会话保留）相对
   基线 fail-closed 是放宽。团队服务器部署前建议恢复“生产模式拒绝无密钥启动”（W05 团队模式
   实施时以 APP_MODE 区分桌面/服务器）。
8. 探针 01/02 的**原始审计脚本**（audit_probes）未随仓库提供；等价断言已并入
   `test_permission_matrix.py`（viewer 删除 KB 403、禁用账号 401 等）。
