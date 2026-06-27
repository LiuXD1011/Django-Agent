"""
Agent 工具系统

参考 WeKnora 的 agent/tools/ 设计：
- Tool 接口：Name, Description, Parameters, Execute
- ToolRegistry：注册、查找、执行工具
- 内置工具：knowledge_search, grep_chunks, get_document_info, thinking
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from django.db.models import Q

logger = logging.getLogger(__name__)

MAX_TOOL_OUTPUT = 16 * 1024  # 16KB，防止上下文窗口污染


# ── 数据结构 ─────────────────────────────────────────────────────────
@dataclass
class ToolResult:
    output: str
    data: Any = None
    error: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict:
        result = {"output": self.output[:MAX_TOOL_OUTPUT]}
        if self.error:
            result["error"] = self.error
        if self.data:
            result["data"] = self.data
        return result


# ── 工具基类 ─────────────────────────────────────────────────────────
class Tool(ABC):
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def description(self) -> str:
        pass

    @abstractmethod
    def parameters(self) -> dict:
        """返回 JSON Schema 格式的参数定义。"""
        pass

    @abstractmethod
    def execute(self, args: dict, context: dict) -> ToolResult:
        """
        执行工具。
        args: LLM 传入的参数
        context: 运行时上下文 {"tenant": ..., "kb_ids": ..., "session_id": ..., "user_id": ...}
        """
        pass

    def to_openai_tool(self) -> dict:
        """转换为 OpenAI function calling 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name(),
                "description": self.description(),
                "parameters": self.parameters(),
            },
        }


# ── 工具注册表 ───────────────────────────────────────────────────────
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        """注册工具，首次注册优先（防劫持）。"""
        if tool.name() not in self._tools:
            self._tools[tool.name()] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def to_openai_tools(self, allowed: list[str] | None = None) -> list[dict]:
        """生成 OpenAI function calling 格式的工具列表。"""
        tools = self._tools.values()
        if allowed:
            tools = [t for t in tools if t.name() in allowed]
        return [t.to_openai_tool() for t in tools]

    def execute_tool(self, name: str, args: dict, context: dict) -> ToolResult:
        """执行指定工具。"""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(output="", error=f"Unknown tool: {name}")

        start = time.monotonic()
        try:
            result = tool.execute(args, context)
            result.duration_ms = int((time.monotonic() - start) * 1000)
            return result
        except Exception as e:
            logger.exception(f"Tool {name} execution failed")
            return ToolResult(
                output="",
                error=f"{type(e).__name__}: {str(e)}\n[Analyze the error above and try a different approach.]",
                duration_ms=int((time.monotonic() - start) * 1000),
            )


# ── 内置工具实现 ─────────────────────────────────────────────────────
class KnowledgeSearchTool(Tool):
    """知识库检索工具。"""

    def name(self) -> str:
        return "knowledge_search"

    def description(self) -> str:
        return "Search the knowledge base for relevant documents. Returns document chunks with titles and relevance scores."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "top_k": {"type": "integer", "description": "Number of results to return (default 5)", "default": 5},
            },
            "required": ["query"],
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        from .search import hybrid_search

        query = args.get("query", "")
        top_k = args.get("top_k", 5)
        tenant_id = context.get("tenant_id")
        kb_ids = context.get("kb_ids", [])

        if not query:
            return ToolResult(output="", error="Query is required")

        refs = hybrid_search(tenant_id, kb_ids, query, top_k)
        if not refs:
            return ToolResult(output="No relevant documents found.", data=[])

        # 格式化输出
        lines = []
        for i, r in enumerate(refs, 1):
            title = r.get("knowledge_title", "Unknown")
            content = r.get("content", "")[:500]
            score = r.get("score", 0)
            lines.append(f"[{i}] {title} (score: {score:.2f})\n{content}")

        output = "\n\n".join(lines)
        return ToolResult(output=output, data=refs)


class GrepChunksTool(Tool):
    """在已检索的 chunk 中搜索关键词。"""

    def name(self) -> str:
        return "grep_chunks"

    def description(self) -> str:
        return "Search for specific keywords within previously retrieved knowledge chunks. Use this to find specific information without making a new knowledge search."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "keywords": {"type": "string", "description": "Keywords to search for"},
                "knowledge_id": {"type": "string", "description": "Optional: limit search to a specific knowledge document ID"},
            },
            "required": ["keywords"],
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        from .models import Chunk

        keywords = args.get("keywords", "")
        knowledge_id = args.get("knowledge_id", "")
        tenant_id = context.get("tenant_id")
        kb_ids = context.get("kb_ids", [])

        if not keywords:
            return ToolResult(output="", error="Keywords are required")

        qs = Chunk.objects.filter(tenant_id=tenant_id, is_enabled=True)
        if kb_ids:
            qs = qs.filter(knowledge_base_id__in=kb_ids)
        if knowledge_id:
            qs = qs.filter(knowledge_id=knowledge_id)

        # 搜索关键词
        terms = keywords.split()
        for term in terms:
            qs = qs.filter(content__icontains=term)

        chunks = qs.select_related("knowledge")[:10]
        if not chunks:
            return ToolResult(output=f"No chunks found matching: {keywords}")

        lines = []
        for c in chunks:
            lines.append(f"[{c.knowledge.title}] {c.content[:300]}")

        return ToolResult(output="\n---\n".join(lines))


class GetDocumentInfoTool(Tool):
    """获取知识条目信息。"""

    def name(self) -> str:
        return "get_document_info"

    def description(self) -> str:
        return "Get information about a specific knowledge document, including its title, description, and chunk count."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "knowledge_id": {"type": "string", "description": "The knowledge document ID"},
            },
            "required": ["knowledge_id"],
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        from .models import Knowledge

        knowledge_id = args.get("knowledge_id", "")
        if not knowledge_id:
            return ToolResult(output="", error="knowledge_id is required")

        try:
            k = Knowledge.objects.get(id=knowledge_id)
        except Knowledge.DoesNotExist:
            return ToolResult(output="", error=f"Document not found: {knowledge_id}")

        chunk_count = k.chunks.filter(is_enabled=True).count() if hasattr(k, 'chunks') else 0
        info = {
            "id": k.id,
            "title": k.title,
            "description": k.description or "",
            "file_name": k.file_name or "",
            "file_type": k.file_type or "",
            "chunk_count": chunk_count,
            "parse_status": k.parse_status,
        }
        return ToolResult(output=json.dumps(info, ensure_ascii=False, indent=2), data=info)


class ThinkingTool(Tool):
    """结构化思考工具。"""

    def name(self) -> str:
        return "thinking"

    def description(self) -> str:
        return "Use this tool to think through a problem step by step. The thinking content is logged but does not produce a visible result. Use this when you need to reason through complex questions."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "thought": {"type": "string", "description": "Your step-by-step reasoning"},
            },
            "required": ["thought"],
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        thought = args.get("thought", "")
        return ToolResult(output=f"[Thinking logged: {len(thought)} chars]", data={"thought": thought})


class ListKnowledgeDocsTool(Tool):
    """列出知识库中的文档。"""

    def name(self) -> str:
        return "list_knowledge_docs"

    def description(self) -> str:
        return "List all documents in the knowledge base. Use this when the user asks what files or documents exist in the knowledge base."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Optional keyword to filter documents", "default": ""},
            },
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        from .models import Knowledge

        keyword = args.get("keyword", "")
        tenant_id = context.get("tenant_id")
        kb_ids = context.get("kb_ids", [])

        qs = Knowledge.objects.filter(tenant_id=tenant_id)
        if kb_ids:
            qs = qs.filter(knowledge_base_id__in=kb_ids)
        if keyword:
            qs = qs.filter(Q(title__icontains=keyword) | Q(description__icontains=keyword))

        docs = qs.order_by("-created_at")[:20]
        if not docs:
            return ToolResult(output="No documents found in the knowledge base.")

        lines = []
        for d in docs:
            desc = (d.description or "")[:100]
            lines.append(f"- {d.title}" + (f" — {desc}" if desc else ""))

        return ToolResult(output="\n".join(lines))


class WebSearchTool(Tool):
    """网络搜索工具。"""

    def name(self) -> str:
        return "web_search"

    def description(self) -> str:
        return "Search the web for current information. Use this when the user asks about recent events or information not in the knowledge base."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
            },
            "required": ["query"],
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        query = args.get("query", "")
        if not query:
            return ToolResult(output="", error="Query is required")

        try:
            import requests as req
            # 使用 DuckDuckGo HTML 搜索（无需 API key）
            resp = req.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            import re
            # 提取搜索结果
            results = re.findall(r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</span>', resp.text, re.DOTALL)
            if not results:
                return ToolResult(output=f"No web results found for: {query}")

            lines = []
            for url, title, snippet in results[:5]:
                title = re.sub(r'<[^>]+>', '', title).strip()
                snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                lines.append(f"- {title}\n  {snippet}\n  URL: {url}")

            return ToolResult(output="\n\n".join(lines))
        except Exception as e:
            return ToolResult(output="", error=f"Web search failed: {str(e)}")


class WebFetchTool(Tool):
    """网页内容获取工具。"""

    def name(self) -> str:
        return "web_fetch"

    def description(self) -> str:
        return "Fetch and read the content of a specific URL. Returns the text content of the page."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
                "max_chars": {"type": "integer", "description": "Maximum characters to return (default 3000)", "default": 3000},
            },
            "required": ["url"],
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        url = args.get("url", "")
        max_chars = args.get("max_chars", 3000)
        if not url:
            return ToolResult(output="", error="URL is required")

        try:
            import requests as req
            resp = req.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.raise_for_status()

            # 简单 HTML → 文本
            text = re.sub(r'<script[^>]*>.*?</script>', '', resp.text, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()

            return ToolResult(output=text[:max_chars])
        except Exception as e:
            return ToolResult(output="", error=f"Failed to fetch URL: {str(e)}")


class DatabaseQueryTool(Tool):
    """数据库查询工具（只读）。"""

    def name(self) -> str:
        return "database_query"

    def description(self) -> str:
        return "Query the knowledge base database for statistics and metadata. Supports read-only queries on knowledge, chunks, and sessions tables."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": ["knowledge_stats", "chunk_stats", "session_stats", "knowledge_list"],
                    "description": "Type of query to run",
                },
            },
            "required": ["query_type"],
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        from .models import Knowledge, Chunk, Session

        query_type = args.get("query_type", "")
        tenant_id = context.get("tenant_id")

        if query_type == "knowledge_stats":
            total = Knowledge.objects.filter(tenant_id=tenant_id).count()
            completed = Knowledge.objects.filter(tenant_id=tenant_id, parse_status="completed").count()
            processing = Knowledge.objects.filter(tenant_id=tenant_id, parse_status__in=["pending", "processing"]).count()
            return ToolResult(output=f"Total: {total}, Completed: {completed}, Processing: {processing}")

        elif query_type == "chunk_stats":
            total = Chunk.objects.filter(tenant_id=tenant_id, is_enabled=True).count()
            return ToolResult(output=f"Total enabled chunks: {total}")

        elif query_type == "session_stats":
            total = Session.objects.filter(tenant_id=tenant_id).count()
            return ToolResult(output=f"Total sessions: {total}")

        elif query_type == "knowledge_list":
            docs = Knowledge.objects.filter(tenant_id=tenant_id).values("id", "title", "parse_status", "file_type")[:10]
            lines = [f"- {d['title']} ({d['file_type'] or '?'}, {d['parse_status']})" for d in docs]
            return ToolResult(output="\n".join(lines) if lines else "No documents found")

        return ToolResult(output="", error=f"Unknown query_type: {query_type}")


class TodoWriteTool(Tool):
    """任务规划工具。"""

    def name(self) -> str:
        return "todo_write"

    def description(self) -> str:
        return "Write a todo list to track your progress on multi-step tasks. Use this to plan and organize your work."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "description": "Task description"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "Task status"},
                        },
                        "required": ["content", "status"],
                    },
                    "description": "List of todo items",
                },
            },
            "required": ["todos"],
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        todos = args.get("todos", [])
        lines = []
        for t in todos:
            status_icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅"}.get(t.get("status", "pending"), "⬜")
            lines.append(f"{status_icon} {t.get('content', '')}")
        return ToolResult(output="\n".join(lines) if lines else "No todos")


class ReadSkillTool(Tool):
    """读取 Skill 完整指令。"""

    def name(self) -> str:
        return "read_skill"

    def description(self) -> str:
        return "Load the full instructions for a skill. Use this when you need to understand how to perform a specific task."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "Name of the skill to load"},
            },
            "required": ["skill_name"],
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        from .agent_skills import get_skills_manager

        skill_name = args.get("skill_name", "")
        if not skill_name:
            return ToolResult(output="", error="skill_name is required")

        manager = get_skills_manager()
        skill = manager.load_skill(skill_name)
        if not skill:
            available = [s["name"] for s in manager.list_skills()]
            return ToolResult(output="", error=f"Skill '{skill_name}' not found. Available: {available}")

        return ToolResult(output=skill.instructions or f"Skill '{skill_name}' has no instructions.")


# ── Wiki 工具 ────────────────────────────────────────────────────────
class WikiSearchTool(Tool):
    """搜索 Wiki 页面。"""

    def name(self) -> str:
        return "wiki_search"

    def description(self) -> str:
        return "Search wiki pages by keyword. Returns matching wiki page titles, slugs, and summaries. Use this to find relevant wiki pages."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords"},
                "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
            },
            "required": ["query"],
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        from .models import WikiPage

        query = args.get("query", "")
        limit = args.get("limit", 10)
        tenant_id = context.get("tenant_id")
        kb_ids = context.get("kb_ids", [])

        if not query:
            return ToolResult(output="", error="Query is required")

        qs = WikiPage.objects.filter(tenant_id=tenant_id)
        if kb_ids:
            qs = qs.filter(knowledge_base_id__in=kb_ids)

        # 搜索标题和内容
        terms = query.split()
        for term in terms:
            qs = qs.filter(title__icontains=term) | WikiPage.objects.filter(
                tenant_id=tenant_id, content__icontains=term
            )

        pages = qs.order_by("-updated_at")[:limit]
        if not pages:
            return ToolResult(output=f"No wiki pages found for: {query}")

        lines = []
        for p in pages:
            summary = (p.description or p.content or "")[:150]
            lines.append(f"[{p.slug}] {p.title}\n  {summary}")

        return ToolResult(output="\n\n".join(lines))


class WikiReadPageTool(Tool):
    """读取 Wiki 页面完整内容。"""

    def name(self) -> str:
        return "wiki_read_page"

    def description(self) -> str:
        return "Read the full content of a wiki page by its slug. Returns the page title, content, and source references."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "The wiki page slug (e.g. 'index', 'page-name')"},
            },
            "required": ["slug"],
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        from .models import WikiPage

        slug = args.get("slug", "")
        tenant_id = context.get("tenant_id")
        kb_ids = context.get("kb_ids", [])

        if not slug:
            return ToolResult(output="", error="Slug is required")

        qs = WikiPage.objects.filter(tenant_id=tenant_id, slug=slug)
        if kb_ids:
            qs = qs.filter(knowledge_base_id__in=kb_ids)

        page = qs.first()
        if not page:
            # 尝试按标题模糊匹配
            qs = WikiPage.objects.filter(tenant_id=tenant_id, title__icontains=slug)
            if kb_ids:
                qs = qs.filter(knowledge_base_id__in=kb_ids)
            page = qs.first()

        if not page:
            return ToolResult(output="", error=f"Wiki page not found: {slug}")

        content = page.content or ""
        sources = page.source_refs or []

        output = f"# {page.title}\n\n{content}"
        if sources:
            output += "\n\n## 来源文档\n"
            for ref in sources[:5]:
                output += f"- {ref.get('title', ref.get('knowledge_id', ''))}\n"

        return ToolResult(output=output[:8000])


class WikiListPagesTool(Tool):
    """列出 Wiki 页面。"""

    def name(self) -> str:
        return "wiki_list_pages"

    def description(self) -> str:
        return "List all wiki pages in the knowledge base. Use this to get an overview of available wiki content."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Filter by category (optional)", "default": ""},
            },
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        from .models import WikiPage

        category = args.get("category", "")
        tenant_id = context.get("tenant_id")
        kb_ids = context.get("kb_ids", [])

        qs = WikiPage.objects.filter(tenant_id=tenant_id)
        if kb_ids:
            qs = qs.filter(knowledge_base_id__in=kb_ids)
        if category:
            qs = qs.filter(category_path__icontains=category)

        pages = qs.order_by("category_path", "title")[:50]
        if not pages:
            return ToolResult(output="No wiki pages found.")

        lines = []
        current_cat = ""
        for p in pages:
            cat = p.category_path or ""
            if cat != current_cat:
                current_cat = cat
                if cat:
                    lines.append(f"\n## {cat}")
            desc = (p.description or "")[:80]
            lines.append(f"- [{p.slug}] {p.title}" + (f" — {desc}" if desc else ""))

        return ToolResult(output="\n".join(lines))


class WikiReadSourceDocTool(Tool):
    """回溯 Wiki 页面的源文档 chunks。"""

    def name(self) -> str:
        return "wiki_read_source_doc"

    def description(self) -> str:
        return "Read the original source document chunks that a wiki page was generated from. Use this to get detailed raw content."

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "knowledge_id": {"type": "string", "description": "The source knowledge document ID"},
                "limit": {"type": "integer", "description": "Max chunks to return (default 10)", "default": 10},
            },
            "required": ["knowledge_id"],
        }

    def execute(self, args: dict, context: dict) -> ToolResult:
        from .models import Chunk, Knowledge

        knowledge_id = args.get("knowledge_id", "")
        limit = args.get("limit", 10)

        if not knowledge_id:
            return ToolResult(output="", error="knowledge_id is required")

        try:
            knowledge = Knowledge.objects.get(id=knowledge_id)
        except Knowledge.DoesNotExist:
            return ToolResult(output="", error=f"Document not found: {knowledge_id}")

        chunks = Chunk.objects.filter(
            knowledge_id=knowledge_id, is_enabled=True
        ).order_by("chunk_index")[:limit]

        if not chunks:
            return ToolResult(output=f"No chunks found for document: {knowledge.title}")

        lines = [f"# {knowledge.title}\n"]
        for c in chunks:
            lines.append(f"## Chunk #{c.chunk_index}\n{c.content}\n")

        return ToolResult(output="\n".join(lines)[:8000])


# ── 全局注册表 ───────────────────────────────────────────────────────
_registry = ToolRegistry()
_registry.register(KnowledgeSearchTool())
_registry.register(GrepChunksTool())
_registry.register(GetDocumentInfoTool())
_registry.register(ThinkingTool())
_registry.register(ListKnowledgeDocsTool())
_registry.register(WebSearchTool())
_registry.register(WebFetchTool())
_registry.register(DatabaseQueryTool())
_registry.register(TodoWriteTool())
_registry.register(ReadSkillTool())
_registry.register(WikiSearchTool())
_registry.register(WikiReadPageTool())
_registry.register(WikiListPagesTool())
_registry.register(WikiReadSourceDocTool())


def get_tool_registry() -> ToolRegistry:
    return _registry


DEFAULT_ALLOWED_TOOLS = [
    "thinking",
    "todo_write",
    "knowledge_search",
    "grep_chunks",
    "list_knowledge_docs",
    "get_document_info",
    "database_query",
    "web_search",
    "web_fetch",
]
