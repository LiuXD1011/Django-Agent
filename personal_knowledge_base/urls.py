from django.urls import path

from . import compat_views, eval_views, views


urlpatterns = [
    # ── Knowledge background tasks ───────────────────────────────────────────
    path("knowledge-bases/copy/progress/<str:task_id>", compat_views.task_progress),
    path("knowledge/move/progress/<str:task_id>", compat_views.task_progress),

    # ── Chunk questions ──────────────────────────────────────────────────────
    path("chunks/by-id/<str:chunk_id>/questions", compat_views.chunk_questions),

    # ── Initialization ───────────────────────────────────────────────────────
    path("initialization/config/<str:kb_id>", compat_views.initialization_config),
    path("initialization/initialize/<str:kb_id>", compat_views.initialization_update),

    # ── System ───────────────────────────────────────────────────────────────
    path("system/info", views.system_info),
    path("system/parser-engines", views.parser_engines),
    path("system/storage-engine-status", views.storage_status),

    # ── Embed public ─────────────────────────────────────────────────────────
    path("embed/<str:channel_id>/exchange", views.embed_public, {"action": "exchange"}),
    path("embed/<str:channel_id>/config", views.embed_public, {"action": "config"}),
    path("embed/<str:channel_id>/suggested-questions", views.embed_public, {"action": "suggested-questions"}),
    path("embed/<str:channel_id>/chunks/<str:chunk_id>", views.embed_public, {"action": "chunks"}),
    path("embed/<str:channel_id>/sessions", views.embed_public, {"action": "sessions"}),
    path("embed/<str:channel_id>/knowledge-chat/<str:session_id>", views.embed_public, {"action": "knowledge-chat"}),
    path("embed/<str:channel_id>/agent-chat/<str:session_id>", views.embed_public, {"action": "agent-chat"}),
    path("embed/<str:channel_id>/messages/<str:session_id>/load", views.embed_public, {"action": "messages"}),
    path("embed/<str:channel_id>/sessions/<str:session_id>/stop", views.embed_public, {"action": "stop"}),
    path("embed/<str:channel_id>/sessions/<str:session_id>/events", views.embed_public, {"action": "events"}),

    # ── RAG Evaluation ────────────────────────────────────────────────────────
    path("rag-eval/run", eval_views.rag_eval_run),
    path("rag-eval/questions", eval_views.rag_eval_questions),
    path("rag-eval/questions/<str:question_id>", eval_views.rag_eval_question_delete),
    path("rag-eval/generate", eval_views.rag_eval_generate),
    path("rag-eval/open-datasets", eval_views.rag_eval_open_datasets),
    path("rag-eval/open-datasets/<str:dataset_id>/status", eval_views.rag_eval_open_dataset_status),
    path("rag-eval/open-datasets/<str:dataset_id>/prepare", eval_views.rag_eval_open_dataset_prepare),
    path("rag-eval/open-runs", eval_views.rag_eval_open_runs),
    path("rag-eval/open-runs/<str:run_id>", eval_views.rag_eval_open_runs),
    path("rag-eval/open-runs/<str:run_id>/cancel", eval_views.rag_eval_open_runs, {"action": "cancel"}),
    path("rag-eval/runs", eval_views.rag_eval_runs),
    path("rag-eval/runs/estimate", eval_views.rag_eval_run_estimate),
    path("rag-eval/runs/<str:run_id>", eval_views.rag_eval_runs),
    path("rag-eval/runs/<str:run_id>/cancel", eval_views.rag_eval_runs, {"action": "cancel"}),
    path("rag-eval/runs/<str:run_id>/resume", eval_views.rag_eval_runs, {"action": "resume"}),
    path("rag-eval/datasets", eval_views.rag_eval_datasets),
    path("rag-eval/datasets/<str:dataset_id>", eval_views.rag_eval_datasets),
    path("rag-eval/datasets/<str:dataset_id>/review", eval_views.rag_eval_dataset_review),
    path("rag-eval/datasets/<str:dataset_id>/publish", eval_views.rag_eval_dataset_publish),
    path("rag-eval/testsets", eval_views.rag_eval_testsets),
    path("rag-eval/testsets/<str:testset_id>", eval_views.rag_eval_testsets),
    path("rag-eval/history", eval_views.rag_eval_history),
    path("rag-eval/reports/<str:run_id>", eval_views.rag_eval_report, name="rag-eval-report"),
    path("rag-eval/retrieval", eval_views.retrieval_eval_run),
    path("rag-eval/chunking", eval_views.chunking_eval_run),
]
