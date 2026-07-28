"""Validation boundary for untrusted PDF attachments from email providers."""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config.settings import Settings, get_settings
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.security.upload_validator import (
    ClamAVMalwareScanner,
    DisabledMalwareScanner,
    MalwareScanner,
)

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_ALLOWED_DECLARED_TYPES = frozenset(
    {
        "",
        "application/octet-stream",
        "application/pdf",
    }
)


class EmailPdfValidationError(Exception):
    """Safe validation error that contains no attachment bytes or raw metadata."""


@dataclass(frozen=True, slots=True)
class ValidatedEmailPdf:
    content: bytes = field(repr=False)
    filename: str
    content_type: str
    sha256_hex: str
    page_count: int


class EmailPdfValidator:
    def __init__(
        self,
        settings: Settings | None = None,
        scanner: MalwareScanner | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._scanner = scanner or self._default_scanner()

    def validate(
        self,
        *,
        content: bytes,
        filename: str | None,
        declared_content_type: str | None,
    ) -> ValidatedEmailPdf:
        if not content:
            raise EmailPdfValidationError("Email attachment is empty")

        max_bytes = _positive_setting(
            self._settings,
            "email_attachment_max_bytes",
            default=25 * 1024 * 1024,
        )
        if len(content) > max_bytes:
            raise EmailPdfValidationError("Email PDF exceeds the configured attachment size limit")

        safe_filename = self._safe_filename(filename)
        if Path(filename or "").suffix.casefold() != ".pdf":
            raise EmailPdfValidationError("Email attachment must use a .pdf extension")
        if not content.startswith(b"%PDF-"):
            raise EmailPdfValidationError("Email attachment is not a PDF document")

        normalized_content_type = (declared_content_type or "").split(";", 1)[0].strip().lower()
        if normalized_content_type not in _ALLOWED_DECLARED_TYPES:
            raise EmailPdfValidationError("Email attachment content type is not PDF")

        try:
            self._scanner.scan(content)
        except ImageValidationError:
            raise EmailPdfValidationError(
                "Email attachment failed malware security scanning"
            ) from None

        page_limit = _positive_setting(
            self._settings,
            "email_pdf_max_pages",
            default=100,
        )
        try:
            reader = PdfReader(io.BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise EmailPdfValidationError("Encrypted email PDFs require manual review")
            page_count = len(reader.pages)
            if page_count < 1:
                raise EmailPdfValidationError("Email PDF contains no readable pages")
            if page_count > page_limit:
                raise EmailPdfValidationError("Email PDF exceeds the configured page limit")
            # Force page-object parsing instead of accepting a plausible header
            # and cross-reference table alone.
            for page in reader.pages:
                _ = page.mediabox
        except EmailPdfValidationError:
            raise
        except (PdfReadError, OSError, TypeError, ValueError, IndexError, KeyError):
            raise EmailPdfValidationError("Email attachment is not a readable PDF") from None

        return ValidatedEmailPdf(
            content=content,
            filename=safe_filename,
            content_type="application/pdf",
            sha256_hex=hashlib.sha256(content).hexdigest(),
            page_count=page_count,
        )

    def _default_scanner(self) -> MalwareScanner:
        scanner_enabled = bool(getattr(self._settings, "malware_scanner_enabled", False))
        if not scanner_enabled:
            if getattr(self._settings, "app_env", "development") == "production":
                return _UnavailableMalwareScanner()
            return DisabledMalwareScanner()
        return ClamAVMalwareScanner(
            host=str(getattr(self._settings, "malware_scanner_host", "localhost")),
            port=int(getattr(self._settings, "malware_scanner_port", 3310)),
            timeout_seconds=float(getattr(self._settings, "malware_scanner_timeout_seconds", 2.0)),
        )

    @staticmethod
    def _safe_filename(filename: str | None) -> str:
        original = re.split(r"[\\/]", filename or "email-document.pdf")[-1]
        stem = Path(original).stem or "email-document"
        normalized_stem = _SAFE_FILENAME.sub("-", stem).strip(".-_") or "email-document"
        return f"{normalized_stem[:80]}.pdf"


class _UnavailableMalwareScanner:
    """Fail closed for untrusted mail attachments in production."""

    def scan(self, content: bytes) -> None:
        del content
        raise ImageValidationError("Malware scanner is unavailable")


def _positive_setting(settings: Any, name: str, *, default: int) -> int:
    value = getattr(settings, name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return default
    return value
