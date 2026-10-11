# 重构代码复核与收尾（2026-10-02）

## 结论

已有重构切片已完成本轮代码复核、遗漏修复和相关回归。**W00–W09 完整方案仍未完成**。
保留 Zcode 和配置迁移的既有改动；在 main 工作区修改，未新建分支、未暂存或提交。
根 .env / .env.example 保持删除。本次没有前端代码、依赖或业务 schema 变更。

## 已修复

| 审计项 | 遗漏与修复 |
|---|---|
| F02 成员撤权 | 原代码仅查 active 成员，没有 active 行时主租户用户被兜底为 owner。认证、角色、管理授权现在统一判断成员状态；移除成员保留 status=revoked，再邀请显式恢复 active |
| F02 凭据生命周期 | 用户/令牌软删除即失效；显式无效 X-Tenant-ID 返回 401，不静默回落；停用租户不能登录/刷新；刷新令牌条件消费和签发共用短事务 |
| F01 凭据读取 | 租户 KV 的 web-search/parser/storage/credentials 读取增加 credentials.manage；viewer/service 不获得第三方服务凭据，普通检索设置读取保留 |
| F13 API 角色 | 门控覆盖 enqueue、同步执行、提交后回调、直接派发和恢复入口；API 只持久化 pending，独立 worker 与本地行为保留 |
| F08 发布竞态 | task_publish_transaction 在短事务内以 owner/status/cancel/lease 条件 UPDATE 锁住 task，再发布初始状态、chunk 替换和终态；异常回滚，不再仅靠 exists |
| F10 健康误报 | 健康路由转入独立 runtime_health 模块。DB 与迁移共同决定 ready；向量退化不摘除普通 API，但组件标 degraded；诊断要求管理员，公开错误只返回固定代码 |
| F03 范围候选 | 全文和 LIKE 回退均在 LIMIT 前限定 KB；向量候选复用一致租户/文档/KB 谓词。原“70 个更近候选”实际更远的测试夹具已纠正 |
| F04/F05 嵌入与重建 | 全库范围按租户检查 KB/文档模型覆盖；混合空间明确降级；不存在 KB 不再抛 StopIteration；重建按实际模型分组，校验数量和维度，失败/取消不冒充 ready |

新增 test_refactor_closeout.py 的 **30 项**回归，包括真实临时 SQLite 双进程交错接管。
“从未有成员记录”的历史单租户账户行为保留；此前物理删除且没有撤权记录的成员，仍需后续数据审计/回填，不能与这种历史账户凭空区分。

## 实际验证

- 修改前相关基线：153 项，OK，退出 0。
- 修复前复现：首批 19 项出现 13 failures + 1 error；健康 4 项全部失败；检索 5 项出现 3 failures + 2 errors；凭据读取 1 项失败。日志原样保留。
- 最终相关后端集合：**339 项，OK，退出 0**。覆盖账户/API、安全、任务领取/恢复、文档/多模态、检索评估、配置及新增回归；不是全仓库套件。
- 新增回归单独执行：**30 项，OK，退出 0**。
- 前端 npm run test:unit：**63 pass / 0 fail，退出 0**。
- python manage.py check：System check identified no issues (0 silenced).，退出 0。
- python manage.py makemigrations --check --dry-run：No changes detected，退出 0。
- 本次没有依赖或前端构建配置修改，未重复构建或三平台发行验证。
- Zcode 原始 885 项日志已核对结尾 OK (skipped=3)；这是历史证据，不替代当前测试。

精确命令、输入、完整日志、逐文件前后 SHA256 位于本机 .cache/refactor-closeout/。
未部署后台服务，未对业务数据库、PG/Redis 容器或 Neo4j 做破坏性迁移。

## 恢复与证据

本次 15 个目标路径的原始副本在 .cache/refactor-closeout/originals/。
manifest.json 区分既有/新增文件，记录原始和修改后哈希；不是 Git HEAD 快照。

- MODIFIED_FILE.tar.gz：本次修改文件、原始副本、清单及本地验证日志；
- DIFF_FILE.patch：只包含本次收尾相对于开始时工作区的差异；
- VERIFICATION.txt：BASELINE / MODIFIED / ROLLBACK 的实际命令、输入、结果、退出码；
- ROLLBACK.sh：核查哈希和目标路径后逐文件恢复，用于隔离演练，不覆写主工作区。

演练流程：复制当前源码到独立副本 → 执行 ROLLBACK.sh → 核验原始哈希 → 重新运行原 153 项基线。
实际演练结果以 VERIFICATION.txt 为准。当前主工作区保留修复；恢复源码行为不等于部署 P0 旧代码。
数据库、密钥、上传文件和外部服务不属于这次源码演练。

## 后续阶段（未完成）

| 阶段 | 剩余验收 |
|---|---|
| W00 | 完整传递依赖锁/哈希、离线资源、可复现安装与 CI；requirements 下限不是完整锁 |
| W01 | 服务凭据 scopes/摘要、历史成员回填、长连接撤权、刷新并发故障测试与完整路由矩阵；旧租户信息仍有 API-key 返回契约 |
| W02 | DocumentRevision、expected_revision、单调 fence、staging/outbox；图片/向量/图谱/Wiki 全链路发布与删除保护；PG 真实并发验收 |
| W03 | EmbeddingSpace/影子 IndexGeneration、保留旧可用版本、并发编辑一致性；轨迹载荷完整性；chunk 索引外层事务和陈旧写保护 |
| W04 | 端口/适配器全面接入、scheduler 显式入口、探针实际时间预算；APP_MODE 分层不等于聊天 SSE 异步化 |
| W05 | PG 检索/中文质量 oracle、Redis 配额/缓存、对象存储、迁移校验；DATABASE_URL 仅切换 ORM，不代表团队底座验收 |
| W06–W07 | 公平队列/死信、Neo4j 版本投影/tombstone/对账、async SSE、backpressure/provider 配额 |
| W08–W09 | 三平台签名安装与升级，1000 在线/100 并行生成及 HA/备份恢复实测 |

下一阶段优先完成 W02/W03 的版本发布协议，再推进 W05 共享底座。现有测试通过不是千人容量或正式团队部署验收。
