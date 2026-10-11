import io
import mimetypes



MIN_IMAGE_BYTES = 512
MIN_IMAGE_DIMENSION = 64
VLM_MAX_DIMENSION = 2048


class InvalidImageError(ValueError):
    pass


class ImageTooSmallError(InvalidImageError):
    pass


def rasterize_svg(data: bytes) -> bytes:
    try:
        from cairosvg.surface import PNGSurface
        from cairosvg.url import fetch
    except ImportError as exc:
        raise InvalidImageError("SVG rasterization dependency is unavailable") from exc
    try:
        def embedded_resource(url, resource_type):
            if not url.startswith("data:image/"):
                raise InvalidImageError("external SVG resources are unavailable")
            return fetch(url, resource_type)

        # Explicit fetch policy also covers CairoSVG versions before safe_fetch.
        return PNGSurface.convert(bytestring=data, unsafe=False, url_fetcher=embedded_resource)
    except Exception as exc:
        raise InvalidImageError(f"invalid SVG image: {exc}") from exc


def inspect_image(data: bytes, mime_type: str = "") -> tuple[int, int, str]:
    from PIL import Image, UnidentifiedImageError
    source = rasterize_svg(data) if mime_type == "image/svg+xml" else data
    try:
        with Image.open(io.BytesIO(source)) as image:
            width, height = image.size
            detected = Image.MIME.get(image.format) or mime_type or "application/octet-stream"
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError("invalid image data") from exc
    if len(data) < MIN_IMAGE_BYTES or width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
        raise ImageTooSmallError("image is below the minimum size")
    return width, height, detected


def normalize_for_vlm(data: bytes, mime_type: str = "") -> tuple[bytes, str, int, int]:
    from PIL import Image, ImageOps, UnidentifiedImageError
    source = rasterize_svg(data) if mime_type == "image/svg+xml" else data
    try:
        with Image.open(io.BytesIO(source)) as opened:
            image = ImageOps.exif_transpose(opened)
            if getattr(image, "is_animated", False):
                image.seek(0)
            image = image.convert("RGB")
            image.thumbnail((VLM_MAX_DIMENSION, VLM_MAX_DIMENSION), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
            return output.getvalue(), "image/jpeg", image.width, image.height
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError("invalid image data") from exc


def guess_image_mime(filename: str, fallback: str = "") -> str:
    return mimetypes.guess_type(filename)[0] or fallback or "application/octet-stream"
