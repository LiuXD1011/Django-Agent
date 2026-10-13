from django.urls import path

from . import views

urlpatterns = [
    # Knowledge Base CRUD
    path("knowledge-bases", views.knowledge_bases),
    path("knowledge-bases/copy", views.kb_copy),
    path("knowledge-bases/<str:kb_id>", views.knowledge_bases),
    path("knowledge-bases/<str:kb_id>/pin", views.kb_pin),
    path("knowledge-bases/<str:kb_id>/move-targets", views.kb_move_targets),
    path("knowledge-bases/<str:kb_id>/hybrid-search", views.kb_hybrid_search),

    # Knowledge Base Stats
    path("knowledge-bases/<str:kb_id>/knowledge/stats", views.knowledge_stats),

    # Knowledge CRUD
    path("knowledge-bases/<str:kb_id>/knowledge", views.knowledge_collection),
    path("knowledge-bases/<str:kb_id>/knowledge/file", views.knowledge_file),
    path("knowledge-bases/<str:kb_id>/knowledge/batch-delete", views.knowledge_batch_delete),
    path("knowledge-bases/<str:kb_id>/knowledge/move", views.knowledge_move),

    # Knowledge Tags
    path("knowledge-bases/<str:kb_id>/tags", views.knowledge_tags),
    path("knowledge-bases/<str:kb_id>/tags/<str:tag_id>", views.knowledge_tags),

    # Knowledge Operations
    path("knowledge/batch", views.knowledge_batch),
    path("knowledge/search", views.knowledge_search),
    path("knowledge/batch-delete", views.knowledge_batch_delete),
    path("knowledge/move", views.knowledge_move),
    path("knowledge/<str:knowledge_id>", views.knowledge_detail),
    path("knowledge/<str:knowledge_id>/stages", views.knowledge_spans),
    path("knowledge/<str:knowledge_id>/spans", views.knowledge_spans),
    path("knowledge/<str:knowledge_id>/reparse", views.knowledge_reparse),
    path("knowledge/<str:knowledge_id>/cancel-parse", views.knowledge_cancel),
    path("knowledge/<str:knowledge_id>/download", views.knowledge_download),
    path("knowledge/<str:knowledge_id>/preview", views.knowledge_preview),
    path("knowledge/<str:knowledge_id>/images/<str:image_id>", views.knowledge_image_content),

    # Chunks
    path("chunks/<str:knowledge_id>", views.chunks_collection),
    path("chunks/<str:knowledge_id>/<str:chunk_id>", views.chunks_collection),
    path("chunks/by-id/<str:chunk_id>", views.chunks_collection),

    # Knowledge Search POST
    path("knowledge-search", views.knowledge_search_post),
]
