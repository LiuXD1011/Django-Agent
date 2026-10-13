from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from .models import Chunk, Knowledge, KnowledgeBase, TaskRecord
from .responses import ok
from .serializers import kb_dict
from .view_security import tenant_object_or_404, tenant_required


@csrf_exempt
@tenant_required
def chunk_questions(request, chunk_id):
    tenant = request.auth_tenant
    chunk = tenant_object_or_404(
        Chunk,
        tenant,
        id=chunk_id,
        deleted_at__isnull=True,
        knowledge__tenant=tenant,
        knowledge__deleted_at__isnull=True,
        knowledge_base__tenant=tenant,
        knowledge_base__deleted_at__isnull=True,
        knowledge__knowledge_base__tenant=tenant,
        knowledge__knowledge_base__deleted_at__isnull=True,
    )

    # Delegate to the active handler with the scoped parent so its write path remains available.
    from knowledge.views import chunks_collection

    return chunks_collection(request, knowledge_id=chunk.knowledge_id, chunk_id=chunk.id)


@csrf_exempt
@tenant_required
def task_progress(request, task_id):
    task = get_object_or_404(TaskRecord, id=task_id)
    payload = task.payload if isinstance(task.payload, dict) else {}
    knowledge_id = payload.get("knowledge_id")
    tenant_object_or_404(
        Knowledge,
        request.auth_tenant,
        id=knowledge_id,
        deleted_at__isnull=True,
        knowledge_base__tenant=request.auth_tenant,
        knowledge_base__deleted_at__isnull=True,
    )

    from .tasks import task_status

    return ok(task_status(task.id))


@csrf_exempt
@tenant_required
def initialization_config(request, kb_id):
    kb = tenant_object_or_404(KnowledgeBase, request.auth_tenant, id=kb_id, deleted_at__isnull=True)
    return ok({"knowledge_base": kb_dict(kb), "config": kb_dict(kb, counts=False)})


@csrf_exempt
@tenant_required
def initialization_update(request, kb_id):
    tenant_object_or_404(KnowledgeBase, request.auth_tenant, id=kb_id, deleted_at__isnull=True)

    from knowledge.views import knowledge_bases

    return knowledge_bases(request, kb_id)
