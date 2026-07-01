# 个人轻量知识库

<p align="center">
  <strong>基于 Django + Vue 的 RAG 知识库问答系统</strong>
</p>

<p align="center">
  <a href="#features">功能特性</a> •
  <a href="#quickstart">快速开始</a> •
  <a href="#configuration">配置说明</a> •
  <a href="#architecture">架构设计</a> •
  <a href="#contributing">参与贡献</a>
</p>

---

<a name="features"></a>

## ✨ 功能特性

- 🔍 **智能检索** - 混合检索架构（Wiki 预合成 → RAG 检索 → 知识图谱补充）
- 🤖 **Agent 推理** - 基于 ReAct 范式的多工具调度引擎
- 🧠 **三层记忆** - 短期（对话历史）+ 工作（上下文压缩）+ 长期（Neo4j 图谱）
- 📖 **Wiki 自动生成** - LLM 驱动的实体抽取与知识网络构建
- 🔄 **流式输出** - 生成与推送解耦，支持断线重连
- 🔧 **MCP 工具仓库** - 14 个内置工具，支持并行调度

<a name="quickstart"></a>

## 🚀 快速开始

### 前置条件

- Python 3.10+
- Node.js 18+
- Neo4j 5.x（可选，用于知识图谱和记忆系统）

### 安装

```bash
# 克隆仓库
git clone https://github.com/LiuXD1011/Django-Agent.git
cd Django-Agent

# 安装后端依赖
pip install -r requirements.txt

# 安装前端依赖
cd frontend && npm install && cd ..
```

### 配置

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env，配置 LLM 接口
# LLM_CHAT_API_KEY=your_api_key
# LLM_CHAT_BASE_URL=https://api.deepseek.com/v1
# LLM_CHAT_MODEL=deepseek-chat
```

### 启动

```bash
# 启动 Neo4j（可选）
docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password neo4j:5-community

# 数据库迁移
python manage.py migrate

# 启动后端
python manage.py runserver

# 启动前端（另开终端）
cd frontend && npm run dev
```

访问 `http://localhost:8000`，首次访问自动创建默认账号。

<a name="configuration"></a>

## ⚙️ 配置说明

### LLM 模型配置

支持每个模型独立配置 API Key 和 Base URL：

```env
# 对话模型
LLM_CHAT_API_KEY=sk-xxx
LLM_CHAT_BASE_URL=https://api.deepseek.com/v1
LLM_CHAT_MODEL=deepseek-chat

# Embedding 模型（可使用不同提供商）
LLM_EMBEDDING_API_KEY=sk-yyy
LLM_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_EMBEDDING_MODEL=text-embedding-v4

# Rerank 模型
LLM_RERANK_API_KEY=sk-zzz
LLM_RERANK_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_RERANK_MODEL=qwen3-rerank
```

### Neo4j 配置

```env
NEO4J_ENABLE=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
```

<a name="architecture"></a>

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                        前端 (Vue 3)                          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     Django API 层                            │
├─────────────┬─────────────┬─────────────┬───────────────────┤
│  accounts   │  knowledge  │    chat     │      agent        │
│  认证/用户   │  知识库/文档  │  对话/会话   │    推理引擎       │
└─────────────┴─────────────┴─────────────┴───────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      核心模块                                │
├─────────────┬─────────────┬─────────────┬───────────────────┤
│   search    │   memory    │    wiki     │   model_providers │
│  RAG 检索   │  记忆系统    │  Wiki 生成   │    LLM 调用       │
└─────────────┴─────────────┴─────────────┴───────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      存储层                                  │
├─────────────┬─────────────┬─────────────────────────────────┤
│   SQLite    │   Neo4j     │         文件系统                  │
│  向量/全文   │  知识图谱    │         文档存储                  │
└─────────────┴─────────────┴─────────────────────────────────┘
```

### 项目结构

```
Django-Agent/
├── accounts/              # 用户与认证
├── knowledge/             # 知识库与文档管理
├── chat/                  # 对话与会话
├── wiki/                  # Wiki 系统
├── agent/                 # Agent 引擎
├── models_config/         # 模型管理
├── graph/                 # 知识图谱
├── core/                  # 共享模块
├── personal_knowledge_base/  # 核心模块
├── frontend/              # Vue 前端
├── config/                # Django 配置
└── manage.py              # Django 管理入口
```

<a name="contributing"></a>

## 🤝 参与贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/xxx`)
3. 提交更改 (`git commit -m 'feat: add xxx'`)
4. 推送到分支 (`git push origin feature/xxx`)
5. 创建 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 🙏 致谢

- [WeKnora](https://github.com/WeKnora/WeKnora) - 参考架构
- [RAGAs](https://github.com/explodinggradients/ragas) - RAG 评估框架
- [Django](https://www.djangoproject.com/) - Web 框架
- [Vue.js](https://vuejs.org/) - 前端框架
