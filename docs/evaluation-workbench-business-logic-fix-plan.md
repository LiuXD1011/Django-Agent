# 评测工作台业务逻辑修复方案

## 1. 文档目的

本文给出 `/platform/evaluation` 的完整修复方案，只定义目标、接口、实现步骤、兼容策略、测试范围和验收标准，不包含代码修改。

修复目标不是单独补一个“删除”按钮，而是使以下对象在业务上保持一致：

- 用户在页面上选择的评测配置；
- 后端实际执行的分块、检索、重排、回答和裁判流程；
- 页面展示的指标、验证状态和报告历史；
- 报告下载、删除、恢复任务和成本估算行为。

## 2. 当前问题与目标行为

| 编号 | 当前问题 | 修复后的目标行为 |
| --- | --- | --- |
| P1 | 报告历史只有下载，没有删除接口和按钮 | 租户只能删除自己的报告；数据库报告和文件报告使用同一删除语义；删除后历史、下载入口和当前任务状态同步更新 |
| P2 | 修改检索、重排、分块或模型后，旧指标仍显示在新配置下 | 指标绑定运行配置快照；运行中锁定配置；运行后修改表单时明确显示“结果属于上一次配置” |
| P3 | 恢复后台任务后，页面控件仍显示默认配置 | 状态接口返回完整请求配置和生效配置；恢复任务时展示真实配置 |
| P4 | 多个分块策略与统一 Retrieval/RAG 指标没有明确归属 | 拆分“主分块策略”和“对比分块策略”；主策略驱动端到端 Retrieval、Answer、Ragas；对比策略只生成同口径检索和资源指标 |
| P5 | 公开数据集分块评测只把生产 Top-20 映射到新分块 | 每个策略使用完整语料构建隔离索引，并按所选检索和重排配置独立检索 |
| P6 | 向量或重排降级时仍可能标记 verified | 评测采用严格执行；请求阶段无法生效时创建前拒绝或标记 degraded/unverified |
| P7 | 每个分块策略缺少 verified，前端始终显示 unverified | 每个策略返回独立验证状态、有效配置、覆盖率和原因 |
| P8 | 分块评测与生产检索在 BM25、向量距离、候选截断和 RRF 上不一致 | 抽取共享排序内核，生产与评测复用相同算法和参数 |
| P9 | 全集估算未计入策略数、分块嵌入和缓存命中 | 按阶段返回工作量、模型调用量、缓存命中和预计时间 |
| P10 | 报告超过 7 天即 stale，与真实数据漂移无关 | 将验证状态与数据新鲜度拆开，只按数据指纹判断 stale |
| P11 | 租户任务 ID 与报告 ID 不同，当前任务下载却使用任务 ID | 状态接口显式返回 `report.id/url/available`，所有报告操作只使用报告身份 |

## 3. 业务模型决策

### 3.1 评测配置

页面配置调整为：

1. **主分块策略**：必选且只能一个，默认 `auto_parent_child`。
2. **对比分块策略**：可选多个，不能包含主策略，默认空列表。
3. **检索策略**：单选 `keyword`、`vector` 或 `hybrid`。
4. **检索重排**：显式布尔值；开启时必须存在可用 Rerank 模型。
5. **Answer 模型**：只用于主策略答案生成。
6. **Judge 模型**：只用于主策略 Ragas 裁判。

主策略完整链路：

`解析文档 → 主策略分块 → 隔离索引 → 检索 → 可选重排 → 上下文 → Answer → Judge/Ragas`

对比策略检索链路：

`解析文档 → 对比策略分块 → 隔离索引 → 检索 → 可选重排 → 检索指标/资源指标`

第一版不对每个对比策略重复执行 Answer 和 Judge，避免 LLM 成本随策略数倍增。页面必须明确“RAG 指标仅属于主分块策略”。

### 3.2 严格执行与降级

- `keyword` 不要求 Embedding。
- `vector` 缺少 Embedding 或索引构建失败时直接失败，不降级。
- `hybrid` 必须同时执行关键词和向量；缺少任一路时为 `degraded`，不能 `verified`。
- `rerank_enabled=true` 但没有 Rerank 模型时，创建前返回 422。
- Rerank 运行中失败时记录题级失败，最终为 `partial` 或 `degraded`。
- `semantic_parent_child` 缺少 Embedding 时，创建前返回 422。
- 用户明确关闭 Rerank 时，生效状态为 `disabled`，不属于 degradation。
- 实际配置与请求配置不一致时，报告记录差异，顶层不得 `verified`。

### 3.3 状态模型

统一拆成：

- `run_status`：`queued | running | completed | partial | failed | cancelled`；
- `verification_status`：`verified | degraded | unverified | failed`；
- `freshness_status`：`current | stale | unknown`；
- `report.available`：报告是否仍可下载。

判断标准：

- `verified`：配置完整生效、数据指纹匹配、覆盖率 100%、必需阶段成功。
- `degraded`：有可用指标，但至少一个请求阶段未按配置生效。
- `unverified`：数据、标注或模型输出不足以验证。
- `failed`：主流程没有形成可用结果。
- `stale`：数据集哈希、文档哈希或公开清单哈希与当前对象不同。
- 代码提交或模型配置不同只标记“历史环境”，不自动 stale。
- 删除“超过 7 天即 stale”的前端判断。

## 4. 接口与数据契约

### 4.1 创建运行

`POST /api/v1/rag-eval/runs` 新请求字段：

```json
{
  "source": {
    "type": "open_dataset",
    "dataset_id": "open_rag_benchmark_180",
    "dataset_version": "arxiv-v1"
  },
  "primary_chunking_strategy": "auto_parent_child",
  "comparison_chunking_strategies": ["fixed_window", "recursive"],
  "retrieval_strategy": "hybrid",
  "rerank_enabled": true,
  "answer_model_id": "",
  "judge_model_id": ""
}
```

兼容规则：

- 旧 `chunking_strategies` 保留一个版本；
- 第一个旧值转换为主策略，其余转换为对比策略；
- 新旧字段同时出现且冲突时返回 400；
- 后端只保存规范化结构，配置指纹也基于该结构。

创建前 preflight：

- 校验数据集已发布或公开数据集 ready；
- 校验主策略与对比策略不重复；
- 校验 Embedding、Rerank、Answer、Judge 模型；
- 返回明确错误码：`embedding_model_required`、`rerank_model_required`、`semantic_model_required`。

### 4.2 运行状态响应

`GET /api/v1/rag-eval/runs/{task_run_id}` 和 active-run 至少返回：

```json
{
  "run_id": "task-run-id",
  "run_status": "completed",
  "requested_configuration": {
    "source": {},
    "primary_chunking_strategy": "auto_parent_child",
    "comparison_chunking_strategies": ["fixed_window"],
    "retrieval_strategy": "hybrid",
    "rerank_enabled": true,
    "answer_model_id": "",
    "judge_model_id": ""
  },
  "effective_pipeline": {
    "embedding_model": "model-name",
    "vector_distance_metric": "l2",
    "rerank": {
      "requested": true,
      "effective": true,
      "model": "model-name"
    },
    "degradations": []
  },
  "verification_status": "verified",
  "freshness_status": "current",
  "metrics": {
    "primary": {"retrieval": {}, "rag": {}},
    "comparisons": {
      "fixed_window": {"retrieval": {}, "resources": {}}
    }
  },
  "report": {
    "id": "report-id",
    "url": "/api/v1/rag-eval/reports/report-id",
    "available": true
  }
}
```

任务 ID 和报告 ID 必须始终分离。前端不得再用任务 ID拼接报告地址。

### 4.3 报告历史

`GET /api/v1/rag-eval/history` 每项返回：

- `report_id`、`task_run_id`；
- `evaluation_type`；
- `dataset.id/version/entries/sha256`；
- `requested_configuration`；
- `effective_pipeline`；
- `verification_status`、`freshness_status`；
- `created_at`、`report_url`、`available`。

旧报告兼容：

- 缺少 `report_id` 时使用旧 `run_id`；
- 缺少任务 ID 时返回 null；
- 缺少配置时显示“旧版报告，配置信息不完整”，不猜测；
- 旧 `verified` 映射到 `verification_status`。

### 4.4 删除报告

新增 `DELETE /api/v1/rag-eval/reports/{report_id}`：

- 只能删除当前租户报告；
- 数据库 `GenericResource` 报告物理删除；
- 公开评测文件报告删除文件；
- `TaskRecord` 保留用于审计，但清除或失效报告指针；
- 成功返回 204；
- 不存在或跨租户统一返回 404；
- 删除后下载 404，历史不再出现；
- 当前页面关联该报告时立即把 `report.available` 置为 false；
- 自动保留改为租户级全局最多 50 份，不再是数据库和文件各 50 份。

### 4.5 估算接口

`POST /api/v1/rag-eval/runs/estimate` 复用创建任务的规范化与 preflight，返回：

- `sample_size`、`strategy_count`、`estimated_seconds`；
- `estimated_calls.chunk_embeddings/query_embeddings/rerank/answer/judge`；
- `cache.reusable_strategy_indexes/indexes_to_build`；
- `based_on_history`。

估算必须计入主策略、对比策略、语义分块、Chunk 数、批大小、缓存命中和 Rerank 次数。确认框使用服务端 `sample_size`，不使用前端硬编码题数。

## 5. 后端实现方案

### 5.1 统一配置与 preflight

在 `personal_knowledge_base/eval_views.py`：

- 将配置处理拆为输入规范化、资源解析、模型 preflight、配置指纹四步；
- 增加旧字段转换；
- 指纹包含主策略、对比策略、检索、重排、模型、数据哈希和索引算法版本；
- active-run 按规范化指纹去重；
- 状态接口返回请求配置、生效管线、验证状态和报告对象。

### 5.2 共享排序内核

从 `personal_knowledge_base/search.py` 抽取公共排序函数：

- 关键词与向量候选排名输入；
- 各路候选上限；
- RRF 融合；
- Rerank 输入上限和尾部拼接；
- 父块解析后的去重和 Top-K；
- requested/effective pipeline 元数据。

生产索引和评测隔离索引都调用该内核。此次修复不改变生产默认向量距离、RRF 或模型，只保证评测与生产一致。

### 5.3 隔离评测索引

在 `chunking_eval` 和 `open_rag_benchmark` 上方建立统一 evaluation-index 服务：

- 输入版本化文档、策略、完整分块参数、Embedding 签名和算法版本；
- 输出只读、租户隔离的临时或缓存索引；
- FTS 使用生产一致的 FTS5 BM25；
- vec0 使用生产一致的向量距离；
- 不写生产 Chunk、FTS 或向量表；
- 缓存键包含数据哈希、策略、参数、Embedding 签名和算法版本；
- 临时文件构建完成后原子替换；
- 取消或失败不发布不完整缓存；
- 公开数据集使用完整语料，不能只索引 qrel 或已有 Top-20 文档。

移除公开评测的 `shared_production_top20` 映射路径。每个策略通过自己的索引执行同一批问题。

### 5.4 主策略端到端执行

调整 `personal_knowledge_base/tasks.py`：

1. 为主策略构建或复用隔离索引。
2. 用该索引产生主策略 Top-20。
3. 计算 Hit@10、MRR@10、Recall@20。
4. 用最终 Top-5 父块上下文生成 Answer。
5. 用同一上下文运行 Judge/Ragas。
6. 对比策略分别构建索引，计算检索、上下文字符数、Chunk 数和构建耗时。
7. 顶层 verified 同时检查配置一致性、覆盖率和必需阶段。

题级结果保留请求/实际策略、Rerank 状态、错误原因、原始和去重后排名、证据命中、Answer/Judge 有效性。报告继续脱敏，不保存原始正文、密钥或完整上下文。

### 5.5 报告服务

在 `personal_knowledge_base/eval_reports.py` 形成统一服务：

- `save_evaluation_report` 返回独立 report_id；
- `get_evaluation_report` 支持数据库和文件报告；
- `delete_evaluation_report` 处理两种存储；
- `recent_evaluation_reports` 统一排序和全局 50 条保留；
- `report_exists` 生成 `report.available`；
- 新鲜度根据数据指纹计算，不按日期。

租户报告写入 `task_run_id`；TaskRecord 结果保存 `report.id/url`，修复当前任务区域下载 404。

## 6. 前端实现方案

### 6.1 配置区

在 `frontend/src/views/Evaluation.vue`：

- 分块复选框改为主策略单选和对比策略多选；
- 对比列表排除主策略；
- 运行中禁用数据集、分块、检索、重排和模型；
- preflight 不满足时显示明确原因；
- 创建任务后保存服务端 `requested_configuration` 快照。

### 6.2 结果区

- 指标上方展示“本结果配置”；
- Retrieval 和 RAG 明确标注属于主策略；
- 对比表只显示检索和资源指标；
- 每策略直接读取 `verification_status`；
- 当前表单与结果快照不一致时显示醒目提示；
- 继续评测使用并展示原任务配置；
- 下载使用 `activeRun.report.url` 或 `report.id`，仅 `available=true` 显示。

### 6.3 报告历史

- 增加配置摘要或展开详情；
- 状态拆成验证状态和新鲜度；
- 每行提供下载和删除；
- 删除确认包含生成时间、数据集、主策略、检索和 Rerank；
- 删除中禁用按钮；
- 204 后移除行并同步当前任务；
- 404 时刷新并提示已不存在；
- 其他错误保留该行；
- `loadHistory` 增加加载态、错误态和重试，不再把失败显示成“暂无报告”。

### 6.4 API 客户端

在 `frontend/src/api/index.ts`：

- 增加 `ragEvalDeleteReport(reportId)`；
- 下载与删除 ID统一 `encodeURIComponent`；
- 为运行、报告、配置和指标建立 TypeScript 类型，逐步替换 `any`。

## 7. 实施顺序

### 阶段一：固定契约和状态语义

1. 增加新请求/响应类型和后端规范化。
2. 增加 verification、freshness、requested/effective pipeline。
3. 修复任务 ID与报告 ID混用。
4. 前端增加配置快照、运行中锁定和每策略状态。

完成条件：页面不会把旧结果、降级结果或错误报告 ID展示成正确结果。

### 阶段二：统一检索与分块执行

1. 抽取共享排序内核。
2. 建立隔离索引和缓存。
3. 租户主策略改为端到端执行。
4. 公开数据集改为完整语料按策略检索。
5. 对比策略统一输出检索和资源指标。

完成条件：相同 Chunk 与模型输入下，生产和评测排序一致；主 RAG 指标只来自主策略。

### 阶段三：报告治理和估算

1. 增加删除服务和 DELETE 接口。
2. 增加历史配置摘要与真实新鲜度。
3. 统一报告保留策略。
4. 重写估算公式和阶段明细。

完成条件：报告可安全删除、历史可辨认、下载身份正确、全集估算覆盖全部成本。

### 阶段四：回归和发布

1. 运行新增和现有测试。
2. 检查实际构建产物的桌面和移动页面。
3. 用公开 180 题子集完成真实 smoke run。
4. 在非生产环境验证缓存占用、耗时和模型调用量后发布。

## 8. 测试方案

### 8.1 后端单元测试

#### 配置与状态

- 新请求规范化正确。
- 旧 `chunking_strategies` 正确转换。
- 新旧字段冲突返回 400。
- 主策略不能出现在对比策略中。
- vector/hybrid 缺 Embedding 返回明确错误。
- Rerank 开启但未配置返回 422。
- semantic 缺 Embedding 返回 422。
- requested/effective 不一致时不能 verified。
- 显式关闭 Rerank 为 disabled 且不是 degradation。

#### 检索一致性

- 固定文档、Embedding 和 Rerank 分数下，生产索引和隔离索引 Top-20 完全一致。
- FTS5 BM25 排名一致。
- vector 距离和候选上限一致。
- hybrid RRF 排名一致。
- Rerank 候选数和尾部拼接一致。
- 父块解析、去重和最终 Top-K 一致。
- keyword、vector、hybrid 分别覆盖。

#### 分块和端到端指标

- 主策略检索来自主策略索引。
- 改变主策略能够改变主 Retrieval/RAG 上下文。
- 对比策略不增加 Answer/Judge 调用。
- 公开数据集不再调用 `shared_production_top20`。
- 每策略都有 verification、coverage、effective pipeline、reasons。
- 单策略失败时顶层状态符合规则。

#### 报告

- 租户报告下载使用 report ID。
- 数据库和文件报告均可删除并从历史消失。
- 删除后下载 404。
- 删除保留 TaskRecord，但报告 unavailable。
- 跨租户删除和下载均 404。
- 两类报告合计最多 50。
- 旧报告可下载和展示。
- 超过 7 天但数据未漂移仍 current。
- 数据或文档哈希变化时 stale。

#### 估算

- 策略数增加时分块、Embedding、Rerank 工作量增加。
- Rerank 关闭时调用数为 0。
- keyword 不计算查询 Embedding。
- 缓存命中时不重复计算索引构建调用。
- 180 与 3045 题返回准确 sample_size。

### 8.2 前端测试

- 默认主策略 auto，对比为空。
- 主策略不会出现在对比选项。
- 创建请求发送新字段。
- 运行中配置控件禁用。
- 恢复任务显示服务端配置。
- 修改表单后旧指标保留但出现不一致提示。
- 主指标明确标注主策略。
- 各策略正确显示 verified/degraded/unverified/failed。
- 当前任务下载使用 report.id/url。
- 历史有删除按钮和确认。
- 取消确认不发请求。
- 删除成功移除行并隐藏当前下载。
- 删除失败保留行并显示错误。
- 历史加载失败显示错误态。
- 不再存在按 7 天计算 stale。

### 8.3 API 集成测试

- 创建、轮询、取消、继续使用同一任务 ID。
- 继续任务严格复用原配置。
- active-run 返回完整配置和报告对象。
- 公开与租户数据集使用统一契约。
- 删除接口对数据库和文件报告一致。
- 历史、下载、删除均满足租户隔离。
- 并发删除：一个成功，其余 404，无临时文件残留。

### 8.4 端到端测试

使用 Playwright 覆盖桌面和 390px 移动视口：

1. 默认主策略、混合检索、Rerank 正确。
2. 运行公开 180 题模拟任务，验证进度和指标归属。
3. 运行中不能修改配置。
4. 完成后修改配置，旧指标出现不一致提示。
5. 刷新恢复运行中、失败、可继续任务，配置与服务端一致。
6. 租户任务完成后从当前区域下载，使用 report ID。
7. 从历史删除数据库和文件报告，列表与当前入口同步。
8. API 失败时错误态、重试和按钮恢复。
9. 全集确认框展示服务端题数、策略数、调用拆分和时间。

### 8.5 真实 smoke test

- 固定公开 180 题：主策略 auto、对比 fixed_window、hybrid、Rerank 开启。
- 保存 requested/effective pipeline、模型签名、清单哈希和报告 ID。
- 抽查至少 10 题 Top-20、父块去重、证据命中和 Answer 上下文。
- 验证下载、删除、删除后 404、历史消失。
- 对比估算与实际 ModelUsage，首版允许误差 ±25%。

## 9. 验收标准

以下全部满足才算完成：

1. 不再出现表单是新配置、指标是旧配置却无提示。
2. 运行中不能修改影响任务的配置。
3. 主 Retrieval/RAG 指标来自主分块策略。
4. 每个对比策略使用自己的完整语料隔离索引。
5. 生产与评测在候选数、BM25、距离、RRF、Rerank、父块去重上共享实现或通过一致性测试。
6. 请求的向量、混合、语义分块或 Rerank 未生效时绝不 verified。
7. 每个策略显示正确状态和原因。
8. 当前任务与历史下载都使用 report ID。
9. 报告可删除，数据库/文件、历史、下载状态一致。
10. stale 只由真实数据指纹漂移决定。
11. 全集估算包含所有策略和模型阶段，smoke test 误差达标。
12. 新增测试通过，现有评测、检索、分块、恢复和租户隔离测试无回归。

## 10. 默认假设与边界

- 不改变生产默认向量距离、RRF 参数或 Rerank 模型。
- 不为每个对比策略执行完整 Answer/Judge；全矩阵 RAG 作为后续高成本模式。
- 删除报告不删除 TaskRecord。
- 不强制迁移旧报告，读取时兼容并标记字段缺失。
- 隔离索引可缓存，但不得污染生产 Chunk、FTS 和向量索引。
- 实施时基于当前已有修改继续，禁止覆盖或回退无关工作区变更。