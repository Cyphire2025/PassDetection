"""Independent, reversible access decisions for directly authorized connections."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.infrastructure.database.mcp_models import (
    MCPAuthorizationCodeModel,
    MCPGrantModel,
    MCPTokenModel,
)
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import AgencyModel, AuditLogModel
from tests.dashboard_session_fixtures import issue_dashboard_access
from tests.integration.test_mcp_authorization import (
    CLIENT,
    REDIRECT,
    RESOURCE,
    VERIFIER,
    call_mcp,
    connect,
    consent,
)
from tests.integration.test_mcp_authorization import (
    mcp_fixture as mcp_fixture,
)
from tests.integration.test_mcp_operations import (
    execute,
    service,
)
from tests.integration.test_mcp_operations import (
    operations_fixture as operations_fixture,
)


async def authorize_device(fixture, *, name="Office PC", platform="Windows"):
    client, session, _, _, _, dashboard = fixture
    response = await client.post(
        "/api/v1/admin/mcp/authorize",
        json={**consent(), "name": name, "device_platform": platform},
        headers={"Authorization": f"Bearer {dashboard}"},
    )
    assert response.status_code == 200, response.text
    code = parse_qs(urlsplit(response.json()["redirect_url"]).query)["code"][0]
    code_row = await session.get(
        MCPAuthorizationCodeModel, MCPAuthorizationService(session, fixture[2]).digest(code)
    )
    grant = await session.get(MCPGrantModel, code_row.grant_id)
    return code, grant


async def exchange(client, code):
    return await client.post(
        "/oauth/mcp/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT,
            "redirect_uri": REDIRECT,
            "resource": RESOURCE,
            "code": code,
            "code_verifier": VERIFIER,
        },
    )


async def set_access(fixture, grant_id, enabled):
    return await fixture[0].patch(
        f"/api/v1/admin/mcp/connections/{grant_id}/access",
        json={"enabled": enabled},
        headers={"Authorization": f"Bearer {fixture[5]}"},
    )


async def test_disable_is_independent_reversible_and_retains_refresh_credentials(mcp_fixture):
    client, session, settings, user, _, dashboard = mcp_fixture
    connections = []
    for name, platform in (("Office PC", "Windows"), ("Travel MacBook", "macOS")):
        code, grant = await authorize_device(mcp_fixture, name=name, platform=platform)
        token_response = await exchange(client, code)
        assert token_response.status_code == 200, token_response.text
        connections.append((grant, token_response.json()))
    first, second = connections
    original_capabilities = list(first[0].capabilities)
    disabled = await set_access(mcp_fixture, first[0].id, False)
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"
    assert disabled.json()["enabled"] is False
    assert disabled.json()["device_platform"] == "Windows"
    assert disabled.json()["capabilities"] == original_capabilities
    assert disabled.json()["revoked_at"] is None
    assert first[0].revocation_reason is None
    with pytest.raises(MCPAuthError) as denied:
        await MCPAuthorizationService(session, settings).verify_access(first[1]["access_token"])
    assert (denied.value.error, denied.value.status_code) == ("access_denied", 403)
    # The SDK token-verifier adapter represents denied bearer credentials as 401.
    assert (await call_mcp(client, first[1]["access_token"])).status_code == 401
    assert (await call_mcp(client, second[1]["access_token"])).status_code == 200
    refresh_fields = {
        "grant_type": "refresh_token",
        "client_id": CLIENT,
        "resource": RESOURCE,
        "refresh_token": first[1]["refresh_token"],
    }
    paused_refresh = await client.post("/oauth/mcp/token", data=refresh_fields)
    assert paused_refresh.status_code == 403
    assert paused_refresh.json()["error"] == "access_denied"
    refresh_row = await session.get(
        MCPTokenModel, MCPAuthorizationService(session, settings).digest(first[1]["refresh_token"])
    )
    assert refresh_row.consumed_at is None
    listing = await client.get(
        "/api/v1/admin/mcp/connections", headers={"Authorization": f"Bearer {dashboard}"}
    )
    devices = {row["id"]: row for row in listing.json()["items"]}
    assert len(devices) == 2
    assert devices[str(first[0].id)]["status"] == "disabled"
    assert devices[str(second[0].id)]["status"] == "active"
    assert devices[str(second[0].id)]["device_platform"] == "macOS"
    enabled = await set_access(mcp_fixture, first[0].id, True)
    assert enabled.status_code == 200 and enabled.json()["status"] == "active"
    assert (await call_mcp(client, first[1]["access_token"])).status_code == 200
    resumed_refresh = await client.post("/oauth/mcp/token", data=refresh_fields)
    assert resumed_refresh.status_code == 200, resumed_refresh.text
    assert resumed_refresh.json()["refresh_token"] != first[1]["refresh_token"]
    assert second[0].enabled is True
    assert first[0].capabilities == original_capabilities and first[0].revoked_at is None
    audits = list((await session.scalars(select(AuditLogModel).where(
        AuditLogModel.action == "mcp.connection_access_changed"
    ).order_by(AuditLogModel.created_at))).all())
    assert [row.metadata_json["enabled"] for row in audits] == [False, True]
    assert all(row.entity_id == str(first[0].id) and row.user_id == user.id for row in audits)


async def test_disable_before_code_exchange_does_not_consume_code(mcp_fixture):
    client, session, settings, *_ = mcp_fixture
    code, grant = await authorize_device(mcp_fixture)
    assert (await set_access(mcp_fixture, grant.id, False)).status_code == 200
    denied = await exchange(client, code)
    assert denied.status_code == 403 and denied.json()["error"] == "access_denied"
    code_row = await session.get(
        MCPAuthorizationCodeModel, MCPAuthorizationService(session, settings).digest(code)
    )
    assert code_row.consumed_at is None
    assert await session.scalar(select(func.count()).select_from(MCPTokenModel)) == 0
    assert (await set_access(mcp_fixture, grant.id, True)).status_code == 200
    assert (await exchange(client, code)).status_code == 200


@pytest.mark.parametrize("terminal", ["expired", "revoked"])
async def test_enable_cannot_restore_expired_or_revoked_connection(mcp_fixture, terminal):
    _, session, _, _, _, dashboard = mcp_fixture
    _, grant = await authorize_device(mcp_fixture)
    assert (await set_access(mcp_fixture, grant.id, False)).status_code == 200
    if terminal == "revoked":
        grant.revoked_at = datetime.now(UTC)
        grant.revocation_reason = "administrator_revoked"
    else:
        grant.created_at = datetime.now(UTC) - timedelta(days=8)
        grant.expires_at = datetime.now(UTC) - timedelta(days=1)
    await session.commit()
    denied = await set_access(mcp_fixture, grant.id, True)
    assert denied.status_code == 409
    await session.refresh(grant)
    assert grant.enabled is False
    listing = await mcp_fixture[0].get(
        "/api/v1/admin/mcp/connections", headers={"Authorization": f"Bearer {dashboard}"}
    )
    assert listing.json()["items"][0]["status"] == terminal


@pytest.mark.parametrize("role", [
    "agency_admin", "agency_manager", "agency_staff", "agency_coordinator", "client_manager",
])
async def test_access_toggle_is_superadmin_only(mcp_fixture, role):
    _, session, _, user, _, _ = mcp_fixture
    _, grant = await authorize_device(mcp_fixture)
    user.role = role
    await session.flush()
    denied = await set_access(mcp_fixture, grant.id, False)
    assert denied.status_code in {401, 403}
    assert grant.enabled is True


@pytest.mark.parametrize("guard", ["anonymous", "cookie_csrf", "stale_mfa"])
async def test_access_toggle_requires_authentication_cookie_csrf_and_recent_mfa(mcp_fixture, guard):
    client, session, _, user, _, dashboard = mcp_fixture
    _, grant = await authorize_device(mcp_fixture)
    headers = {}
    if guard == "cookie_csrf":
        client.cookies.set("access_token", dashboard)
        headers["Origin"] = "https://attacker.example"
    elif guard == "stale_mfa":
        stale, _ = await issue_dashboard_access(
            session,
            user.id,
            "super_admin",
            session_version=1,
            authentication_methods=("pwd", "totp"),
            mfa_authenticated_at=datetime.now(UTC) - timedelta(minutes=11),
        )
        headers["Authorization"] = f"Bearer {stale}"
    denied = await client.patch(
        f"/api/v1/admin/mcp/connections/{grant.id}/access",
        json={"enabled": False},
        headers=headers,
    )
    assert denied.status_code == (401 if guard == "anonymous" else 403)
    assert grant.enabled is True


async def test_old_consent_remains_enabled_without_platform_and_toggle_inputs_are_bounded(mcp_fixture):
    client, session, _, _, _, dashboard = mcp_fixture
    await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    assert grant.enabled is True and grant.device_platform is None
    headers = {"Authorization": f"Bearer {dashboard}"}
    for body in ({"enabled": "false"}, {"enabled": False, "capabilities": []}):
        rejected = await client.patch(
            f"/api/v1/admin/mcp/connections/{grant.id}/access", json=body, headers=headers
        )
        assert rejected.status_code == 422
    invalid_platform = await client.post(
        "/api/v1/admin/mcp/authorize",
        json={**consent(), "device_platform": "untrusted-system-value"},
        headers=headers,
    )
    assert invalid_platform.status_code == 422
    missing = await client.patch(
        f"/api/v1/admin/mcp/connections/{uuid.uuid4()}/access",
        json={"enabled": False},
        headers=headers,
    )
    assert missing.status_code == 404 and grant.enabled is True


async def test_disabled_operation_connection_blocks_new_work_replay_and_inspection(operations_fixture):
    session, _, _, grants, tokens = operations_fixture
    receipt = await execute(operations_fixture)
    grants[0].enabled = False
    await session.flush()
    for operation in (
        lambda: execute(operations_fixture),
        lambda: execute(operations_fixture, key="new-work-must-not-start"),
        lambda: service(operations_fixture).inspect(
            access_token=tokens[0], operation_id=uuid.UUID(receipt["operation_id"])
        ),
    ):
        with pytest.raises(MCPAuthError) as denied:
            await operation()
        assert (denied.value.error, denied.value.status_code) == ("access_denied", 403)
    assert await execute(operations_fixture, token_index=1) == receipt
    assert await session.scalar(select(func.count()).select_from(AgencyModel)) == 1
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 1
    grants[0].enabled = True
    await session.flush()
    assert await execute(operations_fixture) == receipt


async def test_devices_hide_only_explicitly_removed_revoked_grants(mcp_fixture):
    client, session, _, user, _, dashboard = mcp_fixture
    now = datetime.now(UTC)
    cases = (
        ("removed", True, "administrator_removed", True, False),
        ("normally disconnected", True, "administrator_revoked", True, True),
        ("revoked without reason", True, None, True, True),
        ("refresh reuse", True, "refresh_reuse", True, True),
        ("active without reason", False, None, True, True),
        ("active with reserved marker", False, "administrator_removed", True, True),
        ("disabled with reserved marker", False, "administrator_removed", False, True),
        ("different marker", True, "administrator_removed_extra", True, True),
    )
    grants = []
    expected = set()
    for name, revoked, reason, enabled, visible in cases:
        grant = MCPGrantModel(
            id=uuid.uuid4(), user_id=user.id, client_id=CLIENT, name=name,
            resource=RESOURCE, capabilities=["mcp:read"], security_version=1,
            mfa_at=now, created_at=now - timedelta(minutes=1),
            expires_at=now + timedelta(days=1), enabled=enabled,
            revoked_at=now if revoked else None, revocation_reason=reason,
        )
        grants.append(grant)
        if visible:
            expected.add(str(grant.id))
    session.add_all(grants)
    await session.commit()
    response = await client.get(
        "/api/v1/admin/mcp/connections", headers={"Authorization": f"Bearer {dashboard}"}
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {row["id"] for row in items} == expected
    assert response.json()["next_offset"] is None
    assert all("revocation_reason" not in row for row in items)
    assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == len(cases)
    await session.refresh(grants[0])
    assert grants[0].revoked_at is not None and grants[0].revocation_reason == "administrator_removed"


async def test_removed_device_filter_precedes_pagination_and_preserves_revoked_credentials(mcp_fixture):
    client, session, settings, user, _, dashboard = mcp_fixture
    _, tokens = await connect(mcp_fixture)
    removed = await session.scalar(select(MCPGrantModel))
    now = datetime.now(UTC)
    removed.revoked_at, removed.revocation_reason = now, "administrator_removed"
    removed.created_at = now
    visible = []
    for index in range(3):
        grant = MCPGrantModel(
            id=uuid.uuid4(), user_id=user.id, client_id=CLIENT, name=f"Visible connection {index}",
            resource=RESOURCE, capabilities=["mcp:read"], security_version=1,
            mfa_at=now, created_at=now - timedelta(minutes=index + 1),
            expires_at=now + timedelta(days=1), enabled=True,
        )
        session.add(grant)
        visible.append(grant)
    await session.commit()
    auth_rows_before = [
        await session.scalar(select(func.count()).select_from(model))
        for model in (MCPGrantModel, MCPTokenModel, MCPAuthorizationCodeModel)
    ]
    headers = {"Authorization": f"Bearer {dashboard}"}
    first = await client.get("/api/v1/admin/mcp/connections?limit=2", headers=headers)
    assert first.status_code == 200, first.text
    assert [row["id"] for row in first.json()["items"]] == [str(row.id) for row in visible[:2]]
    assert first.json()["next_offset"] == 2
    second = await client.get("/api/v1/admin/mcp/connections?limit=2&offset=2", headers=headers)
    assert [row["id"] for row in second.json()["items"]] == [str(visible[2].id)]
    assert second.json()["next_offset"] is None
    assert [
        await session.scalar(select(func.count()).select_from(model))
        for model in (MCPGrantModel, MCPTokenModel, MCPAuthorizationCodeModel)
    ] == auth_rows_before
    with pytest.raises(MCPAuthError) as denied:
        await MCPAuthorizationService(session, settings).verify_access(tokens["access_token"])
    assert denied.value.error == "invalid_grant"
    refresh = await client.post("/oauth/mcp/token", data={
        "grant_type": "refresh_token", "client_id": CLIENT, "resource": RESOURCE,
        "refresh_token": tokens["refresh_token"],
    })
    assert refresh.status_code == 400 and refresh.json()["error"] == "invalid_grant"
    refresh_row = await session.get(
        MCPTokenModel, MCPAuthorizationService(session, settings).digest(tokens["refresh_token"])
    )
    assert refresh_row.consumed_at is None
    assert (await set_access(mcp_fixture, removed.id, True)).status_code == 409
    assert (await client.post(f"/api/v1/admin/mcp/connections/{removed.id}/revoke", headers=headers)).status_code == 200
    await session.refresh(removed)
    assert removed.revocation_reason == "administrator_removed"
