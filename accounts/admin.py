from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import StorageQuota, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("账户扩展信息", {"fields": ("phone", "avatar", "role")}),)
    list_display = ("username", "phone", "role", "is_staff", "is_superuser")


@admin.register(StorageQuota)
class StorageQuotaAdmin(admin.ModelAdmin):
    list_display = ("user", "used_size", "total_size", "updated_at")

# Register your models here.
