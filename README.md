# 个人轻量知识库

基于 Django + Vue 的 RAG 知识库问答系统，支持多轮对话、Agent 推理、知识图谱、Wiki 自动生成和跨会话记忆。

## 技术栈

| 层级 | 技术 |
|---|---|
| 后端 | Python 3.12、Django 5.2 |
| 数据库 | SQLite + sqlite-vec（向量检索）+ FTS5（全文检索） |
| 图数据库 | Neo4j 5.x（知识图谱 + 记忆系统） |
| 前端 | Vue 3、Vite、Pinia、TDesign Vue Next |
| LLM | 阿里云百炼（DashScope）/ 任意 OpenAI 兼容接口 |

## 快速启动

### 1. 安装依赖

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

### 2. 启动 Neo4j（知识图谱 + 记忆系统）

```bash
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password123 \
  neo4j:5-community
```

### 3. 配置环境变量

复制并编辑 `.env`：

```bash
cp .env.example .env
```

关键配置项：

```env
# LLM 配置（必填）
DASHSCOPE_API_KEY=your_api_key_here

# Neo4j 配置
NEO4J_ENABLE=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password123
```

### 4. 初始化并启动

```bash
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

前端开发模式（另开终端）：

```bash
cd frontend && npm run dev
```

### 5. 访问

打开 `http://localhost:8000`，首次访问自动创建默认账号：

- 邮箱：`admin@knowledge.local`
- 密码：`admin123456`

---

## 核心功能

### 📚 知识库管理

- 支持 PDF、DOCX、TXT、MD、HTML、CSV 等格式
- 自动分块、向量索引、全文索引
- 标签管理、批量操作、跨知识库移动
- 解析状态实时刷新（3 秒轮询）

### 🔍 RAG 检索

- **混合检索**：FTS5 全文 + sqlite-vec 向量 + 知识图谱
- **查询理解**：9 种意图识别 + 查询改写
- **MMR 多样性**：确保结果来自不同文档
- **查询扩展**：召回不足时自动扩展关键词
- **短 chunk 扩展**：自动用相邻内容填充上下文
- **文档头部**：LLM 可见文档标题和描述

### 🤖 Agent 推理

- **ReAct 循环**：Think → Act → Observe，最多 N 轮
- **10 个内置工具**：知识库检索、文档查询、网络搜索、数据库统计等
- **Function Calling**：支持 OpenAI 兼容的工具调用协议
- **并行工具执行**：多工具同时运行
- **上下文窗口管理**：自动压缩过长的对话历史

| 工具 | 说明 |
|---|---|
| `knowledge_search` | 知识库检索 |
| `grep_chunks` | chunk 关键词搜索 |
| `list_knowledge_docs` | 列出文档 |
| `get_document_info` | 文档元信息 |
| `thinking` | 结构化推理 |
| `todo_write` | 任务规划 |
| `web_search` | 网络搜索 |
| `web_fetch` | 网页内容获取 |
| `database_query` | 数据库统计 |
| `read_skill` | 加载 Skill 指令 |

### 🧠 记忆系统

- **Neo4j 图谱存储**：Episode → Entity → Relationship
- **LLM 抽取**：自动从对话中提取实体和关系
- **跨会话检索**：新对话时自动检索相关记忆注入上下文
- **全局开关**：设置页面统一控制

### 📖 Wiki 自动生成

- 自动从文档中提取实体和概念
- 生成结构化 Wiki 页面
- 交叉链接注入
- 索引页自动重建

### 🕸️ 知识图谱

- LLM 驱动的实体/关系抽取
- PMI 权重计算
- 2 跳间接关系扩展
- Neo4j 图数据库存储
- 图谱可视化

---

## 配置说明

### LLM 模型

支持两种配置方式：

**方式 1：环境变量（推荐）**

```env
DASHSCOPE_API_KEY=your_key
ALIYUN_BAILIAN_CHAT_MODEL=qwen3.7-plus
ALIYUN_BAILIAN_EMBEDDING_MODEL=text-embedding-v4
```

**方式 2：数据库配置**

在设置页面添加自定义模型，支持任意 OpenAI 兼容接口（Ollama、DeepSeek、Gemini 等）。

### Neo4j

Neo4j 用于知识图谱和记忆系统。未启用时这两个功能自动降级：

```env
NEO4J_ENABLE=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password123
```

### Langfuse 可观测性（可选）

```env
LANGFUSE_PUBLIC_KEY=your_key
LANGFUSE_SECRET_KEY=your_secret
LANGFUSE_HOST=https://cloud.langfuse.com
```

---

## 生产构建

```bash
cd frontend && npm run build
```

构建产物在 `frontend/dist/`，由 Django 静态文件服务提供。

## 验证

```bash
python manage.py check
cd frontend && npm run build
```

---

## 项目结构

```
Django-Agent/
├── config/                    # Django 项目配置
├── personal_knowledge_base/   # 核心业务逻辑
│   ├── models.py              # 数据模型
│   ├── views.py               # API 视图
│   ├── search.py              # RAG 检索引擎
│   ├── agent_engine.py        # Agent ReAct 引擎
│   ├── agent_tools.py         # Agent 工具系统
│   ├── agent_skills.py        # Skills 系统
│   ├── memory.py              # 记忆系统（Neo4j）
│   ├── mcp_client.py          # MCP 集成
│   ├── observability.py       # Langfuse 可观测性
│   ├── query_understand.py    # 查询理解（意图识别）
│   ├── document_processing.py # 文档处理
│   ├── graph_rag.py           # 知识图谱
│   ├── wiki_ingest.py         # Wiki 生成
│   └── model_providers.py     # LLM 调用
├── frontend/                  # Vue 前端
│   └── src/
│       ├── views/             # 页面组件
│       ├── components/        # 通用组件
│       ├── stores/            # Pinia 状态管理
│       ├── api/               # API 客户端
│       └── styles/            # 全局样式
├── WeKnora/                   # 参考项目（只读）
├── .env                       # 环境变量
├── requirements.txt           # Python 依赖
└── manage.py                  # Django 管理入口
```
