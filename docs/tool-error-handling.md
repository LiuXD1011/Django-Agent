# 工具调用失败处理框架

对齐《Agent 外部工具调用失败处理生命周期》16.2 框架（2026-09 落地），核心原则：
**先分类再处理**——确定性错误修正而非重试；瞬时故障受控重试；持续失败熔断隔离；最后按能力降级。

## 1. 结构化错误（对应 16.2.2）

`ToolResult`（personal_knowledge_base/agent_tools.py）在 `error` 文本之外携带：

| 字段 | 含义 |
|---|---|
| `error_type` | INVALID_ARGUMENT / NOT_FOUND / UNKNOWN_TOOL / UNKNOWN_ACTION / PERMISSION_DENIED / TRANSIENT / EXECUTION_ERROR / CIRCUIT_OPEN |
| `retryable` | True（瞬时，可退避重试）/ False（确定性，重试无意义）/ None（未分类，模型自行判断） |
| `failed_fields` | 校验失败的字段列表 |

- 工具内部用便捷构造器：`ToolResult.validation_error(msg, failed_fields)`、
  `not_found(msg)`、`transient_error(msg)`；存量只传 `error` 的调用点由
  `__post_init__` 按关键词兜底分类。
- 注册表 `execute_tool` 捕获的异常用 `classify_error_text` 分类，瞬态关键词表
  与 agent_engine 的 LLM 层重试判定同源，两层口径一致。
- 回传给模型的文本由 `ToolResult.model_error_text()` 生成：错误原文 + 结构化
  JSON（error_type/retryable/failed_fields）+ 按 retryable 差异化的修正指引
  （可重试→"稍等重试或换路"；不可重试→"修参数/换工具，重复无意义"）。

## 2. 熔断器（对应 16.2.3）

`ToolCircuitBreaker`（注册表内 `registry.breaker`），按工具名三态：

- 只有 `retryable=True` 的失败计入连续失败；确定性失败不进熔断统计；
- 连续失败 ≥ `failure_threshold`（默认 3）→ **Open**：`before_call` 直接拒绝，
  返回 `CIRCUIT_OPEN` 错误快速失败；
- 冷却 `cooldown_seconds`（默认 30s）期满 → **Half-Open**：放行探测；
  探测成功 → Closed，探测失败 → 重新 Open；
- 进程级共享（依赖健康是全局事实），仅存内存，重启复位；线程安全。

## 3. 已知边界（诚实声明）

- **未做通用工具超时**：放弃式超时会遗留持锁线程，加剧本项目 SQLite 锁竞争；
  超时在正确分层已存在——web 工具 HTTP 超时（10s/15s）、actor 工具
  `timeout_ms`（默认 120s）、LLM `total_timeout`。
- **未做备用工具映射**：wiki_search 与 knowledge_search 数据域不同，不是等价
  能力，伪造映射违反业务逻辑。"返回部分结果"降级已有：LLM 失败但存在工具
  产出时 `_synthesize_from_tool_results`（stopped_reason=degraded）。
- "说明能力边界、绝不伪造成功"由既有机制承担：降级轮次标注
  `stopped_reason="degraded"`，无检索结果切换 `SYSTEM_PROMPT_RAG_NO_CONTEXT`。

## 4. 可观测性

- `tool_result` 轨迹事件的 `meta` 携带 error_type/retryable/failed_fields
  （`_tool_result_meta`），前端 TOOL 卡片展示"错误类型 / 可重试 / 失败字段"。
- 测试：`tests/test_tool_error_handling.py`（分类器、状态机、模型文本、注册表集成）。
