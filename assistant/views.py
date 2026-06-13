from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from knowledge.models import KnowledgeBase

from .agents import AssistantOrchestrator
from . import services


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

# Create your views here.
