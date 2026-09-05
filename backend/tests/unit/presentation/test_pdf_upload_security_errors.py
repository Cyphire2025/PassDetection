"""Both dashboard PDF workflows expose accurate failures without starting ingestion."""

from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter

from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.security import upload_security, upload_validator
from app.infrastructure.security.upload_security import UploadSecurityEvidenceError
from app.infrastructure.security.upload_validator import (
    DisabledDocumentIngestionScanner,
    MalwareScannerUnavailableError,
    MalwareScanRejectedError,
)
from app.presentation.api.v1 import document_uploads
from app.presentation.api.v1.routes import (
    document_distribution_upload,
    document_distribution_verification,
    document_rename,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf


def _pdf(*, encrypted: bool = False) -> bytes:
    output = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    if encrypted:
        writer.encrypt("fixture-password")
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("route", ["rename", "distribution-upload", "distribution-verify"])
@pytest.mark.parametrize(
    ("case", "status_code", "message", "retry_after", "audit_code"),
    [
        ("disabled", 503, "PDF uploads are disabled", None, "INGESTION_DISABLED"),
        ("configuration", 503, "scanning is not configured", None, None),
        ("unavailable", 503, "scanning is temporarily unavailable", "30", "SCANNER_UNAVAILABLE"),
        ("daemon-error", 503, "scanning is temporarily unavailable", "30", "SCANNER_UNAVAILABLE"),
        (
            "unexpected",
            503,
            "scanning is temporarily unavailable",
            "30",
            "SCANNER_UNEXPECTED_FAILURE",
        ),
        ("infected", 422, "failed security scanning", None, None),
        ("malformed", 422, "not a readable, unencrypted PDF", None, "PDF_VALIDATION_FAILED"),
        ("encrypted", 422, "not a readable, unencrypted PDF", None, "PDF_VALIDATION_FAILED"),
        ("evidence-unavailable", 503, "scanning is temporarily unavailable", "30", None),
    ],
)
async def test_routes_distinguish_security_availability_and_document_rejections(
    monkeypatch, route, case, status_code, message, retry_after, audit_code
) -> None:
    agency_id, actor_id, group_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    user = SimpleNamespace(id=actor_id, agency_id=agency_id, role=UserRole.AGENCY_ADMIN)
    session = MagicMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    passenger = SimpleNamespace(
        id=uuid.uuid4(),
        updated_at=None,
        client_name="QA Passenger",
        client_phone=None,
        family_head_phone=None,
        confirmed_fields={},
        extracted_fields={},
        staff_metadata={},
        custom_answers=[],
        custom_detail_answers=[],
    )
    for module in (document_distribution_upload, document_distribution_verification):
        monkeypatch.setattr(module, "_get_authorized_group", AsyncMock(return_value=group))
        monkeypatch.setattr(module, "_group_passengers", AsyncMock(return_value=[passenger]))
        monkeypatch.setattr(
            module,
            "_read_linked_document_match_source",
            AsyncMock(return_value=SimpleNamespace(snapshot=())),
        )
        monkeypatch.setattr(
            module, "_linked_document_match_identifiers", AsyncMock(return_value=())
        )

    pipeline = MagicMock(side_effect=AssertionError("Unaccepted PDF reached document ingestion"))
    monkeypatch.setattr(document_rename, "classify_documents_bounded", pipeline)
    monkeypatch.setattr(document_distribution_upload, "TravelDocumentIngestionService", pipeline)
    monkeypatch.setattr(document_distribution_verification, "classify_documents_bounded", pipeline)
    parser = MagicMock(wraps=upload_security._validate_pdf_structure)
    monkeypatch.setattr(upload_security, "_validate_pdf_structure", parser)
    record = AsyncMock()
    if case == "evidence-unavailable":
        record.side_effect = UploadSecurityEvidenceError("synthetic evidence outage")
    quarantine = AsyncMock(return_value=None)
    monkeypatch.setattr(upload_security.UploadSecurityService, "_record", record)
    monkeypatch.setattr(upload_security.UploadSecurityService, "_quarantine", quarantine)
    scanner = SimpleNamespace(scan=MagicMock())
    if case == "disabled":
        scanner = DisabledDocumentIngestionScanner()
    elif case == "configuration":

        def configured_scanner():
            return upload_validator.malware_scanner_from_settings(
                SimpleNamespace(
                    is_development=False,
                    untrusted_document_ingestion_enabled=True,
                    malware_scanner_enabled=False,
                )
            )

        monkeypatch.setattr(document_uploads, "malware_scanner_from_settings", configured_scanner)
    elif case == "unavailable":
        scanner.scan.side_effect = MalwareScannerUnavailableError("scanner hostname must not leak")
    elif case == "unexpected":
        scanner.scan.side_effect = ImageValidationError("unknown scanner failure")
    elif case == "infected":
        scanner.scan.side_effect = MalwareScanRejectedError("private signature must not leak")
    elif case == "daemon-error":
        sock = MagicMock()
        sock.__enter__.return_value = sock
        sock.recv.return_value = b"INSTREAM size limit exceeded. ERROR\0"
        monkeypatch.setattr(upload_validator.socket, "create_connection", lambda *_a, **_k: sock)
        scanner = upload_validator.ClamAVMalwareScanner(
            host="scanner.test", port=3310, timeout_seconds=1
        )
    if case != "configuration":
        monkeypatch.setattr(document_uploads, "malware_scanner_from_settings", lambda: scanner)

    app = FastAPI()
    app.include_router(document_rename.router, prefix="/rename")
    app.include_router(document_distribution_upload.router, prefix="/distribution")
    app.include_router(document_distribution_verification.router, prefix="/distribution")
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[document_rename.get_db_session] = lambda: session
    app.dependency_overrides[require_cookie_csrf] = lambda: None
    operation = "verify" if route == "distribution-verify" else "upload"
    path = (
        "/rename/batches"
        if route == "rename"
        else f"/distribution/groups/{group_id}/visa/{operation}"
    )
    content = b"not a PDF" if case == "malformed" else _pdf(encrypted=case == "encrypted")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            path,
            data={"title": "Synthetic QA"},
            files={"files": ("qa.pdf", content, "application/pdf")},
        )

    assert response.status_code == status_code, response.text
    assert message in response.json()["detail"]
    assert response.headers.get("Retry-After") == retry_after
    assert "private signature" not in response.text
    assert "scanner hostname" not in response.text
    pipeline.assert_not_called()
    session.commit.assert_not_awaited()
    expected_parse_count = int(case in {"malformed", "encrypted", "evidence-unavailable"})
    assert parser.call_count == expected_parse_count
    assert quarantine.await_count == int(case == "infected")
    if case == "configuration":
        record.assert_not_awaited()
    else:
        audit = record.await_args.kwargs
        expected_flow = {
            "rename": "document_rename",
            "distribution-upload": "document_distribution_upload",
            "distribution-verify": "document_distribution_verify",
        }[route]
        assert audit["context"].ingestion_flow == expected_flow
        assert audit["context"].agency_id == agency_id
        if audit_code is not None:
            assert audit["error_code"] == audit_code
        if case == "infected":
            assert audit["scan_status"] == "infected"
        elif case not in {"malformed", "encrypted", "evidence-unavailable"}:
            assert audit["scan_status"] == "scanner_error"
