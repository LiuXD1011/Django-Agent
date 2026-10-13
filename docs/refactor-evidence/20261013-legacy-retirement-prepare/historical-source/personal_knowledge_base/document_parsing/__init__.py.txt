from .legacy_office import LegacyOfficeParseError, convert_legacy_office
from .registry import IMAGE_TYPES, parse_document
from .spreadsheet import SpreadsheetParseError, parse_xls, parse_xlsx
from .types import ImageBlock, ParsedDocument, ParseWarning, TextBlock


def parser_capabilities(tenant=None) -> dict:
    import importlib.util
    from django.conf import settings
    from .legacy_office import _soffice_executable

    dependencies = {
        "PyMuPDF": importlib.util.find_spec("fitz") is not None,
        "Pillow": importlib.util.find_spec("PIL") is not None,
        "python-docx": importlib.util.find_spec("docx") is not None,
        "python-pptx": importlib.util.find_spec("pptx") is not None,
        "CairoSVG": importlib.util.find_spec("cairosvg") is not None,
        "openpyxl": importlib.util.find_spec("openpyxl") is not None,
        "xlrd": importlib.util.find_spec("xlrd") is not None,
        "LibreOffice": _soffice_executable() is not None,
    }
    vlm_available = bool(settings.LLM_USE_ENV_VLM and settings.LLM_VLM_API_KEY)
    if tenant is not None and not vlm_available:
        from personal_knowledge_base.model_types import model_type_aliases
        from personal_knowledge_base.models import ModelConfig
        vlm_available = ModelConfig.objects.filter(tenant=tenant, type__in=model_type_aliases("vlm"), status="active", deleted_at__isnull=True).exists()
    result = {
        "name": "builtin",
        "display_name": "Builtin Multimodal Python Parser",
        "enabled": all(dependencies.values()),
        "available": all(dependencies.values()),
        "formats": ["txt", "md", "markdown", "html", "htm", "json", "csv", "log", "py", "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", *sorted(IMAGE_TYPES)],
        "capabilities": ["text_extraction", "embedded_images", "scanned_pdf", "image_ocr", "image_caption", "remote_image_localization"],
        "dependencies": list(dependencies),
        "dependency_status": dependencies,
        "vlm_available": vlm_available,
    }
    if tenant is not None and vlm_available:
        from personal_knowledge_base.model_providers import vlm_access_state

        denied_state = vlm_access_state(tenant)
        if denied_state:
            result["vlm_available"] = False
            result["vlm_unavailable_reason"] = denied_state
    return result

__all__ = [
    "IMAGE_TYPES",
    "ImageBlock",
    "LegacyOfficeParseError",
    "ParsedDocument",
    "ParseWarning",
    "SpreadsheetParseError",
    "TextBlock",
    "convert_legacy_office",
    "parse_document",
    "parse_xls",
    "parse_xlsx",
    "parser_capabilities",
]
