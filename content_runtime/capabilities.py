from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class ModelCapability:
    text: bool = True
    image: bool = False
    pdf_file: bool = False
    pdf_as_images: bool = False
    max_file_mb: int = 0


def vision_configured():
    return bool(getattr(settings, "VISION_API_KEY", ""))


def get_vision_capability(model_name=None):
    model = (model_name or getattr(settings, "VISION_MODEL", "") or "").lower()
    if not vision_configured():
        return ModelCapability(text=True)
    if "qwen" in model or "vl" in model or "gpt-4o" in model or "vision" in model:
        return ModelCapability(text=True, image=True, pdf_file=False, pdf_as_images=True, max_file_mb=10)
    return ModelCapability(text=True)

