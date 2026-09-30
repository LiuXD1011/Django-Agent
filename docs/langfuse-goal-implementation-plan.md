# Django-Agent：Langfuse 完整接入与验收实施方案

- 编写日期：2026-09-21。
- 文档状态：待执行方案，不代表已经实现或测试通过。
- 执行者：zcode，使用其当前环境提供的 goal 模式推进。
- 选型：只完善 Langfuse，不增加 LangSmith，不迁移到 LangChain/LangGraph。
- WSL 项目根：`/home/liuxuedeng/Django-Agent`。
- Windows 项目根：`\\wsl.localhost\Ubuntu-20.04\home\liuxuedeng\Django-Agent`。
- 应用地址：`http://127.0.0.1:8000/`，执行时重新核实，避免启动重复实例。
- 下文文件清单相对于项目根；命令在 WSL 项目根、已激活的应用 Python 环境执行。

## 0. 直接交给 zcode 的 goal 启动提示词

这是自然语言提示词，不假定 zcode 存在某个特定命令行参数。

```text
请使用 goal 模式执行下面的目标，而不是只输出计划：

在 /home/liuxuedeng/Django-Agent 项目中，完整阅读并执行
/home/liuxuedeng/Django-Agent/docs/langfuse-goal-implementation-plan.md。

目标：完善现有 Langfuse 接入，使普通 RAG、Agent、串并行工具、同步和后台
子 Agent、文档处理、现有评估任务具备正确追踪；完成真实 SDK 契约、
真实服务端、业务回归、前端跳转、故障隔离与回滚验收。

先读 AGENTS.md，再通过 graphify 查询定位代码。按 P0—P7 推进，持续更新
docs/langfuse-implementation-report.md。使用宿主原生 goal 能力；
已有相同目标时继续，不重复创建，不自行设置 token 预算，
遵循宿主的 goal 状态、审批和停止规则。

保留 Django + Vue + 自研 Agent/RAG + LiteLLM，复用本地事件和用量。
先固定 SDK/服务端版本，再按对应官方 API 实现。不得用宽松 Mock 的
通过代替真实 SDK 验证。一个实际业务模型调用只产生一个带用量的 generation。
重点验证线程上下文、SSE 重连、调用耗时、trace_id 与 observation_id 区别。

只用隔离测试数据库和合成样例验证。保留用户现有修改、数据库、知识库、
Docker 卷和既有 secret。不额外接入 LangSmith，不重写 Agent 引擎，
不自动上传历史会话/真实文档，不默认开启付费服务或在线裁判。
默认关闭原始问题、回答、工具 query、文档正文的远端采集。
任何上报失败不应影响主业务，也不得导致模型被重复调用。

可由代码和本文确定的事项自行推进。凭证、部署权限或影响已有服务的操作
按宿主机制处理，明确实际需要的用户输入。
外部条件暂缺时先完成独立实现和离线测试，记录尚未完成的在线验收；
不得把 SDK 初始化成功、UI 可打开、Mock 测试通过冒充端到端成功。
所有必需项通过后才把完整 goal 标记为完成。

最终交付代码、测试、固定版本部署配置、配置示例、诊断命令、运维与回滚
文档、包含实际命令/输入/输出/退出码/追踪证据的实施报告。
修改代码后运行 graphify update .，遵守仓库生成文件的管理规则。
```

## 1. 目标、范围和完成定义

### 1.1 必须实现

把现有“有 Langfuse 代码”提升为“可部署、可验证、可排障、可关闭”的集成，同时不改变问答结果、模型调用次数、SSE 协议、租户隔离和本地统计语义。

覆盖：
1. 普通 RAG：非流式、流式、检索、生成。
2. 主 Agent：迭代、模型、工具、失败与备用模型切换。
3. 并行工具、同步子 Agent、后台子 Agent。
4. 文档处理：任务尝试、解析阶段、阶段内部模型调用。
5. 现有评估：运行摘要与可获得的逐样例评分桥接。
6. 会话轨迹的 Langfuse 跳转及权限。
7. 无配置、关闭、服务不可达、SDK 失败情况下的业务可用性。
8. 可重复部署、诊断、测试和回滚。

### 1.2 明确不做

- 不增加第二个观测平台、多后端插件框架或双写。
- 不迁移 LangChain/LangGraph，不替换现有任务执行架构。
- 不替换 SessionEvent、StreamManager、ModelUsage、本地解析进度。
- 不回填历史会话，不自动上传现有真实文档和数据集。
- 不迁移生产提示词到远程管理，不新增默认在线 LLM 裁判。
- 不新增完整 Langfuse 用户/组织管理后台。
- 点赞点踩产品、完整实验工作台、自动告警属于后续扩展，不是本轮验收要求。

### 1.3 完成定义

必须同时达到：固定版本、真实 SDK 契约、隔离回归、真实服务端可查询、真实应用最小问答、前端关联、故障与回滚验证。

缺凭证或部署权限时，可标记“实现及离线验收完成，在线验收待条件”，但完整目标尚未达成。按照宿主 goal 的规则管理等待/阻塞状态，不能虚报完成或无限重复空转。

## 2. 已核实事实与待验证风险

### 2.1 当前代码定位

| 文件 | 当前职责 | 改造方向 |
| --- | --- | --- |
| `personal_knowledge_base/observability.py` | Langfuse 门面、上下文、模型和评估上报 | 主要改造点，保持业务接口兼容 |
| `personal_knowledge_base/model_usage.py` | 本地用量、远端 generation、轨迹事件 | 关联同一调用，避免重复计费 |
| `personal_knowledge_base/model_providers.py` | Chat/Stream/角色模型/Embedding/Rerank/VLM/备用模型 | 正确的调用生命周期、失败、用量 |
| `personal_knowledge_base/llm_providers.py` | LiteLLM Chat/Embedding，HTTP Rerank | 避免叠加重复自动埋点 |
| `chat/views.py` | 当前聊天入口、RAG、后台生成和 SSE | 一轮问答根、线程交接、trace 引用 |
| `personal_knowledge_base/chat_runtime.py` | 后台线程、聊天维护 | 显式选择继承上下文或独立任务 |
| `personal_knowledge_base/agent_engine.py` | Agent 循环、串并行工具 | 迭代与真实工具执行 span |
| `personal_knowledge_base/agent_actor.py` | 子 Agent 创建、执行、等待 | 父线程捕获上下文与后台生命周期 |
| `personal_knowledge_base/rag_pipeline.py` | 并行预处理、检索 | 阶段追踪和线程传播 |
| `personal_knowledge_base/span_tracker.py` | 本地解析阶段及远端镜像 | 保留本地权威状态，镜像实际阶段 |
| `personal_knowledge_base/tasks.py` | 任务与评估上报调用 | 尝试边界、样例评分关联 |
| `personal_knowledge_base/event_log.py` | 事件写入/折叠/投影 | trace 关联事件和旧字段兼容 |
| `frontend/src/views/chat/components/TrajectoryPanel.vue` | 本地执行轨迹 | 有权限的远端跳转 |
| `config/settings.py`、`.env.example` | 配置 | 总开关、别名、默认值 |
| `requirements.txt` | 当前 `langfuse>=3.0.0` | 固定实测版本 |
| `docker-compose.langfuse.yml` | 自托管草案 | 对照选定版本官方配置修订 |
| `personal_knowledge_base/test_langfuse_observability.py` | Fake 客户端测试 | 补真实 SDK 契约和生命周期测试 |

实际路由从 `config/urls.py`、`chat/urls.py` 复核。`personal_knowledge_base/views.py` 仍有旧实现，不要默认它是活动入口，也不要盲目同步改所有重复实现；根据路由与测试保留必要兼容。

### 2.2 编写时观察到的环境状态

- 应用首页返回 HTTP 200，只证明首页可访问。
- 项目 `.env` 未发现非空 Langfuse 公钥/私钥；未核实 Django 运行进程全部环境变量。
- 默认 3000 端口：Windows 连接被拒绝，WSL 健康请求返回 502。未确认 502 来自代理还是目标服务。
- 现有 FakeLangfuseClient 多个方法接受任意 `**kwargs`；测试不证明真实 SDK 接受相同参数。
- 尚未进行真实模型问答与 Langfuse 端到端验证。

以上是时间点观察，实施时全部重新核实。

### 2.3 优先验证的源码风险

1. `agent_actor.py` 在后台 worker 内执行 `copy_context()`，不是在父线程捕获。
2. `agent_engine.py`、`rag_pipeline.py` 线程池直接提交任务，没有显式传播追踪上下文。
3. `_call_context` 字典原地更新；复制 Context 不会深拷贝其值，并发存在污染风险。
4. `close_business_trace()` 把当前 span 清为 None，而不是恢复外层父级。
5. `report_model_call()` 事后创建并立即结束 generation，未用 duration 建立真实时间范围。
6. Agent 追踪将句柄 `.id` 赋给 trace_id，需核对 observation ID 和 trace ID 区别。
7. 工具参数、文档标题可能进入 metadata，关闭 input/output 不代表全路径脱敏。
8. 旧 API 与无上界 SDK 依赖组合存在升级风险，v4 已调整 observation 创建接口。[S3]
9. Fake 接受的 usage、session/user 等字段必须按真实 SDK 签名验证。
10. worker 清理上下文不会清理原请求线程上下文；需要显式设计交接和 scope 退出。

这是静态风险分析，不代表每条路径都已经运行复现。

## 3. 总体架构与关键决策

### 3.1 轻量门面，远端旁路

保留 `observability.py` 公共函数，内部按需要拆分适配、上下文、脱敏逻辑。业务只使用项目接口，SDK 版本差异收敛到适配层。

本轮只有 Langfuse 和 No-op 行为，不预建多平台注册中心。
本地事件/用量/解析状态仍是业务事实源，Langfuse 是观测副本。
SDK/上报失败不得导致模型再次调用、业务事务回滚或消息终态改变。

### 3.2 先固定版本，再写代码

P0 记录实际 Python、Django、LiteLLM、Pydantic、SDK、服务端版本。

默认优先沿用现有 v3 服务端路线，选固定 v3 SDK，缩小改动；前提是执行时该组合仍满足官方支持、兼容和需求。若现有环境已是 v4，或没有合适 v3 组合，记录理由后采用固定 v4 组合。

只实现一套主版本。最终不得保留无上界 `langfuse>=3.0.0`、镜像 `:latest` 或仅大版本漂移标签。不在方案里猜未经验证的小版本，由 P0 实测选择并锁定。[S2][S3]

上传兼容、查询兼容分别验证。同名大版本不是兼容的充分条件，官网最新签名也不一定适用于锁定旧版。

### 3.3 ID 契约

| 标识 | 定义 |
| --- | --- |
| session_id | 本地会话，关联 Langfuse session；必要时加环境/租户命名空间 |
| request_id | 一轮问答，保留原格式 |
| message_id | 助手消息，关联本地展示和后续反馈 |
| trace_id | SDK 正式接口取得的远端 trace ID |
| observation_id | 单节点 ID，不能与 trace_id 混用 |
| actor_id / parent_actor_id | 子 Agent 身份与业务父级 |
| model_call_id | 建议新增，调用前生成，关联本地用量与唯一 generation |
| attempt / attempt_id | 模型尝试、任务重试、文档处理尝试 |
| task_run_id | 解析或评估任务执行身份 |

不直接把 UUID request_id 当作 OTel trace ID，除非通过正式转换 API 并验证。
远端 ID 在本地取得，不等待网络上传。
本地有 ID 只代表引用已记录，不代表服务端已经接收。

### 3.4 追踪层级

```text
chat.turn                              一轮问答
  rag.prepare                          按实际路径执行
    query.understand
    memory.retrieve
    history.retrieve
  rag.retrieve
    retrieval.hybrid
    retrieval.rerank
  answer.generate
    llm.attempt                        唯一计入该调用用量的 generation
  answer.persist

chat.turn                              Agent 模式
  agent.run
    agent.iteration
      llm.attempt
      tool.<registered_name>
        agent.run                      需要等待完成的子 Agent
          llm.attempt
          tool.<registered_name>
  answer.persist

knowledge.process                      单次文档处理尝试
  stage.parse / stage.chunk / stage.embed / stage.wiki

evaluation.run                         现有评估任务
  evaluation.example
    retrieval / generation / evaluator（实际存在时）
```

名称稳定，动态 ID 放属性。SDK 不支持专用节点类型时用 span + kind。
Embedding/Rerank 按真实业务与 SDK 能力分类，不伪造 Chat 响应。
不产生未执行阶段的假节点。

### 3.5 生命周期

- 问答根从业务处理开始到权威终态/持久化结果产生结束，不跟 HTTP response 或 SSE 连接结束绑定。
- RAG 检索目前在请求线程发生：通过显式句柄衔接生成线程，不为追踪大改执行架构。
- ContextVar/OTel scope 必须在创建它的线程及 Context 内退出，不跨线程使用 reset token。
- joined 子 Agent 留在主 trace；允许独立继续的 detached 子 Agent 建新根，记录 parent_trace_id/request_id/actor_id。
- 回答后的标题、摘要、记忆整理是独立 `chat.maintenance`，通过 originating_request_id/trace_id 关联。
- 文档实际重试产生新的远端尝试，本地复用阶段行不代表远端复用同次执行。
- 成功、失败、取消、超时、降级完成分别标记。
- 超时/取消终态不被晚到成功覆盖，关闭动作幂等。
- 进程强杀不能保证 SDK 队列发送；保留本地 interrupted/recovered 事实，不承诺强杀零丢失。

## 4. 核心实现设计

### 4.1 公共接口

以下是拟定的项目接口，不是可直接调用的官方 SDK 签名：

```python
start_business_trace(name, *, session_id='', user_id='', metadata=None)
close_business_trace(handle, output=None, *, status='completed', error=None)
child_span(name, metadata=None)
trace_agent_execution(session_id, user_id, query, agent_mode='')
trace_llm_call(trace_ctx, model, messages, tools=None)
trace_tool_execution(trace_ctx, tool_name, args)
start_model_call(*, model_call_id, model, provider, scenario, metadata=None)
finish_model_call(handle, *, usage, status, output_preview='', error=None)
report_model_call(...)   # 保留兼容，更新关联调用而不是重复创建
flush_langfuse()          # 诊断/退出使用，不在每个请求或 token 上调用
```

TraceHandle 明确 SDK 句柄、trace_id、observation_id、父引用、结束状态。
上下文 scope 和句柄生命周期分离；幂等结束应支持并发终结竞争。

SDK 初始化、创建、更新、结束、flush 的错误只影响观测。
包围业务函数的上下文管理器必须保留业务异常，不能吞掉业务错误或把业务重跑。
不要用一个覆盖整个业务块的 catch 把所有异常都当作“Langfuse 故障”。

### 4.2 线程传播

```python
from contextvars import copy_context

# 在父线程执行，每个并发任务独立复制，不能并发进入同一个 Context。
ctx = copy_context()
future = executor.submit(ctx.run, work, *args)
```

业务上下文按 copy-on-write 更新，不能修改共享字典。
嵌套结束使用 token 恢复；同时验证 SDK 的 OTel 活动上下文。
若统一线程启动助手，调用点显式选择继承还是独立关联。
更改 `run_database_background` 时审计所有使用者，不让维护任务全部误挂主问答根。

### 4.3 模型生命周期和用量

1. 实际供应商请求前创建 generation，流式在迭代结束/取消/关闭后结束。
2. ModelUsage 继续本地记录，远端更新同一个 model_call_id 的 generation。
3. 上层 trace_llm_call 仅作为不计费用量的业务 span，或复用同一 generation；选一种。
4. 不同时启用会重复记录调用的 LiteLLM callback、SDK 自动 wrapper 和手工上报。
5. 本地内部模型跳过统计规则保持不变，远端/本地按相同范围对账，说明范围差异。
6. 审计 Chat、角色模型、Embedding、Rerank、VLM、摘要、标题、查询理解所有入口。
7. usage_source=provider/estimated/unavailable，缺失不冒充准确零。
8. 缓存/推理 token 是输入/输出子集，不重复累加；未知价格显示未知。
9. model_call_id 优先存 ModelUsage.metadata 和 LLM_CALL 事件，避免不必要迁移。
10. 业务可见备用模型尝试分别记录；LiteLLM 透明内部重试无可靠钩子时不虚构逐次统计。
11. TTFT 与首个可见文本延迟区分，考虑纯工具调用和 reasoning chunk。
12. UTC 记录真实起止，monotonic 计算耗时，不把 monotonic 当日期。

### 4.4 隐私与内容

默认 LOG_CONTENT=false，检查 input、output、metadata、error、自动埋点所有出口。

默认允许：内部标识、模型/供应商、阶段、计数、耗时、token、状态、版本。
默认不发送：问题、回答、工具 query/prompt、文档标题/正文、邮箱用户名、认证头、
Cookie、密钥、带凭证 URL、图片 base64、附件、原始 reasoning。

本地 event_log 白名单不是远端上传白名单。
开启内容采集仍需脱敏、截断、嵌套深度和总大小限制，标记 truncated。
必须对异常文本进行相同审计，不能只处理正常输出。
传播属性和 observation metadata 按固定 SDK 的不同限制分别处理。[S3]

### 4.5 旁路故障与运行状态

- SDK 异步批量上报；不新增逐 token 网络请求。
- 主业务禁止网络 auth_check、flush、查询轮询。
- 初始化失败日志限频，明确重试/重启策略，避免永久静默失效。
- 队列有界，退出 flush 有界；观测可丢弃但业务不阻塞，记录丢弃/错误计数。
- 诊断区分 disabled/missing_credentials/sdk_missing/initialized/auth_failed/unreachable/verified。
- initialized 不等于健康，上报链接存在不等于远端入库。
- pre-fork 前不要提前启动 exporter 线程，客户端按实际进程生命周期初始化。
- 避免 Django autoreload 重复注册 exporter。
- 本轮不建设可靠 outbox；评分重试有界且幂等。

## 5. 配置、部署和诊断

### 5.1 配置表

下列包含项目自定义项，必须在 settings/适配层实现，不是全部都由 SDK 原生读取。

| 配置 | 默认/要求 | 说明 |
| --- | --- | --- |
| LANGFUSE_ENABLED | false | 显式总开关；关闭不出网 |
| LANGFUSE_BASE_URL | 部署时配置 | 新配置首选，适配锁定 SDK |
| LANGFUSE_HOST | 兼容旧配置 | 仅 BASE_URL 未设置时使用 |
| LANGFUSE_PUBLIC_KEY / SECRET_KEY | 空 | 后端凭证，缺失关闭 |
| LANGFUSE_LOG_CONTENT | false | 脱敏后内容采集 |
| LANGFUSE_ORPHAN_MODE | skip | standalone 显式开启 |
| LANGFUSE_UPLOAD_EVAL_DATASETS | false | 仅批准的合成数据用于本轮验收 |
| LANGFUSE_TRACING_ENVIRONMENT | development | 验证 SDK 支持并适配 |
| LANGFUSE_SAMPLE_RATE | 1.0，开发验收 | 根级决定，子节点继承，不与 SDK 重复独立采样 |
| LANGFUSE_UI_BASE_URL | 默认 BASE_URL | 浏览器可访问地址，区分容器 API 地址 |
| LANGFUSE_TRACE_LINKS_ENABLED | false | 授权角色跳转开关 |

新增 ENABLED 会改变“有密钥即启用”的旧行为，升级说明明确要求老部署设置开关。
开发、生产分项目/凭证；不要仅靠 metadata 当访问隔离。
共享 Langfuse 项目只向平台级运维角色提供链接，不能默认给每个业务租户管理员。
租户独立项目与凭证映射属于以后独立需求。

### 5.2 Compose 修订

以锁定服务端版本官方 Compose 为基准，不把现有草案当作可运行部署。[S4]

必须核对：
- web/worker/PostgreSQL/ClickHouse/Redis/对象存储版本及依赖。
- 当前 S3_*、REDIS_URL、ClickHouse 参数是否是该版本有效配置。
- MinIO entrypoint/command 是否正确、凭证长度是否合规。
- 必要 bucket 初始化、对象存储访问权限。
- migration 地址、加密密钥、认证 secret 等该版本必需参数。
- healthcheck、服务就绪、持久化、worker 可消费上报。
- 首次随机 secret；已有部署不重置 secret 或加密密钥。
- 本地入口绑定 127.0.0.1，不额外暴露内部数据库。
- Windows/WSL/容器不同地址和代理；必要时仅对 localhost 健康检查验证代理影响。
- 项目凭证按该版本支持方式创建，禁止硬编码真实密码。
- 用 config --quiet 验证，不把展开后的秘密写到日志。

有现有卷时先检查备份和版本，不自动大版本升级或重建数据。
默认仅本地部署，不购买云资源。

### 5.3 拟新增管理命令 langfuse_check

- 默认：配置存在性、版本、脱敏 endpoint、SDK 兼容性。
- --network：有时限的健康和凭证验证，区分可达与鉴权成功。
- --smoke：创建合成根、子节点和固定用量 generation，带 test_run_id。
- smoke 不调用真实 LLM，避免平台检查产生模型费用。
- flush 后通过固定版本的查询 API 证明入库，退避轮询有截止时间。
- 明确退出码，不把缺凭证/不可达当成功。
- 不删除任何非本次 test_run_id 的数据，不修改业务数据库。
- 查询不在聊天主流程执行；SDK 构造成功不是该命令成功标准。

## 6. 事件与前端

新增注册事件 `observability/trace-linked`，只携带 provider、trace_id、root_observation_id 和归属信息。
更新 KNOWN_EVENT_TYPES、fold_trajectory，遵循已有 FOLD_VERSION 版本规则和测试。

创建根时记录关联，不只在 turn/completed 写字段，确保失败/取消也能定位。
旧 turn/completed.langfuse_trace_id 继续读取，不改写历史 append-only 事件。

建议增量投影：

```json
{
  "langfuse_trace_id": "真实 trace ID，兼容字段",
  "observability": {
    "provider": "langfuse",
    "trace_id": "真实 trace ID",
    "root_observation_id": "根 observation ID",
    "trace_url": "仅后端授权后返回",
    "link_state": "recorded"
  }
}
```

recorded 只代表本地引用存在，不在每次获取轨迹时查询远端。
URL 由服务端可信配置与官方 URL 能力/验证过的路由构造，不从用户内容读取。

前端要求：
- 每轮轨迹增加“查看 Langfuse 追踪”，保留原轨迹面板。
- 缺 ID、关闭或无权限隐藏；旧记录正常渲染。
- 限制 URL 协议/主机；新标签设置 noopener noreferrer。
- 前端无 API Key，不调用 Langfuse 管理接口，不自动公开 trace。
- Django 访问控制和 Langfuse 页面授权两层都要成立。
- 远端不可用不影响本地轨迹加载。

## 7. 文档处理与评估

### 7.1 文档处理

KnowledgeProcessingSpan 保持业务权威来源。
每个实际处理尝试一条根，解析/分块/向量/wiki 等实际阶段镜像。
模型调用隶属真实阶段，跳过的阶段不生成假工作。
默认只有 knowledge_id/kb_id/attempt/计数/耗时/状态，不上传标题、路径、正文或图片。
远端写失败不得触发文档重解析，本地重试保留远端尝试区分。

### 7.2 本轮最低评估桥接

- 复用现有评估结果，不为了 Langfuse 重跑模型或裁判。
- evaluation.run 关联 task_run_id、配置/数据集版本、样例数、指标、失败数。
- 已有逐样例执行边界产生 evaluation.example，挂已有评分。
- 只有汇总指标的旧任务只上报汇总，不伪造逐样例值。
- score 名称、量纲、范围、归属明确，不能把平均值复制给每个样例。
- item/score 使用稳定标识加版本，重复同步幂等。
- 数据集上传默认关闭；用 3 条合成样例验收 item/score 去重和版本变化。
- 上传失败不改变本地任务成功状态，不默认启用在线裁判。
- 完整实验管理、提示词远端发布、点赞点踩产品留待后续。

## 8. 分阶段执行清单

每阶段更新实施报告：文件、决策、实际命令、退出码、结果和未完成项。

### P0：基线和版本路线
- [ ] 阅读 AGENTS.md、graphify 查询、核对真实路由和旧接口。
- [ ] 记录 Git HEAD、未提交修改、拟改文件 SHA-256；保留用户修改。
- [ ] 找到业务 Python 环境，记录版本，区别图谱专用解释器。
- [ ] 检查服务/容器/端口/卷，只报告秘密存在性。
- [ ] 跑聚焦基线，区分原有失败。
- [ ] 固定 SDK/服务端组合，验证 API、参数、ID 和查询兼容。
- [ ] 建立实施报告和验收矩阵。

### P1：配置、部署与 SDK 契约
- [ ] 总开关和别名，更新 .env.example，不覆盖 .env。
- [ ] Compose 固定版本，修订依赖/对象存储/健康检查。
- [ ] 实现 langfuse_check。
- [ ] 真实 SDK 创建/update/end/usage/ID/父子契约测试。
- [ ] 合成 trace 在真实服务端可查询，内容/层级/用量准确。

### P2：门面、上下文、隐私
- [ ] 保留业务入口，句柄和 scope 分离。
- [ ] 嵌套恢复、幂等结束、copy-on-write。
- [ ] 所有出口统一脱敏。
- [ ] 关闭/缺依赖/缺密钥/SDK 各阶段异常测试。
- [ ] 业务异常原样传播、不重复业务执行。

### P3：模型、RAG 与流式
- [ ] 模型请求开始建立 generation，流式消费结束后关闭。
- [ ] model_call_id 关联本地和远端，一份用量。
- [ ] chat.turn 覆盖预处理/检索/生成/持久化。
- [ ] 请求线程和后台线程正确交接。
- [ ] 成功、失败、取消、重连、备用模型测试。
- [ ] 输出、SSE 顺序、本地统计规则保持兼容。

### P4：工具和多 Agent
- [ ] span 包围实际工具执行，不在 future 收集后补造。
- [ ] 每个并行任务独立复制 Context。
- [ ] joined 与 detached 子 Agent 明确区分。
- [ ] 维护独立关联，晚到成功不覆盖终态。
- [ ] 并发请求、租户、actor、iteration 无串扰。

### P5：解析与评估
- [ ] 解析阶段和重试镜像，保留本地状态。
- [ ] 现有任务摘要与可获得样例评分桥接。
- [ ] 3 条合成样例重复同步与版本变化测试。
- [ ] 内容/数据集关闭时不外传正文和参考答案。

### P6：事件与前端
- [ ] 注册/折叠 trace-linked，兼容旧字段。
- [ ] 失败、取消、重连保留关联。
- [ ] 后端角色/租户/URL 控制测试。
- [ ] Vue 链接、历史记录、关闭态测试与构建。

### P7：最终验收
- [ ] 第 9 节所有必需场景通过。
- [ ] 真实应用最小模型问答并查询远端。
- [ ] 关闭、启用、远端故障性能比较。
- [ ] 隔离 Langfuse 停止/恢复，业务继续正常。
- [ ] 隔离副本回滚演练。
- [ ] graphify update、运维文档、实施报告。
- [ ] 所有必须项有证据后才完成整体 goal。

## 9. 测试策略和验收标准

### 9.1 四层测试

1. 门面单元：确定性时钟、记录器、故障注入。
2. 真实 SDK 契约：真实 SDK 对象和参数，在传输/导出边界接本地 sink；不能用万能 Fake 替代核心 SDK。
3. 真实服务：合成 trace，无需模型，正式查询确认存储和关系。
4. 应用 E2E：实际路由、合成输入、少量真实模型请求、Langfuse API/UI 证据。

数据库测试使用 Django 测试数据库或独立实例。部分 tests 使用 unittest.TestCase 并手动 django.setup，执行前审计，禁止指向运行中的 db.sqlite3。
运行中的 SQLite 备份采用一致性机制，不随意复制一个 db 文件忽略 WAL。

### 9.2 验收矩阵

| ID | 场景 | 必须断言 |
| --- | --- | --- |
| A01 | 关闭 | 不出网，业务/本地记录正常 |
| A02 | 缺 SDK/缺凭证/无效凭证 | 分别诊断，业务不受影响，日志无密钥 |
| A03 | SDK smoke | 真实服务可查询根/子/generation，ID 和用量正确 |
| A04 | 非流式 RAG | 一轮一个根，检索与生成正确，调用次数不变 |
| A05 | 流式 RAG | 生命周期覆盖消费，耗时/用量正确 |
| A06 | 断线重连 | 无重复生成/根，回答和 trace 引用一致 |
| A07 | 模型失败切换 | 业务可见尝试分别记录，失败和成功区分 |
| A08 | 串行及两个并行工具 | 时间包围执行，父级正确，不重复 |
| A09 | 同步/后台子 Agent | joined 嵌套，detached 独立关联 |
| A10 | 两租户两会话并发 | request/actor/iteration/内容不串扰 |
| A11 | 嵌套 scope | 内层结束恢复外层，兄弟父级正确 |
| A12 | 取消/超时/异常/晚到结果 | 只终结一次，终态不覆盖 |
| A13 | SDK create/update/end/flush 错误 | 不吞业务异常、不重跑模型 |
| A14 | usage 已知/缺失/缓存/推理 | 单调用唯一 generation，不重复相加 |
| A15 | 内容关闭 | 所有 payload 无问题、答案、工具 query、标题、秘密、图片 |
| A16 | 内容开启 | 脱敏/截断生效，秘密仍不发送 |
| A17 | 解析成功/失败/重试 | 本地阶段不变，尝试与模型归属准确 |
| A18 | 合成评估重复同步 | 无重复 item/score，版本变化可区分 |
| A19 | URL 权限与历史 | 授权角色可跳转，跨租户不泄漏，旧数据正常 |
| A20 | 停止/恢复 Langfuse | 业务可用，诊断准确，新请求恢复 |
| A21 | 重启/autoreload | 不重复 exporter，无新请求上下文污染 |
| A22 | 关闭和回滚 | 原业务恢复，本地/远端数据保留 |

A03 必须真实 SDK+服务；A04/A05 至少各一条真实应用模型请求。
A07—A14 可用受控模型/工具做确定性故障注入，并把并发、嵌套、错误各抽一条到真实服务确认。
控制真实模型调用量，不批量跑用户知识库。远端证据记录 test_run_id/request_id/trace_id、父子结构、查询时间、用量；截图不能替代断言。

### 9.3 性能目标

固定机器、版本、输入，预热后以确定性短请求各跑至少 100 次：
关闭、启用、上报服务不可达三组，记录 p50/p95/首响应时间。

拟定门槛：相对关闭，p95 额外延迟不超过 max(20ms, 基线 p95 的 5%)。
这是项目验收目标，不是 SDK 性能承诺。失败先定位，不能为通过直接抬阈值。
模拟模型测开销，真实模型验证链路；另记队列容量、内存趋势、丢弃/错误计数。

## 10. 执行命令参考

下列命令供实施阶段使用，不表示编写本文时已执行。
确认应用 Python 环境、审批和测试隔离后运行：

```bash
cd /home/liuxuedeng/Django-Agent
git status --short
python --version
python -m pip show Django langfuse litellm pydantic
python -m pip check
graphify query "langfuse observability trace"

python manage.py check
python manage.py test \
  personal_knowledge_base.test_langfuse_observability \
  personal_knowledge_base.test_llm_providers \
  personal_knowledge_base.test_stream_finalization \
  personal_knowledge_base.test_stream_persistence \
  chat.test_stream_protocol
```

执行时核实模块存在和实际测试发现数。新增契约/隐私/并发测试在创建后加入，未发现测试不算通过。
全量回归前审计外部模型调用、文件写入和数据库使用，采用独立配置。

Compose 修订、版本决策和必要备份完成后：

```bash
cd /home/liuxuedeng/Django-Agent
docker compose -f docker-compose.langfuse.yml config --quiet
docker compose -f docker-compose.langfuse.yml up -d
docker compose -f docker-compose.langfuse.yml ps

# 以下依赖 P1 新增实现，当前尚不保证命令存在。
python manage.py langfuse_check
python manage.py langfuse_check --network
python manage.py langfuse_check --smoke
```

前端和最终检查：

```bash
cd /home/liuxuedeng/Django-Agent/frontend
npm run build

cd /home/liuxuedeng/Django-Agent
python manage.py makemigrations --check --dry-run
git diff --check
graphify update .
git status --short
```

复用既有包管理器与依赖，不因为 npm 示例擅自替换 pnpm-lock.yaml。
graphify 不在 PATH 时按 skill 定位，不把图谱 Python 用作业务运行环境。

## 11. 回滚和恢复

### 11.1 配置关闭
设置 ENABLED=false，按原部署方式重启 worker。
验证新请求无导出，普通/Agent/SSE/本地统计正常。
队列已排数据按文档策略处理，关闭不会撤回已经上传的数据。
保留凭证和平台数据，不删数据库和卷。

### 11.2 代码/依赖
P0 保存基线摘要、补丁或提交边界，识别用户既有修改。
在隔离副本回退本轮代码和固定依赖，验证旧业务。
新事件按可忽略增量设计，旧版本保留原字段读取。
尽量不新增迁移；确需迁移则验证旧代码兼容与非破坏恢复。
不得用 reset --hard、清空工作区或覆盖 .env 作为自动回滚。

### 11.3 服务端
只停止本轮新增独立实例；共享既有实例操作需确认。
不执行 docker compose down -v，不清持久卷。
已升级数据库不能仅回退镜像 tag；验证兼容或从已测试备份恢复。
备份覆盖所选版本要求的数据库、对象存储和持久配置，恢复演练在独立实例。

## 12. 交付物与报告模板

必须交付：
1. 聚焦本轮目标的代码和回归测试。
2. 固定版本依赖及可验证 Compose。
3. 不含真实凭证的 .env.example。
4. `personal_knowledge_base/management/commands/langfuse_check.py` 或等价入口。
5. `docs/langfuse-operations.md`：启动、配置、鉴权、诊断、升级、关闭、备份和回滚。
6. `docs/langfuse-implementation-report.md`：阶段、命令、退出码、实际证据。
7. 按项目规则更新 graphify。

报告模板：

```markdown
# Langfuse 实施报告
## 环境与固定版本
## 基线 Git 状态、受影响文件与 SHA-256
## P0—P7 状态
## API、生命周期、兼容性、隐私决策
## 测试结果
| 用例 | 命令/操作 | 输入 | 实际输出摘要 | 退出码 | 证据 | 状态 |
## 真实服务与应用追踪证据
## 用量对账和口径差异
## 性能、故障注入
## 回滚与恢复演练
## 未完成项、外部依赖、后续建议
```

状态用 PASS/FAIL/NOT_RUN/BLOCKED；未运行不算通过。
每项写实际输入输出，日志去除秘密。阶段完成不自动代表整体完成。

## 13. 最终设计自查

- [ ] 无无上界 SDK/镜像漂移，真实 SDK 契约通过。
- [ ] trace 链接用 trace_id，不是 observation_id。
- [ ] SSE 重连不创建新执行或新模型调用。
- [ ] 工具 span 包围真实工作。
- [ ] 并行 Context 独立，字典 copy-on-write，嵌套恢复完整。
- [ ] 请求/生成/维护线程各自退出 scope。
- [ ] 一次调用只有一份用量，透明重试没有虚构统计。
- [ ] LOG_CONTENT=false 覆盖 metadata、异常、自动埋点。
- [ ] 远端失败不造成模型重试、事务回滚、SSE 中断。
- [ ] 共享项目链接不让普通租户角色看到其他租户数据。
- [ ] 评估同步幂等，不重复裁判调用。
- [ ] 强杀、队列丢失、查询最终一致性有明确边界。
- [ ] 回滚保留原数据、卷、secret 和用户修改。

## 14. 官方参考资料

执行时按固定版本选择文档；不要把最新 API 直接套在旧 SDK 上。

- [S1 SDK 总览](https://langfuse.com/docs/observability/sdk/overview)
- [S2 版本兼容](https://langfuse.com/docs/compatibility)
- [S3 Python v3 → v4](https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4)
- [S4 Docker Compose 部署](https://langfuse.com/self-hosting/deployment/docker-compose)
- [S5 Instrumentation](https://langfuse.com/docs/observability/sdk/instrumentation)
- [S6 Python SDK Reference](https://python.reference.langfuse.com/langfuse)
- [S7 产品文档](https://langfuse.com/docs)

本文的事件名、管理命令、性能阈值、阶段和接口草案是项目设计，不是官方 SDK 已有接口或已完成实现。
