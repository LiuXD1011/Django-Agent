from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import UploadSession, UserFile
from . import services


def _current_parent(request):
    parent_id = request.GET.get("folder") or request.POST.get("parent_id")
    return services.normalize_parent(request.user, parent_id) if parent_id else None


def _folder_tree(user):
    return services.folder_options(user)


def _folder_url(parent_id=None):
    url = reverse("drive:file_list")
    return f"{url}?folder={parent_id}" if parent_id else url


def _wants_json(request):
    return (
        "application/json" in request.headers.get("Accept", "")
        or request.headers.get("X-Requested-With") == "fetch"
    )


def _decorate_items(files):
    items = list(files)
    for item in items:
        item.location_label = services.folder_location_label(item.parent)
    return items


def _file_context(request, partial=False):
    parent = _current_parent(request)
    query = request.GET.get("q", "").strip()
    if query:
        files = services.search_files(request.user, query)
    else:
        files = services.active_children(request.user, parent)
    return {
        "files": _decorate_items(files),
        "parent": parent,
        "breadcrumbs": services.folder_path(parent) if parent else [],
        "current_folder_label": services.folder_location_label(parent),
        "folders": _folder_tree(request.user),
        "quota": services.ensure_quota(request.user),
        "query": query,
        "is_partial": partial,
    }


def _selected_items(request):
    ids = [item_id for item_id in request.POST.getlist("item_ids") if item_id]
    return list(UserFile.objects.filter(id__in=ids, user=request.user, is_deleted=False).select_related("parent", "stored_file"))


def _redirect_back(request):
    return redirect(request.META.get("HTTP_REFERER") or reverse("drive:file_list"))


@login_required
def file_list(request):
    return render(request, "drive/file_list.html", _file_context(request))


@login_required
def file_list_partial(request):
    return render(request, "drive/partials/file_table.html", _file_context(request, partial=True))


@login_required
@require_POST
def create_folder_view(request):
    parent_id = request.POST.get("parent_id")
    try:
        services.create_folder(request.user, request.POST.get("folder_name", "新建文件夹"), parent_id)
        messages.success(request, "文件夹已创建")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect(_folder_url(parent_id))


@login_required
@require_POST
def upload_file_view(request):
    uploaded_files = list(request.FILES.getlist("files")) + list(request.FILES.getlist("file"))
    parent_id = request.POST.get("parent_id")
    if not uploaded_files:
        if _wants_json(request):
            return JsonResponse({"ok": False, "message": "请选择文件"}, status=400)
        messages.error(request, "请选择文件")
        return redirect(_folder_url(parent_id))

    created = []
    errors = []
    for uploaded in uploaded_files:
        try:
            created.append(
                services.save_uploaded_file(
                    request.user,
                    uploaded,
                    parent_id,
                    request.POST.get("content_hash", "") if len(uploaded_files) == 1 else "",
                )
            )
        except Exception as exc:
            errors.append(f"{uploaded.name}: {exc}")

    if _wants_json(request):
        status = 400 if errors and not created else 200
        return JsonResponse(
            {
                "ok": not errors,
                "created_count": len(created),
                "errors": errors,
                "redirect_url": _folder_url(parent_id),
                "message": "上传完成" if not errors else "部分文件上传失败",
            },
            status=status,
        )

    if created:
        messages.success(request, f"已上传 {len(created)} 个文件")
    for error in errors:
        messages.error(request, error)
    return redirect(_folder_url(parent_id))


@login_required
@require_POST
def second_upload_view(request):
    item = services.second_upload(
        request.user,
        request.POST.get("filename", ""),
        request.POST.get("content_hash", ""),
        request.POST.get("parent_id"),
    )
    if not item:
        return JsonResponse({"ok": False, "message": "未找到可秒传文件"})
    return JsonResponse({"ok": True, "file_id": item.id, "message": "秒传完成"})


@login_required
@require_POST
def init_upload_view(request):
    try:
        session = services.init_upload_session(
            request.user,
            request.POST.get("filename", ""),
            request.POST.get("content_hash", ""),
            request.POST.get("file_size", 0),
            request.POST.get("chunk_size", 0),
            request.POST.get("chunk_count", 0),
            request.POST.get("parent_id"),
        )
        return JsonResponse({"ok": True, "session_id": session.id, "progress": session.progress_percent})
    except Exception as exc:
        return JsonResponse({"ok": False, "message": str(exc)}, status=400)


@login_required
@require_POST
def upload_chunk_view(request, session_id):
    session = get_object_or_404(UploadSession, id=session_id, user=request.user)
    chunk = request.FILES.get("chunk")
    try:
        services.save_upload_chunk(session, request.POST.get("part_number"), chunk)
        return JsonResponse({"ok": True, "progress": session.progress_percent})
    except Exception as exc:
        return JsonResponse({"ok": False, "message": str(exc)}, status=400)


@login_required
@require_POST
def merge_upload_view(request, session_id):
    session = get_object_or_404(UploadSession, id=session_id, user=request.user)
    try:
        item = services.merge_upload_session(session)
        return JsonResponse({"ok": True, "file_id": item.id, "message": "合并完成"})
    except Exception as exc:
        return JsonResponse({"ok": False, "message": str(exc)}, status=400)


@login_required
@require_POST
def rename_view(request, file_id):
    item = get_object_or_404(UserFile, id=file_id, user=request.user)
    try:
        services.rename_user_file(item, request.POST.get("new_name", item.name))
        messages.success(request, "重命名完成")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect(request.META.get("HTTP_REFERER") or "drive:file_list")


@login_required
@require_POST
def delete_view(request, file_id):
    item = get_object_or_404(UserFile, id=file_id, user=request.user, is_deleted=False)
    services.soft_delete([item])
    messages.success(request, "已移入回收站")
    return redirect(request.META.get("HTTP_REFERER") or "drive:file_list")


@login_required
def download_view(request, file_id):
    item = get_object_or_404(UserFile, id=file_id, user=request.user, is_folder=False, is_deleted=False)
    if not item.stored_file or not item.stored_file.file:
        raise Http404("文件不存在")
    return FileResponse(item.stored_file.file.open("rb"), as_attachment=True, filename=item.name)


@login_required
@require_POST
def move_view(request, file_id):
    item = get_object_or_404(UserFile, id=file_id, user=request.user, is_deleted=False)
    target = services.normalize_parent(request.user, request.POST.get("target_parent_id"))
    try:
        services.move_item(item, target)
        messages.success(request, "移动完成")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect(request.META.get("HTTP_REFERER") or "drive:file_list")


@login_required
@require_POST
def copy_view(request, file_id):
    item = get_object_or_404(UserFile, id=file_id, user=request.user, is_deleted=False)
    target = services.normalize_parent(request.user, request.POST.get("target_parent_id"))
    try:
        services.copy_item(item, target)
        messages.success(request, "复制完成")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect(request.META.get("HTTP_REFERER") or "drive:file_list")


@login_required
@require_POST
def bulk_delete_view(request):
    items = _selected_items(request)
    if not items:
        messages.error(request, "请选择文件")
        return _redirect_back(request)
    services.soft_delete(items)
    messages.success(request, f"已将 {len(items)} 个项目移入回收站")
    return _redirect_back(request)


@login_required
@require_POST
def bulk_move_view(request):
    items = _selected_items(request)
    if not items:
        messages.error(request, "请选择文件")
        return _redirect_back(request)
    try:
        target = services.normalize_parent(request.user, request.POST.get("target_parent_id"))
        moved = 0
        for item in items:
            services.move_item(item, target)
            moved += 1
        messages.success(request, f"已移动 {moved} 个项目")
    except Exception as exc:
        messages.error(request, str(exc))
    return _redirect_back(request)


@login_required
@require_POST
def bulk_copy_view(request):
    items = _selected_items(request)
    if not items:
        messages.error(request, "请选择文件")
        return _redirect_back(request)
    try:
        target = services.normalize_parent(request.user, request.POST.get("target_parent_id"))
        copied = 0
        for item in items:
            services.copy_item(item, target)
            copied += 1
        messages.success(request, f"已复制 {copied} 个项目")
    except Exception as exc:
        messages.error(request, str(exc))
    return _redirect_back(request)


@login_required
def recycle_view(request):
    files = UserFile.objects.filter(user=request.user, is_deleted=True).order_by("-deleted_at")
    return render(request, "drive/recycle.html", {"files": files})


@login_required
def recycle_partial(request):
    files = UserFile.objects.filter(user=request.user, is_deleted=True).order_by("-deleted_at")
    return render(request, "drive/partials/recycle_table.html", {"files": files})


@login_required
@require_POST
def restore_view(request, file_id):
    item = get_object_or_404(UserFile, id=file_id, user=request.user, is_deleted=True)
    services.restore_file(item)
    messages.success(request, "已还原")
    return redirect("recycle:index")


@login_required
@require_POST
def purge_view(request, file_id):
    item = get_object_or_404(UserFile, id=file_id, user=request.user, is_deleted=True)
    services.purge_file(item)
    messages.success(request, "已彻底删除")
    return redirect("recycle:index")

# Create your views here.
