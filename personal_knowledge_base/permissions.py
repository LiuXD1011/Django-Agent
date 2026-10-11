"""统一动作授权：principal + tenant + action 判定，默认拒绝。

角色矩阵（read 是所有已认证主体的基线；写动作按角色收敛）：
- owner：租户创建者/系统管理员/跨租户账号，全部动作；
- admin：与 owner 一致（为未来 owner 专属动作——租户删除/所有权转移——预留分层）；
- editor：业务资源读写（知识库/文档/分块/wiki/agent 与渠道配置/评测），
  不含成员管理、租户配置与凭据、API-Key 轮换；
- viewer：只读与导出；
- service（X-API-Key 主体，无真实用户）：只读与导出；
  破坏性动作一律要求真实用户主体，API-Key 不默认等同 owner。
"""

from functools import wraps

from .authentication import has_tenant_access
from .models import TenantMember

READ = "read"
EXPORT = "export"
KB_WRITE = "kb.write"
KB_DELETE = "kb.delete"
DOCUMENT_WRITE = "document.write"
DOCUMENT_DELETE = "document.delete"
DOCUMENT_MOVE = "document.move"
CHUNK_WRITE = "chunk.write"
WIKI_WRITE = "wiki.write"
AGENT_WRITE = "agent.write"
EVAL_WRITE = "eval.write"
TASK_WRITE = "task.write"
CREDENTIALS_MANAGE = "credentials.manage"
MEMBER_MANAGE = "member.manage"
TENANT_ADMIN = "tenant.admin"
TENANT_CREATE = "tenant.create"

_VIEWER = frozenset({READ, EXPORT})
_EDITOR = _VIEWER | {
    KB_WRITE, DOCUMENT_WRITE, DOCUMENT_DELETE, DOCUMENT_MOVE,
    CHUNK_WRITE, WIKI_WRITE, AGENT_WRITE, EVAL_WRITE, TASK_WRITE,
}
_ADMIN = _EDITOR | {KB_DELETE, CREDENTIALS_MANAGE, MEMBER_MANAGE, TENANT_ADMIN}

ROLE_ACTIONS = {
    "viewer": _VIEWER,
    "editor": _EDITOR,
    "admin": _ADMIN,
    "owner": _ADMIN,
    # 服务主体（租户级 API-Key）：读 + 导出；任何写动作都要求真实用户。
    "service": _VIEWER,
}

# 创建租户要求已认证真实用户；service 主体不允许创建。
_USER_ONLY = frozenset({READ, EXPORT, TENANT_CREATE})

_KNOWN_ROLES = frozenset(ROLE_ACTIONS)


def principal_role(user, tenant) -> str:
    """解析主体在租户内的权威角色；无法证明任何关系时默认 viewer（拒绝写）。"""
    if tenant is None:
        return "viewer"
    if user is None:
        return "service"
    if not has_tenant_access(user, tenant):
        return "viewer"
    if tenant.space_type == "personal":
        return "owner"
    if user.is_system_admin or user.can_access_all_tenants:
        return "owner"
    member = TenantMember.objects.filter(user=user, tenant=tenant).first()
    if member:
        return member.role if member.role in _KNOWN_ROLES else "viewer"
    # Only legacy users without any membership row may use the primary-tenant fallback.
    if user.tenant_id == tenant.id:
        return "owner"
    return "viewer"


def allows(user, tenant, action) -> bool:
    if tenant is None or tenant.status != "active" or tenant.deleted_at is not None:
        return False
    if user is not None and not has_tenant_access(user, tenant):
        return False
    role = principal_role(user, tenant)
    allowed = _USER_ONLY if action == TENANT_CREATE else ROLE_ACTIONS.get(role, frozenset())
    if action == TENANT_CREATE and user is None:
        return False
    return action in allowed


def action_response(request, action):
    """动作不被允许时返回 403 响应，否则返回 None（供多方法视图分支内调用）。

    依赖 tenant_required/auth_context 已解析的 request.auth_user/auth_tenant；
    缺失时自行认证，保证旁路调用路径同样被约束。
    """
    from .responses import fail

    user = getattr(request, "auth_user", None)
    tenant = getattr(request, "auth_tenant", None)
    if user is None and tenant is None and not hasattr(request, "auth_tenant"):
        from .authentication import require_auth

        try:
            user, tenant = require_auth(request)
        except PermissionError:
            return fail("unauthorized", 401, "unauthorized")
        request.auth_user, request.auth_tenant = user, tenant
    if tenant is None:
        return fail("unauthorized", 401, "unauthorized")
    if not allows(user, tenant, action):
        return fail("forbidden", 403, "action_forbidden")
    return None


def user_principal_response(request):
    """写会话/消息等用户私有资源时要求真实用户；service 主体只读。"""
    from .responses import fail

    user = getattr(request, "auth_user", None)
    tenant = getattr(request, "auth_tenant", None)
    if user is None and tenant is None and not hasattr(request, "auth_tenant"):
        from .authentication import require_auth

        try:
            user, tenant = require_auth(request)
        except PermissionError:
            return fail("unauthorized", 401, "unauthorized")
        request.auth_user, request.auth_tenant = user, tenant
    if tenant is None:
        return fail("unauthorized", 401, "unauthorized")
    if user is None:
        return fail("forbidden", 403, "user_principal_required")
    return None


def action_required(action):
    """装饰器形式：非只读方法整体要求某动作（视图内部细粒度分支请用 action_response）。"""
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method in {"GET", "HEAD", "OPTIONS"}:
                return view(request, *args, **kwargs)
            denied = action_response(request, action)
            if denied is not None:
                return denied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
