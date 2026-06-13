from django.urls import path

from . import views

app_name = "recycle"

urlpatterns = [
    path("", views.recycle_view, name="index"),
    path("partial/list/", views.recycle_partial, name="partial"),
    path("<int:file_id>/restore/", views.restore_view, name="restore"),
    path("<int:file_id>/purge/", views.purge_view, name="purge"),
]
