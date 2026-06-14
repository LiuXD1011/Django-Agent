import re
from dataclasses import dataclass, field

import markdown as markdown_lib
from django.conf import settings
from django.db import connection
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe
from openai import OpenAI
from sqlite_vec import serialize_float32

from . import services as rag_services
from .models import KBDocument, WikiBuildJob, WikiLink, WikiPage
from .sqlite_search import ensure_search_tables


WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]+)?(?:\|([^\]]+))?\]\]")


@dataclass
class WikiSearchHit:
    score: float
    page: WikiPage
    query: str = ""
    source_scores: dict = field(default_factory=dict)


def page_slug_for_document(document):
    return f"source-{document.id}"


def short_hash(text):
    return rag_services.short_hash(text)


def extract_wikilink_titles(content):
    titles = []
    seen = set()
    for match in WIKILINK_RE.finditer(content or ""):
        title = rag_services.compact_text(match.group(1))
        if title and title not in seen:
            titles.append(title)
            seen.add(title)
    return titles


def slugify_title(title):
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", (title or "").lower()).strip("-")
    return slug[:150] or "page"


def resolve_wikilink(kb, title):
    title = rag_services.compact_text(title)
    if not title:
        return None
    slug = slugify_title(title)
    return kb.wiki_pages.filter(Q(title=title) | Q(slug=slug)).first()


def delete_wiki_page_indexes(page_id):
    ensure_search_tables()
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM knowledge_wikipage_vec WHERE page_id = %s", [page_id])
        cursor.execute("DELETE FROM knowledge_wikipage_fts WHERE rowid = %s", [page_id])


def upsert_wiki_page_indexes(page):
    ensure_search_tables()
    if page.status != WikiPage.STATUS_READY:
        delete_wiki_page_indexes(page.id)
        return
    index_text = "\n\n".join(part for part in [page.title, page.summary, page.content] if part)
    serialized_vector = serialize_float32(rag_services.normalize_vector(rag_services.embed_text(index_text)))
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM knowledge_wikipage_vec WHERE page_id = %s", [page.id])
        cursor.execute(
            "INSERT INTO knowledge_wikipage_vec(page_id, kb_id, embedding) VALUES (%s, %s, %s)",
            [page.id, page.kb_id, serialized_vector],
        )
        cursor.execute("DELETE FROM knowledge_wikipage_fts WHERE rowid = %s", [page.id])
        cursor.execute(
            "INSERT INTO knowledge_wikipage_fts(rowid, title, content) VALUES (%s, %s, %s)",
            [page.id, page.title, index_text],
        )


def refresh_wiki_links(page):
    WikiLink.objects.filter(source_page=page).delete()
    for target_title in extract_wikilink_titles(page.content):
        WikiLink.objects.create(
            source_page=page,
            target_title=target_title,
            target_page=resolve_wikilink(page.kb, target_title),
            link_type=WikiLink.TYPE_WIKILINK,
        )


def refresh_all_wiki_links(kb):
    for page in kb.wiki_pages.all():
        refresh_wiki_links(page)


def _llm_complete(client, system, prompt):
    response = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()


def _document_context(document, max_chars=12000):
    parts = []
    total = 0
    for chunk in document.chunks.order_by("chunk_index"):
        text = chunk.content.strip()
        if not text:
            continue
        item = f"[chunk {chunk.chunk_index}]\n{text}"
        if total + len(item) > max_chars:
            remaining = max_chars - total
            if remaining > 200:
                parts.append(item[:remaining])
            break
        parts.append(item)
        total += len(item)
    return "\n\n".join(parts)


def _source_prompt(document, context):
    return f"""
文档标题：{document.title or document.source}
来源：{document.source}
片段数量：{document.chunk_count}

请只根据下面的文档片段生成一个只读 Wiki source 页面。使用 Markdown，必须包含这些二级标题：
## Summary
## Key Points
## Useful Quotes
## Connections
## Open Questions

Connections 中可以使用 [[页面名]] 记录和其他资料可能相关的主题，但不要编造不存在的事实。

文档片段：
{context}
""".strip()


def _overview_prompt(kb, source_context):
    return f"""
知识库名称：{kb.name}
知识库描述：{kb.description or "无"}

请根据下面已经生成的 source Wiki 页面摘要，生成一个知识库总览页。使用 Markdown，必须包含这些二级标题：
## Topic Summary
## Major Sources
## Key Conclusions
## Gaps

可以使用 [[来源页标题]] 链接到具体来源页。只总结资料中已经出现的信息，不足处写到 Gaps。

source 页面摘要：
{source_context}
""".strip()


def _extract_section(content, name):
    pattern = rf"(?:^|\n)##+\s*{re.escape(name)}\s*\n(?P<body>.*?)(?=\n##+\s|\Z)"
    match = re.search(pattern, content or "", flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group("body").strip()
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", content or "") if part.strip()]
    return paragraphs[0] if paragraphs else ""


def _mark_page_failed(kb, slug, title, page_type, message, source_document=None):
    page, _created = WikiPage.objects.update_or_create(
        kb=kb,
        slug=slug,
        defaults={
            "page_type": page_type,
            "title": title[:512],
            "source_document": source_document,
            "content": "",
            "summary": "",
            "status": WikiPage.STATUS_FAILED,
            "error_message": str(message)[:2000],
            "metadata": {},
            "content_hash": "",
            "generated_at": timezone.now(),
        },
    )
    delete_wiki_page_indexes(page.id)
    return page


def generate_source_page(kb, document, client):
    if document.status != KBDocument.STATUS_READY:
        raise ValueError("只有已入库文档才能生成 Wiki source 页面。")
    context = _document_context(document)
    if not context:
        raise ValueError("文档没有可用于生成 Wiki 的片段。")

    slug = page_slug_for_document(document)
    title = document.title or document.source or f"文档 {document.id}"
    try:
        content = _llm_complete(
            client,
            "你是个人知识库 Wiki 编写助手。只基于给定资料写结构化、可追溯、中文 Markdown。",
            _source_prompt(document, context),
        )
    except Exception as exc:
        _mark_page_failed(kb, slug, title, WikiPage.TYPE_SOURCE, f"source 页面生成失败：{exc}", source_document=document)
        raise

    summary = _extract_section(content, "Summary")[:2000]
    page, _created = WikiPage.objects.update_or_create(
        kb=kb,
        slug=slug,
        defaults={
            "page_type": WikiPage.TYPE_SOURCE,
            "title": title[:512],
            "content": content,
            "summary": summary,
            "source_document": document,
            "status": WikiPage.STATUS_READY,
            "error_message": "",
            "metadata": {
                "document_id": document.id,
                "source": document.source,
                "chunk_count": document.chunk_count,
            },
            "content_hash": short_hash(context),
            "generated_at": timezone.now(),
        },
    )
    upsert_wiki_page_indexes(page)
    refresh_wiki_links(page)
    return page


def _source_context_for_overview(source_pages, max_chars=12000):
    parts = []
    total = 0
    for page in source_pages:
        key_points = _extract_section(page.content, "Key Points")
        item = "\n".join(
            [
                f"标题：{page.title}",
                f"链接：[[{page.title}]]",
                f"摘要：{page.summary or rag_services.compact_text(page.content)[:500]}",
                f"要点：{key_points[:1200]}",
            ]
        )
        if total + len(item) > max_chars:
            break
        parts.append(item)
        total += len(item)
    return "\n\n".join(parts)


def generate_overview_page(kb, client):
    source_pages = list(
        kb.wiki_pages.filter(page_type=WikiPage.TYPE_SOURCE, status=WikiPage.STATUS_READY).order_by("title")
    )
    if not source_pages:
        raise ValueError("没有可汇总的 source Wiki 页面。")
    source_context = _source_context_for_overview(source_pages)
    try:
        content = _llm_complete(
            client,
            "你是个人知识库 Wiki 总览助手。只基于 source 页面摘要归纳，不补充外部事实。",
            _overview_prompt(kb, source_context),
        )
    except Exception as exc:
        _mark_page_failed(kb, "overview", "知识库总览", WikiPage.TYPE_OVERVIEW, f"overview 页面生成失败：{exc}")
        raise

    summary = _extract_section(content, "Topic Summary")[:2000] or rag_services.compact_text(content)[:2000]
    page, _created = WikiPage.objects.update_or_create(
        kb=kb,
        slug="overview",
        defaults={
            "page_type": WikiPage.TYPE_OVERVIEW,
            "title": "知识库总览",
            "content": content,
            "summary": summary,
            "source_document": None,
            "status": WikiPage.STATUS_READY,
            "error_message": "",
            "metadata": {"source_page_count": len(source_pages)},
            "content_hash": short_hash(source_context),
            "generated_at": timezone.now(),
        },
    )
    upsert_wiki_page_indexes(page)
    refresh_wiki_links(page)
    return page


def _finish_job(job, status, error_message=""):
    job.status = status
    job.error_message = str(error_message)[:2000]
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "error_message", "finished_at"])
    return job


def build_wiki(kb, document=None):
    job = WikiBuildJob.objects.create(
        kb=kb,
        document=document,
        job_type=WikiBuildJob.TYPE_DOCUMENT if document else WikiBuildJob.TYPE_FULL,
    )
    if not settings.LLM_API_KEY:
        return _finish_job(job, WikiBuildJob.STATUS_FAILED, "未配置 LLM_API_KEY，无法生成 Wiki。")

    try:
        client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
        documents = [document] if document else list(kb.documents.filter(status=KBDocument.STATUS_READY).order_by("id"))
        documents = [item for item in documents if item and item.status == KBDocument.STATUS_READY]
        if not documents:
            raise ValueError("当前知识库没有已入库文档，无法生成 Wiki。")
        for item in documents:
            generate_source_page(kb, item, client)
        generate_overview_page(kb, client)
        refresh_all_wiki_links(kb)
    except Exception as exc:
        return _finish_job(job, WikiBuildJob.STATUS_FAILED, exc)
    return _finish_job(job, WikiBuildJob.STATUS_SUCCESS)


def wiki_vector_candidates(kb, query_vector, limit):
    ensure_search_tables()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT page_id, distance
            FROM knowledge_wikipage_vec
            WHERE embedding MATCH %s AND kb_id = %s AND k = %s
            ORDER BY distance
            """,
            [serialize_float32(rag_services.normalize_vector(query_vector)), kb.id, max(1, int(limit))],
        )
        return [(int(page_id), float(distance)) for page_id, distance in cursor.fetchall()]


def wiki_fts_candidates(kb, query, limit):
    if len(rag_services.compact_text(query)) < 3:
        return []
    ensure_search_tables()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT knowledge_wikipage_fts.rowid, bm25(knowledge_wikipage_fts) AS rank
            FROM knowledge_wikipage_fts
            JOIN knowledge_wikipage AS page ON page.id = knowledge_wikipage_fts.rowid
            WHERE knowledge_wikipage_fts MATCH %s AND page.kb_id = %s AND page.status = %s
            ORDER BY rank
            LIMIT %s
            """,
            [rag_services.quote_fts_query(query), kb.id, WikiPage.STATUS_READY, max(1, int(limit))],
        )
        return [(int(page_id), float(rank)) for page_id, rank in cursor.fetchall()]


def search_wiki_pages(kb, query, top_k=3, chat_history=None):
    return search_wiki_pages_with_trace(kb, query, top_k=top_k, chat_history=chat_history)["hits"]


def _trace_wiki_hit(hit, rank):
    return {
        "rank": rank,
        "wiki_page_id": hit.page.id,
        "title": hit.page.title,
        "slug": hit.page.slug,
        "page_type": hit.page.page_type,
        "source_document_id": hit.page.source_document_id,
        "score": round(float(hit.score), 6),
        "source_scores": hit.source_scores,
    }


def search_wiki_pages_with_trace(kb, query, top_k=3, chat_history=None):
    queries = rag_services.rewrite_rag_queries(query, chat_history=chat_history)
    result_limit = max(1, int(top_k))
    candidate_limit = result_limit * 4
    scores = {}
    source_scores = {}
    trace = {
        "original_query": rag_services.compact_text(query),
        "rewritten_queries": queries,
        "top_k": result_limit,
        "candidate_limit": candidate_limit,
        "vector_candidates": [],
        "fts_candidates": [],
        "fusion_candidates": [],
        "final_hits": [],
    }
    for rewritten_query in queries:
        qvec = rag_services.embed_text(rewritten_query)
        for rank, (page_id, distance) in enumerate(wiki_vector_candidates(kb, qvec, candidate_limit), 1):
            scores[page_id] = scores.get(page_id, 0.0) + (1.0 / rank)
            source_scores.setdefault(page_id, {})["vector"] = {
                "query": rewritten_query,
                "rank": rank,
                "distance": distance,
            }
            trace["vector_candidates"].append(
                {
                    "query": rewritten_query,
                    "rank": rank,
                    "wiki_page_id": page_id,
                    "distance": distance,
                }
            )
        for rank, (page_id, fts_rank) in enumerate(wiki_fts_candidates(kb, rewritten_query, candidate_limit), 1):
            scores[page_id] = scores.get(page_id, 0.0) + (0.5 / rank)
            source_scores.setdefault(page_id, {})["fts"] = {
                "query": rewritten_query,
                "rank": rank,
                "rank_score": fts_rank,
            }
            trace["fts_candidates"].append(
                {
                    "query": rewritten_query,
                    "rank": rank,
                    "wiki_page_id": page_id,
                    "rank_score": fts_rank,
                }
            )

    if not scores:
        return {"hits": [], "trace": trace}
    ordered_ids = [page_id for page_id, _score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]
    pages = {
        page.id: page
        for page in WikiPage.objects.filter(
            id__in=ordered_ids,
            kb=kb,
            status=WikiPage.STATUS_READY,
        ).select_related("kb", "source_document")
    }
    trace["fusion_candidates"] = [
        {
            "rank": rank,
            "wiki_page_id": page_id,
            "score": round(float(scores[page_id]), 6),
            "source_scores": source_scores.get(page_id, {}),
            "title": pages[page_id].title if page_id in pages else "",
            "slug": pages[page_id].slug if page_id in pages else "",
        }
        for rank, page_id in enumerate(ordered_ids, 1)
    ]
    hits = []
    for page_id in ordered_ids:
        page = pages.get(page_id)
        if not page:
            continue
        scores_for_page = source_scores.get(page_id, {})
        hits.append(
            WikiSearchHit(
                score=scores[page_id],
                page=page,
                query=(scores_for_page.get("vector") or scores_for_page.get("fts") or {}).get("query", query),
                source_scores=scores_for_page,
            )
        )
        if len(hits) >= result_limit:
            break
    trace["final_hits"] = [_trace_wiki_hit(hit, rank) for rank, hit in enumerate(hits, 1)]
    return {"hits": hits, "trace": trace}


def references_context(hits):
    lines = []
    for index, hit in enumerate(hits or [], 1):
        page = hit.page
        text = page.summary or page.content
        lines.append(
            "\n".join(
                [
                    f"[W{index}] type: wiki_page",
                    f"title: {page.title}",
                    f"page_type: {page.page_type}",
                    f"wiki_page_id: {page.id}",
                    f"score: {hit.score:.4f}",
                    "content:",
                    text[:1800],
                ]
            )
        )
    return "\n\n".join(lines)


def combined_references_context(wiki_hits, chunk_hits):
    sections = []
    wiki_text = references_context(wiki_hits)
    if wiki_text:
        sections.append("Wiki references:\n" + wiki_text)
    chunk_text = rag_services.references_context(chunk_hits)
    if chunk_text:
        sections.append("原文 chunk references:\n" + chunk_text)
    return "\n\n".join(sections)


def refs_payload(hits):
    refs = []
    for hit in hits or []:
        page = hit.page
        refs.append(
            {
                "type": "wiki_page",
                "kb_id": page.kb.kb_id,
                "wiki_page_id": page.id,
                "page_type": page.page_type,
                "slug": page.slug,
                "title": page.title,
                "source": page.source_document.source if page.source_document else "Wiki",
                "status": page.status,
                "score": round(float(hit.score), 4),
                "url": reverse("knowledge:wiki_page", args=[page.kb_id, page.slug]),
            }
        )
    return refs


def wiki_health(kb):
    ready_docs = list(kb.documents.filter(status=KBDocument.STATUS_READY).order_by("title"))
    ready_source_doc_ids = set(
        kb.wiki_pages.filter(
            page_type=WikiPage.TYPE_SOURCE,
            status=WikiPage.STATUS_READY,
            source_document__in=ready_docs,
        ).values_list("source_document_id", flat=True)
    )
    empty_pages = list(
        kb.wiki_pages.filter(status=WikiPage.STATUS_READY).filter(Q(content="") | Q(summary="")).order_by("title")
    )
    ready_pages = list(kb.wiki_pages.filter(status=WikiPage.STATUS_READY).order_by("title"))
    ready_page_ids = [page.id for page in ready_pages]
    incoming_page_ids = set(
        WikiLink.objects.filter(target_page_id__in=ready_page_ids).values_list("target_page_id", flat=True)
    )
    outgoing_counts = {
        item["source_page_id"]: item["count"]
        for item in WikiLink.objects.filter(source_page_id__in=ready_page_ids)
        .values("source_page_id")
        .annotate(count=Count("id"))
    }
    broken_links = list(
        WikiLink.objects.filter(source_page__kb=kb, target_page__isnull=True).select_related("source_page")
    )
    broken_target_counts = {}
    for link in broken_links:
        broken_target_counts[link.target_title] = broken_target_counts.get(link.target_title, 0) + 1
    resolved_link_count = WikiLink.objects.filter(source_page__kb=kb, target_page__isnull=False).count()
    ready_page_count = len(ready_pages)
    return {
        "missing_overview": not kb.wiki_pages.filter(
            page_type=WikiPage.TYPE_OVERVIEW,
            status=WikiPage.STATUS_READY,
        ).exists(),
        "missing_source_docs": [doc for doc in ready_docs if doc.id not in ready_source_doc_ids],
        "empty_pages": empty_pages,
        "broken_links": broken_links,
        "stale_pages": list(kb.wiki_pages.filter(status=WikiPage.STATUS_STALE).order_by("title")),
        "orphan_pages": [
            page
            for page in ready_pages
            if page.page_type != WikiPage.TYPE_OVERVIEW and page.id not in incoming_page_ids
        ],
        "sparse_pages": [page for page in ready_pages if outgoing_counts.get(page.id, 0) < 2],
        "link_density": 0.0 if ready_page_count == 0 else round(resolved_link_count / ready_page_count, 3),
        "phantom_link_count": sum(1 for count in broken_target_counts.values() if count >= 2),
        "page_count": ready_page_count,
        "link_count": resolved_link_count,
    }


def wiki_health_issue_count(health):
    total = 1 if health.get("missing_overview") else 0
    for key in ["missing_source_docs", "empty_pages", "broken_links", "stale_pages", "orphan_pages", "sparse_pages"]:
        total += len(health.get(key) or [])
    return total


def wiki_health_summary(health):
    health = health or {}
    return {
        "missing_overview": bool(health.get("missing_overview")),
        "missing_source_count": len(health.get("missing_source_docs", [])),
        "empty_page_count": len(health.get("empty_pages", [])),
        "broken_link_count": len(health.get("broken_links", [])),
        "stale_page_count": len(health.get("stale_pages", [])),
        "orphan_page_count": len(health.get("orphan_pages", [])),
        "sparse_page_count": len(health.get("sparse_pages", [])),
        "phantom_link_count": int(health.get("phantom_link_count", 0)),
        "link_density": float(health.get("link_density", 0.0)),
        "page_count": int(health.get("page_count", 0)),
        "link_count": int(health.get("link_count", 0)),
    }


def wiki_graph_payload(kb):
    pages = list(kb.wiki_pages.order_by("page_type", "title"))
    nodes = [
        {
            "id": page.id,
            "title": page.title,
            "slug": page.slug,
            "page_type": page.page_type,
            "status": page.status,
            "source_document_id": page.source_document_id,
        }
        for page in pages
    ]
    links = WikiLink.objects.filter(source_page__kb=kb).select_related("source_page", "target_page").order_by("id")
    edges = []
    unresolved_edges = []
    for link in links:
        if link.target_page_id:
            edges.append(
                {
                    "id": link.id,
                    "source": link.source_page_id,
                    "target": link.target_page_id,
                    "target_title": link.target_title,
                    "link_type": link.link_type,
                }
            )
        else:
            unresolved_edges.append(
                {
                    "id": link.id,
                    "source": link.source_page_id,
                    "source_title": link.source_page.title,
                    "target_title": link.target_title,
                    "link_type": link.link_type,
                }
            )
    return {
        "kb": {"id": kb.id, "kb_id": kb.kb_id, "name": kb.name},
        "nodes": nodes,
        "edges": edges,
        "unresolved_edges": unresolved_edges,
        "health": wiki_health_summary(wiki_health(kb)),
    }


def decorate_document_wiki_statuses(kb, documents):
    docs = list(documents)
    page_by_doc_id = {
        page.source_document_id: page
        for page in kb.wiki_pages.filter(
            page_type=WikiPage.TYPE_SOURCE,
            source_document__in=docs,
        ).select_related("source_document")
    }
    for doc in docs:
        page = page_by_doc_id.get(doc.id)
        doc.wiki_page = page
        if doc.status != KBDocument.STATUS_READY:
            doc.wiki_status = "not_ready"
            doc.wiki_status_label = "待入库"
        elif page:
            doc.wiki_status = page.status
            doc.wiki_status_label = page.get_status_display()
        else:
            doc.wiki_status = "missing"
            doc.wiki_status_label = "未生成 Wiki"
    return docs


def render_wiki_markdown(page):
    def repl(match):
        title = rag_services.compact_text(match.group(1))
        display = rag_services.compact_text(match.group(2) or title)
        target = resolve_wikilink(page.kb, title)
        if target:
            return f"[{escape(display)}]({reverse('knowledge:wiki_page', args=[target.kb_id, target.slug])})"
        return f"`{escape(display)}`"

    content = page.content or ""
    pieces = []
    last = 0
    for match in WIKILINK_RE.finditer(content):
        pieces.append(str(escape(content[last : match.start()])))
        pieces.append(repl(match))
        last = match.end()
    pieces.append(str(escape(content[last:])))
    html = markdown_lib.markdown("".join(pieces), extensions=["extra", "sane_lists"])
    return mark_safe(html)
