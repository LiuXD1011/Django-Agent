from django.urls import path

from . import views

app_name = "assistant"

urlpatterns = [
    path("", views.assistant_home, name="index"),
    path("stream/", views.stream_agent, name="stream"),
    path("history/", views.history_partial, name="history"),
    path("memories/", views.memories, name="memories"),
    path("memories/<int:memory_id>/remove/", views.remove_memory, name="memory_remove"),
    path("runs/", views.runs, name="runs"),
    path("runs/<int:run_id>/", views.run_detail, name="run_detail"),
    path("conversations/new/", views.create_conversation, name="conversation_create"),
    path("conversations/<int:conversation_id>/rename/", views.rename_conversation, name="conversation_rename"),
    path("conversations/<int:conversation_id>/delete/", views.delete_conversation, name="conversation_delete"),
]
