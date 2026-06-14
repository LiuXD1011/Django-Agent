import base64
from pathlib import Path

from django.conf import settings
from openai import OpenAI

from .capabilities import get_vision_capability, vision_configured


class VisionExtractionError(Exception):
    def __init__(self, message, failure_code="vision_parse_failed"):
        super().__init__(message)
        self.failure_code = failure_code


def _data_url(mime, data):
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def image_file_to_data_url(file_path, mime):
    with open(file_path, "rb") as fp:
        return _data_url(mime or "image/png", fp.read())


def render_pdf_pages_to_data_urls(file_path, max_pages=None, dpi=None):
    import fitz

    max_pages = max(1, int(max_pages or getattr(settings, "VISION_MAX_PDF_PAGES", 5)))
    dpi = max(72, int(dpi or getattr(settings, "VISION_IMAGE_DPI", 144)))
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    urls = []
    with fitz.open(file_path) as doc:
        for index in range(min(max_pages, doc.page_count)):
            page = doc.load_page(index)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            urls.append(_data_url("image/png", pixmap.tobytes("png")))
    return urls


def extract_markdown_from_images(data_urls, source_name, prompt_hint=""):
    if not vision_configured():
        raise VisionExtractionError("未配置 VISION_API_KEY，无法使用视觉模型解析。", "vision_not_configured")
    capability = get_vision_capability()
    if not capability.image:
        raise VisionExtractionError("当前 VISION_MODEL 不支持图片输入。", "vision_not_supported")
    if not data_urls:
        raise VisionExtractionError("没有可发送给视觉模型的页面或图片。", "empty_vision_input")

    content = [
        {
            "type": "text",
            "text": (
                "请从这些文档页面或图片中抽取可用于知识库检索的正文内容，使用 Markdown 输出。"
                "保留标题、列表、表格的主要文字信息。不要编造看不见的内容。"
                f"\n文件名：{source_name}\n{prompt_hint or ''}"
            ),
        }
    ]
    for url in data_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})

    client = OpenAI(api_key=settings.VISION_API_KEY, base_url=settings.VISION_BASE_URL, timeout=60)
    response = client.chat.completions.create(
        model=settings.VISION_MODEL,
        messages=[{"role": "user", "content": content}],
        max_tokens=getattr(settings, "VISION_PARSE_MAX_TOKENS", 2048),
    )
    text = response.choices[0].message.content or ""
    if not text.strip():
        raise VisionExtractionError("视觉模型没有返回可入库文本。", "empty_text")
    return text


def extract_image_file(file_path, mime, source_name):
    return extract_markdown_from_images([image_file_to_data_url(file_path, mime)], source_name)


def extract_pdf_file_as_images(file_path, source_name):
    urls = render_pdf_pages_to_data_urls(
        file_path,
        max_pages=getattr(settings, "VISION_MAX_PDF_PAGES", 5),
        dpi=getattr(settings, "VISION_IMAGE_DPI", 144),
    )
    return extract_markdown_from_images(urls, source_name, prompt_hint="这是 PDF 渲染后的前几页。")


def suffix_for_temp(profile, fallback_name):
    suffix = profile.suffix or Path(fallback_name or "").suffix.lower()
    return suffix if suffix else ".bin"
