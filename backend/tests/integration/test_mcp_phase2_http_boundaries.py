"""Additional Phase 2 evidence through the real local HTTP application.

These cases complement the access-token matrix with refresh denial, durable
administrative revocation, resource binding and absolute credential deadlines.
Only each test's synthetic SQLite authority is changed; no provider is used.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select

from app.application.mcp import authorization
from app.application.mcp.credentials import utc
from app.infrastructure.database.mcp_models import (
    MCPAuthorizationCodeModel,
    MCPGrantModel,
    MCPTokenModel,
)
from app.presentation.api.v1.routes import mcp_admin
from tests.integration.test_mcp_authorization import (
    CLIENT,
    REDIRECT,
    RESOURCE,
    VERIFIER,
    call_mcp,
    connect,
    consent,
)
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


def _refresh_fields(tokens):
    return {"grant_type": "refresh_token", "client_id": CLIENT,
            "resource": RESOURCE, "refresh_token": tokens["refresh_token"]}


@pytest.mark.parametrize("change", [
    "expired_refresh", "expired_grant", "revoked", "role", "inactive",
    "deleted", "security_version", "mfa_removed", "wrong_grant_resource",
])
async def test_refresh_http_denies_changed_authority_without_issuing_or_consuming(
    mcp_fixture, change,
):
    client, session, _, user, security, _ = mcp_fixture
    _, tokens = await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    refresh = await session.scalar(select(MCPTokenModel).where(MCPTokenModel.kind == "refresh"))
    now = datetime.now(UTC)
    if change == "expired_refresh":
        refresh.expires_at = now - timedelta(seconds=1)
    elif change == "expired_grant":
        grant.created_at, grant.expires_at = now - timedelta(days=8), now - timedelta(seconds=1)
    elif change == "revoked":
        grant.revoked_at = now
    elif change == "role":
        user.role = "agency_admin"
    elif change == "inactive":
        user.is_active = False
    elif change == "deleted":
        user.deleted_at = now
    elif change == "security_version":
        security.session_version += 1
    elif change == "mfa_removed":
        security.mfa_enabled_at = None
        security.mfa_secret_ciphertext = None
    else:
        grant.resource = "https://different.example.test/mcp"
    await session.commit()
    response = await client.post("/oauth/mcp/token", data=_refresh_fields(tokens))
    expected = "invalid_target" if change == "wrong_grant_resource" else "invalid_grant"
    assert response.status_code == 400 and response.json() == {"error": expected}
    assert response.headers["cache-control"] == "no-store"
    assert not response.headers.get_list("set-cookie")
    await session.refresh(refresh)
    assert refresh.consumed_at is None
    assert await session.scalar(select(func.count()).select_from(MCPTokenModel)) == 2
    assert tokens["access_token"] not in response.text and tokens["refresh_token"] not in response.text


async def test_wrong_resource_refresh_preserves_legitimate_refresh(mcp_fixture):
    client, session, _, _, _, _ = mcp_fixture
    _, tokens = await connect(mcp_fixture)
    fields = _refresh_fields(tokens)
    denied = await client.post("/oauth/mcp/token", data={**fields, "resource": RESOURCE + "/other"})
    assert denied.status_code == 400 and denied.json() == {"error": "invalid_target"}
    accepted = await client.post("/oauth/mcp/token", data=fields)
    assert accepted.status_code == 200
    assert (await call_mcp(client, accepted.json()["access_token"])).status_code == 200
    grant = await session.scalar(select(MCPGrantModel))
    assert grant.revoked_at is None


async def test_wrong_resource_access_binding_is_rejected_before_tool_dispatch(mcp_fixture):
    client, session, _, _, _, _ = mcp_fixture
    _, tokens = await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    grant.resource = "https://different.example.test/mcp"
    await session.commit()
    denied = await call_mcp(client, tokens["access_token"])
    assert denied.status_code == 401
    assert "oauth-protected-resource/mcp" in denied.headers["www-authenticate"]
    assert "connection_id" not in denied.text and tokens["access_token"] not in denied.text


async def test_admin_http_revocation_updates_status_and_denies_both_credentials(mcp_fixture):
    client, session, _, _, _, dashboard = mcp_fixture
    _, tokens = await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    headers = {"Authorization": f"Bearer {dashboard}"}
    before = await client.get("/api/v1/admin/mcp/connections", headers=headers)
    assert before.json()["items"][0]["status"] == "active"
    revoked = await client.post(f"/api/v1/admin/mcp/connections/{grant.id}/revoke", headers=headers)
    assert revoked.status_code == 200 and revoked.json() == {"revoked": True}
    after = await client.get("/api/v1/admin/mcp/connections", headers=headers)
    item = after.json()["items"][0]
    assert item["id"] == str(grant.id) and item["status"] == "revoked" and item["revoked_at"]
    assert (await call_mcp(client, tokens["access_token"])).status_code == 401
    refresh = await client.post("/oauth/mcp/token", data=_refresh_fields(tokens))
    assert refresh.status_code == 400 and refresh.json() == {"error": "invalid_grant"}
    assert await session.scalar(select(func.count()).select_from(MCPTokenModel)) == 2


async def test_rotation_near_absolute_expiry_cannot_extend_grant_and_admin_reports_expired(
    mcp_fixture, monkeypatch,
):
    client, session, _, _, _, dashboard = mcp_fixture
    _, tokens = await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    deadline = utc(grant.expires_at)

    class Clock:
        current = deadline - timedelta(seconds=30)

        @classmethod
        def now(cls, _tz=None):
            return cls.current

    monkeypatch.setattr(authorization, "datetime", Clock)
    monkeypatch.setattr(mcp_admin, "datetime", Clock)
    result = await client.post("/oauth/mcp/token", data=_refresh_fields(tokens))
    assert result.status_code == 200 and result.json()["expires_in"] == 30
    rows = list(await session.scalars(select(MCPTokenModel).where(
        MCPTokenModel.created_at == Clock.current)))
    assert {row.kind for row in rows} == {"access", "refresh"}
    assert all(utc(row.expires_at) == deadline for row in rows)
    await session.refresh(grant)
    assert utc(grant.expires_at) == deadline
    Clock.current = deadline
    denied = await client.post("/oauth/mcp/token", data=_refresh_fields(result.json()))
    assert denied.status_code == 400 and denied.json() == {"error": "invalid_grant"}
    listing = await client.get("/api/v1/admin/mcp/connections",
                               headers={"Authorization": f"Bearer {dashboard}"})
    assert listing.status_code == 200
    assert listing.json()["items"][0]["status"] == "expired"


async def test_expired_authorization_code_is_not_consumed_and_issues_no_credentials(mcp_fixture):
    client, session, _, _, _, dashboard = mcp_fixture
    response = await client.post("/api/v1/admin/mcp/authorize", json=consent(),
                                 headers={"Authorization": f"Bearer {dashboard}"})
    code = parse_qs(urlsplit(response.json()["redirect_url"]).query)["code"][0]
    row = await session.scalar(select(MCPAuthorizationCodeModel))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    denied = await client.post("/oauth/mcp/token", data={
        "grant_type": "authorization_code", "client_id": CLIENT, "redirect_uri": REDIRECT,
        "resource": RESOURCE, "code": code, "code_verifier": VERIFIER,
    })
    assert denied.status_code == 400 and denied.json() == {"error": "invalid_grant"}
    assert denied.headers["cache-control"] == "no-store"
    await session.refresh(row)
    assert row.consumed_at is None
    assert await session.scalar(select(func.count()).select_from(MCPTokenModel)) == 0


async def test_mcp_access_credential_cannot_be_used_as_dashboard_management_authority(mcp_fixture):
    client, session, _, _, _, _ = mcp_fixture
    _, tokens = await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert (await client.get("/api/v1/admin/mcp/connections", headers=headers)).status_code == 401
    denied = await client.post(f"/api/v1/admin/mcp/connections/{grant.id}/revoke", headers=headers)
    assert denied.status_code == 401
    await session.refresh(grant)
    assert grant.revoked_at is None
    assert (await call_mcp(client, tokens["access_token"])).status_code == 200
