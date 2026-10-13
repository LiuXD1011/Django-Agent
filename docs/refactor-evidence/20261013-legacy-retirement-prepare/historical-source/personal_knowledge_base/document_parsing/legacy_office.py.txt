import io
import shutil
import subprocess
import tempfile
from pathlib import Path


LEGACY_TARGETS = {"doc": "docx", "ppt": "pptx"}


class LegacyOfficeParseError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _soffice_executable() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def _contains_encryption_message(*outputs: bytes | str | None) -> bool:
    message = "\n".join(
        output.decode("utf-8", errors="ignore") if isinstance(output, bytes) else output
        for output in outputs
        if output
    ).lower()
    return "password" in message or "encrypted" in message


def _is_encrypted_error(error: subprocess.CalledProcessError) -> bool:
    return _contains_encryption_message(error.stdout, error.stderr)


def _is_encrypted_payload(data: bytes) -> bool:
    try:
        import msoffcrypto

        return bool(msoffcrypto.OfficeFile(io.BytesIO(data)).is_encrypted())
    except Exception:
        return False


def convert_legacy_office(name: str, data: bytes, timeout: int = 30) -> tuple[str, bytes]:
    source_format = Path(name or "").suffix.lower().lstrip(".")
    target_format = LEGACY_TARGETS.get(source_format)
    if not target_format:
        raise LegacyOfficeParseError("legacy_office_unsupported_format", "only .doc and .ppt files can be converted")

    if _is_encrypted_payload(data):
        raise LegacyOfficeParseError("legacy_office_encrypted", "encrypted legacy Office files are not supported")

    soffice = _soffice_executable()
    if not soffice:
        raise LegacyOfficeParseError(
            "legacy_office_converter_unavailable",
            "LibreOffice or soffice is required to parse legacy Office files",
        )

    source_name = Path(name).name or f"source.{source_format}"
    with tempfile.TemporaryDirectory(prefix="pkb-office-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        input_path = temporary_path / source_name
        output_dir = temporary_path / "output"
        output_dir.mkdir()
        input_path.write_bytes(data)
        command = [soffice, "--headless", "--convert-to", target_format, "--outdir", str(output_dir), str(input_path)]
        try:
            completed_process = subprocess.run(command, check=True, timeout=timeout, capture_output=True)
        except subprocess.TimeoutExpired as exc:
            raise LegacyOfficeParseError("legacy_office_conversion_timeout", "legacy Office conversion timed out") from exc
        except subprocess.CalledProcessError as exc:
            if _is_encrypted_error(exc):
                raise LegacyOfficeParseError("legacy_office_encrypted", "encrypted legacy Office files are not supported") from exc
            raise LegacyOfficeParseError("legacy_office_conversion_failed", "legacy Office conversion failed") from exc
        except OSError as exc:
            raise LegacyOfficeParseError(
                "legacy_office_converter_unavailable",
                "LibreOffice or soffice is required to parse legacy Office files",
            ) from exc

        output_path = output_dir / f"{input_path.stem}.{target_format}"
        if not output_path.is_file() or not output_path.stat().st_size:
            if _contains_encryption_message(completed_process.stdout, completed_process.stderr):
                raise LegacyOfficeParseError("legacy_office_encrypted", "encrypted legacy Office files are not supported")
            raise LegacyOfficeParseError(
                "legacy_office_conversion_output_missing",
                "legacy Office conversion produced no output file",
            )
        return f"{Path(source_name).stem}.{target_format}", output_path.read_bytes()
