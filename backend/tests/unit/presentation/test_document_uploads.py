from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile

from app.infrastructure.security.upload_validator import (
    DocumentIngestionDisabledError,
    MalwareScannerConfigurationError,
    MalwareScannerUnavailableError,
    MalwareScanRejectedError,
)
from app.presentation.api.v1 import document_uploads


@pytest.fixture(autouse=True)
def _deterministic_upload_security(monkeypatch):
    class _SecurityService:
        def __init__(self, *, scanner) -> None:
            self._scanner = scanner

        async def validate_document(self, *, content: bytes, **_kwargs: object) -> None:
            self._scanner.scan(content)

    monkeypatch.setattr(document_uploads, "UploadSecurityService", _SecurityService)


def _upload(content: bytes, *, filename: str = "document.pdf", size: int | None = None):
    return UploadFile(file=BytesIO(content), filename=filename, size=size)


async def test_document_upload_accepts_exact_per_file_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        document_uploads,
        "get_settings",
        lambda: SimpleNamespace(upload_max_file_size_bytes=4),
    )

    result = await document_uploads.read_bounded_document_uploads(
        [_upload(b"1234", filename=r"C:\fakepath\visa.pdf", size=4)]
    )

    assert result[0].content == b"1234"
    assert result[0].filename == "visa.pdf"
    assert result[0].content_type == "application/pdf"


async def test_document_upload_rejects_actual_bytes_over_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        document_uploads,
        "get_settings",
        lambda: SimpleNamespace(upload_max_file_size_bytes=4),
    )

    with pytest.raises(HTTPException) as exc_info:
        await document_uploads.read_bounded_document_uploads([_upload(b"12345")])

    assert exc_info.value.status_code == 413


async def test_document_upload_rejects_declared_bytes_over_limit_before_read(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        document_uploads,
        "get_settings",
        lambda: SimpleNamespace(upload_max_file_size_bytes=4),
    )
    upload = _upload(b"1234", size=5)

    with pytest.raises(HTTPException) as exc_info:
        await document_uploads.read_bounded_document_uploads([upload])

    assert exc_info.value.status_code == 413
    assert upload.file.closed


async def test_document_upload_rejects_batch_over_actual_total(monkeypatch) -> None:
    scanned: list[bytes] = []
    monkeypatch.setattr(
        document_uploads,
        "get_settings",
        lambda: SimpleNamespace(upload_max_file_size_bytes=4),
    )
    monkeypatch.setattr(document_uploads, "MAX_DOCUMENT_BATCH_BYTES", 6)
    monkeypatch.setattr(
        document_uploads,
        "malware_scanner_from_settings",
        lambda: SimpleNamespace(scan=lambda content: scanned.append(content)),
    )

    with pytest.raises(HTTPException) as exc_info:
        await document_uploads.read_bounded_document_uploads([_upload(b"1234"), _upload(b"5678")])

    assert exc_info.value.status_code == 413
    assert scanned == [b"1234"]


async def test_document_upload_rejects_excess_file_count_before_read(monkeypatch) -> None:
    monkeypatch.setattr(document_uploads, "MAX_DOCUMENT_FILES_PER_REQUEST", 1)
    first = _upload(b"1")
    second = _upload(b"2")

    with pytest.raises(HTTPException) as exc_info:
        await document_uploads.read_bounded_document_uploads([first, second])

    assert exc_info.value.status_code == 413
    assert first.file.closed
    assert second.file.closed


async def test_document_upload_accepts_fifty_files_and_rejects_fifty_one(monkeypatch) -> None:
    monkeypatch.setattr(
        document_uploads,
        "get_settings",
        lambda: SimpleNamespace(upload_max_file_size_bytes=4),
    )
    accepted = [_upload(b"1", filename=f"visa-{index}.pdf", size=1) for index in range(50)]

    result = await document_uploads.read_bounded_document_uploads(accepted)

    assert len(result) == 50

    rejected = [_upload(b"1", filename=f"visa-{index}.pdf", size=1) for index in range(51)]
    with pytest.raises(HTTPException) as exc_info:
        await document_uploads.read_bounded_document_uploads(rejected)

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == "Upload at most 50 PDFs at a time"
    assert all(upload.file.closed for upload in rejected)


async def test_document_upload_closes_unread_handles_after_mid_batch_failure(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        document_uploads,
        "get_settings",
        lambda: SimpleNamespace(upload_max_file_size_bytes=4),
    )
    first = _upload(b"1")
    broken = _upload(b"2")
    remaining = _upload(b"3")
    broken.read = AsyncMock(side_effect=OSError("read failed"))

    with pytest.raises(HTTPException) as exc_info:
        await document_uploads.read_bounded_document_uploads([first, broken, remaining])

    assert exc_info.value.status_code == 400
    assert first.file.closed
    assert broken.file.closed
    assert remaining.file.closed


async def test_document_upload_scans_original_bytes_before_acceptance(monkeypatch) -> None:
    scanner = SimpleNamespace(scan=lambda content: scanned.append(content))
    scanned: list[bytes] = []
    monkeypatch.setattr(
        document_uploads,
        "get_settings",
        lambda: SimpleNamespace(upload_max_file_size_bytes=32),
    )
    monkeypatch.setattr(
        document_uploads,
        "malware_scanner_from_settings",
        lambda: scanner,
    )

    result = await document_uploads.read_bounded_document_uploads(
        [_upload(b"%PDF-enterprise-fixture")]
    )

    assert scanned == [b"%PDF-enterprise-fixture"]
    assert result[0].content == scanned[0]


@pytest.mark.parametrize(
    ("scanner_error", "expected_status"),
    [
        (MalwareScanRejectedError("malware"), 422),
        (MalwareScannerUnavailableError("offline"), 503),
        (DocumentIngestionDisabledError("disabled"), 503),
    ],
)
async def test_document_upload_fails_closed_when_scanning_cannot_accept(
    monkeypatch,
    scanner_error: Exception,
    expected_status: int,
) -> None:
    def reject(_: bytes) -> None:
        raise scanner_error

    monkeypatch.setattr(
        document_uploads,
        "get_settings",
        lambda: SimpleNamespace(upload_max_file_size_bytes=32),
    )
    monkeypatch.setattr(
        document_uploads,
        "malware_scanner_from_settings",
        lambda: SimpleNamespace(scan=reject),
    )
    upload = _upload(b"%PDF-untrusted")

    with pytest.raises(HTTPException) as exc_info:
        await document_uploads.read_bounded_document_uploads([upload])

    assert exc_info.value.status_code == expected_status
    assert upload.file.closed


async def test_scanner_configuration_failure_closes_entire_batch_before_read(monkeypatch) -> None:
    def fail_configuration():
        raise MalwareScannerConfigurationError("synthetic configuration failure")

    monkeypatch.setattr(document_uploads, "malware_scanner_from_settings", fail_configuration)
    uploads = [_upload(b"first"), _upload(b"second")]
    for upload in uploads:
        upload.read = AsyncMock(side_effect=AssertionError("Unconfigured ingestion read content"))

    with pytest.raises(HTTPException) as caught:
        await document_uploads.read_bounded_document_uploads(uploads)

    assert caught.value.status_code == 503
    assert "not configured" in caught.value.detail
    assert caught.value.headers is None
    for upload in uploads:
        upload.read.assert_not_awaited()
        assert upload.file.closed
