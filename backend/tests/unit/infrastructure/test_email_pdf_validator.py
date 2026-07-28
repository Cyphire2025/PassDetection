from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from app.infrastructure.email.pdf_validator import (
    EmailPdfValidationError,
    EmailPdfValidator,
)


class RecordingScanner:
    def __init__(self) -> None:
        self.calls = 0
        self.last_size = 0

    def scan(self, content: bytes) -> None:
        self.calls += 1
        self.last_size = len(content)


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "app_env": "development",
        "email_attachment_max_bytes": 1024 * 1024,
        "email_pdf_max_pages": 10,
        "malware_scanner_enabled": False,
        "malware_scanner_host": "localhost",
        "malware_scanner_port": 3310,
        "malware_scanner_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _pdf(*, pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_validator_scans_hashes_and_sanitizes_untrusted_name() -> None:
    scanner = RecordingScanner()
    source = _pdf(pages=2)
    validator = EmailPdfValidator(  # type: ignore[arg-type]
        settings=_settings(),
        scanner=scanner,
    )

    result = validator.validate(
        content=source,
        filename="../booking confirmation!!.PDF",
        declared_content_type="application/pdf",
    )

    assert scanner.calls == 1
    assert scanner.last_size == len(source)
    assert result.content == source
    assert result.filename == "booking-confirmation.pdf"
    assert result.content_type == "application/pdf"
    assert result.page_count == 2
    assert len(result.sha256_hex) == 64
    assert source.hex() not in repr(result)


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "message"),
    [
        ("document.txt", b"%PDF-1.4 fake", "application/pdf", r"\.pdf"),
        ("document.pdf", b"not-a-pdf", "application/pdf", "not a PDF"),
        ("document.pdf", b"%PDF-1.4 fake", "text/html", "content type"),
    ],
)
def test_pdf_validator_rejects_extension_magic_and_declared_type(
    filename: str,
    content: bytes,
    content_type: str,
    message: str,
) -> None:
    validator = EmailPdfValidator(  # type: ignore[arg-type]
        settings=_settings(),
        scanner=RecordingScanner(),
    )

    with pytest.raises(EmailPdfValidationError, match=message):
        validator.validate(
            content=content,
            filename=filename,
            declared_content_type=content_type,
        )


def test_pdf_validator_enforces_byte_and_page_caps() -> None:
    source = _pdf(pages=2)
    byte_limited = EmailPdfValidator(  # type: ignore[arg-type]
        settings=_settings(email_attachment_max_bytes=len(source) - 1),
        scanner=RecordingScanner(),
    )
    page_limited = EmailPdfValidator(  # type: ignore[arg-type]
        settings=_settings(email_pdf_max_pages=1),
        scanner=RecordingScanner(),
    )

    with pytest.raises(EmailPdfValidationError, match="size limit"):
        byte_limited.validate(
            content=source,
            filename="document.pdf",
            declared_content_type="application/pdf",
        )
    with pytest.raises(EmailPdfValidationError, match="page limit"):
        page_limited.validate(
            content=source,
            filename="document.pdf",
            declared_content_type="application/pdf",
        )


def test_pdf_validator_rejects_unreadable_pdf_after_scanning() -> None:
    scanner = RecordingScanner()
    validator = EmailPdfValidator(  # type: ignore[arg-type]
        settings=_settings(),
        scanner=scanner,
    )

    with pytest.raises(EmailPdfValidationError, match="readable PDF"):
        validator.validate(
            content=b"%PDF-1.7\nnot-a-real-document",
            filename="document.pdf",
            declared_content_type="application/pdf",
        )

    assert scanner.calls == 1


def test_pdf_validator_allows_production_processing_without_optional_scanner() -> None:
    validator = EmailPdfValidator(  # type: ignore[arg-type]
        settings=_settings(app_env="production", malware_scanner_enabled=False),
    )

    result = validator.validate(
        content=_pdf(),
        filename="document.pdf",
        declared_content_type="application/pdf",
    )

    assert result.content_type == "application/pdf"
    assert result.page_count == 1
