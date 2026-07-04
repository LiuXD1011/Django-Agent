"""
Wiki 页面 LLM 生成器

参考同类知识库系统的 WikiPageModifyPrompt 设计：
- 使用 LLM 生成页面内容（而非模板拼接）
- 支持增量合并（新增信息 + 保留已有内容）
- chunk 级引用（verbatim chunk 内容注入）
- 冲突检测（拒绝错误归属）
"""

import json
import logging
import re
from dataclasses import dataclass, field

from .model_providers import role_completion
from .models import Chunk, Knowledge, WikiPage

logger = logging.getLogger(__name__)


# ── Prompt 模板 ─────────────────────────────────────────────────

GENERATE_PAGE_PROMPT = """你是一个 Wiki 页面生成专家。根据以下信息生成一个结构化的 Wiki 页面。

页面标题：{title}
页面类型：{page_type}（entity/concept/summary）

来源文档：
{source_documents}

证据片段：
{evidence_chunks}

要求：
1. 生成一个完整的 Wiki 页面，包含标题、摘要、详细内容、相关页面链接
2. 使用 Markdown 格式
3. 在内容中引用证据片段，格式为 [c001]、[c002] 等
4. 如果有多个来源文档，分析它们之间的关系
5. 内容应该准确、完整、有组织

请输出 JSON 格式：
{{
  "summary": "页面摘要（100-200字）",
  "content": "页面正文（Markdown 格式，包含证据引用）",
  "related_pages": ["相关页面标题1", "相关页面标题2"]
}}"""


MERGE_PAGE_PROMPT = """你是一个 Wiki 页面编辑专家。需要将新信息合并到现有 Wiki 页面中。

页面标题：{title}
页面类型：{page_type}

现有页面内容：
{existing_content}

新增信息：
{new_information}

要求：
1. 将新信息合并到现有内容中，不要丢失已有信息
2. 检测冲突：如果新信息与现有内容矛盾，保留更准确的信息
3. 检测归属：确保新信息确实与页面主题相关
4. 更新证据引用，格式为 [c001]、[c002] 等
5. 保持内容的组织结构

请输出 JSON 格式：
{{
  "summary": "更新后的摘要",
  "content": "更新后的完整页面内容（Markdown 格式）",
  "merged": true,
  "conflicts": ["冲突描述（如有）"]
}}"""


EXTRACT_CHUNK_REFERENCES_PROMPT = """分析以下 Wiki 页面内容和证据片段，确定哪些片段被页面内容引用。

页面内容：
{page_content}

证据片段：
{evidence_chunks}

要求：
1. 找出页面内容中实际引用的片段
2. 返回被引用片段的 ID 列表

请输出 JSON 格式：
{{
  "referenced_chunks": ["chunk_id_1", "chunk_id_2"]
}}"""


# ── 数据结构 ─────────────────────────────────────────────────

@dataclass
class GeneratedPage:
    """LLM 生成的页面"""
    summary: str
    content: str
    related_pages: list[str] = field(default_factory=list)
    referenced_chunks: list[str] = field(default_factory=list)


@dataclass
class MergedPage:
    """LLM 合并后的页面"""
    summary: str
    content: str
    merged: bool = True
    conflicts: list[str] = field(default_factory=list)


# ── 核心函数 ─────────────────────────────────────────────────

def generate_page_content(
    title: str,
    page_type: str,
    knowledge: Knowledge,
    chunks: list[Chunk],
) -> GeneratedPage:
    """
    使用 LLM 生成 Wiki 页面内容。
    参考同类知识库系统的 WikiPageModifyPrompt。
    """
    # 准备来源文档信息
    source_documents = f"文档标题：{knowledge.title}\n文档来源：{knowledge.source or '未知'}"

    # 准备证据片段
    chunk_map = {chunk.id: f"[c{i+1:03d}] {chunk.content[:300]}" for i, chunk in enumerate(chunks[:10])}
    evidence_chunks = "\n".join(f"- {chunk_id}: {text}" for chunk_id, text in chunk_map.items())

    # 调用 LLM 生成
    prompt = GENERATE_PAGE_PROMPT.format(
        title=title,
        page_type=page_type,
        source_documents=source_documents,
        evidence_chunks=evidence_chunks,
    )

    fallback = GeneratedPage(
        summary=f"{title} 与《{knowledge.title}》相关。",
        content=f"# {title}\n\n## 来源摘要\n\n- 《{knowledge.title}》",
        related_pages=[],
        referenced_chunks=[chunk.id for chunk in chunks[:3]],
    )

    try:
        raw = role_completion(
            "extract",
            prompt,
            fallback=json.dumps({"summary": fallback.summary, "content": fallback.content, "related_pages": []}, ensure_ascii=False),
            max_chars=8000,
            tenant=knowledge.tenant,
            scenario="wiki_page_generate",
        )

        parsed = _parse_json(raw)
        if not parsed:
            return fallback

        # 提取 chunk 引用
        content = parsed.get("content", "")
        referenced_chunks = _extract_chunk_references(content, chunk_map)

        return GeneratedPage(
            summary=parsed.get("summary", fallback.summary),
            content=content,
            related_pages=parsed.get("related_pages", []),
            referenced_chunks=referenced_chunks,
        )

    except Exception as e:
        logger.warning(f"Failed to generate page content: {e}")
        return fallback


def merge_page_content(
    page: WikiPage,
    new_knowledge: Knowledge,
    new_chunks: list[Chunk],
) -> MergedPage:
    """
    使用 LLM 增量合并新信息到现有页面。
    参考同类知识库系统的 WikiPageModifyPrompt。
    """
    # 准备新增信息
    new_information = f"来源文档：《{new_knowledge.title}》\n"
    chunk_map = {}
    for i, chunk in enumerate(new_chunks[:8]):
        chunk_id = f"c{i+1:03d}"
        chunk_map[chunk.id] = chunk_id
        new_information += f"[{chunk_id}] {chunk.content[:300]}\n"

    # 调用 LLM 合并
    prompt = MERGE_PAGE_PROMPT.format(
        title=page.title,
        page_type=page.page_type,
        existing_content=page.content[:4000],
        new_information=new_information[:4000],
    )

    fallback = MergedPage(
        summary=page.summary or f"{page.title}",
        content=page.content or f"# {page.title}",
        merged=False,
    )

    try:
        raw = role_completion(
            "extract",
            prompt,
            fallback=json.dumps({"summary": fallback.summary, "content": fallback.content, "merged": False, "conflicts": []}, ensure_ascii=False),
            max_chars=8000,
            tenant=new_knowledge.tenant,
            scenario="wiki_page_merge",
        )

        parsed = _parse_json(raw)
        if not parsed:
            return fallback

        # 提取 chunk 引用
        content = parsed.get("content", "")
        _extract_chunk_references(content, chunk_map)

        return MergedPage(
            summary=parsed.get("summary", fallback.summary),
            content=content,
            merged=parsed.get("merged", False),
            conflicts=parsed.get("conflicts", []),
        )

    except Exception as e:
        logger.warning(f"Failed to merge page content: {e}")
        return fallback


def _extract_chunk_references(content: str, chunk_map: dict[str, str]) -> list[str]:
    """
    从内容中提取 chunk 引用。
    检测 [c001]、[c002] 等格式的引用。
    """
    referenced = []
    for chunk_id, alias in chunk_map.items():
        if f"[{alias}]" in content:
            referenced.append(chunk_id)
    return referenced


def _parse_json(text: str) -> dict | None:
    """解析 JSON"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def inject_cross_links(content: str, all_pages: list[WikiPage], current_slug: str) -> str:
    """
    注入交叉链接。
    参考同类知识库系统的 linkifyContent：Markdown 结构感知的链接注入。
    """
    if not content or not all_pages:
        return content

    # 构建名称到 slug 的映射
    name_to_slug = {}
    for page in all_pages:
        if page.slug == current_slug:
            continue
        name_to_slug[page.title.lower()] = page.slug
        for alias in (page.aliases or []):
            name_to_slug[alias.lower()] = page.slug

    if not name_to_slug:
        return content

    # 按名称长度降序排序（长名称优先匹配）
    sorted_names = sorted(name_to_slug.keys(), key=len, reverse=True)

    # Markdown 结构感知：排除代码块、链接、图片等
    # 简单实现：只在段落文本中替换
    lines = content.split('\n')
    in_code_block = False
    result_lines = []

    for line in lines:
        # 检测代码块
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            result_lines.append(line)
            continue

        if in_code_block:
            result_lines.append(line)
            continue

        # 跳过标题行（避免在标题中插入链接）
        if line.strip().startswith('#'):
            result_lines.append(line)
            continue

        # 在文本中插入链接
        modified_line = line
        for name in sorted_names:
            slug = name_to_slug[name]
            # 只替换第一次出现，且不在已有链接中
            pattern = re.compile(re.escape(name), re.IGNORECASE)
            match = pattern.search(modified_line)
            if match:
                # 检查是否在已有链接中
                before = modified_line[:match.start()]
                if '[[' not in before.split(']')[-1] if ']' in before else True:
                    replacement = f"[[{slug}|{match.group()}]]"
                    modified_line = modified_line[:match.start()] + replacement + modified_line[match.end():]

        result_lines.append(modified_line)

    return '\n'.join(result_lines)
