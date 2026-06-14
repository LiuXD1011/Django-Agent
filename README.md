# 轻量个人知识库

<p align="center">
  本地优先的个人知识管理与 RAG 问答系统，面向文档入库、知识沉淀、多会话记忆和可追溯 AI 助手。
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-blue">
  <img alt="Django" src="https://img.shields.io/badge/Django-5.x-0C4B33">
  <img alt="SQLite" src="https://img.shields.io/badge/SQLite-FTS5%20%2B%20sqlite--vec-003B57">
  <img alt="Local First" src="https://img.shields.io/badge/Local--first-yes-111827">
</p>

## Overview

轻量个人知识库是一个 Django 本地应用，用于管理个人文件、解析多格式文档、构建本地 RAG 索引，并通过统一 AI 助手完成普通聊天、文件信息问答、知识库问答和长期记忆管理。

项目的重点不是做一个简单聊天壳，而是围绕个人资料场景解决几个核心问题：

- 文档格式复杂，解析失败不能污染索引。
- 向量检索对文件名、编号、中文子串和专有名词不够稳定。
- RAG 回答需要可追溯到原始文档片段。
- 长对话不能无限塞进 prompt，需要会话隔离、checkpoint 和长期记忆。
- 多能力问答需要统一入口，而不是拆成多个割裂的页面。

## Highlights

- **本地优先存储**：使用 SQLite、FTS5、sqlite-vec、FileSystemStorage 和 LocMemCache，默认不依赖 Docker、MySQL、Milvus、Redis 或 MinIO。
- **Content Runtime 入库前置层**：通过扩展名、MIME、magic bytes 和二进制特征识别文件族，路由到 LangChain Loader、XLSX 表格解析、LibreOffice 转换、视觉模型抽取或失败隔离。
- **混合 RAG 检索**：同时使用 sqlite-vec 向量召回和 FTS5 trigram 关键词召回，经过 Query Rewrite、Rank Fusion、Rerank 后把 references 注入回答 prompt。
- **Wiki 知识沉淀层**：在原始 chunk 之上生成 source / overview Wiki 页面，并维护 WikiLink、健康检查和图谱 JSON。
- **统一 AI 助手**：一个聊天入口内编排 DriveAgent、WikiAgent、KnowledgeRAGAgent 和 AnswerAgent，保留 AgentRun / AgentEvent 运行链路。
- **多会话与长期记忆**：支持 Conversation、checkpoint、用户级/知识库级长期记忆和 FTS5 记忆检索。
- **可观测与可评估**：提供 `search_with_trace()` 和 `evaluate_rag`，用于分析 query rewrite、召回、融合、rerank 和最终命中效果。

## Architecture

```text
File Upload
  -> Content Runtime
     -> inspect: extension / MIME / magic bytes / binary sample
     -> route: loader / converter / vision / isolation
  -> Entry
  -> Recursive Chunking
  -> Embedding
  -> SQLite FTS5 + sqlite-vec
  -> Query Rewrite
  -> Vector + FTS Retrieval
  -> Rank Fusion + Rerank
  -> References + LLM Answer
```

```text
Assistant
  -> ConversationContextBuilder
     -> checkpoint
     -> long-term memories
     -> recent messages
  -> AssistantOrchestrator
     -> DriveAgent
     -> WikiAgent
     -> KnowledgeRAGAgent
     -> AnswerAgent
  -> SSE streaming response
```

## Quick Start

### 1. Create Environment

```bash
conda create -y -n django-agent python=3.12
conda activate django-agent
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env.local
```

Minimum local configuration:

```env
DJANGO_SECRET_KEY=CHANGE_ME_TO_A_LONG_RANDOM_SECRET
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
SQLITE_DATABASE_PATH=db.sqlite3
```

Optional AI configuration:

```env
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=
LLM_MODEL=qwen-plus

EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_VECTOR_DIM=96

RERANK_MODEL=qwen3-vl-rerank
RERANK_API_KEY=

VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VISION_API_KEY=
VISION_MODEL=qwen-vl-plus
VISION_MAX_PDF_PAGES=5
```

Optional document processing configuration:

```env
LIBREOFFICE_BINARY=soffice
DOCUMENT_CONVERSION_TIMEOUT_SECONDS=60
OFFICE_MIN_TOTAL_TEXT_CHARS=200
OFFICE_MIN_AVG_ENTRY_TEXT_CHARS=30
```

### 3. Initialize Database

```bash
python manage.py migrate
python manage.py check_external_services
python manage.py createsuperuser
```

### 4. Run

```bash
python manage.py runserver 0.0.0.0:8000
```

Open:

```text
http://127.0.0.1:8000/
```

## Common Commands

```bash
python manage.py check
python manage.py test
python manage.py check_external_services
```

Run a RAG evaluation dataset:

```bash
python manage.py evaluate_rag \
  --kb 1 \
  --dataset eval.jsonl \
  --top-k 6 \
  --format markdown
```

Evaluation JSONL format:

```json
{"question":"这篇论文主要解决什么问题？","expected_document_title":"example.pdf","expected_contains":"keyword"}
```

## Project Layout

```text
accounts/          user profile and permissions
assistant/         conversations, memory, agents, streaming assistant
config/            Django settings and root urls
content_runtime/   file inspection, routing, conversion and extraction
drive/             local file management
knowledge/         knowledge bases, RAG indexes, Wiki pages
static/            global CSS and frontend assets
templates/         Django templates
```
