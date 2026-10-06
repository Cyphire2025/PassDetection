from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.domain.entities.entities import User, UserRole
from app.presentation.api.v1.routes import admin
from app.presentation.api.v1.schemas.operations_schemas import UpdatePlatformSettingsRequest


class _Result:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        return self.value


class _Session:
    def __init__(self, row: object | None) -> None:
        self.row = row
        self.statement: object | None = None
        self.added: list[object] = []

    async def execute(self, statement: object) -> _Result:
        self.statement = statement
        return _Result(self.row)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def refresh(self, _value: object) -> None:
        return None


def _admin() -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.com",
        hashed_password="unused",
        full_name="Admin",
        role=UserRole.SUPER_ADMIN,
        agency_id=None,
    )


def _request(*, expected_updated_at: datetime | None) -> UpdatePlatformSettingsRequest:
    return UpdatePlatformSettingsRequest(
        expected_updated_at=expected_updated_at,
        platform_name="Global Connects Dashboard",
        require_client_email=False,
        require_client_phone=False,
        duplicate_contact_policy="block_same_group",
        default_group_status="active",
        auto_archive_closed_groups_days=90,
        passport_data_retention_days=365,
        mrz_review_threshold=0.85,
        allow_manager_group_creation=True,
        audit_log_retention_days=365,
    )


def test_update_platform_settings_request_forbids_extra_and_naive_revision() -> None:
    with pytest.raises(ValidationError):
        UpdatePlatformSettingsRequest.model_validate(
            {**_request(expected_updated_at=None).model_dump(), "unexpected": True}
        )
    with pytest.raises(ValidationError):
        _request(expected_updated_at=datetime(2026, 8, 25, 12, 0))


@pytest.mark.asyncio
async def test_existing_platform_settings_require_exact_locked_revision() -> None:
    current = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
    row = SimpleNamespace(updated_at=current, value={})
    session = _Session(row)

    with pytest.raises(HTTPException) as exc_info:
        await admin.update_platform_settings(
            body=_request(expected_updated_at=None),
            current_user=_admin(),
            session=session,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == admin.PLATFORM_SETTINGS_REVISION_CONFLICT
    assert "FOR UPDATE" in str(session.statement)


@pytest.mark.asyncio
async def test_matching_platform_settings_revision_is_not_persisted_or_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = datetime(2026, 8, 25, 10, 0, 0, 123456, tzinfo=UTC)
    row = SimpleNamespace(updated_at=current, value={})
    session = _Session(row)
    audit: dict[str, Any] = {}

    class _AuditRepository:
        def __init__(self, _session: object) -> None:
            pass

        async def record(self, **kwargs: Any) -> None:
            audit.update(kwargs)

    monkeypatch.setattr(admin, "AuditLogRepository", _AuditRepository)
    response = await admin.update_platform_settings(
        body=_request(expected_updated_at=current),
        current_user=_admin(),
        session=session,  # type: ignore[arg-type]
    )

    assert response.updated_at == current
    assert "expected_updated_at" not in row.value
    assert "expected_updated_at" not in audit["metadata"]
    assert "FOR UPDATE" in str(session.statement)


@pytest.mark.asyncio
async def test_first_platform_settings_creation_requires_null_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session(None)

    class _AuditRepository:
        def __init__(self, _session: object) -> None:
            pass

        async def record(self, **_kwargs: Any) -> None:
            return None

    monkeypatch.setattr(admin, "AuditLogRepository", _AuditRepository)
    await admin.update_platform_settings(
        body=_request(expected_updated_at=None),
        current_user=_admin(),
        session=session,  # type: ignore[arg-type]
    )
    assert len(session.added) == 1

    stale_session = _Session(None)
    with pytest.raises(HTTPException) as exc_info:
        await admin.update_platform_settings(
            body=_request(expected_updated_at=datetime(2026, 8, 25, 10, 0, tzinfo=UTC)),
            current_user=_admin(),
            session=stale_session,  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 409


@pytest.mark.parametrize("role", [role for role in UserRole if role != UserRole.SUPER_ADMIN])
@pytest.mark.parametrize("existing", [False, True])
async def test_non_platform_admin_cannot_modify_or_create_global_policy(role, existing, monkeypatch):
    row = SimpleNamespace(updated_at=datetime.now(UTC), value={"passport_data_retention_days": 365})
    session = _Session(row if existing else None)
    user = _admin()
    user.role = role
    user.agency_id = uuid.uuid4()
    audit = Mock()
    monkeypatch.setattr(admin, "AuditLogRepository", audit)

    with pytest.raises(HTTPException) as denied:
        await admin.update_platform_settings(
            body=_request(expected_updated_at=row.updated_at if existing else None),
            current_user=user, session=session,
        )

    assert denied.value.status_code == 403
    assert session.statement is None
    assert session.added == []
    assert row.value == {"passport_data_retention_days": 365}
    audit.assert_not_called()


async def test_agency_admin_http_policy_read_is_allowed_but_write_is_denied():
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from httpx import ASGITransport, AsyncClient

    from app.domain.exceptions.exceptions import AuthorizationError
    from app.presentation.dependencies.auth import get_current_active_user

    user = _admin()
    user.role = UserRole.AGENCY_ADMIN
    user.agency_id = uuid.uuid4()
    session = _Session(None)
    app = FastAPI()
    app.include_router(admin.router, prefix="/admin")
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[admin.get_db_session] = lambda: session

    @app.middleware("http")
    async def trusted_auth_claims(request: Request, call_next):
        request.state.auth_claims = {"amr": ["totp"], "mfa_at": datetime.now(UTC).timestamp()}
        return await call_next(request)

    @app.exception_handler(AuthorizationError)
    async def denied(_request, _error):
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://example.test") as client:
        read = await client.get("/admin/settings")
        assert read.status_code == 200
        session.statement = None
        write = await client.put("/admin/settings", json=_request(expected_updated_at=None).model_dump(mode="json"))
    assert write.status_code == 403
    assert session.statement is None
    assert session.added == []
