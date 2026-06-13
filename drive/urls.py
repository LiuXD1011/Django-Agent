from django.urls import path

from . import views

app_name = "drive"

urlpatterns = [
    path("", views.file_list, name="file_list"),
    path("partial/list/", views.file_list_partial, name="file_list_partial"),
    path("folders/create/", views.create_folder_view, name="create_folder"),
    path("upload/", views.upload_file_view, name="upload_file"),
    path("upload/second/", views.second_upload_view, name="second_upload"),
    path("upload/init/", views.init_upload_view, name="init_upload"),
    path("upload/<int:session_id>/chunk/", views.upload_chunk_view, name="upload_chunk"),
    path("upload/<int:session_id>/merge/", views.merge_upload_view, name="merge_upload"),
    path("bulk/delete/", views.bulk_delete_view, name="bulk_delete"),
    path("bulk/move/", views.bulk_move_view, name="bulk_move"),
    path("bulk/copy/", views.bulk_copy_view, name="bulk_copy"),
    path("<int:file_id>/rename/", views.rename_view, name="rename"),
    path("<int:file_id>/delete/", views.delete_view, name="delete"),
    path("<int:file_id>/download/", views.download_view, name="download"),
    path("<int:file_id>/move/", views.move_view, name="move"),
    path("<int:file_id>/copy/", views.copy_view, name="copy"),
]
