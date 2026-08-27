from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.repositories import audit_log_repository as repository_module
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogFilters,
    AuditLogRepository,
    InvalidAuditCursorError,
)


class _Scalars:
    def __init__(self, values: list[AuditLogModel]) -> None:
        self._values = values

    def all(self) -> list[AuditLogModel]:
        return self._values


class _Result:
    def __init__(self, values: list[AuditLogModel]) -> None:
        self._values = values

    def scalars(self) -> _Scalars:
        return _Scalars(self._values)


class _Session:
    def __init__(self, results: list[list[AuditLogModel]]) -> None:
        self._results = results
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        return _Result(self._results.pop(0))


def _log(identifier: int, created_at: datetime) -> AuditLogModel:
    return AuditLogModel(
        id=uuid.UUID(int=identifier),
        agency_id=uuid.UUID(int=100),
        user_id=uuid.UUID(int=200),
        actor_email="admin@example.test",
        action="attendance.activity.closed",
        entity_type="attendance_session",
        entity_id=str(uuid.UUID(int=300)),
        ip_address="127.0.0.1",
        result="success",
        metadata_json={},
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_cursor_keeps_created_at_and_id_tiebreaker_with_snapshot_scope() -> None:
    created_at = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
    logs = [_log(3, created_at), _log(2, created_at), _log(1, created_at)]
    session = _Session([logs])
    filters = AuditLogFilters(agency_id=uuid.UUID(int=100), result="success")

    page = await AuditLogRepository(cast(AsyncSession, session)).list_page(
        filters,
        cursor=None,
        limit=2,
    )

    assert [item.id.int for item in page.items] == [3, 2]
    assert page.has_more is True
    assert page.next_cursor is not None
    decoded = repository_module._decode_cursor(page.next_cursor)
    assert decoded.snapshot_id.int == 3
    assert decoded.last_id.int == 2
    assert decoded.snapshot_created_at == created_at
    assert decoded.last_created_at == created_at
    sql = str(session.statements[0]).lower()
    assert "order by audit_logs.created_at desc, audit_logs.id desc" in sql


@pytest.mark.asyncio
async def test_cursor_is_bound_to_the_authorized_filter_scope_before_querying() -> None:
    created_at = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
    first_session = _Session([[_log(3, created_at), _log(2, created_at)]])
    first_filters = AuditLogFilters(agency_id=uuid.UUID(int=100))
    first_page = await AuditLogRepository(cast(AsyncSession, first_session)).list_page(
        first_filters,
        cursor=None,
        limit=1,
    )
    assert first_page.next_cursor is not None
    other_scope_session = _Session([])

    with pytest.raises(InvalidAuditCursorError, match="current filters"):
        await AuditLogRepository(cast(AsyncSession, other_scope_session)).list_page(
            AuditLogFilters(agency_id=uuid.UUID(int=101)),
            cursor=first_page.next_cursor,
            limit=1,
        )

    assert other_scope_session.statements == []


@pytest.mark.parametrize(
    "cursor",
    [
        "%not-base64%",
        base64.urlsafe_b64encode(b"\xff").decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b"[]").decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b'{"v":2}').decode("ascii").rstrip("="),
    ],
)
def test_malformed_or_unknown_cursor_versions_have_one_stable_error(cursor: str) -> None:
    with pytest.raises(InvalidAuditCursorError, match="invalid"):
        repository_module._decode_cursor(cursor)


def test_filter_fingerprint_is_timezone_stable_and_changes_with_result() -> None:
    instant = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
    equivalent = instant.astimezone(UTC)
    success = AuditLogFilters(
        agency_id=uuid.UUID(int=100),
        start_at=instant,
        end_at=instant + timedelta(hours=1),
        result="success",
    )
    same = AuditLogFilters(
        agency_id=uuid.UUID(int=100),
        start_at=equivalent,
        end_at=equivalent + timedelta(hours=1),
        result="success",
    )
    failed = AuditLogFilters(
        agency_id=uuid.UUID(int=100),
        start_at=instant,
        end_at=instant + timedelta(hours=1),
        result="failed",
    )

    assert success.fingerprint() == same.fingerprint()
    assert success.fingerprint() != failed.fingerprint()
