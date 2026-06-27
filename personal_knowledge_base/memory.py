"""
情景记忆系统（Episodic Memory）

基于 Neo4j 图数据库的跨会话记忆，完全复刻 WeKnora 的设计：
- 每次对话完成后，LLM 抽取实体和关系，存入 Neo4j 图
- 新对话开始时，LLM 提取关键词，从图中检索相关记忆注入 prompt

图结构：
  (:MemoryEpisode {id, user_id, session_id, summary, created_at})
  (:MemoryEntity {name, type, description})
  (MemoryEpisode)-[:MENTIONS]->(MemoryEntity)
  (MemoryEntity)-[:RELATED_TO {description, weight}]->(MemoryEntity)
"""

import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from django.conf import settings

logger = logging.getLogger(__name__)

# 后台线程池，用于异步存储记忆
_memory_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="memory")


# ── 数据结构 ─────────────────────────────────────────────────────────
@dataclass
class Episode:
    id: str
    user_id: str
    session_id: str
    summary: str
    created_at: str


@dataclass
class Entity:
    title: str
    type: str
    description: str


@dataclass
class Relationship:
    source: str
    target: str
    description: str
    weight: float = 1.0


@dataclass
class MemoryContext:
    related_episodes: list[Episode] = field(default_factory=list)


# ── LLM Prompts ──────────────────────────────────────────────────────
EXTRACT_GRAPH_PROMPT = """You are an AI assistant that extracts knowledge graphs from conversations.
Given the following conversation, extract entities and relationships.
Output the result in JSON format with the following structure:
{
  "summary": "A brief summary of the conversation",
  "entities": [
    {
      "title": "Entity Name",
      "type": "Entity Type (e.g., Person, Location, Concept, Technology, Organization)",
      "description": "Description of the entity"
    }
  ],
  "relationships": [
    {
      "source": "Source Entity Name",
      "target": "Target Entity Name",
      "description": "Description of the relationship",
      "weight": 1.0
    }
  ]
}

Conversation:
{conversation}"""

EXTRACT_KEYWORDS_PROMPT = """You are an AI assistant that extracts search keywords from a user query.
Given the following query, extract relevant keywords for searching a knowledge graph.
Focus on nouns, proper nouns, and key concepts. Return 3-8 keywords.
Output the result in JSON format:
{{
  "keywords": ["keyword1", "keyword2"]
}}

Query:
{query}"""

# JSON Schema 定义，用于结构化输出
EXTRACT_GRAPH_SCHEMA = {
    "name": "memory_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "A brief summary of the conversation"},
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Entity name"},
                        "type": {"type": "string", "description": "Entity type"},
                        "description": {"type": "string", "description": "Entity description"},
                    },
                    "required": ["title", "type", "description"],
                    "additionalProperties": False,
                },
            },
            "relationships": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "description": "Source entity name"},
                        "target": {"type": "string", "description": "Target entity name"},
                        "description": {"type": "string", "description": "Relationship description"},
                        "weight": {"type": "number", "description": "Relationship weight"},
                    },
                    "required": ["source", "target", "description", "weight"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "entities", "relationships"],
        "additionalProperties": False,
    },
}

EXTRACT_KEYWORDS_SCHEMA = {
    "name": "keyword_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Relevant keywords for searching a knowledge graph",
            },
        },
        "required": ["keywords"],
        "additionalProperties": False,
    },
}


# ── Neo4j 记忆仓库 ──────────────────────────────────────────────────
class MemoryRepository:
    """Neo4j 图数据库记忆仓库，复用 graph_rag 的驱动连接。"""

    def __init__(self):
        self._driver = None

    @property
    def available(self) -> bool:
        return self.enabled and self.driver is not None

    @property
    def enabled(self) -> bool:
        return bool(getattr(settings, "NEO4J_ENABLE", False))

    @property
    def driver(self):
        if not self.enabled:
            return None
        if self._driver is not None:
            return self._driver
        try:
            from neo4j import GraphDatabase
        except ImportError:
            return None
        try:
            self._driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            )
        except Exception:
            self._driver = None
        return self._driver

    def save_episode(self, episode: Episode, entities: list[Entity], relations: list[Relationship]):
        """将 Episode + Entity + 关系写入 Neo4j。"""
        driver = self.driver
        if not driver:
            return
        with driver.session() as session:
            def _write(tx):
                # 1. 创建 Episode 节点
                tx.run(
                    """
                    MERGE (e:MemoryEpisode {id: $id})
                    SET e.user_id    = $user_id,
                        e.session_id = $session_id,
                        e.summary    = $summary,
                        e.created_at = $created_at
                    """,
                    id=episode.id,
                    user_id=episode.user_id,
                    session_id=episode.session_id,
                    summary=episode.summary,
                    created_at=episode.created_at,
                )
                # 2. 创建 Entity 节点 + MENTIONS 边
                for ent in entities:
                    tx.run(
                        """
                        MERGE (n:MemoryEntity {name: $name})
                        SET n.type = $type, n.description = $description
                        WITH n
                        MATCH (e:MemoryEpisode {id: $episode_id})
                        MERGE (e)-[:MENTIONS]->(n)
                        """,
                        name=ent.title,
                        type=ent.type,
                        description=ent.description,
                        episode_id=episode.id,
                    )
                # 3. 创建 Entity 之间的 RELATED_TO 边
                for rel in relations:
                    tx.run(
                        """
                        MATCH (s:MemoryEntity {name: $source})
                        MATCH (t:MemoryEntity {name: $target})
                        MERGE (s)-[r:RELATED_TO {description: $description}]->(t)
                        SET r.weight = $weight
                        """,
                        source=rel.source,
                        target=rel.target,
                        description=rel.description,
                        weight=rel.weight,
                    )

            try:
                session.execute_write(_write)
            except Exception:
                logger.exception("Failed to save memory episode to Neo4j")

    def find_related_episodes(self, user_id: str, keywords: list[str], limit: int = 5) -> list[Episode]:
        """根据关键词检索用户的相关记忆 Episode。"""
        driver = self.driver
        if not driver:
            return []
        with driver.session() as session:
            def _read(tx):
                result = tx.run(
                    """
                    MATCH (e:MemoryEpisode)-[:MENTIONS]->(n:MemoryEntity)
                    WHERE e.user_id = $user_id AND n.name IN $keywords
                    RETURN DISTINCT e
                    ORDER BY e.created_at DESC
                    LIMIT $limit
                    """,
                    user_id=user_id,
                    keywords=keywords,
                    limit=limit,
                )
                episodes = []
                for record in result:
                    node = record["e"]
                    episodes.append(Episode(
                        id=node["id"],
                        user_id=node["user_id"],
                        session_id=node["session_id"],
                        summary=node["summary"],
                        created_at=node["created_at"],
                    ))
                return episodes

            try:
                return session.execute_read(_read)
            except Exception:
                logger.exception("Failed to find related episodes from Neo4j")
                return []


# 全局仓库实例
_memory_repo = MemoryRepository()


def is_memory_available() -> bool:
    """检查记忆系统是否可用（Neo4j 已启用且连接正常）。"""
    return _memory_repo.available


# ── LLM 调用 ─────────────────────────────────────────────────────────
def _structured_completion(tenant, prompt: str, schema: dict, model_id: str = "") -> dict | None:
    """调用 LLM 并要求结构化 JSON 输出。"""
    from .model_providers import chat_completion

    messages = [{"role": "user", "content": prompt}]
    try:
        # 尝试使用 response_format 要求结构化输出
        raw = _chat_completion_raw(tenant, messages, model_id, response_format={
            "type": "json_schema",
            "json_schema": schema,
        })
        if raw:
            return json.loads(raw)
    except Exception:
        pass

    # 回退：普通 LLM 调用 + JSON 解析
    try:
        raw = _chat_completion_raw(tenant, messages, model_id)
        if raw:
            # 尝试提取 JSON 块
            import re
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                return json.loads(match.group())
    except Exception:
        logger.exception("Failed to parse LLM response as JSON")
    return None


def _chat_completion_raw(tenant, messages: list[dict], model_id: str = "", response_format: dict | None = None) -> str:
    """底层 LLM 调用，支持 response_format。"""
    from .model_providers import (
        ModelConfigurationError,
        _env_text_completion,
        default_model,
        is_env_chat_model_id,
        openai_compatible_chat_raw,
    )
    from django.conf import dj_settings

    # 环境变量配置的 Bailian 模型
    if (not model_id or is_env_chat_model_id(model_id)) and dj_settings.WEKNORA_USE_BAILIAN_CHAT and dj_settings.DASHSCOPE_API_KEY:
        base_url = dj_settings.ALIYUN_BAILIAN_BASE_URL
        api_key = dj_settings.DASHSCOPE_API_KEY
        model_name = dj_settings.ALIYUN_BAILIAN_CHAT_MODEL
    else:
        if is_env_chat_model_id(model_id):
            raise ModelConfigurationError("Bailian chat model is not configured")
        from .models import ModelConfig
        model = ModelConfig.objects.filter(id=model_id, tenant=tenant).first() if model_id else default_model(tenant, "chat")
        if not model:
            raise ModelConfigurationError("No chat model configured")
        params = model.parameters or {}
        base_url = (params.get("base_url") or params.get("baseURL") or "").rstrip("/")
        api_key = params.get("api_key") or params.get("apiKey") or params.get("token")
        model_name = params.get("model") or model.name

    url = f"{base_url.rstrip('/')}/chat/completions" if not base_url.endswith("/chat/completions") else base_url
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {"model": model_name, "messages": messages, "stream": False}
    if response_format:
        body["response_format"] = response_format

    import requests as req
    resp = req.post(url, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


# ── 核心接口 ─────────────────────────────────────────────────────────
def add_episode(tenant, user_id: str, session_id: str, messages: list[dict]):
    """
    将一轮对话存入记忆图谱。
    在后台线程中执行，不阻塞调用方。
    """
    if not _memory_repo.available:
        return

    def _do():
        try:
            # 1. 拼接对话文本
            conversation = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            prompt = EXTRACT_GRAPH_PROMPT.format(conversation=conversation)

            # 2. LLM 抽取实体和关系
            result = _structured_completion(tenant, prompt, EXTRACT_GRAPH_SCHEMA)
            if not result:
                logger.warning("Memory extraction returned no result")
                return

            # 3. 构建 Episode
            episode = Episode(
                id=str(uuid.uuid4()),
                user_id=user_id,
                session_id=session_id,
                summary=result.get("summary", ""),
                created_at=datetime.now(timezone.utc).isoformat(),
            )

            # 4. 构建 Entity 和 Relationship
            entities = [Entity(**e) for e in result.get("entities", []) if e.get("title")]
            relations = [Relationship(**r) for r in result.get("relationships", []) if r.get("source") and r.get("target")]

            # 5. 写入 Neo4j
            _memory_repo.save_episode(episode, entities, relations)
            logger.info(f"Memory episode saved: {episode.id}, entities={len(entities)}, relations={len(relations)}")
        except Exception:
            logger.exception("Failed to add memory episode")

    _memory_executor.submit(_do)


def retrieve_memory(tenant, user_id: str, query: str) -> MemoryContext:
    """
    根据用户问题检索相关记忆。
    返回 MemoryContext，包含相关 Episode 摘要列表。
    """
    if not _memory_repo.available:
        return MemoryContext()

    try:
        # 1. LLM 提取关键词
        prompt = EXTRACT_KEYWORDS_PROMPT.format(query=query)
        result = _structured_completion(tenant, prompt, EXTRACT_KEYWORDS_SCHEMA)
        if not result or not result.get("keywords"):
            return MemoryContext()

        keywords = [k for k in result["keywords"] if isinstance(k, str) and k.strip()]
        if not keywords:
            return MemoryContext()

        # 2. Neo4j 检索相关 Episode
        episodes = _memory_repo.find_related_episodes(user_id, keywords, limit=5)
        return MemoryContext(related_episodes=episodes)
    except Exception:
        logger.exception("Failed to retrieve memory")
        return MemoryContext()
