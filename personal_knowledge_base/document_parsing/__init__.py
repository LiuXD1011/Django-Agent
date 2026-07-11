from .registry import IMAGE_TYPES, parse_document
from .types import ImageBlock, ParsedDocument, ParseWarning, TextBlock


def parser_capabilities(tenant=None) -> dict:
    import importlib.util
    from django.conf import settings

    dependencies = {
        "PyMuPDF": importlib.util.find_spec("fitz") is not None,
        "Pillow": importlib.util.find_spec("PIL") is not None,
        "python-docx": importlib.util.find_spec("docx") is not None,
        "python-pptx": importlib.util.find_spec("pptx") is not None,
        "CairoSVG": importlib.util.find_spec("cairosvg") is not None,
    }
    vlm_available = bool(settings.LLM_USE_ENV_VLM and settings.LLM_VLM_API_KEY)
    if tenant is not None and not vlm_available:
        from personal_knowledge_base.model_types import model_type_aliases
        from personal_knowledge_base.models import ModelConfig
        vlm_available = ModelConfig.objects.filter(tenant=tenant, type__in=model_type_aliases("vlm"), status="active", deleted_at__isnull=True).exists()
    return {
        "name": "builtin",
        "display_name": "Builtin Multimodal Python Parser",
        "enabled": all(dependencies.values()),
        "available": all(dependencies.values()),
        "formats": ["txt", "md", "markdown", "html", "htm", "json", "csv", "log", "py", "pdf", "docx", "pptx", *sorted(IMAGE_TYPES)],
        "capabilities": ["text_extraction", "embedded_images", "scanned_pdf", "image_ocr", "image_caption", "remote_image_localization"],
        "dependencies": list(dependencies),
        "dependency_status": dependencies,
        "vlm_available": vlm_available,
    }

__all__ = ["IMAGE_TYPES", "ImageBlock", "ParsedDocument", "ParseWarning", "TextBlock", "parse_document", "parser_capabilities"]
