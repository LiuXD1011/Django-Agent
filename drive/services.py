import hashlib
import mimetypes
import os
import shutil
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.utils import timezone

from accounts.models import StorageQuota

from .models import StoredFile, UploadSession, UserFile


def file_suffix(name):
    return Path(name).suffix.lower().lstrip(".")


def inspect_stored_file_if_needed(stored_file, force=False):
    if not stored_file or (stored_file.last_inspected_at and not force):
        return None
    from content_runtime.inspectors import inspect_stored_file

    return inspect_stored_file(stored_file, save=True)


def normalize_parent(user, parent_id=None):
    if not parent_id:
        return None
    return UserFile.objects.get(id=parent_id, user=user, is_folder=True, is_deleted=False)


def folder_path(folder):
    path = []
    current = folder
    while current:
        path.append(current)
        current = current.parent
    return list(reversed(path))


def folder_location_label(folder):
    if not folder:
        return "全部文件"
    return "全部文件 / " + " / ".join(item.name for item in folder_path(folder))


def folder_options(user):
    folders = list(
        UserFile.objects.filter(user=user, is_folder=True, is_deleted=False)
        .select_related("parent")
        .order_by("name")
    )
    by_parent = {}
    for folder in folders:
        by_parent.setdefault(folder.parent_id, []).append(folder)
    for siblings in by_parent.values():
        siblings.sort(key=lambda item: item.name.lower())

    options = []

    def walk(parent_id, depth, parent_label):
        for folder in by_parent.get(parent_id, []):
            path_label = f"{parent_label} / {folder.name}" if parent_label else folder.name
            options.append(
                {
                    "id": folder.id,
                    "name": folder.name,
                    "depth": depth,
                    "label": f"{'-- ' * depth}{folder.name}",
                    "path_label": f"全部文件 / {path_label}",
                }
            )
            walk(folder.id, depth + 1, path_label)

    walk(None, 0, "")
    return options


def unique_name(user, parent, name, exclude_id=None):
    base, ext = os.path.splitext(name.strip() or "未命名")
    candidate = f"{base}{ext}"
    index = 1
    qs = UserFile.objects.filter(user=user, parent=parent, is_deleted=False, name=candidate)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    while qs.exists():
        candidate = f"{base} ({index}){ext}"
        qs = UserFile.objects.filter(user=user, parent=parent, is_deleted=False, name=candidate)
        if exclude_id:
            qs = qs.exclude(id=exclude_id)
        index += 1
    return candidate


def ensure_quota(user):
    quota, _ = StorageQuota.objects.get_or_create(
        user=user,
        defaults={"total_size": settings.DEFAULT_STORAGE_QUOTA_BYTES},
    )
    return quota


def ensure_capacity(user, size_delta):
    quota = ensure_quota(user)
    if size_delta > 0 and quota.used_size + size_delta > quota.total_size:
        raise ValueError("存储空间不足")
    return quota


def adjust_capacity(user, size_delta):
    quota = ensure_capacity(user, size_delta)
    quota.used_size = max(0, quota.used_size + size_delta)
    quota.save(update_fields=["used_size", "updated_at"])


def active_children(user, parent):
    return UserFile.objects.filter(user=user, parent=parent, is_deleted=False).select_related("stored_file")


def search_files(user, query):
    return (
        UserFile.objects.filter(user=user, is_deleted=False, name__icontains=query)
        .select_related("stored_file", "parent")
        .order_by("-is_folder", "name")
    )


def create_folder(user, name, parent_id=None):
    parent = normalize_parent(user, parent_id)
    name = unique_name(user, parent, name)
    return UserFile.objects.create(user=user, parent=parent, name=name, is_folder=True)


def _write_upload_to_temp(uploaded_file):
    tmp_dir = settings.MEDIA_ROOT / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{timezone.now().timestamp()}_{uploaded_file.name}"
    digest = hashlib.md5()
    size = 0
    with tmp_path.open("wb") as out:
        for chunk in uploaded_file.chunks():
            digest.update(chunk)
            size += len(chunk)
            out.write(chunk)
    return tmp_path, digest.hexdigest(), size


@transaction.atomic
def create_user_file_from_stored(user, stored_file, display_name, parent):
    name = unique_name(user, parent, display_name)
    adjust_capacity(user, stored_file.size)
    stored_file.ref_count += 1
    stored_file.save(update_fields=["ref_count"])
    return UserFile.objects.create(
        user=user,
        parent=parent,
        stored_file=stored_file,
        name=name,
        is_folder=False,
        file_size=stored_file.size,
        suffix=stored_file.suffix,
        mime_type=stored_file.mime_type,
    )


@transaction.atomic
def save_uploaded_file(user, uploaded_file, parent_id=None, provided_hash=""):
    parent = normalize_parent(user, parent_id)
    tmp_path, content_hash, size = _write_upload_to_temp(uploaded_file)
    if provided_hash and provided_hash != content_hash:
        tmp_path.unlink(missing_ok=True)
        raise ValueError("文件 MD5 校验失败")

    stored_file = StoredFile.objects.filter(owner=user, content_hash=content_hash, size=size).first()
    if not stored_file:
        mime_type = uploaded_file.content_type or mimetypes.guess_type(uploaded_file.name)[0] or ""
        stored_file = StoredFile(
            owner=user,
            content_hash=content_hash,
            original_name=uploaded_file.name,
            suffix=file_suffix(uploaded_file.name),
            mime_type=mime_type,
            size=size,
        )
        with tmp_path.open("rb") as fp:
            stored_file.file.save(uploaded_file.name, File(fp), save=False)
        stored_file.save()
        inspect_stored_file_if_needed(stored_file, force=True)
    else:
        inspect_stored_file_if_needed(stored_file)
    tmp_path.unlink(missing_ok=True)
    return create_user_file_from_stored(user, stored_file, uploaded_file.name, parent)


@transaction.atomic
def second_upload(user, filename, content_hash, parent_id=None):
    parent = normalize_parent(user, parent_id)
    stored_file = StoredFile.objects.filter(owner=user, content_hash=content_hash).order_by("-created_at").first()
    if not stored_file:
        return None
    inspect_stored_file_if_needed(stored_file)
    return create_user_file_from_stored(user, stored_file, filename or stored_file.original_name, parent)


def init_upload_session(user, filename, content_hash, file_size, chunk_size, chunk_count, parent_id=None):
    parent = normalize_parent(user, parent_id)
    ensure_capacity(user, int(file_size or 0))
    return UploadSession.objects.create(
        user=user,
        parent=parent,
        filename=filename,
        content_hash=content_hash,
        file_size=int(file_size or 0),
        chunk_size=int(chunk_size or 0),
        chunk_count=int(chunk_count or 0),
        status=UploadSession.STATUS_UPLOADING,
    )


def save_upload_chunk(session, part_number, chunk_file):
    part_number = int(part_number)
    if part_number < 1 or part_number > session.chunk_count:
        raise ValueError("分片序号非法")
    chunk_dir = session.chunk_dir()
    chunk_dir.mkdir(parents=True, exist_ok=True)
    part_path = chunk_dir / f"part-{part_number:06d}"
    with part_path.open("wb") as out:
        for chunk in chunk_file.chunks():
            out.write(chunk)
    received = set(session.received_chunks or [])
    received.add(part_number)
    session.received_chunks = sorted(received)
    session.status = UploadSession.STATUS_UPLOADING
    session.save(update_fields=["received_chunks", "status", "updated_at"])
    return session


@transaction.atomic
def merge_upload_session(session):
    if len(set(session.received_chunks or [])) != session.chunk_count:
        raise ValueError("分片尚未上传完成")

    chunk_dir = session.chunk_dir()
    tmp_dir = settings.MEDIA_ROOT / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    merged_path = tmp_dir / f"merged-{session.id}-{session.filename}"
    digest = hashlib.md5()
    size = 0
    with merged_path.open("wb") as merged:
        for part_number in range(1, session.chunk_count + 1):
            part_path = chunk_dir / f"part-{part_number:06d}"
            if not part_path.exists():
                raise ValueError(f"缺少第 {part_number} 个分片")
            with part_path.open("rb") as part:
                while True:
                    buf = part.read(1024 * 1024)
                    if not buf:
                        break
                    digest.update(buf)
                    size += len(buf)
                    merged.write(buf)

    content_hash = digest.hexdigest()
    if session.content_hash and content_hash != session.content_hash:
        session.status = UploadSession.STATUS_FAILED
        session.error_message = "合并后 MD5 校验失败"
        session.save(update_fields=["status", "error_message", "updated_at"])
        merged_path.unlink(missing_ok=True)
        raise ValueError(session.error_message)
    if session.file_size and size != session.file_size:
        merged_path.unlink(missing_ok=True)
        raise ValueError("合并后文件大小不一致")

    stored_file = StoredFile.objects.filter(owner=session.user, content_hash=content_hash, size=size).first()
    if not stored_file:
        stored_file = StoredFile(
            owner=session.user,
            content_hash=content_hash,
            original_name=session.filename,
            suffix=file_suffix(session.filename),
            mime_type=mimetypes.guess_type(session.filename)[0] or "",
            size=size,
        )
        with merged_path.open("rb") as fp:
            stored_file.file.save(session.filename, File(fp), save=False)
        stored_file.save()
        inspect_stored_file_if_needed(stored_file, force=True)
    else:
        inspect_stored_file_if_needed(stored_file)
    user_file = create_user_file_from_stored(session.user, stored_file, session.filename, session.parent)
    session.status = UploadSession.STATUS_MERGED
    session.stored_file = stored_file
    session.save(update_fields=["status", "stored_file", "updated_at"])
    merged_path.unlink(missing_ok=True)
    shutil.rmtree(chunk_dir, ignore_errors=True)
    return user_file


def rename_user_file(user_file, new_name):
    user_file.name = unique_name(user_file.user, user_file.parent, new_name, exclude_id=user_file.id)
    user_file.save(update_fields=["name", "updated_at"])
    return user_file


def soft_delete(user_files):
    now = timezone.now()
    for item in user_files:
        item.is_deleted = True
        item.deleted_at = now
        item.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
        if item.is_folder:
            soft_delete(item.children.filter(is_deleted=False))


def restore_file(item):
    item.name = unique_name(item.user, item.parent, item.name, exclude_id=item.id)
    item.is_deleted = False
    item.deleted_at = None
    item.save(update_fields=["name", "is_deleted", "deleted_at", "updated_at"])
    for child in item.children.all():
        restore_file(child)


def purge_file(item):
    if item.is_folder:
        for child in list(item.children.all()):
            purge_file(child)
    else:
        adjust_capacity(item.user, -item.file_size)
        if item.stored_file:
            stored = item.stored_file
            stored.ref_count = max(0, stored.ref_count - 1)
            stored.save(update_fields=["ref_count"])
    item.delete()


@transaction.atomic
def copy_item(item, target_parent):
    validate_target_parent(item, target_parent)
    if item.is_folder:
        copied = UserFile.objects.create(
            user=item.user,
            parent=target_parent,
            name=unique_name(item.user, target_parent, item.name),
            is_folder=True,
        )
        for child in item.children.filter(is_deleted=False):
            copy_item(child, copied)
        return copied
    return create_user_file_from_stored(item.user, item.stored_file, item.name, target_parent)


def is_descendant(folder, target_parent):
    current = target_parent
    while current:
        if current.id == folder.id:
            return True
        current = current.parent
    return False


def validate_target_parent(item, target_parent):
    if target_parent and target_parent.user_id != item.user_id:
        raise ValueError("目标文件夹不存在")
    if item.is_folder and target_parent and is_descendant(item, target_parent):
        raise ValueError("不能移动或复制到自身或子目录")


def move_item(item, target_parent):
    validate_target_parent(item, target_parent)
    item.parent = target_parent
    item.name = unique_name(item.user, target_parent, item.name, exclude_id=item.id)
    item.save(update_fields=["parent", "name", "updated_at"])
    return item
