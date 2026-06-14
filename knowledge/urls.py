from django.urls import path

from . import views

app_name = "knowledge"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create_kb, name="create"),
    path("<int:kb_id>/ingest/", views.ingest, name="ingest"),
    path("<int:kb_id>/wiki/build/", views.build_wiki, name="build_wiki"),
    path("<int:kb_id>/wiki/graph.json", views.wiki_graph_json, name="wiki_graph_json"),
    path("<int:kb_id>/wiki/<slug:slug>/", views.wiki_page, name="wiki_page"),
]
