import gzip
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path, PurePosixPath

from django.conf import settings


class DocumentConversionError(Exception):
    def __init__(self, message, failure_code="conversion_failed", metadata=None):
        super().__init__(message)
        self.failure_code = failure_code
        self.metadata = metadata or {}


class ArchiveExtractionError(Exception):
    def __init__(self, message, failure_code="archive_no_supported_files", metadata=None):
        super().__init__(message)
        self.failure_code = failure_code
        self.metadata = metadata or {}


@dataclass
class ConvertedDocument:
    data: bytes
    source_family: str
    target_format: str
    tool: str
    seconds: float
    metadata: dict = field(default_factory=dict)

    def as_metadata(self):
        return {
            "source_family": self.source_family,
            "target_format": self.target_format,
            "tool": self.tool,
            "conversion_seconds": self.seconds,
            **(self.metadata or {}),
        }


@dataclass
class ArchiveMember:
    name: str
    data: bytes
    metadata: dict = field(default_factory=dict)


def _setting_int(name, default):
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _libreoffice_binary():
    configured = getattr(settings, "LIBREOFFICE_BINARY", "soffice") or "soffice"
    if Path(configured).is_absolute():
        return configured if Path(configured).exists() else ""
    return shutil.which(configured) or ""


def convert_office_to_pdf(file_bytes, source_name, source_family="legacy_office"):
    binary = _libreoffice_binary()
    if not binary:
        raise DocumentConversionError(
            "未找到 LibreOffice，无法自动转换 Office 文档。请安装 LibreOffice，或手动转为 PDF/DOCX/PPTX 后再入库。",
            failure_code="needs_conversion",
            metadata={"tool": getattr(settings, "LIBREOFFICE_BINARY", "soffice")},
        )

    max_bytes = _setting_int("DOCUMENT_CONVERSION_MAX_MB", 50) * 1024 * 1024
    if max_bytes > 0 and len(file_bytes or b"") > max_bytes:
        raise DocumentConversionError(
            "Office 文件超过自动转换大小限制。",
            failure_code="conversion_failed",
            metadata={"max_bytes": max_bytes, "size_bytes": len(file_bytes or b"")},
        )

    suffix = Path(source_name or "").suffix.lower() or ".doc"
    started = time.perf_counter()
    timeout = _setting_int("DOCUMENT_CONVERSION_TIMEOUT_SECONDS", 60)
    with tempfile.TemporaryDirectory(prefix="doc-convert-") as workdir:
        workdir_path = Path(workdir)
        input_path = workdir_path / f"input{suffix}"
        output_dir = workdir_path / "out"
        output_dir.mkdir(parents=True, exist_ok=True)
        input_path.write_bytes(file_bytes or b"")
        cmd = [
            binary,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(input_path),
        ]
        try:
            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=max(1, timeout),
            )
        except subprocess.TimeoutExpired as exc:
            raise DocumentConversionError(
                "LibreOffice 转换超时。",
                failure_code="conversion_failed",
                metadata={"timeout_seconds": timeout},
            ) from exc
        except OSError as exc:
            raise DocumentConversionError(
                f"LibreOffice 转换启动失败：{exc}",
                failure_code="conversion_failed",
            ) from exc

        pdf_candidates = sorted(output_dir.glob("*.pdf"))
        if completed.returncode != 0 or not pdf_candidates:
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise DocumentConversionError(
                f"LibreOffice 转换失败：{stderr or '未生成 PDF'}",
                failure_code="conversion_failed",
                metadata={
                    "returncode": completed.returncode,
                    "stdout": (completed.stdout or "")[-1000:],
                    "stderr": (completed.stderr or "")[-1000:],
                },
            )
        data = pdf_candidates[0].read_bytes()
        return ConvertedDocument(
            data=data,
            source_family=source_family or "office",
            target_format="pdf",
            tool=Path(binary).name,
            seconds=round(time.perf_counter() - started, 4),
            metadata={"source_name": source_name or "", "output_name": pdf_candidates[0].name},
        )


def convert_legacy_office_to_pdf(file_bytes, source_name):
    return convert_office_to_pdf(file_bytes, source_name, source_family="legacy_office")


def _archive_limits():
    return {
        "max_files": _setting_int("ARCHIVE_MAX_FILES", 20),
        "max_total_bytes": _setting_int("ARCHIVE_MAX_TOTAL_BYTES", 20 * 1024 * 1024),
        "max_single_file_bytes": _setting_int("ARCHIVE_MAX_SINGLE_FILE_BYTES", 10 * 1024 * 1024),
    }


def _ensure_archive_size_limits(member_count, total_bytes, single_size=0):
    limits = _archive_limits()
    if limits["max_files"] > 0 and member_count > limits["max_files"]:
        raise ArchiveExtractionError(
            "压缩包内文件数量超过限制。",
            failure_code="archive_limit_exceeded",
            metadata={**limits, "member_count": member_count},
        )
    if limits["max_total_bytes"] > 0 and total_bytes > limits["max_total_bytes"]:
        raise ArchiveExtractionError(
            "压缩包解压后总大小超过限制。",
            failure_code="archive_limit_exceeded",
            metadata={**limits, "total_bytes": total_bytes},
        )
    if limits["max_single_file_bytes"] > 0 and single_size > limits["max_single_file_bytes"]:
        raise ArchiveExtractionError(
            "压缩包内单文件大小超过限制。",
            failure_code="archive_limit_exceeded",
            metadata={**limits, "single_file_bytes": single_size},
        )


def _safe_zip_name(name):
    normalized = (name or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        return ""
    return normalized


def _inner_name_for_gzip(source_name):
    path = Path(source_name or "archive.gz")
    if path.suffix.lower() in {".gz", ".gzip"} and path.stem:
        return path.stem
    return f"{path.name}.txt"


def extract_archive_members(file_bytes, source_name):
    suffix = Path(source_name or "").suffix.lower()
    if suffix not in {".zip", ".gz", ".gzip"}:
        raise ArchiveExtractionError(
            "当前压缩格式暂不支持自动解包。",
            failure_code="archive_unsupported",
            metadata={"suffix": suffix},
        )

    if suffix in {".gz", ".gzip"}:
        try:
            data = gzip.decompress(file_bytes or b"")
        except OSError as exc:
            raise ArchiveExtractionError(
                f"Gzip 解压失败：{exc}",
                failure_code="parser_exception",
            ) from exc
        _ensure_archive_size_limits(1, len(data), len(data))
        if not data:
            raise ArchiveExtractionError("Gzip 解压后为空。", failure_code="archive_no_supported_files")
        return [
            ArchiveMember(
                name=_inner_name_for_gzip(source_name),
                data=data,
                metadata={"archive_type": "gzip", "source_archive": source_name or ""},
            )
        ]

    try:
        with zipfile.ZipFile(BytesIO(file_bytes or b"")) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            safe_infos = []
            total_size = 0
            for info in infos:
                safe_name = _safe_zip_name(info.filename)
                if not safe_name:
                    raise ArchiveExtractionError(
                        "压缩包包含不安全路径。",
                        failure_code="archive_limit_exceeded",
                        metadata={"filename": info.filename},
                    )
                total_size += int(info.file_size or 0)
                _ensure_archive_size_limits(len(safe_infos) + 1, total_size, int(info.file_size or 0))
                safe_infos.append((info, safe_name))
            members = []
            for index, (info, safe_name) in enumerate(safe_infos):
                with archive.open(info) as fp:
                    data = fp.read()
                if not data:
                    continue
                members.append(
                    ArchiveMember(
                        name=safe_name,
                        data=data,
                        metadata={
                            "archive_type": "zip",
                            "source_archive": source_name or "",
                            "member_index": index,
                            "compressed_size": int(info.compress_size or 0),
                            "file_size": int(info.file_size or 0),
                        },
                    )
                )
    except ArchiveExtractionError:
        raise
    except zipfile.BadZipFile as exc:
        raise ArchiveExtractionError(
            f"Zip 解包失败：{exc}",
            failure_code="parser_exception",
        ) from exc

    if not members:
        raise ArchiveExtractionError("压缩包中没有可读取文件。", failure_code="archive_no_supported_files")
    return members
