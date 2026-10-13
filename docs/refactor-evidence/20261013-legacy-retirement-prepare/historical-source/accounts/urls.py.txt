from django.urls import path

from personal_knowledge_base.responses import ok
from personal_knowledge_base.views import generic_action, generic_collection

from . import views

urlpatterns = [
    # Auth
    path("auth/register", views.auth_register),
    path("auth/register-by-invite", views.auth_register),
    path("auth/invitations/lookup", lambda request: ok({"valid": False})),
    path("auth/login", views.auth_login),
    path("auth/csrf", views.auth_csrf),
    path("auth/devices", views.auth_devices),
    path("auth/devices/<uuid:device_id>", views.auth_device_detail),
    path("auth/logout-all", views.auth_logout_all),
    path("auth/auto-setup", views.auth_auto_setup),
    path("auth/config", views.auth_config),
    path("auth/switch-tenant", views.switch_tenant),
    path("auth/oidc/config", views.oidc_config),
    path("auth/oidc/url", views.oidc_url),
    path("auth/oidc/callback", views.oidc_callback),
    path("auth/refresh", views.auth_refresh),
    path("auth/validate", views.auth_validate),
    path("auth/logout", views.auth_logout),
    path("auth/me", views.auth_me),
    path("auth/me/preferences", views.auth_preferences),
    path("auth/change-password", views.auth_change_password),

    # Tenants
    path("tenants", views.tenants_collection),
    path("tenants/all", views.tenants_collection),
    path("tenants/search", views.tenants_collection),
    path("tenants/kv/<str:key>", views.tenant_kv),
    path("tenants/<int:tenant_id>", views.tenant_detail),
    path("tenants/<int:tenant_id>/api-key", views.tenant_api_key),
    path("tenants/<int:tenant_id>/members", views.tenant_members),
    path("tenants/<int:tenant_id>/members/<str:user_id>", views.tenant_members),
    path("tenants/<int:tenant_id>/leave", generic_action, {"resource_type": "tenants", "action": "leave"}),
    path("tenants/<int:tenant_id>/invitations", generic_collection, {"resource_type": "tenant_invitations"}),
    path("tenants/<int:tenant_id>/invite-links", generic_action, {"resource_type": "tenant_invitations", "action": "invite-links"}),
    path("tenants/<int:tenant_id>/audit-log", views.audit_logs),

    # Me / invitations
    path("me/invitations", generic_collection, {"resource_type": "my_invitations"}),
    path("me/invitations/pending-count", lambda request: ok({"count": 0})),
    path("me/invitations/<str:item_id>/accept", generic_action, {"resource_type": "my_invitations", "action": "accept"}),
    path("me/invitations/<str:item_id>/decline", generic_action, {"resource_type": "my_invitations", "action": "decline"}),

    # System audit
    path("system/admin/audit-log", views.audit_logs),
]
