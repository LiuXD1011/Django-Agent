from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path, re_path
from django.views.generic import TemplateView

from personal_knowledge_base import views


from personal_knowledge_base.langfuse_access import langfuse_access

urlpatterns = [
    path("api/v1/observability/langfuse/status", langfuse_access),
    path("api/v1/observability/langfuse/session", langfuse_access, {"action": "session"}),
    path("api/v1/observability/langfuse/session/clear", langfuse_access, {"action": "clear"}),
    path("health", views.health),
    path("api/v1/", include("accounts.urls")),
    path("api/v1/", include("knowledge.urls")),
    path("api/v1/", include("chat.urls")),
    path("api/v1/", include("wiki.urls")),
    path("api/v1/", include("agent.urls")),
    path("api/v1/", include("models_config.urls")),
    path("api/v1/", include("personal_knowledge_base.urls")),
    path("files", views.serve_file),
    path("api/v1/files/presigned", views.presigned_file),
    re_path(r"^im/callback/(?P<channel_id>[^/]+)$", views.im_callback),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static("/assets/", document_root=settings.BASE_DIR / "frontend" / "dist" / "assets")

urlpatterns += [
    re_path(r"^(?!api/|files|assets/|health|im/).*$", TemplateView.as_view(template_name="index.html")),
]
