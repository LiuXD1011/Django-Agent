import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from django.db import transaction

from .model_providers import role_completion
from .models import Chunk, Knowledge, KnowledgeBase, WikiFolder, WikiLogEntry, WikiPage, WikiPendingOp


WIKI_TASK_TYPE = "wiki:ingest"
MAX_CONTENT_FOR_WIKI = 32768
DEFAULT_BATCH_SIZE = 5
LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


@dataclass
class SlugUpdate:
    slug: str
    page_type: str
    title: str
    action: str
    knowledge: Knowledge | None = None
    summary: str = ""
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    details: str = ""
    chunk_ids: list[str] = field(default_factory=list)


def wiki_enabled(kb: KnowledgeBase) -> bool:
    return bool((kb.indexing_strategy or {}).get("wiki_enabled"))


def wiki_config(kb: KnowledgeBase) -> dict:
    return kb.wiki_config if isinstance(kb.wiki_config, dict) else {}


def slugify(value: str) -> str:
    base = re.sub(r"\s+", "-", (value or "").strip().lower())
    base = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff/_-]+", "-", base).strip("-")
    return base[:160] or "page"


def canonical_slug(page_type: str, title: str) -> str:
    prefix = {
        "summary": "summary",
        "entity": "entity",
        "concept": "concept",
        "synthesis": "synthesis",
        "comparison": "comparison",
    }.get(page_type or "", "page")
    return f"{prefix}/{slugify(title)}"


def extraction_granularity(kb: KnowledgeBase) -> str:
    value = str(wiki_config(kb).get("extraction_granularity") or "standard").strip()
    return value if value in {"focused", "standard", "exhaustive"} else "standard"


def extraction_limit(kb: KnowledgeBase) -> int:
    return {"focused": 6, "standard": 10, "exhaustive": 16}.get(extraction_granularity(kb), 10)


def safe_json_object(text: str) -> dict:
    if not text:
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def unique_strings(values, limit: int | None = None) -> list[str]:
    seen = set()
    items = []
    for value in values or []:
        text = normalize_name(value)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        items.append(text)
        if limit and len(items) >= limit:
            break
    return items


def has_sufficient_text(content: str) -> bool:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", content or "")
    text = re.sub(r"\s+", "", text)
    return len(text) >= 8


def doc_ref(knowledge: Knowledge) -> dict:
    return {
        "knowledge_id": knowledge.id,
        "title": knowledge.title,
        "file_name": knowledge.file_name,
        "source": knowledge.source,
    }


def ref_knowledge_id(ref) -> str:
    if isinstance(ref, dict):
        return str(ref.get("knowledge_id") or ref.get("id") or ref.get("knowledgeId") or "")
    return str(ref or "")


def page_has_source(page: WikiPage, knowledge_id: str) -> bool:
    return any(ref_knowledge_id(ref) == knowledge_id for ref in (page.source_refs or []))


def add_source_ref(refs: list, knowledge: Knowledge) -> list:
    refs = list(refs or [])
    knowledge_id = knowledge.id
    refs = [ref for ref in refs if ref_knowledge_id(ref) != knowledge_id]
    refs.append(doc_ref(knowledge))
    return refs


def remove_source_ref(refs: list, knowledge_id: str) -> list:
    return [ref for ref in (refs or []) if ref_knowledge_id(ref) != knowledge_id]


def old_slugs_for_knowledge(kb: KnowledgeBase, knowledge_id: str) -> list[str]:
    result = []
    for page in WikiPage.objects.filter(knowledge_base=kb):
        if page_has_source(page, knowledge_id):
            result.append(page.slug)
    return result


def chunk_aliases(chunks: list[Chunk]) -> dict[str, str]:
    return {chunk.id: f"c{idx + 1:03d}" for idx, chunk in enumerate(chunks)}


def chunk_lookup(chunk_ids: list[str]) -> dict[str, Chunk]:
    ids = [item for item in unique_strings(chunk_ids) if item]
    if not ids:
        return {}
    return {chunk.id: chunk for chunk in Chunk.objects.filter(id__in=ids)}


def short_chunk_text(text: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit].rstrip() + ("..." if len(text) > limit else "")


def fallback_candidates(content: str, title: str, limit: int) -> dict:
    text = f"{title}\n{content[:6000]}"
    raw = []
    raw.extend(re.findall(r"[A-Z][A-Za-z0-9_+-]{1,30}(?:\s+[A-Z][A-Za-z0-9_+-]{1,30}){0,3}", text))
    raw.extend(re.findall(r"[\u4e00-\u9fff]{2,12}", text))
    stop_words = {
        "使用",
        "支持",
        "管理",
        "数据",
        "数据库",
        "架构",
        "文件",
        "文档",
        "摘要",
        "知识",
        "当前",
        "通过",
    }
    names = []
    for item in raw:
        item = normalize_name(item).strip("。,.，；;：:")
        if len(item) < 2 or item in stop_words:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", item) and len(item) > 8:
            continue
        names.append(item)
    names = unique_strings(names, limit)
    entities = []
    concepts = []
    for idx, name in enumerate(names):
        item = {"name": name, "aliases": [], "description": f"{name} 在文档《{title}》中被重点提及。"}
        if idx % 3 == 1:
            concepts.append(item)
        else:
            entities.append(item)
    return {"entities": entities, "concepts": concepts}


def extract_candidates(knowledge: Knowledge, content: str) -> list[dict]:
    kb = knowledge.knowledge_base
    limit = extraction_limit(kb)
    fallback = fallback_candidates(content, knowledge.title, limit)
    prompt = (
        "你正在执行 Wiki 知识库文档映射阶段。请从文档中提取适合生成 Wiki 页面的话题，"
        "严格输出 JSON，格式为 {\"entities\": [{\"name\":\"...\",\"aliases\":[],\"description\":\"...\"}], "
        "\"concepts\": [{\"name\":\"...\",\"aliases\":[],\"description\":\"...\"}]}。"
        f"\n抽取粒度：{extraction_granularity(kb)}，最多 {limit} 个。"
        f"\n标题：{knowledge.title}\n内容：{content[:12000]}"
    )
    raw = role_completion(
        "extract",
        prompt,
        fallback=json.dumps(fallback, ensure_ascii=False),
        max_chars=6000,
        tenant=knowledge.tenant,
        scenario="wiki_candidate_slugs",
    )
    payload = safe_json_object(raw) or fallback
    items = []
    for page_type, key in [("entity", "entities"), ("concept", "concepts")]:
        for value in payload.get(key) or []:
            if isinstance(value, str):
                value = {"name": value}
            if not isinstance(value, dict):
                continue
            name = normalize_name(value.get("name") or value.get("title"))
            if not name:
                continue
            aliases = unique_strings(value.get("aliases") or [], 6)
            items.append(
                {
                    "page_type": page_type,
                    "title": name,
                    "slug": canonical_slug(page_type, name),
                    "aliases": aliases,
                    "description": normalize_name(value.get("description") or value.get("summary") or f"{name} 与《{knowledge.title}》相关。"),
                    "details": normalize_name(value.get("details") or ""),
                }
            )
    seen = set()
    deduped = []
    for item in items:
        key = item["slug"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    if not deduped:
        for page_type, values in [("entity", fallback.get("entities") or []), ("concept", fallback.get("concepts") or [])]:
            for value in values:
                name = normalize_name(value.get("name") if isinstance(value, dict) else value)
                if name:
                    deduped.append(
                        {
                            "page_type": page_type,
                            "title": name,
                            "slug": canonical_slug(page_type, name),
                            "aliases": [],
                            "description": f"{name} 与《{knowledge.title}》相关。",
                            "details": "",
                        }
                    )
                if len(deduped) >= limit:
                    break
    return deduped


def citation_chunks(item: dict, chunks: list[Chunk], aliases: dict[str, str]) -> list[str]:
    needles = [item.get("title"), *(item.get("aliases") or [])]
    matched = []
    for chunk in chunks:
        content = chunk.content or ""
        if any(needle and needle in content for needle in needles):
            matched.append(chunk.id)
        if len(matched) >= 6:
            break
    if not matched and chunks:
        matched.append(chunks[0].id)
    return matched


def generate_summary(knowledge: Knowledge, content: str) -> str:
    fallback = short_chunk_text(content, 220)
    return role_completion(
        "summary",
        f"请为 Wiki 页面生成一段不超过 160 字的中文摘要，只输出摘要文本。\n标题：{knowledge.title}\n内容：{content[:9000]}",
        fallback=fallback,
        max_chars=260,
        tenant=knowledge.tenant,
        scenario="wiki_summary",
    ).strip() or fallback


def map_one_document(knowledge: Knowledge) -> tuple[list[SlugUpdate], dict]:
    chunks = list(Chunk.objects.filter(knowledge=knowledge, deleted_at__isnull=True).order_by("chunk_index", "created_at"))
    content = "\n\n".join(chunk.content for chunk in chunks)[:MAX_CONTENT_FOR_WIKI]
    if not chunks or not has_sufficient_text(content):
        return [], {"skipped": True, "reason": "insufficient_text", "pages": 0, "links": 0}
    aliases = chunk_aliases(chunks)
    candidates = extract_candidates(knowledge, content)
    updates: list[SlugUpdate] = []
    summary = generate_summary(knowledge, content)
    summary_slug = f"summary/{knowledge.id}"
    updates.append(
        SlugUpdate(
            slug=summary_slug,
            page_type="summary",
            title=knowledge.title,
            action="upsert_summary",
            knowledge=knowledge,
            summary=summary,
            chunk_ids=[chunk.id for chunk in chunks[:8]],
        )
    )
    new_slugs = {summary_slug}
    for item in candidates:
        chunk_ids = citation_chunks(item, chunks, aliases)
        new_slugs.add(item["slug"])
        updates.append(
            SlugUpdate(
                slug=item["slug"],
                page_type=item["page_type"],
                title=item["title"],
                action="upsert",
                knowledge=knowledge,
                summary=item["description"],
                aliases=item["aliases"],
                description=item["description"],
                details=item["details"],
                chunk_ids=chunk_ids,
            )
        )
    for slug in old_slugs_for_knowledge(knowledge.knowledge_base, knowledge.id):
        if slug not in new_slugs:
            updates.append(SlugUpdate(slug=slug, page_type="", title="", action="retract", knowledge=knowledge))
    return updates, {"skipped": False, "pages": len(new_slugs), "links": max(0, len(new_slugs) - 1), "summary_slug": summary_slug}


def folder_for_type(kb: KnowledgeBase, page_type: str):
    labels = {"summary": "摘要", "entity": "实体", "concept": "概念", "synthesis": "综合", "comparison": "对比", "index": "目录"}
    name = labels.get(page_type or "page", "页面")
    folder, _ = WikiFolder.objects.get_or_create(
        knowledge_base=kb,
        name=name,
        parent_id="",
        defaults={"tenant": kb.tenant, "path": name, "depth": 0, "sort_order": len(labels)},
    )
    changed = False
    if folder.tenant_id != kb.tenant_id:
        folder.tenant = kb.tenant
        changed = True
    if not folder.path:
        folder.path = name
        changed = True
    if changed:
        folder.save(update_fields=["tenant", "path", "updated_at"])
    return folder


def render_summary_content(update: SlugUpdate, links: list[str]) -> str:
    parts = [f"# {update.title}", "", update.summary]
    if links:
        parts.extend(["", "## 相关页面", ""])
        parts.extend(f"- [[{slug}]]" for slug in links)
    return "\n".join(part for part in parts if part is not None).strip()


def render_page_content(title: str, page_type: str, contributions: dict) -> tuple[str, list[str]]:
    lines = [f"# {title}", "", "## 来源摘要", ""]
    all_chunks = []
    for knowledge_id, contribution in sorted(contributions.items(), key=lambda item: item[1].get("doc_title", "")):
        doc_title = contribution.get("doc_title") or knowledge_id
        description = contribution.get("description") or contribution.get("summary") or "文档中包含相关信息。"
        lines.append(f"- 《{doc_title}》：{description}")
        all_chunks.extend(contribution.get("chunks") or [])
    lookup = chunk_lookup(all_chunks)
    if lookup:
        lines.extend(["", "## 证据片段", ""])
        ordered = unique_strings(all_chunks)
        alias_map = {chunk_id: f"c{idx + 1:03d}" for idx, chunk_id in enumerate(ordered)}
        for chunk_id in ordered:
            chunk = lookup.get(chunk_id)
            if chunk:
                lines.append(f"- [{alias_map[chunk_id]}] {short_chunk_text(chunk.content)}")
    if page_type == "concept":
        lines.extend(["", "## 相关实体", ""])
    return "\n".join(lines).strip(), unique_strings(all_chunks)


def page_contributions(page: WikiPage) -> dict:
    meta = page.page_metadata if isinstance(page.page_metadata, dict) else {}
    contributions = meta.get("contributions")
    return dict(contributions) if isinstance(contributions, dict) else {}


def save_page_links(page: WikiPage):
    old_out = list(page.out_links or [])
    out_links = []
    for match in LINK_RE.finditer(page.content or ""):
        slug = match.group(1).strip()
        if slug and slug != page.slug and slug not in out_links:
            out_links.append(slug)
    page.out_links = out_links
    page.save(update_fields=["out_links", "updated_at"])
    removed = set(old_out) - set(out_links)
    added = set(out_links) - set(old_out)
    if removed:
        for target in WikiPage.objects.filter(knowledge_base=page.knowledge_base, slug__in=removed):
            target.in_links = [slug for slug in (target.in_links or []) if slug != page.slug]
            target.save(update_fields=["in_links", "updated_at"])
    if added:
        for target in WikiPage.objects.filter(knowledge_base=page.knowledge_base, slug__in=added):
            links = list(target.in_links or [])
            if page.slug not in links:
                links.append(page.slug)
                target.in_links = links
                target.save(update_fields=["in_links", "updated_at"])


def update_page_links(page: WikiPage, content: str):
    page.content = content
    page.save(update_fields=["content", "updated_at"])
    save_page_links(page)


def reduce_summary(kb: KnowledgeBase, update: SlugUpdate, related_slugs: list[str]) -> WikiPage | None:
    knowledge = update.knowledge
    if knowledge is None:
        return None
    folder = folder_for_type(kb, "summary")
    page, _ = WikiPage.objects.update_or_create(
        knowledge_base=kb,
        slug=update.slug,
        defaults={
            "tenant": kb.tenant,
            "title": update.title,
            "summary": update.summary,
            "source_refs": [doc_ref(knowledge)],
            "chunk_refs": unique_strings(update.chunk_ids),
            "aliases": unique_strings([Path(knowledge.file_name or knowledge.title).stem]),
            "page_type": "summary",
            "status": "published",
            "folder_id": folder.id,
            "category_path": [folder.name],
            "wiki_path": f"{folder.name}/{update.title}",
            "depth": 1,
            "page_metadata": {"source_knowledge_id": knowledge.id},
        },
    )
    update_page_links(page, render_summary_content(update, related_slugs))
    return page


def reduce_page(kb: KnowledgeBase, slug: str, updates: list[SlugUpdate]) -> WikiPage | None:
    page = WikiPage.objects.filter(knowledge_base=kb, slug=slug).first()
    retract_ids = {update.knowledge.id for update in updates if update.action == "retract" and update.knowledge}
    additions = [update for update in updates if update.action == "upsert" and update.knowledge]
    if not page and not additions:
        return None
    if page:
        contributions = page_contributions(page)
        source_refs = list(page.source_refs or [])
    else:
        first = additions[0]
        folder = folder_for_type(kb, first.page_type)
        page = WikiPage.objects.create(
            tenant=kb.tenant,
            knowledge_base=kb,
            slug=slug,
            title=first.title,
            page_type=first.page_type,
            status="published",
            folder_id=folder.id,
            category_path=[folder.name],
            wiki_path=f"{folder.name}/{first.title}",
            depth=1,
        )
        contributions = {}
        source_refs = []
    for knowledge_id in retract_ids:
        contributions.pop(knowledge_id, None)
        source_refs = remove_source_ref(source_refs, knowledge_id)
    aliases = set(page.aliases or [])
    chunk_ids = []
    for update in additions:
        knowledge = update.knowledge
        if knowledge is None:
            continue
        source_refs = add_source_ref(source_refs, knowledge)
        aliases.update(update.aliases or [])
        contributions[knowledge.id] = {
            "doc_title": knowledge.title,
            "description": update.description or update.summary,
            "details": update.details,
            "chunks": unique_strings(update.chunk_ids),
        }
    if not contributions:
        page.delete()
        return None
    for contribution in contributions.values():
        chunk_ids.extend(contribution.get("chunks") or [])
    first_add = additions[0] if additions else None
    if first_add:
        page.title = first_add.title or page.title
        page.page_type = first_add.page_type or page.page_type
        page.summary = first_add.summary or page.summary
    page.source_refs = source_refs
    page.chunk_refs = unique_strings(chunk_ids)
    page.aliases = sorted(aliases)
    meta = page.page_metadata if isinstance(page.page_metadata, dict) else {}
    meta["contributions"] = contributions
    page.page_metadata = meta
    page.status = "published"
    if not page.folder_id:
        folder = folder_for_type(kb, page.page_type)
        page.folder_id = folder.id
        page.category_path = [folder.name]
        page.wiki_path = f"{folder.name}/{page.title}"
        page.depth = 1
    page.version = (page.version or 1) + 1
    page.save(
        update_fields=[
            "title",
            "summary",
            "source_refs",
            "chunk_refs",
            "aliases",
            "page_metadata",
            "page_type",
            "status",
            "folder_id",
            "category_path",
            "wiki_path",
            "depth",
            "version",
            "updated_at",
        ]
    )
    content, _ = render_page_content(page.title, page.page_type, contributions)
    update_page_links(page, content)
    return page


def clean_dead_links(kb: KnowledgeBase, pages: list[WikiPage] | None = None):
    known = set(WikiPage.objects.filter(knowledge_base=kb).values_list("slug", flat=True))
    target_pages = pages or list(WikiPage.objects.filter(knowledge_base=kb))
    for page in target_pages:
        content = page.content or ""

        def repl(match):
            slug = match.group(1).strip()
            label = match.group(2) or slug
            return match.group(0) if slug in known else label

        new_content = LINK_RE.sub(repl, content)
        if new_content != content:
            update_page_links(page, new_content)
        else:
            save_page_links(page)


def inject_cross_links(kb: KnowledgeBase, pages: list[WikiPage] | None = None):
    all_pages = list(WikiPage.objects.filter(knowledge_base=kb).exclude(page_type__in=["index"]))
    refs = []
    for page in all_pages:
        names = [page.title, *(page.aliases or [])]
        for name in unique_strings(names):
            if len(name) >= 2:
                refs.append((page.slug, name))
    refs.sort(key=lambda item: len(item[1]), reverse=True)
    target_pages = pages or all_pages
    for page in target_pages:
        if page.page_type == "index":
            continue
        content = page.content or ""
        linked = False
        for slug, name in refs[:80]:
            if slug == page.slug or f"[[{slug}" in content or name not in content:
                continue
            pattern = re.escape(name)
            new_content, count = re.subn(pattern, f"[[{slug}|{name}]]", content, count=1)
            if count:
                content = new_content
                linked = True
        if linked:
            update_page_links(page, content)


def rebuild_index_page(kb: KnowledgeBase) -> WikiPage:
    folder = folder_for_type(kb, "index")
    groups = defaultdict(list)
    for page in WikiPage.objects.filter(knowledge_base=kb).exclude(page_type="index").order_by("page_type", "title"):
        groups[page.page_type].append(page)
    labels = {"summary": "摘要", "entity": "实体", "concept": "概念", "synthesis": "综合", "comparison": "对比", "page": "页面"}
    lines = ["# Wiki 目录", "", f"当前知识库共有 {sum(len(items) for items in groups.values())} 个 Wiki 页面。"]
    for page_type, pages in sorted(groups.items()):
        lines.extend(["", f"## {labels.get(page_type, page_type)}", ""])
        lines.extend(f"- [[{page.slug}|{page.title}]]" for page in pages)
    page, _ = WikiPage.objects.update_or_create(
        knowledge_base=kb,
        slug="index",
        defaults={
            "tenant": kb.tenant,
            "title": "Wiki 目录",
            "summary": "自动生成的 Wiki 页面索引。",
            "source_refs": [],
            "chunk_refs": [],
            "aliases": ["目录", "Index"],
            "page_type": "index",
            "status": "published",
            "folder_id": folder.id,
            "category_path": [folder.name],
            "wiki_path": "目录/Wiki 目录",
            "depth": 1,
        },
    )
    update_page_links(page, "\n".join(lines).strip())
    return page


def process_wiki_ingest(kb_id: str, batch_size: int | None = None) -> dict:
    kb = KnowledgeBase.objects.select_related("tenant").get(id=kb_id)
    batch_size = batch_size or int(wiki_config(kb).get("ingest_batch_size") or DEFAULT_BATCH_SIZE)
    ops = list(WikiPendingOp.objects.filter(task_type=WIKI_TASK_TYPE, scope="knowledge_base", scope_id=kb.id).order_by("id")[:batch_size])
    if not wiki_enabled(kb):
        WikiPendingOp.objects.filter(task_type=WIKI_TASK_TYPE, scope_id=kb.id, op="ingest").delete()
        ops = [op for op in ops if op.op == "retract"]
        if not ops:
            return {"processed": 0, "pages": 0, "links": 0, "skipped": True}
    if not ops:
        return {"processed": 0, "pages": 0, "links": 0}
    latest_by_key = {}
    for op in ops:
        latest_by_key[op.dedup_key or f"{op.op}:{op.id}"] = op
    effective_ops = list(latest_by_key.values())
    updates_by_slug: dict[str, list[SlugUpdate]] = defaultdict(list)
    results = []
    touched_knowledge_ids = []
    for op in effective_ops:
        if op.op == "ingest":
            knowledge_id = str(op.payload.get("knowledge_id") or op.dedup_key)
            knowledge = Knowledge.objects.select_related("tenant", "knowledge_base").filter(id=knowledge_id, deleted_at__isnull=True).first()
            if not knowledge:
                continue
            mapped, result = map_one_document(knowledge)
            touched_knowledge_ids.append(knowledge.id)
            for update in mapped:
                updates_by_slug[update.slug].append(update)
            results.append({"knowledge_id": knowledge.id, **result})
        elif op.op == "retract":
            knowledge_id = str(op.payload.get("knowledge_id") or op.dedup_key)
            knowledge = Knowledge.objects.select_related("tenant", "knowledge_base").filter(id=knowledge_id).first()
            old_slugs = old_slugs_for_knowledge(kb, knowledge_id)
            for slug in old_slugs:
                updates_by_slug[slug].append(SlugUpdate(slug=slug, page_type="", title="", action="retract", knowledge=knowledge))
            touched_knowledge_ids.append(knowledge_id)
            results.append({"knowledge_id": knowledge_id, "retracted": len(old_slugs)})
    pages_by_slug = {}
    summary_updates = {}
    for slug, updates in updates_by_slug.items():
        summaries = [update for update in updates if update.action == "upsert_summary"]
        if summaries:
            summary_updates[slug] = summaries[-1]
    with transaction.atomic():
        for slug, updates in updates_by_slug.items():
            if slug in summary_updates:
                summary_update = summary_updates[slug]
                related_slugs = [
                    related_slug
                    for related_slug, related_updates in updates_by_slug.items()
                    if related_slug != slug
                    and any(
                        related.action == "upsert"
                        and related.knowledge
                        and summary_update.knowledge
                        and related.knowledge.id == summary_update.knowledge.id
                        for related in related_updates
                    )
                ]
                page = reduce_summary(kb, summary_update, related_slugs)
            else:
                page = reduce_page(kb, slug, updates)
            if page:
                pages_by_slug[page.slug] = page
        index_page = rebuild_index_page(kb)
        pages_by_slug[index_page.slug] = index_page
        touched_pages = list(pages_by_slug.values())
        clean_dead_links(kb, touched_pages)
        inject_cross_links(kb, touched_pages)
        clean_dead_links(kb)
        for op in ops:
            op.delete()
    total_links = sum(len(page.out_links or []) for page in WikiPage.objects.filter(knowledge_base=kb))
    WikiLogEntry.objects.create(
        tenant=kb.tenant,
        knowledge_base=kb,
        knowledge_id=(unique_strings(touched_knowledge_ids) or [""])[0],
        action="ingest",
        summary=f"Processed {len(effective_ops)} Wiki pending operations.",
        pages_affected=sorted(pages_by_slug.keys()),
        details={"results": results},
    )
    return {"processed": len(effective_ops), "pages": len(pages_by_slug), "links": total_links, "results": results}


def enqueue_wiki_ingest(knowledge: Knowledge) -> dict:
    kb = knowledge.knowledge_base
    if not wiki_enabled(kb):
        return {"pages": 0, "links": 0, "skipped": True}
    if not Chunk.objects.filter(knowledge=knowledge, deleted_at__isnull=True).exists():
        return {"pages": 0, "links": 0, "skipped": True, "reason": "no_chunks"}
    WikiPendingOp.objects.filter(task_type=WIKI_TASK_TYPE, scope_id=kb.id, dedup_key=knowledge.id).delete()
    WikiPendingOp.objects.create(
        tenant=knowledge.tenant,
        task_type=WIKI_TASK_TYPE,
        scope="knowledge_base",
        scope_id=kb.id,
        op="ingest",
        dedup_key=knowledge.id,
        payload={"knowledge_id": knowledge.id},
    )
    return process_wiki_ingest(kb.id)


def prepare_wiki_for_reparse(knowledge: Knowledge):
    WikiPendingOp.objects.filter(task_type=WIKI_TASK_TYPE, scope_id=knowledge.knowledge_base_id, dedup_key=knowledge.id).delete()


def cleanup_wiki_for_knowledge(knowledge: Knowledge) -> dict:
    kb = knowledge.knowledge_base
    if not kb:
        return {"pages": 0, "links": 0}
    WikiPendingOp.objects.filter(task_type=WIKI_TASK_TYPE, scope_id=kb.id, dedup_key=knowledge.id).delete()
    WikiPendingOp.objects.create(
        tenant=knowledge.tenant,
        task_type=WIKI_TASK_TYPE,
        scope="knowledge_base",
        scope_id=kb.id,
        op="retract",
        dedup_key=knowledge.id,
        payload={"knowledge_id": knowledge.id},
    )
    return process_wiki_ingest(kb.id)


def cleanup_wiki_for_kb(kb: KnowledgeBase):
    WikiPendingOp.objects.filter(scope_id=kb.id).delete()
    WikiLogEntry.objects.filter(knowledge_base=kb).delete()
    WikiPage.objects.filter(knowledge_base=kb).delete()
    WikiFolder.objects.filter(knowledge_base=kb).delete()


def sync_manual_page_links(page: WikiPage):
    if not page.folder_id:
        folder = folder_for_type(page.knowledge_base, page.page_type)
        page.folder_id = folder.id
        page.category_path = [folder.name]
        page.wiki_path = f"{folder.name}/{page.title}"
        page.depth = 1
        page.save(update_fields=["folder_id", "category_path", "wiki_path", "depth", "updated_at"])
    save_page_links(page)
