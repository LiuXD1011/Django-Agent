# Langfuse 实施复核与修复报告

> 更新：2026-09-22。本文是对 zcode 实现的独立代码复核结果，替代原先“全部验收 PASS”的结论。
> 原报告、改动前文件及 SHA-256 保存在项目的 .cache/langfuse-review-20260922/original/ 与 baseline-hashes.json。
> 本轮没有启用/重启正在使用的 8000 服务，没有修改应用或 Langfuse 的 .env，也没有调用付费模型。

## 1. 结论

接入方向可以保留：用项目自有 observability 门面包裹 Langfuse，保留本地 SessionEvent / ModelUsage / KnowledgeProcessingSpan 作为业务事实源。不过原实现存在实际业务故障、追踪上下文串线、错误状态丢失、用量映射不正确，以及默认隐私开关覆盖不完整等问题，已针对复现路径修复。

- 修复前，第一批新增的 **19 个回归测试全部失败：18 failures + 1 error**。
- 修复后，**156 个相关测试全部通过**（包括 25 个本轮独立回归、14 个真实 SDK 契约测试），Django system check 为 0 issues。
- 本机 Langfuse **真实合成冒烟通过**：服务端回读校验根/子/generation 类型、父子关系、结束时间、session_id、trace_id 和固定用量。
- 缓存/推理 token 的扁平映射已经额外在真实服务端回读验证，不只是在 Fake 或内存导出器里检查 JSON。
- 这不是“所有业务路径已端到端验收”：本次未重新进行真实模型问答、备用供应商切换、浏览器交互、进程强杀、autoreload、停服恢复、完整请求性能基准等实机验收。

## 2. 已修复的问题

| 优先级 | 问题 / 影响 | 实际修复 |
| --- | --- | --- |
| P1 | 非流式 Agent 分支先引用局部 obs，且未创建 engine；请求可直接 500 | 移除遮蔽模块导入的局部 import；恢复 AgentEngine 初始化；新增真实视图回归 |
| P1 | 流式 RAG 将根句柄留在请求 Context；下一轮请求可能嵌套到上一轮 | 请求级 request_trace_scope 负责清理 Context；后台保留复制的上下文，独立负责结束 span |
| P1 | RAG 准备/后台生成/Agent 执行异常或 GeneratorExit 时，追踪漏结束或标为成功 | 异常与 finally 路径补齐；失败映射 ERROR；工具返回 error 也进入错误状态 |
| P1 | 根被采样丢弃后，嵌套 Agent 会重新抽样；standalone 模式还能复活模型节点 | 使用无远端 span 的空句柄传播“不采样”决定，子树不再单独抽样 |
| P1 | standalone 模型调用解引用 None；rerank span.update 收到不支持的 usage_details | 无父级时从 client 创建；仅 generation/embedding 更新用量，span 正常更新状态并结束 |
| P1 | 缓存/推理 token 用嵌套字典上传；SDK 能序列化并不代表服务器语义正确 | 扁平整数用量 + 互斥分类，见 §3 |
| P1 | LOG_CONTENT=false 仍可能上传标题、query、嵌套正文和异常文本；token 数又被误当密钥删去 | 默认隐藏内容字段/错误详情；保留数值 token 指标和内部消息 ID；补充 Bearer/JSON 凭证打码及深度/条目上限 |
| P2 | 客户端已缓存后，总开关被绕过；首次并发初始化缺乏锁 | 开关检查优先于缓存；客户端初始化加锁。已排队数据仍可能发送，运行配置变更需重启 |
| P2 | ModelCall 生命周期创建失败后又走事后 report_model_call，造成错误时间范围或重报 | 以 model_call_id 判断生命周期已尝试，不再补造 generation |
| P2 | APP_TASKS_SYNC 下 chat.maintenance 继承主问答根，不是真正独立任务 | 显式 detached scope，并记录 originating_trace_id/request_id |
| P2 | 用户模型没有 is_staff，实际平台管理员看不到链接；旧轨迹字段无规范跳转 | 按 is_active + is_system_admin 授权；支持历史 trace 字段；校验 32 位 hex、项目 ID、HTTP(S) URL，转义路径 |
| P2 | Dataset item 无稳定 ID，重复运行堆积相同题目；上传开关绕开内容开关 | dataset + version + 脱敏后的内容生成稳定 ID；上传必须同时开启两个开关 |
| P2 | smoke 在首个不完整 HTTP 200 后直接判错，且缺少根/结束状态校验 | 在真实截止时间内重试最终一致性；完整校验后才 PASS；查询禁止隐式重试并限制超时 |
| P2 | 诊断声称 endpoint 脱敏，却原样打印地址、异常和响应正文 | endpoint 只打印 scheme/host/port；不打印查询串、userinfo、远端错误正文和异常详情 |
| P2 | 原报告已列出的两个断流测试失败长期保留 | 断流错误使用通用“生成失败”；发送 SSE 时读取 CAS 最终结果，成功完成的回答不被重放为错误 |

最后一行是独立存在的断流问题，不把它归因于 Langfuse；本轮一并修复，原测试无需修改即可通过。

## 3. 正确的用量口径

本地 ModelUsage 保持供应商口径：prompt_tokens 包含缓存，completion_tokens 包含推理。

远端 usage_details 使用扁平数值和互斥分类：

~~~json
{
  "input": 20,
  "input_cached_tokens": 80,
  "output": 20,
  "output_reasoning_tokens": 10,
  "total": 130
}
~~~

对应本地 prompt=100、completion=30、cached=80、reasoning=10。
非 total 项之和等于 total；不把缓存或推理 token 再重复加到输入/输出中。
异常的子集值限制在对应总量内；本地计费记录保持原规则。

- 服务端回读 trace：891b4a1550b040111904ec9836c172a1。
- 服务端返回与上述 JSON 完全一致；见 TOKEN_READBACK.log。
- 官方口径：[Token & cost tracking](https://langfuse.com/docs/observability/features/token-and-cost-tracking)。
- 模型价格表仍需与自定义 token 分类匹配；本次验证的是数量映射，不声称费用账单已完成逐项对账。

## 4. 本轮验证

解释器：/home/liuxuedeng/anaconda3/envs/django-agent/bin/python。
SDK：3.15.0；沿用当前锁定服务版本，不升级依赖。

### 4.1 基线与修复后

~~~bash
# 在项目目录，用上述解释器运行。
LANGFUSE_ENABLED=false python manage.py test \
  personal_knowledge_base.test_langfuse_review \
  personal_knowledge_base.test_langfuse_observability \
  personal_knowledge_base.test_langfuse_sdk_contract \
  personal_knowledge_base.test_langfuse_model_lifecycle \
  personal_knowledge_base.test_langfuse_p4_multiagent \
  personal_knowledge_base.test_stream_finalization \
  personal_knowledge_base.test_actor_events \
  personal_knowledge_base.test_llm_providers \
  personal_knowledge_base.test_stream_persistence \
  chat.test_stream_protocol \
  tests.test_session_trajectory --noinput -v 1
python manage.py check
~~~

| 验证 | 结果 | 退出码 / 证据 |
| --- | --- | --- |
| 修复前首批 19 个新增回归 | FAILED (failures=18, errors=1) | 1；BASELINE.log |
| 修复后相关测试 | Ran 156 tests；OK | 0；MODIFIED.log |
| Django 配置检查 | System check identified no issues (0 silenced). | 0；CHECK.log |
| 合成 smoke | verified + PASS | 0；SMOKE.log |
| 真实缓存/推理用量回读 | TOKEN_BUCKET_READBACK PASS | 0；TOKEN_READBACK.log |
| 隔离副本回滚 | 见 VERIFICATION.txt 的命令、哈希校验和复现结果 | 回滚只恢复到本轮复核前的 zcode 工作区，不回退到 Git HEAD |

所有证据位于项目 .cache/langfuse-review-20260922/，其中测试日志里的异常来自合成故障注入，不是未处理的测试失败。
真实 SDK 测试使用内存 exporter + 本地 HTTP sink；smoke 和 token 回读才是真实 Langfuse 服务入库验证。

### 4.2 合成 smoke

~~~bash
# 仅向此命令进程注入本机项目凭证；不在命令行写明密钥。
# LANGFUSE_ENABLED=true, LANGFUSE_SAMPLE_RATE=1, LANGFUSE_LOG_CONTENT=false
# LANGFUSE_BASE_URL=http://127.0.0.1:3000
# NO_PROXY=no_proxy=127.0.0.1,localhost
python manage.py langfuse_check --smoke --deadline 30
~~~

- trace_id：8b6289bba2a6b4ade070168608afe49e
- root_observation_id：b9a98855dc3f2735
- 合成 input=42、output=17。
- 此命令不调用真实 LLM；生成的合成记录保留在本机 Langfuse。
- --deadline 约束回读轮询，不包含配置、健康检查、鉴权、上传/flush 和进程退出。

## 5. 原报告中应撤回或降级的结论

1. 原来的 SDK 契约测试只证明嵌套 usage_details 可以序列化，不能证明缓存/推理统计正确；本轮已改测试并实际回读。
2. --noreload 实例重启不等于验证 autoreload，也不证明 SIGTERM 会运行 atexit；这些仍需进程级实测。
3. Fake 权限测试通过不等于真实 User 模型具备 is_staff；本轮新增真实模型的系统管理员回归。
4. 评估 Dataset 现在具备稳定 item ID；但 report_evaluation_run 仍是任务结束后的结果桥接，不是完整评估生命周期埋点，也没有完整关联 Langfuse Dataset Run。
5. 确定性 score_id 是局部去重机制，不代表整个评估 trace/observation 重复同步幂等；重放仍可能新增 trace。完整同步幂等与真实时序是后续工作。
6. 原性能脚本测的是观测门面，不是完整“确定性短请求 + 模拟模型”端到端延迟；不能直接认定计划中的业务请求性能门槛已验收。
7. 原报告记录的模型 E2E、停服/恢复、备用模型链、Compose 全部健康属于历史记录，本次不作为重新验证成功的证据。
8. 旧代码“有密钥即启用”不认识 LANGFUSE_ENABLED：回退到旧修订时，仅设置该开关不足以关闭旧实现，需同时移除旧进程凭证或采用兼容关闭补丁。

## 6. 后续上线检查

- 在重启任何正在使用的应用前，保存现有配置；按运维手册先在隔离进程验证。
- 使用真实系统管理员登录轨迹面板验证链接；普通用户/API-Key 不返回跳转 URL。
- 补一轮流式/非流式 RAG 与 Agent 的真实模型 smoke，按 model_call_id 对账。
- 对真实 worker 模式与同步测试模式分别验证独立 maintenance 追踪。
- 若开启内容采集，先核对数据范围；文本正则打码并非任意敏感自然语言的完整识别器。
- 若上线要求覆盖完整原计划，应补齐评估运行/重试幂等、完整请求性能、autoreload/退出过程验收后再标记对应项 PASS。

## 7. 变更与回滚

业务修复集中在 chat/views.py、personal_knowledge_base/observability.py、model_usage.py、chat_runtime.py、span_tracker.py 与 langfuse_check 命令。其余改动为测试和两份说明文档；本轮未修改前端代码、数据库 schema、依赖版本或环境密钥。

- MODIFIED_FILE：修改后的 observability.py 快照，供离线核对，不替代项目实际文件。
- DIFF_FILE：相对本轮 zcode 基线的源码/测试/文档差异，不混入此前未提交修改。
- VERIFICATION.txt：准确命令、输入、字面结果、退出码与回滚复现证据。
- ROLLBACK.sh：仅恢复本轮改动，先核验源备份与目标哈希；目标后续发生变化时拒绝覆盖。须显式给出目标目录，已在隔离副本验证；不会操作数据库、.env 或 Docker 卷。

## 2026-09-30：本地未提交改动的提交前修复

本轮从原有未提交工作区继续修复，不把 Git HEAD 当作修复前基线。
未执行提交、暂存、真实数据库迁移、服务账号登录或外部模型调用。
修复前文件快照保存在 `/tmp/django-agent-fix-baseline-xaegrgtr`；
本轮日志归档至 `.cache/commit-readiness-20260930/`。

### 修复范围

1. 会话轨迹使用项目实际 Bearer 用户鉴权；活动系统管理员获得链接，普通用户和
   API-Key 不获得链接，总开关仍生效。
2. 思考配置以事务中的第一条条件写入原子领取版本，配置与版本同事务提交；
   重新读取模型参数和能力后合并策略，保留最新凭证。版本冲突返回 409，
   SQLite BUSY/LOCKED 在事务回滚后按 50/100/200 毫秒重试，持续繁忙返回 503。
   原有 SQLite busy timeout 保持不变。
3. 关闭自动登录时，鉴权和 Origin 检查之后返回 `auto_login_disabled`，已授权
   用户可以手动打开远程 UI。实际 Cookie 转移及清理继续执行本机/同回环主机限制。
   前端只打开经校验的配置项目和同项目 trace URL，错误时不弹出窗口。
4. API 地址按 BASE_URL、兼容 HOST、localhost 缺省值解析；UI 地址独立配置，
   项目 ID 按 UI_PROJECT_ID、兼容 PROJECT_ID、服务器初始化 ID 回退。
   启动器、账号桥和轨迹链接使用一致配置。
5. SDK 固定采样率为 1，仅业务根执行采样，整个子树遵守同一决定。
6. 后台子 Agent 在调度前复制父上下文，继承冻结思考策略并建立独立追踪；
   同步与后台线程都使用子 Agent 的调用身份。
7. 两类评估保留原始样例 ID、行号、失败状态和评分输入 ID；失败或无法匹配的
   例子不上报数值评分，不因过滤失败回答而移动后续评分。
   未完成评分阶段恢复时先按保存的 ID 重排评分，再交给按位置复用的适配器。
   身份不确定的异常 checkpoint 保留已有数值汇总，不为修复关联追加模型调用，
   结果明确降级并给出 `checkpoint_score_identity_unmatched` 原因。
8. 完成事件未给出有效追踪 ID 时保留之前关联的旧 `langfuse_trace_id` 字段。
9. 性能脚本使用隔离数据库、合成凭证、独立 SDK 资源和本地目标，显式启用
   B/C 组并校验真实观测。它测量观测门面开销，不能代表完整问答耗时。
   不可达组在保留目标端口期间检查实际 HTTP 请求目标和连接失败；计时外 flush
   等待上限为 12 秒。缺失、空转或错路由的上传处理器均使脚本非零退出。

### 隔离验收命令

解释器：`/home/liuxuedeng/anaconda3/envs/django-agent/bin/python`。
后端测试使用 Django 测试数据库，SQLite 并发用例另建临时文件数据库；
HTTP 契约用本地 sink，模型边界使用合成响应。

~~~bash
export DJANGO_DB_PATH=/tmp/django-agent-fix-tests-unused.sqlite3
export LANGFUSE_ENABLED=false LANGFUSE_AUTOSTART=false APP_TASKS_SYNC=true
TASK_PY=/home/liuxuedeng/anaconda3/envs/django-agent/bin/python
"$TASK_PY" manage.py test \
  personal_knowledge_base.test_submission_regressions \
  personal_knowledge_base.test_benchmark_transport_regressions \
  personal_knowledge_base.test_langfuse_settings_defaults \
  personal_knowledge_base.test_langfuse_access_regressions \
  personal_knowledge_base.test_thinking_regressions \
  personal_knowledge_base.test_evaluation_examples \
  personal_knowledge_base.test_langfuse_review \
  personal_knowledge_base.test_langfuse_observability \
  personal_knowledge_base.test_langfuse_sdk_contract \
  personal_knowledge_base.test_langfuse_model_lifecycle \
  personal_knowledge_base.test_langfuse_p4_multiagent \
  personal_knowledge_base.test_settings_thinking \
  personal_knowledge_base.test_stream_finalization \
  personal_knowledge_base.test_actor_events \
  personal_knowledge_base.test_llm_providers \
  personal_knowledge_base.test_stream_persistence \
  chat.test_stream_protocol tests.test_session_trajectory \
  personal_knowledge_base.test_ragas_evaluation_loop \
  personal_knowledge_base.test_open_rag_benchmark --noinput -v1
"$TASK_PY" manage.py check
"$TASK_PY" manage.py makemigrations --check --dry-run
"$TASK_PY" scripts/bench_langfuse_overhead.py
node --test frontend/src/services/langfuse.test.mjs \
  frontend/src/views/settings/settings-ui.test.mjs \
  frontend/src/views/KnowledgeDetail.multimodal.test.mjs
npm --prefix frontend run build
graphify update .
git diff --check
~~~

### 本轮证据与范围

首批核心回归在修复前出现 7 个预期失败；额外的项目 ID 回退测试也先失败再通过。
第一轮组合后端测试运行 296 项，结果 `OK (skipped=1)`；前端 13 项通过，生产构建
通过，Django 检查无问题，迁移差异检查为 `No changes detected`。

最终只读复核发现未完成评分 checkpoint 的身份重排、不可达性能组的实际传输
验证，以及空 HOST 的默认值回退遗漏。补充修复先以回归复现，再重新验收：

| 验证 | 最终结果 | 退出码 / 日志 |
| --- | --- | --- |
| 完整相关后端回归 | Ran 306 tests；OK (skipped=1)，305 通过、1 跳过 | 0；django-agent-fix-final-tests.log |
| 前端可执行回归 | 13 通过 | 0；django-agent-fix-final-ui-tests.log |
| 前端生产构建 | built；保留已有 bundle 大小提示 | 0；django-agent-fix-build.log |
| Django 检查 | System check identified no issues (0 silenced). | 0；django-agent-fix-final-check.log |
| 迁移差异检查 | No changes detected | 0；django-agent-fix-final-migrations.log |
| 观测门面基准 | A=0、B/C=600 个观测；实际不可达请求 8 次、连接失败 8 次；validation=PASS | 0；django-agent-fix-final-benchmark.log |
| 基准 p95 额外延迟 | 1.135 毫秒；门槛 20 毫秒，PASS | 同上；仅观测门面 |
| AST 图谱更新 | 5085 节点、12805 边、290 社区 | 0；django-agent-fix-final-graphify.log |
| Git 差异空白检查 | 无输出 | 0；git diff --check |

后端跳过项为默认不运行的真实本地 Langfuse 登录测试。测试日志中的合成故障和
基准 C 组连接失败为预期路径；以断言、验证标志和退出码判断结果。
补充修复的精确命令、初次失败和修复后证据见
`django-agent-fix-final-findings-fix-report.md`；最终只读重新复核记录归档至同一目录。
重新复核通过：两个 Important 和一个 Minor 问题均已关闭，未发现新的分级问题。
完整需求合规和代码质量结论见 `django-agent-fix-final-rereview-report.md`。

真实 Langfuse 登录、实际服务入库和外部模型 E2E：**NOT_RUN**。
前面章节中的真实服务/浏览器/模型记录为历史证据，不代表本轮重新执行成功。
