from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes.admin_accounts import (
    _get_manageable_account,
    delete_managed_account,
)


class _AccountResult:
    def __init__(self, row: tuple[object, str | None] | None) -> None:
        self._row = row

    def first(self) -> tuple[object, str | None] | None:
        return self._row


def _account(*, agency_id: uuid.UUID, role: str = UserRole.AGENCY_STAFF.value) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        role=role,
        email="staff@example.test",
        is_active=True,
        updated_at=None,
    )


def _manager(*, agency_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        role=UserRole.AGENCY_MANAGER,
        email="manager@example.test",
    )


@pytest.mark.asyncio
async def test_agency_manager_can_manage_staff_in_the_same_agency() -> None:
    agency_id = uuid.uuid4()
    staff = _account(agency_id=agency_id)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_AccountResult((staff, "Agency"))),
    )

    account, agency_name = await _get_manageable_account(
        session,  # type: ignore[arg-type]
        _manager(agency_id=agency_id),  # type: ignore[arg-type]
        staff.id,
    )

    assert account is staff
    assert agency_name == "Agency"


@pytest.mark.asyncio
async def test_agency_manager_cannot_manage_staff_from_another_agency() -> None:
    staff = _account(agency_id=uuid.uuid4())
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_AccountResult((staff, "Other Agency"))),
    )

    with pytest.raises(HTTPException) as exc_info:
        await _get_manageable_account(
            session,  # type: ignore[arg-type]
            _manager(agency_id=uuid.uuid4()),  # type: ignore[arg-type]
            staff.id,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_deleting_staff_revokes_sessions_audits_and_removes_account() -> None:
    agency_id = uuid.uuid4()
    staff = _account(agency_id=agency_id)
    manager = _manager(agency_id=agency_id)
    session = SimpleNamespace(delete=AsyncMock(), flush=AsyncMock())
    refresh_tokens = SimpleNamespace(revoke_all_for_user=AsyncMock())
    audit_logs = SimpleNamespace(record=AsyncMock())
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    with (
        patch(
            "app.presentation.api.v1.routes.admin_accounts._get_manageable_account",
            AsyncMock(return_value=(staff, "Agency")),
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts.RefreshTokenRepository",
            return_value=refresh_tokens,
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts.AuditLogRepository",
            return_value=audit_logs,
        ),
    ):
        result = await delete_managed_account(
            account_id=staff.id,
            request=request,  # type: ignore[arg-type]
            current_user=manager,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )

    refresh_tokens.revoke_all_for_user.assert_awaited_once_with(staff.id)
    audit_logs.record.assert_awaited_once()
    session.delete.assert_awaited_once_with(staff)
    session.flush.assert_awaited_once()
    assert result.result == "deleted"
    assert result.preserved_history is False
