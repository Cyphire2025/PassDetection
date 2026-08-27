"""Strict upload validation for passport images."""

from __future__ import annotations

import io
import re
import socket
import struct
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config.settings import get_settings
from app.domain.exceptions.exceptions import ImageValidationError

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_SUPPORTED_SOURCE_FORMATS = frozenset(
    {
        "AVIF",
        "BMP",
        "HEIC",
        "HEIF",
        "JPEG",
        "PNG",
        "TIFF",
        "WEBP",
    }
)
_SUPPORTED_FORMAT_MESSAGE = (
    "Unsupported image format. Please upload a JPEG/JPG, PNG, WebP, "
    "HEIC/HEIF, AVIF, BMP, or TIFF image"
)


def _register_mobile_image_decoders() -> None:
    """Register optional libheif-backed Pillow decoders when installed."""

    try:
        import pillow_heif
    except ImportError:
        return

    pillow_heif.register_heif_opener()
    register_avif = getattr(pillow_heif, "register_avif_opener", None)
    if register_avif is not None:
        register_avif()


_register_mobile_image_decoders()


@dataclass(frozen=True)
class ValidatedUpload:
    content: bytes
    content_type: str
    filename: str
    width: int
    height: int
    format: str


class MalwareScanner(Protocol):
    def scan(self, content: bytes) -> None: ...


class MalwareScannerUnavailableError(ImageValidationError):
    """Raised when the configured scanning boundary cannot make a decision."""


class MalwareScanRejectedError(ImageValidationError):
    """Raised when bytes are malicious or the scanner response is untrusted."""


class MalwareScannerConfigurationError(RuntimeError):
    """Raised before ingestion when a non-development scanner boundary is unsafe."""


class DocumentIngestionDisabledError(ImageValidationError):
    """Raised when this deployment deliberately does not accept documents."""


class DisabledMalwareScanner:
    """Explicit development-only scanner used by deterministic local tests."""

    def scan(self, content: bytes) -> None:
        return None


class DisabledDocumentIngestionScanner:
    """Fail-closed boundary for deliberately document-free deployments."""

    def scan(self, content: bytes) -> None:
        raise DocumentIngestionDisabledError("Document ingestion is disabled")


class ClamAVMalwareScanner:
    """ClamAV INSTREAM scanner for production upload malware checks."""

    def __init__(self, *, host: str, port: int, timeout_seconds: float) -> None:
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds

    def scan(self, content: bytes) -> None:
        deadline = time.monotonic() + self._timeout_seconds
        try:
            with socket.create_connection(
                (self._host, self._port), timeout=self._timeout_seconds
            ) as sock:
                self._set_remaining_timeout(sock, deadline)
                sock.sendall(b"zINSTREAM\0")
                for offset in range(0, len(content), 8192):
                    chunk = content[offset : offset + 8192]
                    self._set_remaining_timeout(sock, deadline)
                    sock.sendall(struct.pack("!I", len(chunk)) + chunk)
                self._set_remaining_timeout(sock, deadline)
                sock.sendall(struct.pack("!I", 0))
                self._set_remaining_timeout(sock, deadline)
                response = sock.recv(4096).decode("utf-8", errors="replace")
        except (OSError, TimeoutError) as exc:
            raise MalwareScannerUnavailableError(
                "Malware scanner is unavailable. Please try again later"
            ) from exc

        if "FOUND" in response:
            raise MalwareScanRejectedError("Uploaded file failed security scanning")
        if "OK" not in response:
            raise MalwareScanRejectedError("Malware scanner returned an invalid response")

    def healthcheck(self) -> None:
        """Require a valid ClamAV PONG before a production process becomes ready."""

        try:
            with socket.create_connection(
                (self._host, self._port), timeout=self._timeout_seconds
            ) as sock:
                sock.settimeout(self._timeout_seconds)
                sock.sendall(b"zPING\0")
                response = sock.recv(64).decode("ascii", errors="replace").strip("\x00\r\n ")
        except OSError as exc:
            raise MalwareScannerConfigurationError(
                "Configured malware scanner is unavailable"
            ) from exc
        if response != "PONG":
            raise MalwareScannerConfigurationError(
                "Configured malware scanner failed its health check"
            )

    @staticmethod
    def _set_remaining_timeout(sock: socket.socket, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Malware scan exceeded its total timeout")
        sock.settimeout(remaining)


def malware_scanner_from_settings(settings: Any | None = None) -> MalwareScanner:
    """Return the one configured scanner used by every untrusted upload path."""

    active_settings = settings or get_settings()
    if not bool(getattr(active_settings, "untrusted_document_ingestion_enabled", True)):
        return DisabledDocumentIngestionScanner()
    if not bool(getattr(active_settings, "malware_scanner_enabled", False)):
        if not bool(getattr(active_settings, "is_development", False)):
            raise MalwareScannerConfigurationError(
                "Untrusted document ingestion requires a malware scanner outside development"
            )
        return DisabledMalwareScanner()
    return ClamAVMalwareScanner(
        host=str(getattr(active_settings, "malware_scanner_host", "localhost")),
        port=int(getattr(active_settings, "malware_scanner_port", 3310)),
        timeout_seconds=float(getattr(active_settings, "malware_scanner_timeout_seconds", 2.0)),
    )


def assert_malware_scanner_ready(settings: Any | None = None) -> None:
    """Fail startup when an enabled non-development ingestion lane is unscanned."""

    active_settings = settings or get_settings()
    if not bool(getattr(active_settings, "untrusted_document_ingestion_enabled", True)):
        return
    scanner = malware_scanner_from_settings(active_settings)
    if bool(getattr(active_settings, "is_development", False)):
        return
    if not isinstance(scanner, ClamAVMalwareScanner):
        raise MalwareScannerConfigurationError(
            "Untrusted document ingestion requires a functioning malware scanner"
        )
    scanner.healthcheck()


class UploadValidator:
    def __init__(self, scanner: MalwareScanner | None = None) -> None:
        self._settings = get_settings()
        self._scanner = scanner or self._default_scanner()

    def validate(
        self, *, content: bytes, filename: str | None, declared_content_type: str | None
    ) -> ValidatedUpload:
        if not content:
            raise ImageValidationError("Uploaded file is empty")

        max_size = self._settings.upload_max_file_size_bytes
        if len(content) > max_size:
            raise ImageValidationError(
                f"Image is too large. Maximum allowed size is {max_size // (1024 * 1024)} MB"
            )

        # Scan the original bytes, but never persist them. The decoded pixels
        # are re-encoded below so metadata, polyglot trailers, misleading
        # extensions, and unsupported provider MIME types cannot reach storage
        # or OCR.
        self._scanner.scan(content)

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    image_format = (image.format or "").upper()
                    if image_format not in _SUPPORTED_SOURCE_FORMATS:
                        raise ImageValidationError(_SUPPORTED_FORMAT_MESSAGE)

                    width, height = image.size
                    if width <= 0 or height <= 0:
                        raise ImageValidationError("Image dimensions are invalid")
                    if width * height > self._settings.upload_max_pixels:
                        raise ImageValidationError(
                            "Image resolution is too large. Please upload a smaller image"
                        )

                    # load() forces the decoder to validate the complete image,
                    # rather than accepting only a plausible header.
                    image.seek(0)
                    image.load()
                    canonical_image = self._to_rgb(ImageOps.exif_transpose(image))
                    try:
                        canonical_content = self._encode_jpeg(canonical_image)
                    finally:
                        canonical_image.close()
        except (
            UnidentifiedImageError,
            OSError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise ImageValidationError("Uploaded file is not a readable image") from exc

        safe_name = self._safe_filename(filename, ".jpg")
        return ValidatedUpload(
            content=canonical_content,
            content_type="image/jpeg",
            filename=safe_name,
            width=width,
            height=height,
            format="JPEG",
        )

    @staticmethod
    def _to_rgb(image: Image.Image) -> Image.Image:
        if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", rgba.size, "white")
            composited = Image.alpha_composite(background, rgba).convert("RGB")
            rgba.close()
            background.close()
            return composited
        return image.convert("RGB")

    @staticmethod
    def _encode_jpeg(image: Image.Image) -> bytes:
        output = io.BytesIO()
        image.save(
            output,
            format="JPEG",
            quality=94,
            optimize=True,
            progressive=True,
        )
        return output.getvalue()

    def _safe_filename(self, filename: str | None, extension: str) -> str:
        original = Path(filename or "passport").name
        stem = Path(original).stem or "passport"
        stem = _SAFE_FILENAME.sub("-", stem).strip(".-_") or "passport"
        return f"{stem[:80]}{extension}"

    def _default_scanner(self) -> MalwareScanner:
        return malware_scanner_from_settings(self._settings)
