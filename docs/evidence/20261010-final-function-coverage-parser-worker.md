# 功能覆盖收尾审查（2026-10-10）

依据 [UI 基线](../desktop-refactor/UI-BASELINE.md)、[数据基线](../desktop-refactor/DATA-BASELINE.md)、[解析基线](../desktop-refactor/PARSER-BASELINE.md)。范围是基线 105 个前端 API 绑定和相关现有业务；API 数量、源码存在、受控服务测试均不能代替实际厂商或页面验收。本轮未操作 GUI、用户数据库或模型凭据，未发厂商请求。

## 已证明并修复

| 项目 | 红证据 | 当前实现和验证 |
| --- | --- | --- |
| 四条保留诊断 API | 实际 HTTP、IPC 各四条均返回 `[404,404,404,404]` | 新 [system-routes](../../packages/core/src/adapters/system-routes.ts) 注册 parser-engines、parser-engines/check、storage-engine-status、storage-engine-check；root 接入 application，移除旧重复 system/info。 |
| 系统信息的 Neo4j/Embedding DTO | 原 `graph_database_engine:'none'` 被 Settings 当作可用；原系统响应缺维度，页面固定显示 384 | [diagnostics](../../packages/core/src/system/diagnostics.ts) 返回未启用状态、仅配置但未验证连接状态；真实配置维度与当前 signature、实际 sqlite-vec 向量维度分开。[Settings](../../frontend/src/views/Settings.vue) 显示未配置/待索引验证/已索引验证，取消 384 假默认。 |
| 连接测试页面假成功 | 编译后的实际 SFC 收到 `{state:'disabled'}` 仍显示“连接测试通过” | [SystemConfiguration](../../frontend/src/views/settings/SystemConfiguration.vue) 仅 `connected` 显示通过；停用、未配置、未知响应与异常分别处理。 |

诊断不是写入/连通性测试：SQLite 只读 quick_check、foreign_key_check、FTS5、实际 vec API/version、连接及文件类型检查；明确 `write_probe_performed:false`。Parser 调用应用拥有的 Python/helper，返回实际 parser_version、逐格式/逐依赖状态，缺失 helper 不宣称成功。Worker 目前不返回逐依赖包版本，明确 `dependency_versions_status:'not_reported_by_worker'`；不臆造版本。DOC/PPT 依赖真实 LibreOffice 能力，扫描页渲染不等于本地 OCR。

POST 默认 `{}` 与当前前端一致（两个 check 方法没有当前 Vue 消费）。同时允许固定 builtin/local/sqlite selectors，拒绝 caller URL、路径、SQL、命令及任意引擎。

本轮验证：

- `TMPDIR=/dev/shm MARLIN_TEST_PYTHON=/tmp/marlin-parser-isolation-20261010/bin/python node --import tsx --test test/system-diagnostics.test.ts`：5/5，7.5865 秒。真实 HTTP、IPC、无 Django 独立 helper；SQLite 数据检查、1536 维实际存储、配置改为 1024 后失效、跨租户、撤权、取消、坏 helper、无 secret/path 输出、零 model_usage。
- `node --test src/views/settings/system-fields.test.mjs src/views/Settings.behavior.test.mjs`：12/12，1.1386 秒；这是前端编译组件行为测试，不是实际页面/外部连接验收。
- `npm run test:unit`：190/190，19.7408 秒。
- Core 初轮 `npm run typecheck`、`npm run build`：exit 0；随后全 core 重查发现并行 Agent hook 在途类型错误，已交其 owner 修复，全应用最终 freeze/build 由协调者合并验证，不据初轮宣称后续全部 source 已绿。
- Settings/SystemConfiguration 实际 script + inlineTemplate + 真实 API/client 依赖 TypeScript 语义检查：最终 0 diagnostics；检查发现旧 payload 必填键 delete 类型问题，已仅修可选 DTO 类型；动态 auth headers 类型由 root 在其文件修复。临时检查脚本已删除。
- 最后类型修正后两个组件关联 12/12 行为测试再次通过（1.0241 秒）；前端 `npm run build`：exit 0，37.10 秒，仅已有 chunk 大小提示。此次产物是当前共享源码快照，不代替并行 Langfuse/observability 完成后的统一部署构建。
- 使用 tmpfs 仅绕过当前磁盘 journal 阻塞，不构成磁盘持久性或性能验收。

## 源码已证明、协调者已分配的剩余项

以下记录是审查发现时的状态，不能把负责人随后开始修改当作已验证修复；删除旧 Django 前须合并其最终证据。

| 项目 | 可复现的源码链 | 状态 |
| --- | --- | --- |
| Native Langfuse session/open/clear | [settings-routes](../../packages/core/src/adapters/settings-routes.ts) 无 trusted localSession 时 501；原 [IPC](../../packages/core/src/adapters/ipc.ts) 不绑定该上下文；原 desktop 仅 external browser 打开，不能自动继承 Electron cookie | `ui_baseline` 已接完整链路；保留同主机本地自动登录、core 凭据、private cookie、受限 owned window，未以万能 URL/renderer key 绕过。 |
| 业务追踪及授权轨迹链接未接线 | [IntegrationService](../../packages/core/src/integrations/index.ts) 有真实 recordTrace adapter，但发现时没有业务调用；[journal](../../packages/core/src/jobs/journal.ts) 只折叠已有事件，未产生新授权 trace_url | `parser_baseline` 接业务观测。连接测试不是业务 trace 上报证明；`upload_eval_datasets` 配置也不能代替实际评测 adapter。 |
| Agent graph/web_fetch/read_skill 未接线 | 发现时 [application](../../packages/core/src/application.ts) 只传 integrations；[tools](../../packages/core/src/agents/tools.ts) 缺各 hook 时确定返回 NOT_CONFIGURED；旧 [agent_tools](../../personal_knowledge_base/agent_tools.py) 有实际 Graph/WebFetch/ReadSkill 实现 | `parser_baseline` 接 hooks。普通 Chat graphRetrieval 已接线，不能与 Agent 工具混为一项。旧业务 skills 目录若确实为空必须明示，不读取开发者/Codex 技能。 |

## 已存在的实现，不误记为 404/空壳

- Evaluation 真实专用 retrieval/chunking、候选逐题持久化/编辑/删除/审核/发布/版本、配置估算、任务取消/恢复、历史/报告下载已恢复。[既有本轮评测证据](20261010-evaluation-retention-parser-worker.json) 分开记录受控 HTTP/Ragas 与待 root 实际厂商/页面验收；候选不是有效题，未知付费结果不自动重放。
- [Wiki routes](../../packages/core/src/adapters/wiki-routes.ts) 包含页面/目录/search/graph/stats/log/lint/issues/status；[Wiki service](../../packages/core/src/wiki/index.ts) 实际检查坏双链并持久化状态、模型生成经文档 workflow hook。旧 [wiki/views.py](../../wiki/views.py) lint/issues 本身返回空项/静态 resolved，没有真实 auto-fix 实现，不能将旧占位算作被删除的修复能力。
- Graph 固定 namespace/generation 模板、当前源过滤、删除 outbox/tombstone cleanup、只读 readiness 与 Chat 检索 hook 已存在；外部连接未配时给真实状态/警告，不算外服通过。
- 模型四角色 CRUD/默认/思考/上下文/凭据保护/真实 runtime/用量，检索阈值/父块/关系扩展，设备撤销/密码改后撤销均有实际域实现；本轮未重复先前验收。
- WebSearch provider 有实际请求/来源结果；MCP 用真实 SDK 协议 discovery/call/close。没有真实配置时，不算连接或厂商成功。不能把内部已被路由替换的旧 Settings test 501 当成当前路由失败。
- [数据 CLI](../../packages/core/src/tools/migrate.ts) 提供 import/backup/restore；[存储实现](../../packages/core/src/storage/legacy.ts) 校验独立目标、表/文件 hash、凭据与归属，媒体、.settings、.secrets、.cache、archives 都纳入。没有旧前端“备份恢复按钮”契约，不能据没有新按钮宣称功能缺失。

## 确定的适用边界与尚未证明的问题

1. **旧 Neo4j 图迁移路径缺失（源码确定；原数据有无旧图未知）。** 当前 importLegacy 只读 SQLite/文件；旧图以每 KB label/kg 属性存在外部 Neo4j，新 [templates](../../packages/core/src/graph/templates.ts) 只查询 MarlinEntity/MARLIN_REL 和 SQLite 已发布 generation。没有旧节点/边/provenance 导出转换及导入发布路径，不能宣称原外部图自动可见，也不能用付费重新抽取冒充无损迁移。
2. **PostgreSQL 导入不在当前实现。** 当前 CLI 要求旧 db.sqlite3。原用户若是 SQLite 可按本边界验收；实际 PostgreSQL 数据存在与否尚未盘点，不能宣称全数据库引擎已迁移。
3. **Capabilities DTO 的外部兼容待判定。** 当前公共端点存在且现 EndpointResolver 所需 service_id/client_protocol/auth_modes 均提供；旧 api_version、protocol_min/max、recovery_epoch、features、limits 省略。现前端无这些字段的消费，因此未证明现 UI 失败；外部消费者仍需兼容决策。
4. **远程/PWA 明确边界。** [HTTP adapter](../../packages/core/src/adapters/http.ts) 仅 loopback 开发桥；native 为本机 IPC，无远程 HTTP 服务。浏览器 API 同源；[PwaStatus](../../frontend/src/components/PwaStatus.vue) 仅浏览器生产壳安装/更新，native 不注册 worker，不承诺完整离线知识库或设备同步。远程部署与 native 服务切换不能据源码存在就算通过。
5. **启动字段提示风险（源码可见）。** Startup API 已标 field_support，但 SystemConfiguration 表单不展示该说明；Django allowed_hosts/CORS/debug/proxy/retry 等遗留字段不能宣称作用于 TS runtime。当前修复未改该功能边界，需要单独 UI 说明决策。
6. **备份在并发写入下的跨 DB/文件一致性仍待专项验证。** 现单 DB、单文件校验存在；本轮未复测整个运行应用被取消/崩溃/同时换源时的快照。不得仅据 hash 检查推断这项已通过。
7. **105 前端 API 不是全部旧后端功能清单。** Dormant channel/share/invitation/admin collections 的原资源行可导入，不等于每个旧 endpoint 已恢复。它们没有本轮 105 API 的现 UI 调用；本轮未证明实际使用需求或完整业务等价，清理旧后端前需对其逐项适用性确认。

没有删除旧源码、提交、修改原数据或重跑厂商验收。上述待验/缺口不以固定成功、空数组、禁用正常能力或 mock 请求替代。

## 本负责人最终源码/当前构建身份

| 文件 | SHA-256 |
| --- | --- |
| Settings.vue | `d65a2ff9262be9dd5a7ca9ebd624ddbf13f7a5f88c7e7f082edce770ac869390` |
| SystemConfiguration.vue | `87f39863baa52934c5678f3fa2f415406245d53c0ddfc92434085902738ab677` |
| Settings-IVxte19U.js | `e899a94cebc0d4d46830e0ff9b4eb78abf52e6bf18dd1a5c09cb472551e1bcc9` |
| index-D5r-Vd_7.js | `894092ae9308fa6cd117a37bd85636fc1ec6f0218e971e6c59c497c9a0ad717c` |
