# VLM 熔断、任务恢复与知识清理设计

## 背景与目标

当前多模态文档处理存在三个相互放大的问题：阿里云百炼 VLM 免费额度耗尽后，每张图片仍重复发起 OCR 和 Caption 请求；Django 进程重启后，数据库中的 `pending` 和失去执行进程的 `running` 任务不会恢复；重复上传和软删除记录遗留任务、文件及派生数据。

本次改造保持 Django 单体、SQLite、本地存储和现有顺序任务队列，不引入 Redis、Celery 或独立常驻 Worker。目标是让 VLM 权限故障快速降级，让文档任务可在服务重启后恢复，并提供安全、可审计的重复数据清理能力。

## 全局约束

- 只修改 Django-Agent 主项目。
- 不修改 `MiMo-Code`、`open-webui`、`WeKnora`、`xiaolinnote_ai` 及其子目录。
- 继续在本地 `main` 分支工作，不创建新分支或 worktree。
- 保留 SQLite 顺序执行，避免恢复任务并发写入数据库。
- 重复知识只在同一租户、同一知识库内判定；跨知识库的相同文件必须保留。
- VLM 权限故障不得导致含图文档的文本解析失败。

## 1. VLM 权限识别与单文档熔断

### 已确认的外部原因

当前环境使用阿里云百炼兼容端点和 `qwen-vl-plus`。服务端返回 HTTP 403，错误码为 `AllocationQuota.FreeTierOnly`，含义是免费额度已耗尽且账户启用了“仅使用免费额度”。项目代码无法代替用户修改阿里云账户的付费或额度设置。

账户侧恢复方式是关闭“仅使用免费额度”或补充付费信息。代码侧负责准确识别、快速停止重复请求并给出安全告警。

### 异常模型

模型调用层新增明确的访问拒绝异常，包含：

- HTTP 状态码；
- 上游错误码；
- 不含密钥的错误信息；
- 是否属于不可重试的权限/配额错误。

OpenAI 兼容请求遇到 401 或 403 时，将响应中的错误码和信息解析为该异常。其他网络错误、超时和 5xx 继续沿用现有普通失败路径。

### 熔断范围与行为

熔断器作用域限定为一次 `process_document_images()` 调用，不跨文档持久化：

1. OCR 或 Caption 第一次遇到不可重试的 401/403 后，立即打开本次文档的 VLM 熔断器。
2. 当前图片不再继续发起第二种视觉请求。
3. 后续图片仍创建 `KnowledgeImage` 资产记录，但不再访问远程 VLM。
4. 被跳过图片统一记录访问拒绝原因，状态为 `failed`；已经成功取得 OCR 或 Caption 的图片允许保留已有结果并标记 `partial`。
5. 含图文档继续进入 Embedding 和后续阶段；单独图片仍按现有规则在没有任何可检索结果时失败。
6. 下一个新文档重新尝试一次 VLM，使账户权限修复后无需重启应用即可恢复。

Parser 能力检测接口应在探测到访问拒绝时返回 `vlm_available: false` 和安全的不可用原因，不暴露 API Key 或完整请求数据。该能力观察记录只保存在当前进程使用的 Django cache 中，有效期 300 秒；它是短期诊断信号，不是跨进程的全局熔断状态，也不改变“下一份新文档重新尝试 VLM”的行为。

## 2. 数据库任务恢复与租约

### 数据库作为恢复源

`TaskRecord` 继续作为任务状态的事实来源，内存 `deque` 只负责当前进程内的顺序调度。任务恢复仅支持能够由 `task_type + payload` 重建的已知任务；本次首先支持 `process_knowledge`。

任务处理函数注册表负责将：

```text
process_knowledge + {knowledge_id} -> process_knowledge(knowledge_id)
```

重建为可执行函数。未知任务类型不自动恢复，并记录明确失败原因。

### 原子认领

任务执行前使用带状态条件的数据库更新，将 `pending` 原子变为 `running`。更新行数为零代表任务已经被其他线程或进程认领，当前执行器必须直接跳过。这样即使 Django 自动重载或多个应用进程同时扫描，也不会重复处理同一任务。

### 心跳租约

- 任务运行时每 15 秒刷新一次 `TaskRecord.updated_at`。
- 任务完成或失败后立即停止心跳线程。
- 启动恢复时，超过 90 秒未更新的 `running` 任务视为租约过期，重置为 `pending`。
- 最近 90 秒仍有心跳的 `running` 任务不触碰。

复用现有 `updated_at` 作为租约时间，不增加数据库字段或迁移。

### 启动恢复

Django 实际服务进程启动后执行一次恢复：

1. 将租约过期的 `running` 文档任务重置为 `pending`。
2. 删除或终止指向不存在、已软删除或已取消 Knowledge 的任务。
3. 同一 Knowledge 存在多个未完成任务时，通常保留最早一条；用户批准的例外是存在租约仍新鲜的 `running` 任务时，优先保留该运行所有者，即使另有更早的 `pending` 任务，避免并发重复执行。其余任务标记为失败，并说明已被合并。
4. 将剩余 `pending process_knowledge` 按创建时间加入现有顺序队列。

`migrate`、`makemigrations`、`test`、`shell` 等管理命令不启动恢复器。`runserver` 只在自动重载后的实际服务子进程中恢复。启动扫描发生数据库表不存在等初始化错误时，仅记录日志，不阻塞 Django 启动。

### 进度与失败语义

恢复任务使用原任务 ID，不创建新的 `TaskRecord`。成功后变为 `completed`；业务异常按现有规则变为 `failed`；SQLite 锁错误继续使用现有有限重试。恢复动作本身不改变 Knowledge 的业务状态，实际处理函数开始时再设置 `parse_status=processing`。

## 3. 重复知识与失效任务清理

### 管理命令

新增：

```bash
python manage.py cleanup_knowledge_state
python manage.py cleanup_knowledge_state --confirm
```

默认模式只打印计划清理的重复组、知识记录、任务和文件数量，不写入数据库或存储。只有 `--confirm` 才执行不可逆清理，并输出实际处理汇总。

### 重复判定与保留规则

重复键为：

```text
(tenant_id, knowledge_base_id, file_hash)
```

其中 `file_hash` 必须为非空 SHA-256。文件名不同但字节完全相同仍视为重复；跨租户或跨知识库永不合并。

保留顺序：

1. `deleted_at` 为空的有效记录优先；
2. 多个有效记录中 `parse_status=completed` 优先；
3. 状态相同时保留创建时间最早的记录。

当前数据中较早副本已经软删除、较晚副本仍有效，因此保留有效副本并彻底清理软删除副本，避免恢复用户已经主动删除的旧记录或删除当前可见知识。

### 清理范围

每个被清理 Knowledge 同步处理：

- 取消并删除关联 `TaskRecord`；
- 删除 `KnowledgeProcessingSpan`；
- 删除 Chunk 对应的 FTS 和向量索引，再删除 Chunk；
- 删除 Neo4j Knowledge 命名空间；
- 清理 Wiki 待处理操作、引用和派生页面；
- 删除 `KnowledgeImage`；仅删除 `storage_owned=true` 的派生图片文件；
- 删除 Knowledge 数据行；
- 原始文件仅在没有任何保留 Knowledge 引用相同 `file_path` 时删除。

清理操作应逐 Knowledge 隔离。外部 Neo4j 或 Wiki 清理失败时，命令记录错误并保留该 Knowledge 数据行，避免出现“数据库已删除但外部残留无法重试”的半清理状态。

数据库提交后才可安全删除的索引、缓存和存储文件由 `cleanup_knowledge_artifacts` TaskRecord 清单持久化。清理命令在后续运行中重试这些清单并在全部成功后删除记录；启动任务恢复器明确跳过该类型，避免把清理清单当作未知业务任务置为失败。

### 失效任务整理

- 指向不存在或已软删除 Knowledge 的未完成任务删除。
- 同一有效 Knowledge 的多个 `pending/running` 任务按上述规则合并：新鲜 `running` 所有者优先，否则保留最早一条。
- 租约过期的唯一 `running` 任务重置为 `pending`，由启动恢复逻辑执行。
- 有效 Knowledge 的历史 `completed/failed` 任务保留用于诊断；重复 Knowledge 被删除时，其全部任务随之删除。

## 4. 测试与验收

### VLM

- Mock 403 `AllocationQuota.FreeTierOnly`，验证当前图片不再调用 Caption，后续图片不再调用 VLM。
- 验证每张图片仍有失败资产和统一告警。
- 验证普通超时或单张图片内容错误不会错误触发权限熔断。
- 验证下一个文档会重新尝试 VLM。
- 验证含图文档降级完成，单图无结果仍失败。

### 任务恢复

- 验证启动恢复 pending 任务。
- 验证 90 秒内有心跳的 running 任务不恢复，过期任务会恢复。
- 验证原子认领只允许一个执行器运行。
- 验证同一 Knowledge 的重复未完成任务被合并。
- 验证软删除、取消和不存在 Knowledge 的任务不会运行。
- 验证测试、迁移和 shell 命令不触发后台恢复。

### 清理

- 验证同知识库相同哈希被识别，跨知识库相同哈希保留。
- 验证有效副本优先于较早的软删除副本。
- 验证预览模式零写入。
- 验证确认模式清理任务、Span、Chunk、索引、图片、Wiki、图谱和无共享引用的文件。
- 验证共享 `file_path` 不会被误删。
- 验证外部清理失败时保留 Knowledge 以便重试。

### 最终验证

- 执行 Django 全量测试。
- 执行 `python manage.py makemigrations --check --dry-run`。
- 对当前数据库先执行清理预览，再执行 `--confirm`，核对保留和删除 ID。
- 重启本地 Django 服务，验证 pending 任务恢复且没有重复执行。
- 检查 `git diff --name-only`，不得出现四个参考项目路径。

## 非目标

- 不代替用户修改阿里云账户的付费、配额或“仅免费额度”设置。
- 不引入跨机器分布式任务调度。
- 不并行处理多个文档。
- 不改变 GraphRAG 或 Wiki 的启用策略与性能。
