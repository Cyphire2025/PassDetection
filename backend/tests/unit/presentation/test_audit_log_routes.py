from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository,
    InvalidAuditCursorError,
)
from app.presentation.api.v1.routes.audit_logs import (
    _audit_csv,
    _audit_filters,
    _audit_scope,
    _safe_csv_cell,
    page_audit_logs,
)
from app.presentation.api.v1.schemas.audit_log_schemas import AuditLogListItemResponse


def _user(role: UserRole, agency_id: uuid.UUID | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="admin@example.test",
        role=role,
        agency_id=agency_id,
    )


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/audit-logs/page",
            "query_string": b"",
            "headers": [],
            "scheme": "https",
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 443),
        }
    )


def _log(*, actor_email: str = "admin@example.test", entity_id: str = "entity") -> AuditLogModel:
    return AuditLogModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        actor_email=actor_email,
        action="passport.deleted",
        entity_type="passport",
        entity_id=entity_id,
        ip_address="203.0.113.10",
        metadata_json={"passport_number": "must-not-export"},
        result="blocked",
        created_at=datetime(2026, 8, 23, 10, 0, tzinfo=UTC),
    )


def test_audit_scope_never_allows_an_agency_admin_to_select_another_tenant() -> None:
    own_agency = uuid.uuid4()
    other_agency = uuid.uuid4()
    user = _user(UserRole.AGENCY_ADMIN, own_agency)

    assert _audit_scope(user, None) == own_agency
    assert _audit_scope(user, own_agency) == own_agency
    with pytest.raises(HTTPException) as exc_info:
        _audit_scope(user, other_agency)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Audit scope is unavailable"


def test_super_admin_may_explicitly_scope_or_review_the_global_ledger() -> None:
    target = uuid.uuid4()
    user = _user(UserRole.SUPER_ADMIN, None)

    assert _audit_scope(user, None) is None
    assert _audit_scope(user, target) == target


def test_audit_filters_validate_time_order_and_normalize_strings() -> None:
    start = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
    filters = _audit_filters(
        agency_id=uuid.uuid4(),
        start_at=start,
        end_at=start + timedelta(hours=1),
        actor="  admin@example.test  ",
        event_type=" passport.deleted ",
        entity_type=" passport ",
        entity_id=" 123 ",
        result="blocked",
    )
    assert filters.actor == "admin@example.test"
    assert filters.event_type == "passport.deleted"
    assert filters.result == "blocked"

    with pytest.raises(HTTPException) as exc_info:
        _audit_filters(
            agency_id=None,
            start_at=start + timedelta(seconds=1),
            end_at=start,
            actor=None,
            event_type=None,
            entity_type=None,
            entity_id=None,
            result=None,
        )
    assert exc_info.value.status_code == 422


def test_csv_export_is_formula_safe_and_excludes_metadata_and_network_data() -> None:
    log = _log(actor_email='=HYPERLINK("https://example.test")', entity_id="+1+1")
    exported = _audit_csv([log])
    rows = list(csv.reader(io.StringIO(exported)))

    assert rows[0] == [
        "id",
        "created_at",
        "agency_id",
        "actor",
        "event_type",
        "entity_type",
        "entity_id",
        "result",
    ]
    assert rows[1][3].startswith("'=")
    assert rows[1][6].startswith("'+")
    assert "must-not-export" not in exported
    assert "203.0.113.10" not in exported
    assert _safe_csv_cell("  -formula").startswith("'")


def test_typed_result_contract_rejects_unrecognized_database_values() -> None:
    log = _log()
    with pytest.raises(ValidationError):
        AuditLogListItemResponse(
            id=log.id,
            agency_id=log.agency_id,
            user_id=log.user_id,
            actor_email=log.actor_email,
            event_type=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            result="unknown",
            created_at=log.created_at,
        )


@pytest.mark.asyncio
async def test_invalid_cursor_returns_stable_code_and_audits_the_blocked_attempt() -> None:
    agency_id = uuid.uuid4()
    current_user = _user(UserRole.AGENCY_ADMIN, agency_id)
    list_page = AsyncMock(side_effect=InvalidAuditCursorError("invalid"))
    record = AsyncMock()

    with (
        patch.object(AuditLogRepository, "list_page", new=list_page),
        patch.object(AuditLogRepository, "record", new=record),
    ):
        response = await page_audit_logs(
            request=_request(),
            cursor="invalid",
            page_size=50,
            start_at=None,
            end_at=None,
            actor=None,
            event_type=None,
            entity_type=None,
            entity_id=None,
            result=None,
            agency_id=None,
            current_user=current_user,
            session=cast(AsyncSession, object()),
        )

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "AUDIT_CURSOR_INVALID"
    record.assert_awaited_once()
    audit_call = record.await_args.kwargs
    assert audit_call["agency_id"] == agency_id
    assert audit_call["result"] == "blocked"
    assert audit_call["metadata"]["returned_count"] == 0
    assert "invalid" not in str(audit_call["metadata"])
