from django.urls import path, re_path

from . import views

urlpatterns = [
    # Wiki Pages CRUD
    path("knowledge-bases/<str:kb_id>/wiki/pages", views.wiki_pages),
    re_path(r"^knowledge-bases/(?P<kb_id>[^/]+)/wiki/pages/(?P<slug>.*)$", views.wiki_pages),

    # Wiki Folders CRUD
    path("knowledge-bases/<str:kb_id>/wiki/folders", views.wiki_folders),
    path("knowledge-bases/<str:kb_id>/wiki/folders/<str:folder_id>", views.wiki_folders),

    # Wiki Index & Search
    path("knowledge-bases/<str:kb_id>/wiki/index", views.wiki_index),
    path("knowledge-bases/<str:kb_id>/wiki/search", views.wiki_search),

    # Wiki Graph
    path("knowledge-bases/<str:kb_id>/wiki/graph", views.wiki_graph),

    # Wiki Stats, Log, Lint, Issues
    path("knowledge-bases/<str:kb_id>/wiki/stats", views.wiki_stats),
    path("knowledge-bases/<str:kb_id>/wiki/log", views.wiki_log),
    path("knowledge-bases/<str:kb_id>/wiki/lint", views.wiki_lint),
    path("knowledge-bases/<str:kb_id>/wiki/issues", views.wiki_issues),
    path("knowledge-bases/<str:kb_id>/wiki/issues/<str:issue_id>/status", views.wiki_issues),
]
