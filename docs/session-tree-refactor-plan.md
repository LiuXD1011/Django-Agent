# 会话存储重构方案：Append-only 条目树

> 状态：设计稿（待排期）。本方案源于 2026-09 的 agent 实测与 [pi](../../references/pi) 项目分析，
> 是 SQLite 锁问题（`database is locked` → agent-chat 500）的长期解法。
> 短期缓解（`db_retry.retry_on_db_lock` 重试 + continue-stream 快速失败）已上线。

## 1. 现状与痛点

当前流式生成链路涉及三类并发写：

| 写路径 | 位置 | 问题 |
|---|---|---|
| 每个流事件落库 | `stream_manager.append_event` → `StreamEventRecord` + `StreamState` | 高频小事务，读偏移(count)→写(create) 在同一事务内形成锁升级竞争 |
| 流状态 upsert | `stream_manager.ensure_stream` → `StreamState.update_or_create` | `select_for_update` 在 SQLite 上是空操作，防不住竞争（曾直接导致 agent-chat 500） |
| 消息/快照/记忆写 | `Message` 更新、`ContextSnapshot`、memory | 与上面两类并发时互相加剧锁等待 |

根本原因：**流式状态 = 内存 StreamManager + 数据库 StreamState/StreamEventRecord 双写**，
"数据库里的流状态"本质上是对"内存事件日志"的投影，两者靠反复 upsert 保持一致。
已重试缓解，但写放大和锁竞争面仍在。

## 2. 目标设计（借鉴 pi 的 append-only entry tree）

### 2.1 数据模型

新增 `SessionEntry`（消息只是其中一种条目）：

```
SessionEntry
  id            UUID pk
  session_id    FK(Session)
  parent_id     FK(SessionEntry, null)   # 树结构，支持分叉/重跑
  seq           int                       # 会话内单调递增
  entry_type    varchar                   # message / tool_call / compaction /
                                          # context_snapshot / custom
  payload       JSON                      # 条目内容（含 UI-only 数据）
  created_at
```

配套一张 `SessionOperation` 操作日志（`operation_started/finished`、`step_attempt`）：
崩溃恢复时按"是否有未闭合的 operation"判定 空闲 / 挂起可恢复 / 损坏 三态，
替代现在"StreamState 存在与否"的模糊判断。

### 2.2 关键语义（从 pi 迁移）

1. **快照权威、事件瞬态**：断线重连/恢复一律以数据库中的会话快照为准，
   SSE 事件只是"提示"。`continue_stream` 从"回放事件流"变为"读快照 + 增量"。
2. **非破坏性 compaction**：上下文压缩 = 追加一条 `compaction` 条目
   （summary + retained_tail + tokens_before），原始历史永不改写；
   构建 LLM 上下文时才投影为"summary + 保留尾部"。RAG 定制点：把
   "本会话已检索过的 chunk 清单"写进 compaction 的 details，压缩后模型仍知道自己查过什么。
3. **两层消息投影**：持久层 `AgentMessage`（含 ui_only/citations/tool_meta 等元数据）
   与发送给 LLM 的 OpenAI dict 之间用 `convert_to_llm()` 投影过滤，
   替代现在直接操作 dict + `<user_question>` 字符串拼接（`agent_engine.py`）。

### 2.3 写路径变化

- 生成线程只 **append**（单写者、无 update、无 count-then-insert），SQLite 写竞争面
  收敛为"每会话串行"；跨会话并发由 WAL 承担。
- `StreamManager` 退化为纯内存 fan-out（SSE 推送），不再是事实源；
  `StreamState`/`StreamEventRecord` 两张表随迁移废弃。
- 事件不需要逐 token 落库（现在每个 thinking/tool 事件都写两行），写放大数量级下降。

## 3. 迁移步骤（可分四批独立上线）

1. **双写期**：新增 SessionEntry，chat_endpoint 在写 Message 的同时 append entry；
   读路径不变。校验一致性（脚本对账 Message ↔ entry）。
2. **读切换**：`messages_load` / `build_agent_history_with_snapshot` 改读 entry 投影，
   Message 表降级为兼容视图（或用 SQL 视图过渡）。
3. **流状态切换**：`continue_stream` 改为"读快照 + operation 三态判定"，
   下线 StreamState/StreamEventRecord。
4. **前端能力解锁**（收益兑现）：消息编辑重发=新分支；任意历史节点重跑；
   会话树导航 UI（Vue 端基于 parent_id 渲染）。

## 4. 风险与边界

- SQLite 仍是单写者数据库，本方案降低竞争面但不改变"写吞吐上限"；
  多租户生产部署仍建议 PostgreSQL（迁移后双写逻辑对 PG 同样成立）。
- `visible_to_user=False` 的 actor 隐藏消息、`request_id` 幂等去重、
  上下文快照边界（`context_snapshot.py`）语义需要在 entry 模型中一一对应，双写期对账脚本兜底。
- 工作量估计：后端 3-5 天 + 前端树导航 2-3 天，建议单开分支、以第 1/2 批先行。
