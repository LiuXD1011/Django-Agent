"""Create new private accounts without reassigning historical spaces."""
import secrets

from django.db import transaction

from .models import Tenant, TenantMember, User


@transaction.atomic
def create_personal_user(*, username, email, password_hash):
    user = User.objects.create(username=username, email=email, password_hash=password_hash)
    tenant = Tenant.objects.create(
        name=f"{username} 的空间", api_key=secrets.token_urlsafe(24),
        space_type="personal", personal_owner=user,
    )
    TenantMember.objects.create(user=user, tenant=tenant, role="owner")
    user.tenant = tenant
    user.save(update_fields=["tenant", "updated_at"])
    return user
