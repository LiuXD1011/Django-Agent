from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from drive.models import UserFile

from .models import KnowledgeBase
from . import services, wiki_services


@login_required
def index(request):
    kbs = KnowledgeBase.objects.filter(user=request.user).prefetch_related("documents")
    selected = None
    if request.GET.get("kb"):
        selected = get_object_or_404(KnowledgeBase, id=request.GET["kb"], user=request.user)
    elif kbs:
        selected = kbs[0]
    files = UserFile.objects.filter(user=request.user, is_deleted=False, is_folder=False)
    files = services.decorate_file_statuses(selected, files)
    documents = []
    wiki_overview = None
    wiki_sources = []
    wiki_jobs = []
    wiki_health = None
    wiki_health_count = 0
    if selected:
        documents = wiki_services.decorate_document_wiki_statuses(
            selected,
            services.decorate_document_statuses(
                selected.documents.select_related("user_file", "extraction").order_by("-updated_at")
            ),
        )
        wiki_overview = selected.wiki_pages.filter(page_type="overview").order_by("-updated_at").first()
        wiki_sources = selected.wiki_pages.filter(page_type="source").select_related("source_document").order_by("title")
        wiki_jobs = selected.wiki_build_jobs.select_related("document").order_by("-started_at")[:5]
        wiki_health = wiki_services.wiki_health(selected)
        wiki_health_count = wiki_services.wiki_health_issue_count(wiki_health)
    return render(
        request,
        "knowledge/index.html",
        {
            "kbs": kbs,
            "selected": selected,
            "files": files,
            "documents": documents,
            "wiki_overview": wiki_overview,
            "wiki_sources": wiki_sources,
            "wiki_jobs": wiki_jobs,
            "wiki_health": wiki_health,
            "wiki_health_count": wiki_health_count,
        },
    )


@login_required
@require_POST
def create_kb(request):
    kb = KnowledgeBase.objects.create(
        user=request.user,
        name=request.POST.get("name") or "未命名知识库",
        description=request.POST.get("description") or "",
    )
    messages.success(request, "知识库已创建")
    return redirect(f"/knowledge/?kb={kb.id}")


@login_required
@require_POST
def ingest(request, kb_id):
    kb = get_object_or_404(KnowledgeBase, id=kb_id, user=request.user)
    count = 0
    text = request.POST.get("text", "").strip()
    url = request.POST.get("url", "").strip()
    file_ids = request.POST.getlist("file_ids")
    try:
        if text:
            services.ingest_text(kb, "text", "manual", "手动文本", text)
            count += 1
        if url:
            services.ingest_url(kb, url)
            count += 1
        for file_item in UserFile.objects.filter(user=request.user, id__in=file_ids, is_deleted=False, is_folder=False):
            services.ingest_user_file(kb, file_item)
            count += 1
        messages.success(request, f"已入库 {count} 个文档")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect(f"/knowledge/?kb={kb.id}")


@login_required
@require_POST
def build_wiki(request, kb_id):
    kb = get_object_or_404(KnowledgeBase, id=kb_id, user=request.user)
    job = wiki_services.build_wiki(kb)
    if job.status == "success":
        messages.success(request, "Wiki 已生成/刷新")
    else:
        messages.error(request, job.error_message or "Wiki 生成失败")
    return redirect(f"/knowledge/?kb={kb.id}")


@login_required
def wiki_page(request, kb_id, slug):
    kb = get_object_or_404(KnowledgeBase, id=kb_id, user=request.user)
    page = get_object_or_404(
        kb.wiki_pages.select_related("source_document", "kb"),
        slug=slug,
    )
    return render(
        request,
        "knowledge/wiki_page.html",
        {
            "kb": kb,
            "page": page,
            "content_html": wiki_services.render_wiki_markdown(page),
            "outgoing_links": page.outgoing_links.select_related("target_page").all(),
        },
    )


@login_required
def wiki_graph_json(request, kb_id):
    kb = get_object_or_404(KnowledgeBase, id=kb_id, user=request.user)
    return JsonResponse(wiki_services.wiki_graph_payload(kb), json_dumps_params={"ensure_ascii": False, "indent": 2})


# Create your views here.
