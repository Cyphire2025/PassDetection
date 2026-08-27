from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.infrastructure import operational_retention as retention_module
from app.infrastructure.database.models import UntrustedUploadScanModel
from app.infrastructure.operational_retention import apply_operational_retention
from app.infrastructure.security import upload_security


class _RowCount:
    def __init__(self, value: int) -> None:
        self.rowcount = value


class _Scalars:
    def __init__(self, values: list[UntrustedUploadScanModel]) -> None:
        self._values = values

    def all(self) -> list[UntrustedUploadScanModel]:
        return self._values


class _ScalarRows:
    def __init__(self, values: list[UntrustedUploadScanModel]) -> None:
        self._values = values

    def scalars(self) -> _Scalars:
        return _Scalars(self._values)


class _Session:
    def __init__(self, results: list[object]) -> None:
        self._results = results
        self.statements: list[object] = []
        self.flush = AsyncMock()

    async def execute(self, statement: object) -> object:
        self.statements.append(statement)
        return self._results.pop(0)


def _upload_row(
    *,
    disposition: str,
    now: datetime,
    ciphertext: bytes | None = None,
) -> UntrustedUploadScanModel:
    return UntrustedUploadScanModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        user_id=None,
        ingestion_flow="test",
        content_sha256="a" * 64,
        byte_size=100,
        declared_media_type="application/pdf",
        scanner_name="test",
        scanner_version=None,
        scan_status="infected" if disposition == "quarantined" else "clean",
        disposition=disposition,
        detection_category=None,
        error_code=None,
        quarantine_key_ciphertext=ciphertext,
        quarantine_key_version=1 if ciphertext is not None else None,
        retention_expires_at=now - timedelta(seconds=1),
        created_at=now - timedelta(days=30),
    )


@pytest.mark.asyncio
async def test_operational_retention_is_bounded_and_stages_quarantine_cleanup(
    monkeypatch,
) -> None:
    now = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
    settings = get_settings()
    key = f"{settings.malware_quarantine_prefix}/2026/08/01/evidence.bin.enc"
    ciphertext = upload_security._quarantine_fernet(settings, purpose="locator").encrypt(
        key.encode("utf-8")
    )
    clean = _upload_row(disposition="accepted", now=now)
    quarantined = _upload_row(
        disposition="quarantined",
        now=now,
        ciphertext=ciphertext,
    )
    session = _Session(
        [
            _RowCount(2),
            _RowCount(3),
            _ScalarRows([clean, quarantined]),
            _RowCount(2),
            _RowCount(1),
        ]
    )
    staged: list[dict[str, object]] = []

    def stage(_session: object, **kwargs: object):
        staged.append(kwargs)
        return (SimpleNamespace(object_count=1),)

    audit = AsyncMock()
    monkeypatch.setattr(retention_module, "stage_storage_cleanup_jobs", stage)
    monkeypatch.setattr(
        retention_module,
        "AuditLogRepository",
        lambda _session: SimpleNamespace(record=audit),
    )

    result = await apply_operational_retention(
        cast(AsyncSession, session),
        now=now,
        settings=settings,
    )

    assert result.expired_runtimes == 2
    assert result.deleted_discard_tombstones == 3
    assert result.deleted_upload_scan_records == 2
    assert result.deleted_runtime_registrations == 1
    assert result.quarantine_cleanup_jobs == 1
    assert result.quarantine_objects_scheduled == 1
    assert staged[0]["source"] == "untrusted_upload_quarantine"
    assert staged[0]["storage_keys"] == [key]
    assert audit.await_args.kwargs["metadata"] == result.as_dict()
    assert session.flush.await_count == 1
    rendered = "\n".join(
        str(statement.compile(dialect=postgresql.dialect())).lower()
        for statement in session.statements
    )
    assert "skip locked" in rendered
    assert "attendance_discard_tombstones.retention_expires_at" in rendered
    assert "untrusted_upload_scans.retention_expires_at" in rendered
    assert "not (exists" in rendered


@pytest.mark.asyncio
async def test_corrupt_quarantine_locator_is_retained_and_reported(monkeypatch) -> None:
    now = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
    corrupt = _upload_row(
        disposition="quarantined",
        now=now,
        ciphertext=b"not-authenticated",
    )
    session = _Session(
        [
            _RowCount(0),
            _RowCount(0),
            _ScalarRows([corrupt]),
            _RowCount(0),
        ]
    )
    audit = AsyncMock()
    monkeypatch.setattr(
        retention_module,
        "AuditLogRepository",
        lambda _session: SimpleNamespace(record=audit),
    )

    result = await apply_operational_retention(
        cast(AsyncSession, session),
        now=now,
        settings=get_settings(),
    )

    assert result.quarantine_locator_failures == 1
    assert result.deleted_upload_scan_records == 0
    assert corrupt.error_code == "QUARANTINE_LOCATOR_INVALID"
    assert len(session.statements) == 4
    assert audit.await_count == 1
