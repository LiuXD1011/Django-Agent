import json
import logging

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from personal_knowledge_base.authentication import require_auth
from personal_knowledge_base.models import KnowledgeBase, WikiFolder, WikiLogEntry, WikiPage, WikiPendingOp
from personal_knowledge_base.responses import fail, ok
from personal_knowledge_base.serializers import wiki_folder_dict, wiki_page_dict
from personal_knowledge_base.wiki_ingest import sync_manual_page_links

logger = logging.getLogger(__name__)


# ── Utility Functions ─────────────────────────────────────────────────


def parse_body(request):
    if request.content_type and request.content_type.startswith("multipart/"):
        return request.POST.dict()
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except Exception:
        return {}


def auth_context(request):
    try:
        return require_auth(request)
    except PermissionError:
        return None, None


def bounded_int(value, default, minimum=None, maximum=None):
    try:
        number = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        number = default
    if minimum is not None:
        number = max(number, minimum)
    if maximum is not None:
        number = min(number, maximum)
    return number


def paginate(qs, request):
    page_size = bounded_int(request.GET.get("page_size", request.GET.get("limit", 20)), 20, 1, 200)
    if "offset" in request.GET and "page" not in request.GET:
        offset = bounded_int(request.GET.get("offset"), 0, 0)
        page = offset // page_size + 1
    else:
        page = bounded_int(request.GET.get("page"), 1, 1)
        offset = (page - 1) * page_size
    total = qs.count()
    return qs[offset : offset + page_size], {"page": page, "page_size": page_size, "total": total}


def list_response(items, meta=None, aliases=None):
    payload = {"items": items, "data": items}
    for alias in aliases or []:
        payload[alias] = items
    if meta:
        payload.update(meta)
    return payload


def csv_values(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = str(value).split(",")
    return [str(item).strip() for item in values if str(item).strip()]


def bool_from_value(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on", "enabled"}


def slugify(value):
    value = (value or "page").strip().lower()
    value = "".join(ch if ch.isalnum() else "-" for ch in value)
    return "-".join(part for part in value.split("-") if part) or "page"


def visible_wiki_pages_queryset(kb_or_id):
    if isinstance(kb_or_id, KnowledgeBase):
        qs = WikiPage.objects.filter(knowledge_base=kb_or_id)
    else:
        qs = WikiPage.objects.filter(knowledge_base_id=kb_or_id)
    return qs.exclude(page_type="index").exclude(slug="index")


# ── Wiki Page Views ──────────────────────────────────────────────────


@csrf_exempt
def wiki_pages(request, kb_id, slug=None):
    _, tenant = auth_context(request)
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    if slug:
        slug = slug.lstrip("/")
        page = get_object_or_404(WikiPage, knowledge_base=kb, slug=slug)
        if request.method == "GET":
            return ok(wiki_page_dict(page))
        if request.method == "DELETE":
            page.delete()
            return ok({})
        data = parse_body(request)
        page.title = data.get("title", page.title)
        page.content = data.get("content", page.content)
        page.summary = data.get("summary", page.summary)
        page.folder_id = data.get("folder_id", page.folder_id)
        if "page_type" in data:
            page.page_type = data.get("page_type") or page.page_type
        if "aliases" in data and isinstance(data.get("aliases"), list):
            page.aliases = data.get("aliases")
        page.save()
        sync_manual_page_links(page)
        return ok(wiki_page_dict(page))
    if request.method == "GET":
        pages = visible_wiki_pages_queryset(kb).order_by("title")
        return ok({"items": [wiki_page_dict(p) for p in pages]})
    data = parse_body(request)
    title = data.get("title", "Untitled")
    page = WikiPage.objects.create(
        tenant=tenant or kb.tenant,
        knowledge_base=kb,
        slug=data.get("slug") or slugify(title),
        title=title,
        content=data.get("content", ""),
        summary=data.get("summary", ""),
        folder_id=data.get("folder_id", ""),
        page_type=data.get("page_type") or "page",
        aliases=data.get("aliases") if isinstance(data.get("aliases"), list) else [],
        status=data.get("status") or "published",
    )
    sync_manual_page_links(page)
    return ok(wiki_page_dict(page), status=201)


# ── Wiki Folder Views ────────────────────────────────────────────────


@csrf_exempt
def wiki_folders(request, kb_id, folder_id=None):
    _, tenant = auth_context(request)
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    if folder_id:
        folder = get_object_or_404(WikiFolder, id=folder_id, knowledge_base=kb)
        if request.method == "DELETE":
            folder.delete()
            return ok({})
        data = parse_body(request)
        folder.name = data.get("name", folder.name)
        folder.parent_id = data.get("parent_id", folder.parent_id)
        folder.path = data.get("path", folder.path)
        folder.depth = data.get("depth", folder.depth)
        folder.sort_order = data.get("sort_order", folder.sort_order)
        folder.save()
        return ok(wiki_folder_dict(folder))
    if request.method == "GET":
        folders = WikiFolder.objects.filter(knowledge_base=kb).order_by("sort_order")
        return ok({"items": [wiki_folder_dict(f) for f in folders]})
    data = parse_body(request)
    name = data.get("name", "Folder")
    folder = WikiFolder.objects.create(
        tenant=tenant or kb.tenant,
        knowledge_base=kb,
        name=name,
        parent_id=data.get("parent_id", ""),
        path=data.get("path") or name,
        depth=data.get("depth", 0),
        sort_order=data.get("sort_order", 0),
    )
    return ok(wiki_folder_dict(folder), status=201)


# ── Wiki Index & Search ─────────────────────────────────────────────


def wiki_index(request, kb_id):
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    pages = visible_wiki_pages_queryset(kb).order_by("page_type", "sort_order", "title")
    labels = {"index": "目录", "summary": "摘要", "entity": "实体", "concept": "概念", "page": "页面"}
    groups = []
    for page_type in sorted({page.page_type for page in pages}):
        grouped = [wiki_page_dict(page) for page in pages if page.page_type == page_type]
        groups.append({"type": page_type, "title": labels.get(page_type, page_type), "pages": grouped})
    return ok({"groups": groups, "items": [wiki_page_dict(p) for p in pages]})


def wiki_search(request, kb_id):
    kb = get_object_or_404(KnowledgeBase, id=kb_id)
    q = request.GET.get("q") or request.GET.get("query") or ""
    limit = min(max(int(request.GET.get("limit", 50) or 50), 1), 200)
    pages = visible_wiki_pages_queryset(kb)
    if q:
        pages = pages.filter(Q(title__icontains=q) | Q(content__icontains=q))
    items = [wiki_page_dict(p) for p in pages.order_by("title")[:limit]]
    return ok({"items": items, "pages": items})


# ── Wiki Link Helpers ────────────────────────────────────────────────


def wiki_link_slugs(page: WikiPage) -> list[str]:
    refs = page.out_links if isinstance(page.out_links, list) and page.out_links else []
    if not refs:
        refs = page.source_refs if isinstance(page.source_refs, list) else []
    slugs = []
    for ref in refs:
        if isinstance(ref, dict):
            value = ref.get("slug") or ref.get("target") or ref.get("page_slug")
        else:
            value = ref
        value = str(value or "").strip()
        if value and value not in slugs:
            slugs.append(value)
    return slugs


# ── Wiki Graph Views ────────────────────────────────────────────────


def wiki_graph_dataset(kb_id):
    pages = list(visible_wiki_pages_queryset(kb_id))
    by_slug = {page.slug: page for page in pages}
    out_map = {page.slug: [slug for slug in wiki_link_slugs(page) if slug in by_slug and slug != page.slug] for page in pages}
    in_map = {slug: [] for slug in by_slug}
    for source, targets in out_map.items():
        for target in targets:
            in_map.setdefault(target, []).append(source)
    return pages, by_slug, out_map, in_map


def wiki_graph_node(page: WikiPage, out_map, in_map):
    link_count = len(set(out_map.get(page.slug, [])) | set(in_map.get(page.slug, [])))
    return {"id": page.slug, "slug": page.slug, "label": page.title, "title": page.title, "page_type": page.page_type, "link_count": link_count}


def wiki_graph_type_filter(request):
    raw = request.GET.get("types") or ""
    return {item.strip() for item in raw.split(",") if item.strip()}


def is_visible_wiki_slug(slug: str, by_slug: dict) -> bool:
    page = by_slug.get(slug)
    return bool(page and page.slug != "index" and page.page_type != "index")


def wiki_graph_subgraph(kb_id, request):
    pages, by_slug, out_map, in_map = wiki_graph_dataset(kb_id)
    type_filter = wiki_graph_type_filter(request)
    eligible = [
        page
        for page in pages
        if page.slug != "index"
        and page.page_type != "index"
        and (not type_filter or page.page_type in type_filter)
    ]
    eligible_slugs = {page.slug for page in eligible}
    mode = (request.GET.get("mode") or "overview").strip() or "overview"
    if mode not in {"overview", "ego"}:
        return None, "mode must be 'overview' or 'ego'"
    limit = min(max(int(request.GET.get("limit", 500) or 500), 1), 2000)
    depth = min(max(int(request.GET.get("depth", 1) or 1), 1), 3)
    center = (request.GET.get("center") or "").strip()
    if mode == "ego":
        if not center:
            return None, "center is required when mode=ego"
        if center not in by_slug:
            selected_slugs = []
        else:
            seen = {center}
            frontier = {center}
            for _ in range(depth):
                next_frontier = set()
                for slug in frontier:
                    next_frontier.update(out_map.get(slug, []))
                    next_frontier.update(in_map.get(slug, []))
                next_frontier = {slug for slug in next_frontier if slug in eligible_slugs and slug not in seen}
                seen.update(next_frontier)
                frontier = next_frontier
            selected_slugs = [slug for slug in seen if (slug in eligible_slugs or slug == center) and is_visible_wiki_slug(slug, by_slug)]
    else:
        ranked = sorted(eligible, key=lambda page: (-(len(set(out_map.get(page.slug, [])) | set(in_map.get(page.slug, [])))), page.title))
        selected_slugs = [page.slug for page in ranked]
    total = len(selected_slugs)
    selected_slugs = selected_slugs[:limit]
    selected = set(selected_slugs)
    nodes = [wiki_graph_node(by_slug[slug], out_map, in_map) for slug in selected_slugs if slug in by_slug]
    edges = []
    for source in selected_slugs:
        for target in out_map.get(source, []):
            if target in selected:
                edges.append({"source": source, "target": target})
    meta = {"mode": mode, "total": total if mode == "ego" else len(eligible), "returned": len(nodes), "truncated": total > len(nodes), "center": center, "depth": depth}
    return {"nodes": nodes, "edges": edges, "meta": meta}, None


def wiki_graph(request, kb_id):
    data, error = wiki_graph_subgraph(kb_id, request)
    if error:
        return fail(error, 400)
    return ok(data)


# ── Wiki Stats, Log, Lint, Issues ───────────────────────────────────


def wiki_stats(request, kb_id):
    pages = visible_wiki_pages_queryset(kb_id)
    folders = WikiFolder.objects.filter(knowledge_base_id=kb_id)
    _, _, out_map, in_map = wiki_graph_dataset(kb_id)
    by_type = {}
    for page in pages:
        by_type[page.page_type] = by_type.get(page.page_type, 0) + 1
    total_links = sum(len(targets) for targets in out_map.values())
    orphan_count = sum(1 for page in pages if not out_map.get(page.slug) and not in_map.get(page.slug))
    return ok({
        "pages": pages.count(),
        "folders": folders.count(),
        "total_pages": pages.count(),
        "total_links": total_links,
        "pages_by_type": by_type,
        "orphan_count": orphan_count,
        "recent_updates": [wiki_page_dict(p) for p in pages.order_by("-updated_at")[:5]],
        "pending_tasks": WikiPendingOp.objects.filter(scope_id=kb_id).count(),
        "pending_issues": 0,
        "is_active": True,
    })


def wiki_log(request, kb_id):
    items = [
        {
            "id": item.id,
            "knowledge_base_id": item.knowledge_base_id,
            "knowledge_id": item.knowledge_id,
            "action": item.action,
            "doc_title": item.doc_title,
            "summary": item.summary,
            "pages_affected": item.pages_affected,
            "details": item.details,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in WikiLogEntry.objects.filter(knowledge_base_id=kb_id).order_by("-created_at")[:100]
    ]
    return ok({"items": items})


def wiki_lint(request, kb_id):
    return ok({"issues": []})


def wiki_issues(request, kb_id, issue_id=None):
    return ok({"items": []} if not issue_id else {"id": issue_id, "status": "resolved"})
