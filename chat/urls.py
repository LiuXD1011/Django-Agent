from django.urls import path

from . import views


urlpatterns = [
    # ── Sessions CRUD ────────────────────────────────────────────────
    path("sessions", views.sessions_collection),
    path("sessions/batch", views.sessions_collection),
    path("sessions/<str:session_id>", views.sessions_collection),

    # ── Session actions ──────────────────────────────────────────────
    path("sessions/<str:session_id>/messages", views.session_messages_clear),
    path("sessions/<str:session_id>/generate_title", views.session_title),
    path("sessions/<str:session_id>/stop", views.session_stop),
    path("sessions/<str:session_id>/pin", views.session_pin),
    path("sessions/<str:session_id>/trajectory", views.session_trajectory),
    path("sessions/<str:session_id>/events", views.session_events),

    # ── Continue stream (断线重连) ──────────────────────────────────
    path("sessions/continue-stream/<str:session_id>", views.continue_stream),

    # ── Chat endpoints ───────────────────────────────────────────────
    path("knowledge-chat/<str:session_id>", views.chat_endpoint),
    path("agent-chat/<str:session_id>", views.chat_endpoint, {"agent": True}),

    # ── Messages ─────────────────────────────────────────────────────
    path("messages/search", views.messages_search),
    path("messages/chat-history-stats", views.chat_history_stats),
    path("messages/<str:session_id>/load", views.messages_load),
    path("messages/<str:session_id>/<str:message_id>", views.message_delete),
]
