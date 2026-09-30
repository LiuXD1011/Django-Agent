from django.urls import path

from . import views
from .thinking_views import thinking_settings

urlpatterns = [
    path("models/<str:model_id>/thinking", thinking_settings),
    path("models/providers", views.model_providers),
    path("models/usage", views.model_usage),
    path("models", views.models_collection),
    path("models/<str:model_id>", views.models_collection),
    path("models/<str:model_id>/test", views.model_test),
    path("models/<str:model_id>/credentials", views.model_credentials),
    path("models/<str:model_id>/credentials/<str:field>", views.model_credentials),
]
