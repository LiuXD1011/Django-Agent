from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from knowledge.models import KnowledgeBase

from .agents import AssistantOrchestrator
from . import services
from .memory import delete_memory_index
from .models import AgentRun, ConversationMemory


@login_required
def assistant_home(request):
    if "agent" in request.GET:
        kb = request.GET.get("kb", "")
        url = "/assistant/"
        if kb.isdigit():
            url = f"{url}?kb={kb}"
        return redirect(url)

    knowledge_bases = KnowledgeBase.objects.filter(user=request.user, status="active")
    selected_kb_id = ""
    requested_kb_id = request.GET.get("kb", "")
    if requested_kb_id.isdigit() and knowledge_bases.filter(id=requested_kb_id).exists():
        selected_kb_id = requested_kb_id

    requested_conversation_id = request.GET.get("conversation", "")
    if requested_conversation_id.isdigit():
        conversation, _created = services.get_or_create_conversation(
            request.user,
            requested_conversation_id,
            defaults={"default_kb_id": int(selected_kb_id) if selected_kb_id else None},
        )
    else:
        conversation = services.adopt_orphan_messages(request.user)
        if conversation is None:
            conversation = services.active_conversations(request.user).order_by("-updated_at", "-id").first()
        if conversation is None:
            conversation, _created = services.get_or_create_conversation(
                request.user,
                defaults={"default_kb_id": int(selected_kb_id) if selected_kb_id else None},
                adopt_legacy=False,
            )
    if not selected_kb_id and conversation.default_kb_id:
        selected_kb_id = str(conversation.default_kb_id)

    chat_messages = services.history(request.user, conversation)
    return render(
        request,
        "assistant/index.html",
        {
            "chat_messages": chat_messages,
            "knowledge_bases": knowledge_bases,
            "selected_kb_id": selected_kb_id,
            "selected_conversation": conversation,
            "conversations": services.active_conversations(request.user),
        },
    )


@login_required
def history_partial(request):
    conversation_id = request.GET.get("conversation", "")
    conversation = services.active_conversations(request.user).filter(id=conversation_id).first()
    chat_messages = services.history(request.user, conversation)
    return render(request, "assistant/partials/history.html", {"chat_messages": chat_messages})


@login_required
@require_POST
def stream_agent(request):
    message = (request.POST.get("message") or "").strip()
    use_drive = request.POST.get("use_drive") in {"1", "true", "on", "yes"}
    kb_id = (request.POST.get("kb_id") or "").strip()
    conversation_id = (request.POST.get("conversation_id") or "").strip()

    def generate():
        conversation = None
        if conversation_id:
            conversation = services.active_conversations(request.user).filter(id=conversation_id).first()
            if not conversation:
                yield services.sse({"type": "token", "data": "选择的对话不存在或不可用。"})
                yield services.sse({"type": "done"})
                return
        if conversation is None:
            conversation, _created = services.get_or_create_conversation(request.user)
            yield services.sse(
                {
                    "type": "conversation",
                    "data": {
                        "id": conversation.id,
                        "title": conversation.title,
                        "url": f"/assistant/?conversation={conversation.id}",
                    },
                }
            )
        orchestrator = AssistantOrchestrator(
            request.user,
            message,
            conversation,
            allow_drive=use_drive,
            kb_id=kb_id,
        )
        for event in orchestrator.stream():
            yield services.sse(event)

    response = StreamingHttpResponse(generate(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    return response


@login_required
@require_POST
def create_conversation(request):
    kb = None
    kb_id = (request.POST.get("kb_id") or "").strip()
    if kb_id.isdigit():
        kb = KnowledgeBase.objects.filter(user=request.user, status="active", id=kb_id).first()
    conversation, _created = services.get_or_create_conversation(
        request.user,
        defaults={"default_kb": kb} if kb else None,
        adopt_legacy=False,
    )
    return JsonResponse(
        {
            "ok": True,
            "conversation": {
                "id": conversation.id,
                "title": conversation.title,
                "url": f"/assistant/?conversation={conversation.id}",
            },
        }
    )


@login_required
@require_POST
def rename_conversation(request, conversation_id):
    conversation = services.active_conversations(request.user).filter(id=conversation_id).first()
    if not conversation:
        return JsonResponse({"ok": False, "message": "选择的对话不存在或不可用。"}, status=404)
    title = (request.POST.get("title") or "").strip()[:120]
    if not title:
        return JsonResponse({"ok": False, "message": "标题不能为空。"}, status=400)
    conversation.title = title
    conversation.save(update_fields=["title", "updated_at"])
    return JsonResponse({"ok": True, "conversation": {"id": conversation.id, "title": conversation.title}})


@login_required
@require_POST
def delete_conversation(request, conversation_id):
    conversation = services.active_conversations(request.user).filter(id=conversation_id).first()
    if not conversation:
        return JsonResponse({"ok": False, "message": "选择的对话不存在或不可用。"}, status=404)
    next_conversation = services.active_conversations(request.user).exclude(id=conversation.id).first()
    conversation.delete()
    return JsonResponse(
        {
            "ok": True,
            "next_url": f"/assistant/?conversation={next_conversation.id}" if next_conversation else "/assistant/",
        }
    )


@login_required
def memories(request):
    memories_qs = ConversationMemory.objects.filter(
        user=request.user,
        status=ConversationMemory.STATUS_ACTIVE,
    ).select_related("kb", "source_conversation", "source_message")
    selected_kb = request.GET.get("kb", "")
    selected_kind = request.GET.get("kind", "")
    if selected_kb.isdigit():
        memories_qs = memories_qs.filter(kb_id=selected_kb)
    elif selected_kb == "user":
        memories_qs = memories_qs.filter(kb__isnull=True)
    if selected_kind:
        memories_qs = memories_qs.filter(kind=selected_kind)
    return render(
        request,
        "assistant/memories.html",
        {
            "memories": memories_qs.order_by("-updated_at", "-id"),
            "knowledge_bases": KnowledgeBase.objects.filter(user=request.user, status="active"),
            "selected_kb": selected_kb,
            "selected_kind": selected_kind,
            "kind_choices": ConversationMemory.KIND_CHOICES,
        },
    )


@login_required
@require_POST
def remove_memory(request, memory_id):
    memory = get_object_or_404(ConversationMemory, id=memory_id, user=request.user)
    memory.status = ConversationMemory.STATUS_ARCHIVED
    memory.save(update_fields=["status", "updated_at"])
    delete_memory_index(memory.id)
    messages.success(request, "长期记忆已移除")
    return redirect("assistant:memories")


def _require_platform_admin(request):
    if request.user.is_platform_admin:
        return True
    messages.error(request, "无权访问运行调试页面")
    return False


@login_required
def runs(request):
    if not _require_platform_admin(request):
        return redirect("assistant:index")
    runs_qs = (
        AgentRun.objects.filter(parent_run__isnull=True)
        .select_related("user")
        .prefetch_related("child_runs")
        .order_by("-started_at")[:80]
    )
    return render(request, "assistant/runs.html", {"runs": runs_qs})


@login_required
def run_detail(request, run_id):
    if not _require_platform_admin(request):
        return redirect("assistant:index")
    run = get_object_or_404(
        AgentRun.objects.select_related("user", "parent_run").prefetch_related("events", "child_runs__events"),
        id=run_id,
    )
    return render(
        request,
        "assistant/run_detail.html",
        {
            "run": run,
            "children": run.child_runs.select_related("user").order_by("started_at", "id"),
            "events": run.events.order_by("created_at", "id"),
        },
    )

# Create your views here.
