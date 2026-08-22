from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes.admin_accounts import (
    _deactivate_coordinator_assignments,
    _fence_coordinator_mobile_sessions,
    _fence_dashboard_sessions,
    _get_manageable_account,
    delete_managed_account,
    reset_managed_account_mfa,
)
from app.presentation.api.v1.routes.admin_accounts import (
    router as admin_accounts_router,
)
from app.presentation.api.v1.routes.tour_operations import list_coordinators


def test_account_administration_mutations_require_cookie_csrf() -> None:
    expected = {
        ("/staff", "POST"),
        ("/{account_id}/reset-password", "POST"),
        ("/{account_id}/reset-mfa", "POST"),
        ("/{account_id}/revoke-sessions", "POST"),
        ("/{account_id}/status", "PATCH"),
        ("/{account_id}", "DELETE"),
    }

    for path, method in expected:
        route = next(
            route
            for route in admin_accounts_router.routes
            if route.path == path and method in route.methods
        )
        dependencies = {
            dependency.call.__name__ for dependency in route.dependant.dependencies
        }
        assert "require_cookie_csrf" in dependencies, (path, method)
        assert "require_recent_mfa" in dependencies, (path, method)


class _AccountResult:
    def __init__(self, row: tuple[object, str | None] | None) -> None:
        self._row = row

    def first(self) -> tuple[object, str | None] | None:
        return self._row


class _ScalarResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _EmptyScalarsResult:
    def scalars(self) -> _EmptyScalarsResult:
        return self

    def all(self) -> list[object]:
        return []


class _ScalarsResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> _ScalarsResult:
        return self

    def all(self) -> list[object]:
        return self._values


def _account(*, agency_id: uuid.UUID, role: str = UserRole.AGENCY_STAFF.value) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        role=role,
        email="staff@example.test",
        hashed_password="existing-password-hash",
        is_active=True,
        deleted_at=None,
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
async def test_session_fence_revokes_refresh_tokens_and_existing_access_tokens() -> None:
    account = _account(agency_id=uuid.uuid4())
    state = SimpleNamespace(session_version=4, updated_at=None)
    session = SimpleNamespace()
    identity_repository = SimpleNamespace(get_state=AsyncMock(return_value=state))
    refresh_tokens = SimpleNamespace(revoke_all_for_user=AsyncMock())

    with (
        patch(
            "app.presentation.api.v1.routes.admin_accounts.IdentitySecurityRepository",
            return_value=identity_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts.RefreshTokenRepository",
            return_value=refresh_tokens,
        ),
    ):
        await _fence_dashboard_sessions(session, account)  # type: ignore[arg-type]

    identity_repository.get_state.assert_awaited_once_with(account.id, lock=True)
    refresh_tokens.revoke_all_for_user.assert_awaited_once_with(account.id)
    assert state.session_version == 5
    assert state.updated_at is not None


@pytest.mark.asyncio
async def test_coordinator_session_fence_revokes_mobile_access_and_refresh_families() -> None:
    agency_id = uuid.uuid4()
    coordinator = _account(
        agency_id=agency_id,
        role=UserRole.AGENCY_COORDINATOR.value,
    )
    session = SimpleNamespace()
    revoke_mobile = AsyncMock()

    with patch(
        "app.presentation.api.v1.routes.admin_accounts.revoke_user_mobile_sessions",
        new=revoke_mobile,
    ):
        await _fence_coordinator_mobile_sessions(  # type: ignore[arg-type]
            session,
            coordinator,
            reason="credential_reset",
        )

    revoke_mobile.assert_awaited_once_with(
        session,
        agency_id=agency_id,
        user_id=coordinator.id,
        subject_role="coordinator",
        reason="credential_reset",
    )


@pytest.mark.asyncio
async def test_supervised_mfa_reset_clears_factors_and_revokes_sessions() -> None:
    agency_id = uuid.uuid4()
    account = _account(agency_id=agency_id)
    manager = _manager(agency_id=agency_id)
    state = SimpleNamespace(mfa_required=True)
    session = SimpleNamespace()
    identity_repository = SimpleNamespace(
        get_state=AsyncMock(return_value=state),
        reset_mfa=AsyncMock(),
    )
    refresh_tokens = SimpleNamespace(revoke_all_for_user=AsyncMock())
    audit = AsyncMock()
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    with (
        patch(
            "app.presentation.api.v1.routes.admin_accounts._get_manageable_account",
            AsyncMock(return_value=(account, "Agency")),
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts.IdentitySecurityRepository",
            return_value=identity_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts.RefreshTokenRepository",
            return_value=refresh_tokens,
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts._audit_account_action",
            new=audit,
        ),
    ):
        response = await reset_managed_account_mfa(
            account_id=account.id,
            request=request,  # type: ignore[arg-type]
            current_user=manager,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )

    identity_repository.reset_mfa.assert_awaited_once_with(state=state)
    refresh_tokens.revoke_all_for_user.assert_awaited_once_with(account.id)
    audit.assert_awaited_once()
    assert response.status_code == 204
    assert response.headers["Cache-Control"] == "private, no-store, max-age=0"


@pytest.mark.asyncio
async def test_coordinator_deactivation_locks_every_active_group_deterministically() -> None:
    agency_id = uuid.uuid4()
    coordinator = _account(
        agency_id=agency_id,
        role=UserRole.AGENCY_COORDINATOR.value,
    )
    group_ids = [uuid.uuid4(), uuid.uuid4()]
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _ScalarsResult(list(reversed(group_ids))),
                SimpleNamespace(),
                SimpleNamespace(),
                SimpleNamespace(),
            ]
        )
    )

    await _deactivate_coordinator_assignments(  # type: ignore[arg-type]
        session,
        coordinator,
    )

    assert session.execute.await_count == 4
    lock_statement = session.execute.await_args_list[1].args[0]
    lock_sql = str(lock_statement.compile(dialect=postgresql.dialect()))
    assert "FROM client_groups" in lock_sql
    assert "ORDER BY client_groups.id ASC" in lock_sql
    assert "FOR UPDATE OF client_groups" in lock_sql
    locked_ids = next(
        value
        for value in lock_statement.compile().params.values()
        if isinstance(value, list)
    )
    assert locked_ids == sorted(set(group_ids), key=str)


@pytest.mark.asyncio
async def test_deleting_staff_revokes_sessions_audits_and_removes_account() -> None:
    agency_id = uuid.uuid4()
    staff = _account(agency_id=agency_id)
    manager = _manager(agency_id=agency_id)
    session = SimpleNamespace(
        delete=AsyncMock(),
        execute=AsyncMock(return_value=_ScalarResult(0)),
        flush=AsyncMock(),
    )
    refresh_tokens = SimpleNamespace(revoke_all_for_user=AsyncMock())
    session_fence = AsyncMock()
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
            "app.presentation.api.v1.routes.admin_accounts._fence_dashboard_sessions",
            new=session_fence,
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

    session_fence.assert_awaited_once_with(session, staff)
    audit_logs.record.assert_awaited_once()
    session.delete.assert_awaited_once_with(staff)
    session.flush.assert_awaited_once()
    assert result.result == "deleted"
    assert result.preserved_history is False


@pytest.mark.asyncio
async def test_deleting_coordinator_with_attendance_history_removes_login_but_preserves_history() -> None:
    agency_id = uuid.uuid4()
    coordinator = _account(
        agency_id=agency_id,
        role=UserRole.AGENCY_COORDINATOR.value,
    )
    coordinator.email = "coordinator@example.test"
    manager = _manager(agency_id=agency_id)
    session = SimpleNamespace(
        delete=AsyncMock(),
        execute=AsyncMock(
            side_effect=[
                _ScalarResult(0),
                _ScalarResult(1),
                _ScalarResult(0),
            ]
        ),
        flush=AsyncMock(),
    )
    refresh_tokens = SimpleNamespace(revoke_all_for_user=AsyncMock())
    session_fence = AsyncMock()
    audit_logs = SimpleNamespace(record=AsyncMock())
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    deactivate_assignments = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.admin_accounts._get_manageable_account",
            AsyncMock(return_value=(coordinator, "Agency")),
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts._deactivate_coordinator_assignments",
            deactivate_assignments,
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts.RefreshTokenRepository",
            return_value=refresh_tokens,
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts._fence_dashboard_sessions",
            new=session_fence,
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts.AuditLogRepository",
            return_value=audit_logs,
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts.hash_password",
            return_value="revoked-password-hash",
        ),
    ):
        result = await delete_managed_account(
            account_id=coordinator.id,
            request=request,  # type: ignore[arg-type]
            current_user=manager,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )

    session_fence.assert_awaited_once_with(session, coordinator)
    deactivate_assignments.assert_awaited_once_with(session, coordinator)
    audit_logs.record.assert_awaited_once()
    session.delete.assert_not_awaited()
    session.flush.assert_awaited_once()
    assert coordinator.is_active is False
    assert coordinator.deleted_at is not None
    assert coordinator.updated_at == coordinator.deleted_at
    assert coordinator.email == f"deleted-{coordinator.id}@deleted.invalid"
    assert coordinator.hashed_password == "revoked-password-hash"
    assert result.result == "deleted"
    assert result.preserved_history is True


@pytest.mark.asyncio
async def test_deleting_staff_with_an_owned_mailbox_scrubs_credentials_and_preserves_owner() -> None:
    agency_id = uuid.uuid4()
    staff = _account(agency_id=agency_id)
    manager = _manager(agency_id=agency_id)
    session = SimpleNamespace(
        delete=AsyncMock(),
        execute=AsyncMock(side_effect=[_ScalarResult(1), SimpleNamespace()]),
        flush=AsyncMock(),
    )
    refresh_tokens = SimpleNamespace(revoke_all_for_user=AsyncMock())
    session_fence = AsyncMock()
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
            "app.presentation.api.v1.routes.admin_accounts._fence_dashboard_sessions",
            new=session_fence,
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts.AuditLogRepository",
            return_value=audit_logs,
        ),
        patch(
            "app.presentation.api.v1.routes.admin_accounts.hash_password",
            return_value="revoked-password-hash",
        ),
    ):
        result = await delete_managed_account(
            account_id=staff.id,
            request=request,  # type: ignore[arg-type]
            current_user=manager,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
        )

    session.delete.assert_not_awaited()
    session_fence.assert_awaited_once_with(session, staff)
    assert result.preserved_history is True
    assert staff.is_active is False
    assert staff.deleted_at is not None
    update_statement = session.execute.await_args_list[1].args[0]
    assert "UPDATE email_connections" in str(update_statement)
    assert "owner_user_id" in str(update_statement)


@pytest.mark.asyncio
async def test_coordinator_listing_excludes_deleted_accounts() -> None:
    agency_id = uuid.uuid4()
    session = SimpleNamespace(execute=AsyncMock(return_value=_EmptyScalarsResult()))

    result = await list_coordinators(
        current_user=_manager(agency_id=agency_id),  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )

    assert result == []
    statement = session.execute.await_args.args[0]
    assert "users.deleted_at IS NULL" in str(statement)
