from django.urls import path

from . import views

app_name = "assistant"

urlpatterns = [
    path("", views.assistant_home, name="index"),
    path("stream/", views.stream_agent, name="stream"),
    path("history/", views.history_partial, name="history"),
    path("conversations/new/", views.create_conversation, name="conversation_create"),
    path("conversations/<int:conversation_id>/rename/", views.rename_conversation, name="conversation_rename"),
    path("conversations/<int:conversation_id>/delete/", views.delete_conversation, name="conversation_delete"),
]
