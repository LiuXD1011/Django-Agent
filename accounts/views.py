from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render

from .forms import ProfileForm, RegisterForm
from .models import User


def login_view(request):
    if request.user.is_authenticated:
        return redirect("drive:file_list")
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect(request.GET.get("next") or "drive:file_list")
    return render(request, "accounts/login.html", {"form": form})


def register_view(request):
    if request.user.is_authenticated:
        return redirect("drive:file_list")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "注册成功")
        return redirect("drive:file_list")
    return render(request, "accounts/register.html", {"form": form})


def logout_view(request):
    logout(request)
    return redirect("home")


@login_required
def profile_view(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "资料已更新")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})


@login_required
def admin_users(request):
    if not request.user.is_platform_admin:
        messages.error(request, "无权访问管理员页面")
        return redirect("drive:file_list")
    users = User.objects.select_related("storage_quota").order_by("-date_joined")
    return render(request, "accounts/admin_users.html", {"users": users})

# Create your views here.
