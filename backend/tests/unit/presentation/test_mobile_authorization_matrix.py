from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.realtime_authorization import (
    load_mobile_realtime_authorization,
)
from app.application.security.mobile_access_policy import MobileAccessPolicy
from app.core.config.settings import Settings
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import AuthenticationError, AuthorizationError
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileDeviceSessionModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
)
from app.presentation.api.v1.router import api_v1_router
from app.presentation.api.v1.routes import mobile_realtime as realtime_route
from app.presentation.api.v1.routes.mobile_auth_session_support import (
    _refresh_principal,
)
from app.presentation.api.v1.routes.mobile_ops import (
    _require_client_manager_trip,
    _require_coordinator_trip,
)
from app.presentation.api.v1.routes.mobile_resources import (
    authorize_mobile_document_download,
    get_mobile_manager_readiness,
)
from app.presentation.dependencies.mobile_auth import (
    get_current_mobile_claims,
    require_unrestricted_mobile_claims,
)

RouteKey = tuple[str, str]

_PUBLIC_MOBILE_HTTP: frozenset[RouteKey] = frozenset(
    {
        ("POST", "/mobile/auth/otp/request"),
        ("POST", "/mobile/auth/otp/verify"),
        ("POST", "/mobile/auth/claim/verify"),
        ("POST", "/mobile/auth/login"),
        ("POST", "/mobile/auth/activate"),
        ("POST", "/mobile/auth/refresh"),
        ("GET", "/mobile/associations/apple"),
        ("HEAD", "/mobile/associations/apple"),
        ("GET", "/mobile/associations/android"),
        ("HEAD", "/mobile/associations/android"),
    }
)

_DIRECT_SESSION_MOBILE_HTTP: frozenset[RouteKey] = frozenset(
    {
        ("GET", "/mobile/auth/me"),
        ("POST", "/mobile/auth/passenger/trip/switch"),
        ("POST", "/mobile/auth/password/change"),
        ("POST", "/mobile/auth/logout"),
        ("POST", "/mobile/auth/logout-all"),
        ("GET", "/mobile/me"),
    }
)

_UNRESTRICTED_SESSION_MOBILE_HTTP: frozenset[RouteKey] = frozenset(
    {
        ("GET", "/mobile/trips"),
        ("GET", "/mobile/trips/{group_id}/manifest"),
        ("GET", "/mobile/sync/snapshot"),
        ("GET", "/mobile/sync/changes"),
        ("POST", "/mobile/sync/ack"),
        ("GET", "/mobile/trips/{group_id}/itinerary"),
        ("GET", "/mobile/trips/{group_id}/announcements"),
        ("GET", "/mobile/trips/{group_id}/common-documents"),
        ("GET", "/mobile/trips/{group_id}/personal-documents"),
        ("GET", "/mobile/trips/{group_id}/documents"),
        ("POST", "/mobile/trips/{group_id}/documents/{document_id}/authorize"),
        (
            "GET",
            "/mobile/trips/{group_id}/personal-documents/{document_id}/content",
        ),
        (
            "GET",
            "/mobile/trips/{group_id}/common-documents/{document_id}/content",
        ),
        ("GET", "/mobile/trips/{group_id}/documents/{document_id}/content"),
        ("GET", "/mobile/trips/{group_id}/room"),
        ("GET", "/mobile/trips/{group_id}/meals"),
        ("GET", "/mobile/trips/{group_id}/qr"),
        ("GET", "/mobile/manager/groups/{group_id}/readiness"),
        ("POST", "/mobile/integrity/challenges"),
        ("POST", "/mobile/integrity/app-attest/keys/register"),
        ("GET", "/mobile/coordinator/groups/{group_id}/passengers"),
        ("GET", "/mobile/manager/groups/{group_id}/passengers"),
        (
            "GET",
            "/mobile/coordinator/groups/{group_id}/passengers/{passenger_id}",
        ),
        ("GET", "/mobile/manager/groups/{group_id}/passengers/{passenger_id}"),
        (
            "GET",
            "/mobile/manager/groups/{group_id}/passengers/{passenger_id}/documents/"
            "{document_type}/preview",
        ),
        ("GET", "/mobile/coordinator/groups/{group_id}/attendance/sessions"),
        ("GET", "/mobile/manager/groups/{group_id}/attendance/sessions"),
        ("POST", "/mobile/coordinator/groups/{group_id}/attendance/sessions"),
        ("POST", "/mobile/manager/groups/{group_id}/attendance/sessions"),
        (
            "GET",
            "/mobile/coordinator/groups/{group_id}/attendance/sessions/{session_id}",
        ),
        (
            "GET",
            "/mobile/coordinator/groups/{group_id}/attendance/sessions/{session_id}/roster",
        ),
        (
            "PUT",
            "/mobile/coordinator/groups/{group_id}/attendance/sessions/{session_id}/closeout-checkpoint",
        ),
        (
            "GET",
            "/mobile/manager/groups/{group_id}/attendance/sessions/{session_id}/closeout",
        ),
        (
            "GET",
            "/mobile/manager/groups/{group_id}/attendance/sessions/{session_id}/roster",
        ),
        (
            "PUT",
            "/mobile/coordinator/groups/{group_id}/attendance/sessions/{session_id}/complete",
        ),
        (
            "PUT",
            "/mobile/manager/groups/{group_id}/attendance/sessions/{session_id}/complete",
        ),
        ("POST", "/mobile/coordinator/groups/{group_id}/attendance/actions"),
        ("GET", "/mobile/coordinator/groups/{group_id}/attendance/summary"),
        ("POST", "/mobile/coordinator/groups/{group_id}/incidents"),
        ("POST", "/mobile/push/register"),
        ("POST", "/mobile/push/unregister"),
        ("GET", "/mobile/notifications"),
        ("POST", "/mobile/notifications/{notification_id}/read"),
    }
)

_EXPECTED_MOBILE_HTTP = (
    _PUBLIC_MOBILE_HTTP | _DIRECT_SESSION_MOBILE_HTTP | _UNRESTRICTED_SESSION_MOBILE_HTTP
)


def _claims(
    role: str = "coordinator",
    *,
    principal_id: uuid.UUID | None = None,
    agency_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    generation: int = 7,
) -> MobileAccessClaims:
    principal = principal_id or uuid.uuid4()
    return MobileAccessClaims(
        principal_id=principal,
        account_id=principal,
        principal_type=role,  # type: ignore[arg-type]
        agency_id=agency_id or uuid.uuid4(),
        session_id=session_id or uuid.uuid4(),
        session_generation=generation,
        password_change_required=False,
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
    )


def _mobile_http_routes() -> dict[RouteKey, APIRoute]:
    routes: dict[RouteKey, APIRoute] = {}
    for route in api_v1_router.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/mobile"):
            continue
        for method in route.methods:
            key = (method, route.path)
            assert key not in routes, f"duplicate mobile route: {key}"
            routes[key] = route
    return routes


def _dependency_calls(route: APIRoute) -> list[object]:
    calls: list[object] = []
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        calls.append(dependency.call)
        pending.extend(dependency.dependencies)
    return calls


def test_every_mobile_http_route_has_an_explicit_authentication_classification() -> None:
    routes = _mobile_http_routes()

    assert set(routes) == _EXPECTED_MOBILE_HTTP
    for key in _PUBLIC_MOBILE_HTTP:
        calls = _dependency_calls(routes[key])
        assert get_current_mobile_claims not in calls
        assert require_unrestricted_mobile_claims not in calls
    for key in _DIRECT_SESSION_MOBILE_HTTP:
        calls = _dependency_calls(routes[key])
        assert get_current_mobile_claims in calls
        assert require_unrestricted_mobile_claims not in calls
    for key in _UNRESTRICTED_SESSION_MOBILE_HTTP:
        calls = _dependency_calls(routes[key])
        assert require_unrestricted_mobile_claims in calls
        assert get_current_mobile_claims in calls


def test_realtime_is_the_only_mobile_websocket_and_uses_custom_preaccept_auth() -> None:
    websocket_routes = {
        route.path: route
        for route in api_v1_router.routes
        if isinstance(route, APIWebSocketRoute) and route.path.startswith("/mobile")
    }

    assert set(websocket_routes) == {"/mobile/realtime"}
    code_names = set(websocket_routes["/mobile/realtime"].endpoint.__code__.co_names)
    assert "_bearer_token" in code_names
    assert "authorize_mobile_realtime" in code_names
    assert "accept" in code_names


def test_every_role_specific_ops_route_calls_its_shared_fail_closed_guard() -> None:
    routes = _mobile_http_routes()
    coordinator = {
        key: route for key, route in routes.items() if key[1].startswith("/mobile/coordinator/")
    }
    manager = {
        key: route
        for key, route in routes.items()
        if key[1].startswith("/mobile/manager/")
        and key[1] != "/mobile/manager/groups/{group_id}/readiness"
    }

    assert coordinator
    assert manager
    for route in coordinator.values():
        assert "_require_coordinator_trip" in route.endpoint.__code__.co_names
    for route in manager.values():
        assert "_require_client_manager_trip" in route.endpoint.__code__.co_names


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("guard", "wrong_role"),
    [
        (_require_coordinator_trip, "passenger"),
        (_require_coordinator_trip, "client_manager"),
        (_require_client_manager_trip, "passenger"),
        (_require_client_manager_trip, "coordinator"),
    ],
)
async def test_role_guards_reject_before_any_object_query(guard, wrong_role: str) -> None:
    session = MagicMock()
    session.execute = AsyncMock()

    with pytest.raises(AuthorizationError):
        await guard(session, _claims(wrong_role), uuid.uuid4())

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_manager_readiness_rejects_wrong_role_before_any_object_query() -> None:
    session = MagicMock()
    session.execute = AsyncMock()

    with pytest.raises(AuthorizationError, match="Client Manager"):
        await get_mobile_manager_readiness(
            group_id=uuid.uuid4(),
            claims=_claims("coordinator"),
            session=session,
        )

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_document_authorization_denies_trip_before_integrity_or_object_lookup() -> None:
    deny = AuthorizationError("Mobile trip access is not available")
    integrity = MagicMock()
    integrity.enforce_action = AsyncMock()
    resolver = AsyncMock()
    session = MagicMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_resources."
            "MobileAccessPolicy.require_trip_access",
            new=AsyncMock(side_effect=deny),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._resolve_mobile_document",
            new=resolver,
        ),
        pytest.raises(AuthorizationError, match="trip access"),
    ):
        await authorize_mobile_document_download(
            group_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            request=MagicMock(client=None),
            version=1,
            body=None,
            claims=_claims("passenger"),
            session=session,
            integrity_service=integrity,
        )

    integrity.enforce_action.assert_not_awaited()
    resolver.assert_not_awaited()


@pytest.mark.asyncio
async def test_access_policy_and_realtime_deny_cross_scope_and_lifecycle_rows(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    agency_id = uuid.uuid4()
    other_agency_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    other_principal_id = uuid.uuid4()
    db_session.add_all(
        [
            AgencyModel(
                id=agency_id,
                name="Authorization matrix agency",
                email=f"{agency_id}@example.test",
            ),
            AgencyModel(
                id=other_agency_id,
                name="Cross-tenant agency",
                email=f"{other_agency_id}@example.test",
            ),
            UserModel(
                id=principal_id,
                email=f"{principal_id}@example.test",
                hashed_password="not-used",
                full_name="Assigned coordinator",
                role="agency_coordinator",
                agency_id=agency_id,
            ),
            UserModel(
                id=other_principal_id,
                email=f"{other_principal_id}@example.test",
                hashed_password="not-used",
                full_name="Other coordinator",
                role="agency_coordinator",
                agency_id=agency_id,
            ),
        ]
    )
    await db_session.flush()

    group_specs = {
        "allowed": (agency_id, None),
        "cross_user_trip": (agency_id, None),
        "cross_tenant": (other_agency_id, None),
        "disabled": (agency_id, None),
        "role_disabled": (agency_id, None),
        "revoked": (agency_id, None),
        "soft_deleted": (agency_id, now),
    }
    groups: dict[str, ClientGroupModel] = {}
    for label, (group_agency_id, deleted_at) in group_specs.items():
        group = ClientGroupModel(
            id=uuid.uuid4(),
            name=label,
            token=f"{label}-{uuid.uuid4()}",
            agency_id=group_agency_id,
            status="active",
            deleted_at=deleted_at,
        )
        groups[label] = group
        db_session.add(group)
    await db_session.flush()

    accesses: dict[str, GCGroupAccessModel] = {}
    for label, group in groups.items():
        access = GCGroupAccessModel(
            agency_id=group.agency_id,
            group_id=group.id,
            is_enabled=label != "disabled",
            coordinator_access_enabled=label != "role_disabled",
            revoked_at=now if label == "revoked" else None,
        )
        accesses[label] = access
        db_session.add(access)
    await db_session.flush()

    for label, group in groups.items():
        if label == "cross_user_trip":
            assigned_user = other_principal_id
        else:
            assigned_user = principal_id
        db_session.add(
            CoordinatorGroupAssignmentModel(
                agency_id=group.agency_id,
                group_id=group.id,
                coordinator_user_id=assigned_user,
                active=True,
            )
        )
    await db_session.flush()

    claims = _claims(
        "coordinator",
        principal_id=principal_id,
        agency_id=agency_id,
    )
    policy = MobileAccessPolicy(db_session)

    allowed = await policy.require_trip_access(claims, groups["allowed"].id)
    assert allowed.group.id == groups["allowed"].id
    for label in (
        "cross_user_trip",
        "cross_tenant",
        "disabled",
        "role_disabled",
        "revoked",
        "soft_deleted",
    ):
        with pytest.raises(AuthorizationError, match="not available"):
            await policy.require_trip_access(claims, groups[label].id)

    realtime = await load_mobile_realtime_authorization(
        db_session,
        claims,
        maximum_trips=20,
    )
    assert realtime.trip_ids == frozenset({groups["allowed"].id})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("revoked_session", "session is no longer active"),
        ("expired_status", "session is no longer active"),
        ("generation_rotated", "session is no longer active"),
        ("disabled_account", "account is inactive"),
        ("role_downgraded", "account is inactive"),
    ],
)
async def test_live_dependency_rechecks_session_and_staff_account_state(
    db_session: AsyncSession,
    scenario: str,
    message: str,
) -> None:
    now = datetime.now(tz=UTC)
    agency_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    session_id = uuid.uuid4()
    agency = AgencyModel(
        id=agency_id,
        name="Session authorization agency",
        email=f"{agency_id}@example.test",
    )
    user = UserModel(
        id=principal_id,
        email=f"{principal_id}@example.test",
        hashed_password="not-used",
        full_name="Live coordinator",
        role="agency_coordinator",
        agency_id=agency_id,
        is_active=True,
    )
    device_session = MobileDeviceSessionModel(
        id=session_id,
        agency_id=agency_id,
        subject_role="coordinator",
        user_id=principal_id,
        account_id=principal_id,
        device_identifier_hash="d" * 64,
        platform="android",
        app_version="1.0.0",
        status="active",
        session_generation=7,
        refresh_family_id=uuid.uuid4(),
        last_seen_at=now,
        expires_at=now + timedelta(days=1),
        created_at=now - timedelta(minutes=1),
        updated_at=now,
    )
    if scenario == "revoked_session":
        device_session.status = "revoked"
        device_session.revoked_at = now
    elif scenario == "expired_status":
        device_session.status = "expired"
    elif scenario == "generation_rotated":
        device_session.session_generation = 8
    elif scenario == "disabled_account":
        user.is_active = False
    elif scenario == "role_downgraded":
        user.role = "agency_staff"
    else:  # pragma: no cover - guarded by the parameter table
        raise AssertionError(scenario)
    db_session.add_all([agency, user, device_session])
    await db_session.flush()

    claims = _claims(
        "coordinator",
        principal_id=principal_id,
        agency_id=agency_id,
        session_id=session_id,
        generation=7,
    )
    with (
        patch(
            "app.presentation.dependencies.mobile_auth.decode_mobile_access_token",
            return_value=claims,
        ),
        pytest.raises(AuthenticationError, match=message),
    ):
        await get_current_mobile_claims(
            HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials="authorization-matrix-token",
            ),
            db_session,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("row_count", [0, 2])
async def test_refresh_fails_closed_on_missing_or_ambiguous_selected_trip_access(
    row_count: int,
) -> None:
    identity = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        passenger_submission_id=uuid.uuid4(),
    )
    access = SimpleNamespace(id=uuid.uuid4())
    selected_access_id = uuid.uuid4()
    device_session = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=identity.agency_id,
        subject_role="passenger",
        passenger_identity_id=identity.id,
        selected_gc_group_access_id=selected_access_id,
        selected_group_id=identity.group_id,
    )
    result = MagicMock()
    result.all.return_value = [(identity, access)] * row_count
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    with pytest.raises(HTTPException) as caught:
        await _refresh_principal(session, device_session)

    assert caught.value.status_code == 401
    assert caught.value.detail == "Mobile identity is inactive"
    session.execute.assert_awaited_once()
    sql = str(session.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "JOIN gc_group_access" in sql
    assert "JOIN client_groups" in sql
    assert "gc_group_access.is_enabled IS true" in sql
    assert "gc_group_access.passenger_access_enabled IS true" in sql
    assert "gc_group_access.revoked_at IS NULL" in sql
    assert "gc_group_access.access_starts_at" in sql
    assert "gc_group_access.access_expires_at" in sql
    assert "client_groups.status IN ('active', 'closed')" in sql
    assert "client_groups.deleted_at IS NULL" in sql
    assert selected_access_id.hex in sql


@pytest.mark.asyncio
async def test_refresh_returns_the_exact_locked_access_used_for_offline_lease() -> None:
    identity = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        passenger_submission_id=uuid.uuid4(),
    )
    access = SimpleNamespace(id=uuid.uuid4(), access_generation=11)
    device_session = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=identity.agency_id,
        subject_role="passenger",
        passenger_identity_id=identity.id,
        selected_gc_group_access_id=access.id,
        selected_group_id=identity.group_id,
    )
    access_result = MagicMock()
    access_result.all.return_value = [(identity, access)]
    name_result = MagicMock()
    name_result.scalar_one.return_value = "Authorized passenger"
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[access_result, name_result])

    principal, name, password_change_required, selected_access = await _refresh_principal(
        session,
        device_session,
    )

    assert principal is identity
    assert name == "Authorized passenger"
    assert password_change_required is False
    assert selected_access is access
    passenger_sql = str(
        session.execute.await_args_list[1].args[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "passport_submissions.group_id" in passenger_sql
    assert identity.group_id.hex in passenger_sql


@pytest.mark.asyncio
async def test_realtime_rejects_invalid_session_before_accepting_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def rejected(_token: str, *, maximum_trips: int) -> None:
        assert maximum_trips == 100
        raise AuthenticationError("revoked")

    monkeypatch.setattr(realtime_route, "authorize_mobile_realtime", rejected)

    class _Hub:
        accepting_connections = True
        config = SimpleNamespace(max_trips_per_connection=100)

        def __init__(self) -> None:
            self.authorization_slots = 0
            self.registered = False

        async def begin_authorization(self) -> uuid.UUID:
            self.authorization_slots += 1
            return uuid.uuid4()

        async def end_authorization(self, _reservation_id: uuid.UUID) -> None:
            self.authorization_slots -= 1

        async def register(self, _authorization) -> None:
            self.registered = True
            raise AssertionError("an unauthorized socket must not be registered")

    class _Socket:
        query_params: dict[str, str] = {}
        headers = {"authorization": "Bearer revoked-token"}
        url = SimpleNamespace(scheme="wss", netloc="api.example.test")

        def __init__(self) -> None:
            self.accepted = False
            self.closed_code: int | None = None

        async def accept(self) -> None:
            self.accepted = True

        async def close(self, code: int) -> None:
            self.closed_code = code

    hub = _Hub()
    socket = _Socket()
    await realtime_route.mobile_realtime_socket(
        socket,  # type: ignore[arg-type]
        settings=Settings(app_secret_key="authorization-matrix-test", _env_file=None),
        hub=hub,  # type: ignore[arg-type]
    )

    assert socket.accepted is False
    assert socket.closed_code == 4401
    assert hub.registered is False
    assert hub.authorization_slots == 0
