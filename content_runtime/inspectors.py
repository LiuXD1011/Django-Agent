import mimetypes
from dataclasses import asdict, dataclass, field
from pathlib import Path

from django.utils import timezone


TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".jsonl",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".css",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".java",
    ".f",
    ".for",
    ".f90",
    ".go",
    ".rs",
    ".sh",
    ".bash",
    ".zsh",
    ".bat",
    ".ps1",
    ".ini",
    ".conf",
    ".cfg",
    ".toml",
    ".properties",
    ".gradle",
    ".sql",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
}
HTML_SUFFIXES = {".html", ".htm"}
RTF_SUFFIXES = {".rtf"}
PDF_SUFFIXES = {".pdf"}
DOCX_SUFFIXES = {".docx"}
PPTX_SUFFIXES = {".pptx"}
XLSX_SUFFIXES = {".xlsx"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
LEGACY_OFFICE_SUFFIXES = {".doc", ".ppt", ".xls"}
ARCHIVE_SUFFIXES = {".zip", ".gz", ".gzip", ".tar", ".tgz", ".bz2", ".7z", ".rar", ".xz"}
MEDIA_SUFFIXES = {".mp3", ".mp4", ".wav", ".avi", ".mov", ".webm", ".mkv"}
BINARY_SUFFIXES = {".exe", ".dll", ".so", ".db", ".sqlite", ".bin", ".dat", ".swf"}


@dataclass
class FileProfile:
    suffix: str = ""
    mime: str = ""
    family: str = "unknown"
    parser_mode: str = "unsupported"
    failure_code: str = ""
    reason: str = ""
    is_binary: bool = False
    sample_size: int = 0
    printable_ratio: float | None = None
    magic: str = ""
    metadata: dict = field(default_factory=dict)

    def as_metadata(self):
        data = asdict(self)
        data["metadata"] = dict(self.metadata or {})
        return data


def _starts_with(sample, prefix):
    return len(sample) >= len(prefix) and sample[: len(prefix)] == prefix


def sniff_mime(sample, fallback=""):
    if _starts_with(sample, b"%PDF-"):
        return "application/pdf", "pdf"
    if _starts_with(sample, b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if _starts_with(sample, b"\xff\xd8\xff"):
        return "image/jpeg", "jpeg"
    if _starts_with(sample, b"GIF8"):
        return "image/gif", "gif"
    if _starts_with(sample, b"BM"):
        return "image/bmp", "bmp"
    if _starts_with(sample, b"RIFF") and sample[8:12] == b"WEBP":
        return "image/webp", "webp"
    if _starts_with(sample, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "application/x-ole-storage", "ole"
    if _starts_with(sample, b"PK\x03\x04"):
        return fallback or "application/zip", "zip"
    return fallback or "application/octet-stream", ""


def binary_ratio(sample):
    if not sample:
        return False, None
    if b"\x00" in sample:
        return True, 0.0
    printable = 0
    for byte in sample:
        if byte in (9, 10, 13) or 32 <= byte <= 126 or byte >= 128:
            printable += 1
    ratio = printable / len(sample)
    return ratio < 0.70, ratio


def family_for(suffix, mime, magic, is_binary):
    if suffix in TEXT_SUFFIXES:
        return "text"
    if suffix in HTML_SUFFIXES:
        return "html"
    if suffix in RTF_SUFFIXES:
        return "rtf"
    if suffix in PDF_SUFFIXES or mime == "application/pdf":
        return "pdf"
    if suffix in DOCX_SUFFIXES:
        return "docx"
    if suffix in PPTX_SUFFIXES:
        return "pptx"
    if suffix in XLSX_SUFFIXES:
        return "xlsx"
    if suffix in IMAGE_SUFFIXES or mime.startswith("image/"):
        return "image"
    if suffix in LEGACY_OFFICE_SUFFIXES or magic == "ole":
        return "legacy_office"
    if suffix in ARCHIVE_SUFFIXES:
        return "archive"
    if suffix in MEDIA_SUFFIXES or mime.split("/", 1)[0] in {"audio", "video"}:
        return "media"
    if suffix in BINARY_SUFFIXES or is_binary:
        return "binary"
    return "unknown"


def route_for_family(family):
    if family in {"text", "html", "pdf", "docx", "pptx"}:
        return "loader", "", ""
    if family == "xlsx":
        return "extractor", "", ""
    if family == "rtf":
        return "extractor", "", ""
    if family == "image":
        return "vision", "needs_vision", "图片需要视觉模型抽取文本。"
    if family == "legacy_office":
        return "convert", "needs_conversion", "旧版 Office 格式需要 LibreOffice 转换后入库。"
    if family == "archive":
        return "archive", "archive_unsupported", "仅支持安全解包 zip/gz 后入库。"
    if family == "media":
        return "unsupported", "media_unsupported", "音视频文件暂不支持入库。"
    if family == "binary":
        return "unsupported", "binary_unsupported", "二进制文件不能作为文档解析。"
    return "unsupported", "unsupported_format", "当前文件格式暂不支持。"


def inspect_bytes(filename, stored_mime="", sample=b""):
    suffix = Path(filename or "").suffix.lower()
    guessed = stored_mime or mimetypes.guess_type(filename or "")[0] or ""
    mime, magic = sniff_mime(sample, guessed)
    is_binary, printable_ratio = binary_ratio(sample)
    family = family_for(suffix, mime, magic, is_binary)
    parser_mode, failure_code, reason = route_for_family(family)
    return FileProfile(
        suffix=suffix,
        mime=mime,
        family=family,
        parser_mode=parser_mode,
        failure_code=failure_code,
        reason=reason,
        is_binary=bool(is_binary or family in {"legacy_office", "archive", "media", "binary"}),
        sample_size=len(sample),
        printable_ratio=printable_ratio,
        magic=magic,
        metadata={"filename": filename or ""},
    )


def inspect_stored_file(stored_file, save=True, sample_bytes=8192):
    sample = b""
    try:
        with stored_file.file.open("rb") as fp:
            sample = fp.read(sample_bytes)
    except Exception:
        sample = b""
    profile = inspect_bytes(stored_file.original_name, stored_file.mime_type, sample)
    if save:
        stored_file.detected_mime = profile.mime[:128]
        stored_file.content_family = profile.family[:32]
        stored_file.is_binary = profile.is_binary
        stored_file.inspection_metadata = profile.as_metadata()
        stored_file.last_inspected_at = timezone.now()
        stored_file.save(
            update_fields=[
                "detected_mime",
                "content_family",
                "is_binary",
                "inspection_metadata",
                "last_inspected_at",
            ]
        )
    return profile
