"""Strict upload validation for passport images."""

from __future__ import annotations

import io
import re
import socket
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image, UnidentifiedImageError

from app.core.config.settings import get_settings
from app.domain.exceptions.exceptions import ImageValidationError

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


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


class DisabledMalwareScanner:
    """Explicit local/demo scanner used only when AV is not configured."""

    def scan(self, content: bytes) -> None:
        return None


class ClamAVMalwareScanner:
    """ClamAV INSTREAM scanner for production upload malware checks."""

    def __init__(self, *, host: str, port: int, timeout_seconds: float) -> None:
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds

    def scan(self, content: bytes) -> None:
        try:
            with socket.create_connection((self._host, self._port), timeout=self._timeout_seconds) as sock:
                sock.settimeout(self._timeout_seconds)
                sock.sendall(b"zINSTREAM\0")
                for offset in range(0, len(content), 8192):
                    chunk = content[offset:offset + 8192]
                    sock.sendall(struct.pack("!I", len(chunk)) + chunk)
                sock.sendall(struct.pack("!I", 0))
                response = sock.recv(4096).decode("utf-8", errors="replace")
        except OSError as exc:
            raise ImageValidationError("Malware scanner is unavailable. Please try again later") from exc

        if "FOUND" in response:
            raise ImageValidationError("Uploaded file failed security scanning")
        if "OK" not in response:
            raise ImageValidationError("Malware scanner returned an invalid response")


class UploadValidator:
    _magic_types = (
        (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
        (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
        (b"RIFF", "image/webp", ".webp"),
    )

    _pil_types = {
        "JPEG": ("image/jpeg", ".jpg"),
        "PNG": ("image/png", ".png"),
        "WEBP": ("image/webp", ".webp"),
    }

    def __init__(self, scanner: MalwareScanner | None = None) -> None:
        self._settings = get_settings()
        self._scanner = scanner or self._default_scanner()

    def validate(self, *, content: bytes, filename: str | None, declared_content_type: str | None) -> ValidatedUpload:
        if not content:
            raise ImageValidationError("Uploaded file is empty")

        max_size = self._settings.upload_max_file_size_bytes
        if len(content) > max_size:
            raise ImageValidationError(f"Image is too large. Maximum allowed size is {max_size // (1024 * 1024)} MB")

        magic_content_type, magic_ext = self._detect_magic(content)
        if magic_content_type is None:
            raise ImageValidationError("Unsupported image format. Please upload a JPEG, PNG, or WebP image")

        if magic_content_type == "image/webp" and content[8:12] != b"WEBP":
            raise ImageValidationError("Invalid WebP image signature")

        self._scanner.scan(content)

        try:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image_format = image.format or ""
                width, height = image.size
        except (
            UnidentifiedImageError,
            OSError,
            Image.DecompressionBombError,
        ) as exc:
            raise ImageValidationError("Uploaded file is not a readable image") from exc

        if image_format not in self._pil_types:
            raise ImageValidationError("Unsupported image format. Please upload a JPEG, PNG, or WebP image")

        pil_content_type, pil_ext = self._pil_types[image_format]
        if pil_content_type != magic_content_type:
            raise ImageValidationError("Image header does not match the encoded image format")

        if width <= 0 or height <= 0:
            raise ImageValidationError("Image dimensions are invalid")

        if width * height > self._settings.upload_max_pixels:
            raise ImageValidationError("Image resolution is too large. Please upload a smaller image")

        safe_name = self._safe_filename(filename, pil_ext)
        return ValidatedUpload(
            content=content,
            content_type=pil_content_type,
            filename=safe_name,
            width=width,
            height=height,
            format=image_format,
        )

    def _detect_magic(self, content: bytes) -> tuple[str | None, str | None]:
        for signature, content_type, extension in self._magic_types:
            if content.startswith(signature):
                return content_type, extension
        return None, None

    def _safe_filename(self, filename: str | None, extension: str) -> str:
        original = Path(filename or "passport").name
        stem = Path(original).stem or "passport"
        stem = _SAFE_FILENAME.sub("-", stem).strip(".-_") or "passport"
        return f"{stem[:80]}{extension}"

    def _default_scanner(self) -> MalwareScanner:
        if not self._settings.malware_scanner_enabled:
            return DisabledMalwareScanner()
        return ClamAVMalwareScanner(
            host=self._settings.malware_scanner_host,
            port=self._settings.malware_scanner_port,
            timeout_seconds=self._settings.malware_scanner_timeout_seconds,
        )
