# 轻量个人知识库

<p align="center">
  <strong>面向个人文档管理、知识库沉淀与 AI 问答的本地优先知识工作台。</strong>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="Django" src="https://img.shields.io/badge/Django-5.2-092E20?style=flat-square&logo=django&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/SQLite-FTS5%20%2B%20sqlite--vec-003B57?style=flat-square&logo=sqlite&logoColor=white">
  <img alt="Storage" src="https://img.shields.io/badge/Storage-Local%20FileSystem-2563EB?style=flat-square">
</p>

---

## 项目简介

轻量个人知识库是一个本地优先的 Django 应用，用于管理个人文件、构建知识库、生成 Wiki 总览，并通过统一 AI 助手进行问答。

项目当前采用纯本地运行架构：SQLite 保存业务数据、对话、记忆、全文索引和向量索引；本地文件系统保存上传文件和头像；Django `LocMemCache` 提供进程内缓存。默认不依赖 MySQL、Milvus、Redis、MinIO 或 Docker 服务。

适合以下场景：

- 在个人电脑或轻量服务器上管理文档和资料。
- 将 PDF、DOCX、PPTX、Markdown、HTML、文本等文件入库，进行 RAG 问答。
- 将知识库内容沉淀为可浏览、可复用的 Wiki 页面。
- 在同一个 AI 助手入口中组合普通聊天、文件信息、知识库检索、Wiki 上下文和长期记忆。

## 核心功能

- **文件管理**：支持文件上传、分片上传、秒传、文件夹、移动、复制、下载、回收站和本地头像。
- **知识库入库**：使用 LangChain loader 解析多种文档格式，并统一切块、向量化和索引。
- **本地 RAG 检索**：使用 SQLite FTS5 做关键词/子串检索，使用 `sqlite-vec` 做向量检索，并进行融合召回。
- **候选重排**：支持 DashScope `qwen3-vl-rerank` 对候选片段重排；未配置时自动降级为融合排序。
- **Wiki 层**：为知识库生成 overview 和 source Wiki 页面，将原始资料整理为结构化知识。
- **统一 AI 助手**：单入口聊天，可允许使用文件信息，也可选择一个知识库作为问答范围。
- **多 Agent 编排**：内部使用 `AssistantOrchestrator` 协调 DriveAgent、WikiAgent、KnowledgeRAGAgent 和 AnswerAgent。
- **对话与记忆**：支持多会话、会话 checkpoint、用户级/知识库级长期记忆，并通过 FTS5 检索注入上下文。
- **本地优先部署**：默认只依赖 Python、Django、SQLite 和本地文件系统，适合个人使用和轻量部署。

## 系统架构

```text
浏览器
  |
  v
Django 视图与模板
  |
  +-- 文件模块
  |     本地 FileSystemStorage
  |
  +-- 知识库模块
  |     LangChain loaders -> chunks -> embeddings
  |     SQLite FTS5 + sqlite-vec
  |
  +-- Wiki 模块
  |     Source pages + overview pages
  |     SQLite FTS5 + sqlite-vec
  |
  +-- AI 助手模块
        ConversationContextBuilder
        AssistantOrchestrator
        DriveAgent / WikiAgent / KnowledgeRAGAgent / AnswerAgent
        ConversationMemory + FTS5
```

### 数据存储

| 数据类型 | 存储方式 |
| --- | --- |
| 用户、文件元数据、对话、记忆、知识库 | SQLite |
| 全文索引 | SQLite FTS5 |
| 向量索引 | sqlite-vec |
| 上传文件和头像 | 本地 `media/` 目录 |
| 缓存 | Django LocMemCache |

## 技术栈

- Python 3.12
- Django 5.2
- SQLite、FTS5、sqlite-vec
- LangChain Community loaders
- OpenAI 兼容的聊天与 Embedding API
- DashScope 文本重排 API
- Django Templates、原生 JavaScript、CSS

## 快速开始

### 1. 创建运行环境

```bash
conda create -y -n django-agent python=3.12
conda activate django-agent
pip install -r requirements.txt
```

也可以使用 Python 内置虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 创建本地配置

```bash
cp .env.example .env.local
```

至少需要替换默认密钥：

```dotenv
DJANGO_SECRET_KEY=CHANGE_ME_GENERATE_A_LONG_RANDOM_SECRET
```

如需启用 AI 生成、Embedding 和重排能力，可继续配置：

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=
LLM_MODEL=deepseek-chat

EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_VECTOR_DIM=96

RERANK_MODEL=qwen3-vl-rerank
RERANK_API_KEY=
```

`RERANK_API_KEY` 为空时，系统会尝试复用 `EMBEDDING_API_KEY`。

### 3. 初始化数据库

```bash
python manage.py migrate
python manage.py check_external_services
python manage.py createsuperuser
```

### 4. 启动开发服务

```bash
python manage.py runserver 0.0.0.0:8000
```

访问地址：

```text
http://127.0.0.1:8000/
```

如果通过 WSL2 或局域网访问，请将实际访问地址加入：

```dotenv
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,你的IP
```

## 配置说明

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | 必填 | Django 签名与加密密钥，使用前请替换。 |
| `DJANGO_DEBUG` | `1` | 调试模式。非本地开发环境建议设置为 `0`。 |
| `DJANGO_ALLOWED_HOSTS` | `127.0.0.1,localhost` | 允许访问的主机名或 IP，多个值用英文逗号分隔。 |
| `SQLITE_DATABASE_PATH` | `db.sqlite3` | SQLite 数据库路径。 |
| `DEFAULT_STORAGE_QUOTA_BYTES` | `10737418240` | 默认用户存储配额，默认 10 GB。 |
| `LLM_BASE_URL` | 按服务商配置 | OpenAI 兼容聊天接口地址。 |
| `LLM_API_KEY` | 空 | 聊天模型 API Key。 |
| `LLM_MODEL` | `deepseek-chat` | 聊天模型名称。 |
| `EMBEDDING_BASE_URL` | 按服务商配置 | OpenAI 兼容 Embedding 接口地址。 |
| `EMBEDDING_API_KEY` | 空 | Embedding API Key。 |
| `EMBEDDING_MODEL` | `text-embedding-v4` | Embedding 模型名称。 |
| `EMBEDDING_VECTOR_DIM` | `96` | sqlite-vec 向量表维度。 |
| `RERANK_MODEL` | `qwen3-vl-rerank` | 重排模型名称。 |
| `RERANK_API_KEY` | 空 | 重排 API Key。 |

## 常用命令

```bash
# 项目检查
python manage.py check
python manage.py check_external_services

# 运行测试
python manage.py test

# 数据库迁移
python manage.py makemigrations
python manage.py migrate

# 创建管理员账号
python manage.py createsuperuser

# 收集静态资源
python manage.py collectstatic --noinput
```

## 项目结构

```text
accounts/      用户模型、个人资料、认证、用户管理
assistant/     AI 助手、对话、记忆、多 Agent 编排
config/        Django 项目配置与根路由
drive/         本地文件管理、上传、文件夹、回收站
knowledge/     知识库入库、RAG、Wiki、SQLite 索引
scripts/       本地辅助脚本
static/        CSS、JavaScript、图片资源
templates/     Django 模板
```

## 开发说明

- 项目默认面向本地和单机轻量部署，尽量减少外部基础设施依赖。
- 上传文件和头像默认保存在 `media/`。
- SQLite 数据库默认保存在 `db.sqlite3`。
- 如果修改 `EMBEDDING_VECTOR_DIM`，需要重建向量索引或重新入库知识库。
- 未配置 AI Key 时，文件管理等基础功能仍可使用；AI 生成、Wiki 生成、重排和长期记忆抽取会降级或跳过。

## 数据备份

建议同时备份数据库和上传文件：

```bash
cp db.sqlite3 db.sqlite3.bak
cp -a media media.bak
```

恢复时需要同时恢复二者。数据库保存文件元数据，`media/` 保存真实文件内容。

## 发布前检查

公开发布前建议执行：

```bash
git status --short
rg -n "SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE|/home/" .
```

`.env.example` 用作公开配置模板，部署环境的真实配置应保存在本地环境中。

## 路线图

- 长期记忆管理界面。
- 知识库重建和批量刷新工具。
- Wiki 页面编辑与刷新冲突处理。
- 更多文档解析器和更丰富的元数据提取。
- 可选的生产部署指南。

## 许可证

当前仓库尚未包含许可证文件。公开发布前建议补充 `LICENSE`，明确他人是否可以使用、修改和再分发本项目。
