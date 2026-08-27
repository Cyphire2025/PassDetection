from __future__ import annotations

import io
from collections.abc import Callable
from typing import cast

import pytest
from fastapi import UploadFile
from pypdf import PdfWriter
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.settings import get_settings
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.database.models import UntrustedUploadScanModel
from app.infrastructure.security.upload_security import (
    UploadSecurityContext,
    UploadSecurityEvidenceError,
    UploadSecurityService,
)
from app.infrastructure.security.upload_validator import (
    MalwareScanner,
    MalwareScannerUnavailableError,
    MalwareScanRejectedError,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.document_uploads import read_bounded_document_uploads


class _CleanScanner:
    def __init__(self) -> None:
        self.calls = 0

    def scan(self, _content: bytes) -> None:
        self.calls += 1


class _InfectedScanner:
    def scan(self, _content: bytes) -> None:
        raise MalwareScanRejectedError("infected")


class _UnavailableScanner:
    def scan(self, _content: bytes) -> None:
        raise MalwareScannerUnavailableError("unavailable")


class _UnexpectedFailureScanner:
    def scan(self, _content: bytes) -> None:
        raise TimeoutError("socket deadline")


class _Storage:
    def __init__(self, *, fail_upload: bool = False) -> None:
        self.fail_upload = fail_upload
        self.uploads: list[tuple[bytes, str, str]] = []
        self.deleted: list[str] = []

    async def upload_file(self, content: bytes, key: str, content_type: str) -> str:
        if self.fail_upload:
            raise OSError("storage unavailable")
        self.uploads.append((content, key, content_type))
        return key

    async def delete_files(self, keys: list[str]) -> int:
        self.deleted.extend(keys)
        return len(keys)


class _EvidenceStore:
    def __init__(self, *, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.records: list[UntrustedUploadScanModel] = []

    def factory(self) -> _EvidenceSession:
        return _EvidenceSession(self)


class _EvidenceSession:
    def __init__(self, store: _EvidenceStore) -> None:
        self._store = store
        self._pending: UntrustedUploadScanModel | None = None

    async def __aenter__(self) -> _EvidenceSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def add(self, record: UntrustedUploadScanModel) -> None:
        self._pending = record

    async def commit(self) -> None:
        if self._store.fail_commit:
            raise OSError("database unavailable")
        assert self._pending is not None
        self._store.records.append(self._pending)


def _pdf() -> bytes:
    target = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(target)
    return target.getvalue()


def _service(
    *,
    scanner: MalwareScanner,
    evidence: _EvidenceStore,
    storage: _Storage | None = None,
    max_bytes: int = 10 * 1024 * 1024,
) -> UploadSecurityService:
    settings = get_settings().model_copy(
        update={
            "upload_max_file_size_bytes": max_bytes,
            "malware_quarantine_enabled": True,
        }
    )
    factory = cast(
        async_sessionmaker[AsyncSession],
        cast(Callable[[], _EvidenceSession], evidence.factory),
    )
    return UploadSecurityService(
        settings=settings,
        scanner=scanner,
        session_factory=factory,
        storage=cast(MinioStorageRepository, storage or _Storage()),
    )


@pytest.mark.asyncio
async def test_clean_original_pdf_is_scanned_before_acceptance_and_recorded() -> None:
    scanner = _CleanScanner()
    evidence = _EvidenceStore()

    await _service(scanner=scanner, evidence=evidence).validate_document(
        content=_pdf(),
        declared_content_type="application/pdf",
        context=UploadSecurityContext(ingestion_flow="distribution_pdf"),
    )

    assert scanner.calls == 1
    assert len(evidence.records) == 1
    assert evidence.records[0].scan_status == "clean"
    assert evidence.records[0].disposition == "accepted"
    assert evidence.records[0].content_sha256


@pytest.mark.asyncio
async def test_infected_original_is_encrypted_in_quarantine_and_rejected() -> None:
    content = _pdf()
    evidence = _EvidenceStore()
    storage = _Storage()

    with pytest.raises(MalwareScanRejectedError):
        await _service(
            scanner=_InfectedScanner(), evidence=evidence, storage=storage
        ).validate_document(
            content=content,
            declared_content_type="application/pdf",
            context=UploadSecurityContext(ingestion_flow="passport_image"),
        )

    assert len(storage.uploads) == 1
    assert storage.uploads[0][0] != content
    assert storage.uploads[0][2] == "application/octet-stream"
    assert evidence.records[0].scan_status == "infected"
    assert evidence.records[0].disposition == "quarantined"
    assert evidence.records[0].quarantine_key_ciphertext is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("scanner", [_UnavailableScanner(), _UnexpectedFailureScanner()])
async def test_scanner_timeout_or_unavailable_fails_closed_and_is_recorded(
    scanner: MalwareScanner,
) -> None:
    evidence = _EvidenceStore()

    with pytest.raises(MalwareScannerUnavailableError):
        await _service(scanner=scanner, evidence=evidence).validate_document(
            content=_pdf(),
            declared_content_type="application/pdf",
            context=UploadSecurityContext(ingestion_flow="document_rename"),
        )

    assert evidence.records[0].scan_status == "scanner_error"
    assert evidence.records[0].disposition == "rejected"


@pytest.mark.asyncio
async def test_malformed_pdf_is_scanned_then_rejected_with_durable_status() -> None:
    scanner = _CleanScanner()
    evidence = _EvidenceStore()

    with pytest.raises(ImageValidationError, match="readable PDF"):
        await _service(scanner=scanner, evidence=evidence).validate_document(
            content=b"not-a-pdf",
            declared_content_type="application/pdf",
            context=UploadSecurityContext(ingestion_flow="document_rename"),
        )

    assert scanner.calls == 1
    assert evidence.records[0].scan_status == "malformed"


@pytest.mark.asyncio
async def test_oversized_input_is_rejected_before_scanner_work() -> None:
    scanner = _CleanScanner()
    evidence = _EvidenceStore()

    with pytest.raises(ImageValidationError, match="size limit"):
        await _service(scanner=scanner, evidence=evidence, max_bytes=4).validate_document(
            content=b"12345",
            declared_content_type="application/pdf",
            context=UploadSecurityContext(ingestion_flow="document_rename"),
        )

    assert scanner.calls == 0
    assert evidence.records[0].scan_status == "oversized"


@pytest.mark.asyncio
async def test_quarantine_failure_never_allows_infected_content_to_continue() -> None:
    evidence = _EvidenceStore()

    with pytest.raises(MalwareScanRejectedError):
        await _service(
            scanner=_InfectedScanner(),
            evidence=evidence,
            storage=_Storage(fail_upload=True),
        ).validate_document(
            content=_pdf(),
            declared_content_type="application/pdf",
            context=UploadSecurityContext(ingestion_flow="passport_image"),
        )

    assert evidence.records[0].scan_status == "infected"
    assert evidence.records[0].disposition == "rejected"
    assert evidence.records[0].error_code == "QUARANTINE_STORAGE_FAILED"


@pytest.mark.asyncio
async def test_database_failure_removes_new_quarantine_object_and_fails_closed() -> None:
    evidence = _EvidenceStore(fail_commit=True)
    storage = _Storage()

    with pytest.raises(UploadSecurityEvidenceError):
        await _service(
            scanner=_InfectedScanner(), evidence=evidence, storage=storage
        ).validate_document(
            content=_pdf(),
            declared_content_type="application/pdf",
            context=UploadSecurityContext(ingestion_flow="passport_image"),
        )

    assert storage.deleted == [storage.uploads[0][1]]


@pytest.mark.asyncio
async def test_authenticated_pdf_boundary_uses_durable_security_service() -> None:
    evidence = _EvidenceStore()
    content = _pdf()
    service = _service(scanner=_CleanScanner(), evidence=evidence)

    uploads = await read_bounded_document_uploads(
        [UploadFile(file=io.BytesIO(content), filename="visa.pdf", size=len(content))],
        security_context=UploadSecurityContext(ingestion_flow="document_distribution_upload"),
        security_service=service,
    )

    assert uploads[0].content == content
    assert evidence.records[0].ingestion_flow == "document_distribution_upload"
    assert evidence.records[0].scan_status == "clean"
