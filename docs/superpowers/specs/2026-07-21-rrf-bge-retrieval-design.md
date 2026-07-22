# 设计：BGE-M3 双路召回 + RRF + BGE-Reranker 检索链

日期：2026-07-21
状态：已批准，实施中

## 背景

5 个 spec.md（personal_knowledge_base、knowledge、models_config、chat、agent）已更新为正式契约：
原始文档经 FTS5 BM25 与 BGE-M3 向量双路召回、标准 RRF（k=60）融合、BGE-Reranker 重排，
并要求可观测字段、显式降级、索引重建治理和 MRR@10 评估。

当前实现与契约的差距：BM25 分与向量分直接相加；查询向量用 `stable_embedding` 哈希，
与入库向量不在同一语义空间；`_fit_vectors` 截断/补零到 384 维；embedding/rerank 失败静默兜底。

## 决策

1. BGE-M3 / BGE-Reranker 走 OpenAI 兼容远程 API（默认模型名 `BAAI/bge-m3`、
   `BAAI/bge-reranker-v2-m3`），不引入本地推理依赖。
2. 严格模式：检索与入库链路彻底移除 `stable_embedding` 兜底；`source="local"` 视为未配置；
   维度不匹配直接报错，绝不截断补零。
3. 配置优先级：环境变量优先（`LLM_USE_ENV_*` 开关语义不变），数据库默认模型兜底。
4. 向量索引治理：vec 表维度 = `LLM_EMBEDDING_DIM`（默认 1024）；`search_index_meta` 原始 SQL 表
   存 `(signature, status)`；维度或签名变化 → 置 `needs_rebuild` 并入队后台重建任务，
   重建完成前向量查询显式降级 FTS-only（`reindex_required`）。
5. 旧“分数直接相加”保留为 `_baseline_score_addition_search()`，仅供检索评估对比。

## 核心管线

`hybrid_search_ex(tenant_id, kb_ids, query, top_k=10, *, keyword_top_k, vector_top_k, rerank_top_k, rrf_k)`
返回 `(results, meta)`：

```
FTS5 BM25 召回（默认 4*top_k）──┐
                                ├─ RRF 融合（rank 从 1，score=Σ 1/(rrf_k+rank)，默认 k=60）
BGE-M3 向量召回（默认 4*top_k）─┘
        ↓ 内容去重
BGE-Reranker 重排（默认输入 2*top_k）→ 严格按重排分数取 top_k
```

- 每条结果带 `keyword_rank / vector_rank / rrf_score / rerank_score / match_sources`。
- `meta` 含 `degraded / degradations[{stage, reason}] / rrf_k / embedding_model / rerank_model / candidate_counts`。
- 降级：embedding 未配置/失败/维度不符/待重建 → FTS-only（stage=vector）；
  rerank 未配置/失败 → 按 RRF 排序（stage=rerank）。
- `hybrid_search()` 保留旧签名：核心管线 + 查询扩展/MMR/多样化/GraphRAG/短 Chunk 扩展；
  图谱结果标记 `match_sources:["graph"]`，不伪装成双路召回。

## API 变更

- knowledge 检索端点：候选参数（非法值回退默认）+ `retrieval` 元信息 + 可观测字段。
- models_config：`POST /api/v1/models/<id>/test`（真实请求校验：embedding 数量/有限值/1024 维，
  rerank ≥2 文档索引/分数/排序完整性）；模型列表标注生效配置；更新生效 Embedding → `needs_reindex` 并入队重建。
- chat：降级阶段与原因写入助手消息 `agent_steps.knowledge_search.degradations`，回答继续生成。
- agent：`knowledge_search` 复用同一 `hybrid_search_ex`，工具输出附降级说明。

## 检索评估

`retrieval_eval.py`：MRR@10 与 Recall@20；`run_retrieval_comparison` 对比 RRF+重排 vs 基线，
返回 `delta_pct` 与 `pass`（MRR@10 ≥ +5% 且 Recall@20 不降）。
版本化数据集 `personal_knowledge_base/eval_datasets/retrieval_v1.json`；
端点 `POST /api/v1/rag-eval/retrieval`。

## 测试

- `test_hybrid_rrf.py`：RRF 公式、双路命中奖励、降级、维度守卫、索引同步、API 契约。
- `test_retrieval_eval.py`：指标计算；桩向量+桩重排 fixture 上提升 ≥5%；端点契约。
- models_config：测试接口校验规则、生效标识、needs_reindex、凭证脱敏。
- 全量回归：`python manage.py test personal_knowledge_base knowledge models_config chat agent`。

## 非目标

前端页面、Wiki/图谱检索逻辑、本地推理接入、Django migration（全部用原始 SQL 建表）。
