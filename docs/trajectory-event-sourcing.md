# 会话轨迹:事件溯源设计(session trajectory event sourcing)

参考 `references/deepseek-harness` 的轨迹体系,适配本项目的 Django + 多租户知识库业务。

## 1. 目标与非目标

**目标**
- 一次问答(request)从用户提问到最终回答的全过程事实被持久记录:检索、思考、工具调用、
  模型调用、降级、子代理。
- 轨迹成为**产品数据**:租户可在前端查看自己会话的轨迹台账(轮次 → 步骤 → 工具链)。
- `Message` 表降级为**投影**:由事件派生,可随时从事件完整重建。
- 事件不可变:只追加,不更新,不删除。

**非目标(诚实边界)**
- 不做"从事件派生 LLM 请求历史"(模型消息历史仍由 `build_agent_history_*` 从 Message 投影构建,
  属于方案的第五阶段演进,本次不迁移)。
- 不做跨会话的全局事件总线;事件严格归属会话。
- 不替换 langfuse;事件日志与 langfuse 无耦合(未来可加镜像转换器)。

## 2. 数据模型

### SessionEvent(persional_knowledge_base/models.py)

| 字段 | 说明 |
|---|---|
| id | 自增主键(全局单调,辅助排序) |
| tenant / session | 归属,租户隔离靠 session 外键 + 查询过滤 |
| seq | 会话内单调递增,`(session, seq)` 唯一 |
| request_id | 业务请求关联(一次问答一组事件) |
| type | 事件类型,`域/名称` 命名 |
| data | JSON,只写不改;冻结纪律由写入层保证 |
| created_at | 写入时间(逻辑时钟,业务事实时间在 data 内) |

seq 分配:`Session.event_seq` 计数字段 + `F()` 原子递增 + `refresh_from_db` 回读 +
`(session, seq)` 唯一约束兜底,冲突时整行重试(兼容 SQLite)。

### 不可变纪律

写入层只提供 `append`;不提供 update/delete API;投影重建只读事件。
`data` 在 append 时做一次深拷贝并过滤非 JSON 原生类型,防止调用方后续原地篡改已存事件。

## 3. 事件词汇表(对齐业务域,首版 17 种)

| 域 | 类型 | 关键 data 字段 | 发射点 |
|---|---|---|---|
| 会话 | `session/started` | title, kb_ids | 首条消息时(无则不发) |
| 轮次 | `turn/user-message` | content, images, attachments, mentioned_items, channel | chat_endpoint 创建用户消息 |
| 轮次 | `turn/assistant-created` | mode(agent/rag), model_id | 创建 assistant 占位消息 |
| 轮次 | `turn/completed` | stopped_reason, duration_ms, content_length | complete_message_with_result |
| 轮次 | `turn/error` | message | 生成失败 |
| 检索 | `retrieval/search` | query, kb_ids, top_k | run_rag_pipeline 入口 |
| 检索 | `retrieval/result` | count, intent, degradations, ref_titles(仅标题+chunk_id) | 检索返回 |
| Agent | `agent/iteration` | iteration, model | 每轮循环开始 |
| Agent | `agent/thinking` | iteration, content, duration_ms | LLM 返回文本 |
| 工具 | `tool/call` | tool_call_id, name, argument_keys(键名列表) | on_event |
| 工具 | `tool/result` | tool_call_id, name, output_excerpt(≤500), error, duration_ms | on_event |
| 子代理 | `agent/actor` | actor_id, event(spawned/completed/cancelled), agent_type, status | AgentActor 生命周期 |
| 模型 | `llm/call` | model, scenario, prompt_tokens, completion_tokens, duration_ms, success | record_model_usage |
| 系统 | `llm/retry` | attempt, reason | 模型重试 |
| 系统 | `context/compacted` | trigger, before_tokens, after_tokens | 上下文压缩 |

**隐私纪律(与 `LANGFUSE_LOG_CONTENT=false` 同源,但由写入层强制)**:
- 不落系统提示、不落检索文档原文;引用只记 `chunk_id + 标题`;
- 工具参数只记键名列表(防 prompt 注入内容/敏感值入日志);输出截断 500 字符;
- 用户消息与最终回答是**业务数据本身**(Message 表已有),事件里允许保存原文。

## 4. 写入路径(埋设点)

所有写入经由唯一入口 `personal_knowledge_base/event_log.py`:

```
append_event(session, request_id, type, data)   # 单条
events_for_session(session_id, after_seq, limit) # 读取
fold_trajectory(events)                          # 服务端折叠为轨迹台账结构
rebuild_projection(session_id)                   # 从事件重建 Message 投影
```

| 业务位置 | 事件 |
|---|---|
| `chat/views.py` chat_endpoint 用户消息创建 | turn/user-message |
| chat_endpoint agent 分支 assistant 创建 | turn/assistant-created |
| `_run_agent_generation` 的 `on_event` | agent/thinking、tool/call、tool/result、turn/completed、turn/error |
| `agent_engine.execute` 循环头 | agent/iteration |
| `run_rag_pipeline` 检索前后 | retrieval/search、retrieval/result |
| `record_model_usage` | llm/call |
| `AgentActor` 状态迁移 | agent/actor |

**失败纪律**:事件写入失败只记 WARNING,绝不打断问答主流程(轨迹是增强,不是瓶颈);
但事件一旦写成功即为事实,投影失败可由重建命令修复——**事件 > 投影**。

## 5. 投影:Message 由事件派生

`fold_projection(events)` 按 `request_id` 分组折叠:
- `turn/user-message` → user Message(content/mentioned_items/images/attachments/channel)
- `turn/completed` + `agent/thinking|tool/*` → assistant Message
  (content=最终回答,agent_steps=[thinking/tool 结果聚合],agent_duration_ms,knowledge_references)
- `turn/error` → assistant Message(is_fallback=True, content=错误文案)

在线路径仍直接写 Message(事务内先事件后投影,双写);`rebuild_projection` 管理命令
可对任意会话删除投影消息并从事件重建,用于校验"投影 ⟺ 事件"不变量(测试断言)。

## 6. 轨迹读取 API(chat/urls.py)

| 端点 | 说明 |
|---|---|
| `GET /api/v1/sessions/<id>/trajectory/` | 服务端 `fold_trajectory` 产物:轮次分组台账(前端直接渲染) |
| `GET /api/v1/sessions/<id>/events/?after_seq=&limit=` | 原始事件分页(审计/调试) |

两者都走 `_get_visible_session` 的租户/可见性过滤,与现有会话权限同源。

### 轨迹台账结构(fold_trajectory 输出)

```json
{
  "session_id": "...",
  "turns": [{
    "request_id": "...",
    "started_at": "...", "completed_at": "...",
    "mode": "agent", "stopped_reason": "completed", "duration_ms": 8300,
    "user": {"content": "...", "attachments": 1},
    "assistant": {"content": "...", "model": "glm-4"},
    "steps": [{
      "iteration": 1, "thought": "...",
      "tools": [{"name": "knowledge_search", "argument_keys": ["query"],
                 "output_excerpt": "...", "error": "", "duration_ms": 320}],
      "llm": {"model": "...", "prompt_tokens": 1200, "completion_tokens": 300}
    }],
    "retrievals": [{"query": "...", "count": 5, "degradations": []}],
    "actors": [{"actor_id": "...", "agent_type": "...", "status": "done"}],
    "usage": {"prompt_tokens": 1500, "completion_tokens": 450}
  }]
}
```

## 7. 前端(Vue 3 + TDesign)

- `frontend/src/views/chat/components/TrajectoryPanel.vue`:轨迹台账。
  粗分隔线 = 轮次;每轮内部:用户消息卡、检索行、思考行、工具链(嵌套缩进)、
  回答卡、页脚(模型/token/总耗时/stopped_reason)。
- `Chat.vue` 头部加"对话 / 轨迹"视图切换;轨迹懒加载(切到才拉取)。
- `api/index.ts` 增加 `sessionTrajectory(sessionId)`。

## 8. 验证策略

| 层 | 验证 |
|---|---|
| 事件层 | Django 测试:seq 连续性/唯一冲突重试/不可变纪律/data 冻结 |
| 投影层 | rebuild 后 Message 与在线双写结果字段级一致 |
| 业务流 | mock LLM 的 agent 全链路:断言事件序列完整性(turn→retrieval→thinking→tool→completed) |
| 权限 | 跨租户访问 trajectory/events 返回 404 |
| 前端 | Playwright(mock API):轨迹页轮次/工具/用量渲染、空态、404、切换回对话视图 |
