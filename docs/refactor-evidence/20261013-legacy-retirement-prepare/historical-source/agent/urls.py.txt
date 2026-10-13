from django.urls import path

from . import views

urlpatterns = [
    # ── Agents ───────────────────────────────────────────────────────────────
    path("agents/placeholders", views.generic_action, {"resource_type": "agents", "action": "placeholders"}),
    path("agents/type-presets", views.generic_action, {"resource_type": "agents", "action": "type-presets"}),
    path("agents", views.generic_collection, {"resource_type": "agents"}),
    path("agents/<str:item_id>", views.generic_collection, {"resource_type": "agents"}),
    path("agents/<str:item_id>/copy", views.generic_action, {"resource_type": "agents", "action": "copy"}),
    path("agents/<str:item_id>/suggested-questions", views.generic_action, {"resource_type": "agents", "action": "suggested-questions"}),
    path("agents/<str:item_id>/embed-channels", views.generic_collection, {"resource_type": "embed_channels"}),
    path("agents/<str:item_id>/im-channels", views.generic_collection, {"resource_type": "im_channels"}),

    # ── MCP Services ─────────────────────────────────────────────────────────
    path("mcp-oauth/callback", views.generic_action, {"resource_type": "mcp_oauth", "action": "callback"}),
    path("mcp-services", views.generic_collection, {"resource_type": "mcp_services"}),
    path("mcp-services/<str:item_id>", views.generic_collection, {"resource_type": "mcp_services"}),
    path("mcp-services/<str:item_id>/test", views.generic_action, {"resource_type": "mcp_services", "action": "test"}),
    path("mcp-services/<str:item_id>/tools", views.generic_action, {"resource_type": "mcp_services", "action": "tools"}),
    path("mcp-services/<str:item_id>/resources", views.generic_action, {"resource_type": "mcp_services", "action": "resources"}),
    path("mcp-services/<str:item_id>/credentials", views.generic_action, {"resource_type": "mcp_services", "action": "credentials"}),
    path("mcp-services/<str:item_id>/credentials/<str:sub_id>", views.generic_action, {"resource_type": "mcp_services", "action": "credentials"}),
    path("mcp-services/<str:item_id>/tool-approvals", views.generic_action, {"resource_type": "mcp_services", "action": "tool-approvals"}),
    path("mcp-services/<str:item_id>/tool-approvals/<str:sub_id>", views.generic_action, {"resource_type": "mcp_services", "action": "tool-approvals"}),
    path("mcp-services/<str:item_id>/oauth/authorize-url", views.generic_action, {"resource_type": "mcp_services", "action": "oauth/authorize-url"}),
    path("mcp-services/<str:item_id>/oauth/status", views.generic_action, {"resource_type": "mcp_services", "action": "oauth/status"}),
    path("mcp-services/<str:item_id>/oauth/token", views.generic_action, {"resource_type": "mcp_services", "action": "oauth/token"}),

    # ── Agent Tools ──────────────────────────────────────────────────────────
    path("agent-tools/tool-approvals/<str:item_id>", views.generic_action, {"resource_type": "agent_tools", "action": "tool-approvals"}),

    # ── Embed Channels ───────────────────────────────────────────────────────
    path("embed-channels", views.generic_collection, {"resource_type": "embed_channels"}),
    path("embed-channels/<str:item_id>", views.generic_collection, {"resource_type": "embed_channels"}),
    path("embed-channels/<str:item_id>/rotate-token", views.generic_action, {"resource_type": "embed_channels", "action": "rotate-token"}),
    path("embed-channels/<str:item_id>/preview-session", views.generic_action, {"resource_type": "embed_channels", "action": "preview-session"}),
    path("embed-channels/<str:item_id>/stats", views.generic_action, {"resource_type": "embed_channels", "action": "stats"}),

    # ── IM Channels ──────────────────────────────────────────────────────────
    path("im-channels", views.generic_collection, {"resource_type": "im_channels"}),
    path("im-channels/<str:item_id>", views.generic_collection, {"resource_type": "im_channels"}),
    path("im-channels/<str:item_id>/toggle", views.generic_action, {"resource_type": "im_channels", "action": "toggle"}),
    path("im-channels/wechat/qrcode", views.generic_action, {"resource_type": "im_channels", "action": "qrcode"}),
    path("im-channels/wechat/qrcode/status", views.generic_action, {"resource_type": "im_channels", "action": "qrcode-status"}),

    # ── Web Search Providers ─────────────────────────────────────────────────
    path("web-search/providers", views.generic_action, {"resource_type": "web_search", "action": "providers"}),
    path("web-search-providers/types", views.generic_action, {"resource_type": "web_search_providers", "action": "types"}),
    path("web-search-providers/test", views.generic_action, {"resource_type": "web_search_providers", "action": "test"}),
    path("web-search-providers", views.generic_collection, {"resource_type": "web_search_providers"}),
    path("web-search-providers/<str:item_id>", views.generic_collection, {"resource_type": "web_search_providers"}),
    path("web-search-providers/<str:item_id>/credentials", views.generic_action, {"resource_type": "web_search_providers", "action": "credentials"}),
    path("web-search-providers/<str:item_id>/credentials/<str:sub_id>", views.generic_action, {"resource_type": "web_search_providers", "action": "credentials"}),
    path("web-search-providers/<str:item_id>/test", views.generic_action, {"resource_type": "web_search_providers", "action": "test"}),

    # ── Vector Stores ────────────────────────────────────────────────────────
    path("vector-stores/types", views.generic_action, {"resource_type": "vector_stores", "action": "types"}),
    path("vector-stores/test", views.generic_action, {"resource_type": "vector_stores", "action": "test"}),
    path("vector-stores", views.generic_collection, {"resource_type": "vector_stores"}),
    path("vector-stores/<str:item_id>", views.generic_collection, {"resource_type": "vector_stores"}),
    path("vector-stores/<str:item_id>/test", views.generic_action, {"resource_type": "vector_stores", "action": "test"}),

    # ── Data Sources ─────────────────────────────────────────────────────────
    path("data-sources/types", views.generic_action, {"resource_type": "data_sources", "action": "types"}),
    path("data-sources/validate-credentials", views.generic_action, {"resource_type": "data_sources", "action": "validate-credentials"}),
    path("data-sources", views.generic_collection, {"resource_type": "data_sources"}),
    path("data-sources/logs/<str:item_id>", views.generic_collection, {"resource_type": "sync_logs"}),
    path("data-sources/<str:item_id>", views.generic_collection, {"resource_type": "data_sources"}),
    path("data-sources/<str:item_id>/<str:action>", views.generic_action, {"resource_type": "data_sources"}),
    path("data-sources/<str:item_id>/credentials/<str:sub_id>", views.generic_action, {"resource_type": "data_sources", "action": "credentials"}),

    # ── Knowledge image route (using generic_action) ─────────────────────────
    path("knowledge/image/<str:knowledge_id>/<str:chunk_id>", views.generic_action, {"resource_type": "knowledge", "action": "image"}),

    # ── Evaluation ───────────────────────────────────────────────────────────
    path("evaluation/", views.generic_action, {"resource_type": "evaluation", "action": "run"}),

    # ── Initialization routes (using generic_action) ─────────────────────────
    path("initialization/ollama/status", views.generic_action, {"resource_type": "ollama", "action": "status"}),
    path("initialization/ollama/models", views.generic_action, {"resource_type": "ollama", "action": "models"}),
    path("initialization/ollama/models/check", views.generic_action, {"resource_type": "ollama", "action": "check"}),
    path("initialization/ollama/models/download", views.generic_action, {"resource_type": "ollama", "action": "download"}),
    path("initialization/ollama/download/progress/<str:task_id>", views.generic_action, {"resource_type": "ollama", "action": "download-progress"}),
    path("initialization/ollama/download/tasks", views.generic_action, {"resource_type": "ollama", "action": "tasks"}),
    path("initialization/remote/check", views.generic_action, {"resource_type": "models", "action": "remote/check"}),
    path("initialization/embedding/test", views.generic_action, {"resource_type": "models", "action": "embedding/test"}),
    path("initialization/rerank/check", views.generic_action, {"resource_type": "models", "action": "rerank/check"}),
    path("initialization/multimodal/test", views.generic_action, {"resource_type": "models", "action": "multimodal/test"}),
    path("initialization/extract/text-relation", views.generic_action, {"resource_type": "extract", "action": "text-relation"}),
    path("initialization/extract/fabri-tag", views.generic_action, {"resource_type": "extract", "action": "fabri-tag"}),
    path("initialization/extract/fabri-text", views.generic_action, {"resource_type": "extract", "action": "fabri-text"}),

    # ── System routes (using generic_action) ─────────────────────────────────
    path("system/parser-engines/check", views.generic_action, {"resource_type": "system", "action": "parser-engines/check"}),
    path("system/docreader/reconnect", views.generic_action, {"resource_type": "system", "action": "docreader"}),
    path("system/storage-engine-check", views.generic_action, {"resource_type": "system", "action": "storage-engine-check"}),

    # ── Wiki move-page and auto-fix (using generic_action) ───────────────────
    path("knowledge-bases/<str:kb_id>/wiki/move-page", views.generic_action, {"resource_type": "wiki", "action": "move-page"}),
    path("knowledge-bases/<str:kb_id>/wiki/rebuild-links", views.generic_action, {"resource_type": "wiki", "action": "rebuild-links"}),
    path("knowledge-bases/<str:kb_id>/wiki/auto-fix", views.generic_action, {"resource_type": "wiki", "action": "auto-fix"}),

    # ── Miscellaneous resource routes ────────────────────────────────────────
    path("user-favorites", views.generic_collection, {"resource_type": "user_favorites"}),
    path("user-favorites/<str:item_id>/<str:sub_id>", views.generic_collection, {"resource_type": "user_favorites"}),
    path("skills", views.generic_action, {"resource_type": "skills", "action": "list"}),
    path("chunker/preview", views.generic_action, {"resource_type": "chunker", "action": "preview"}),

    # ── System admin resource routes ─────────────────────────────────────────
    path("system/admin/promote", views.generic_action, {"resource_type": "system_admin", "action": "promote"}),
    path("system/admin/revoke", views.generic_action, {"resource_type": "system_admin", "action": "revoke"}),
    path("system/admin/list", views.generic_collection, {"resource_type": "system_admins"}),
    path("system/admin/settings", views.generic_collection, {"resource_type": "system_settings"}),
    path("system/admin/settings/<str:item_id>", views.generic_collection, {"resource_type": "system_settings"}),
]
