"""First-party assistant authority is not an external OAuth/device credential."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.client_policy import validate_authorization_client, validate_client
from app.application.mcp.credentials import MCPAuthError
from app.domain.assistant_identity import ASSISTANT_CLIENT_ID
from app.infrastructure.database.mcp_models import MCPGrantModel
from tests.integration.test_mcp_authorization import (
    REDIRECT,
    RESOURCE,
    call_mcp,
    connect,
    consent,
)
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


async def private_grant(fixture):
    _, session, _, user, _, _ = fixture
    now = datetime.now(UTC)
    grant = MCPGrantModel(
        id=uuid.uuid4(), user_id=user.id, client_id=ASSISTANT_CLIENT_ID,
        name="Dashboard assistant", device_platform=None, resource=RESOURCE,
        capabilities=["mcp:read"], security_version=1, mfa_at=now,
        created_at=now, expires_at=now + timedelta(hours=1),
        enabled=True, read_enabled=True, write_enabled=False,
        allowed_read_sections=None, allowed_write_sections=[], permission_revision=1,
    )
    session.add(grant)
    await session.commit()
    return grant


async def test_reserved_identity_cannot_become_an_external_oauth_client(mcp_fixture):
    client, session, settings, _, _, dashboard = mcp_fixture
    # A deployment typo must not make the internal identity externally issuable.
    settings.mcp.approved_clients[ASSISTANT_CLIENT_ID] = [REDIRECT]
    with pytest.raises(MCPAuthError, match="invalid_client"):
        validate_client(settings.mcp, ASSISTANT_CLIENT_ID)
    with pytest.raises(MCPAuthError, match="invalid_client"):
        await validate_authorization_client(settings.mcp, ASSISTANT_CLIENT_ID, REDIRECT)
    response = await client.post(
        "/api/v1/admin/mcp/authorize", json={**consent(), "client_id": ASSISTANT_CLIENT_ID},
        headers={"Authorization": f"Bearer {dashboard}"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client"
    assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 0


async def test_public_mcp_and_file_transport_reject_even_a_valid_private_principal(mcp_fixture, monkeypatch):
    client, session, _, user, _, _ = mcp_fixture
    grant = await private_grant(mcp_fixture)
    private_token = "gcmcp_access_synthetic-private-only"

    async def verified_private(_self, token, capability=None):
        assert token == private_token
        return MCPPrincipal(grant.id, user.id, ASSISTANT_CLIENT_ID, ("mcp:read",),
                            datetime.now(UTC) + timedelta(seconds=90), RESOURCE)

    # Prove these public boundaries reject the private identity independently
    # of the internal verifier/context, even if its bearer bytes were exposed.
    monkeypatch.setattr(MCPAuthorizationService, "verify_access", verified_private)
    response = await call_mcp(client, private_token)
    assert response.status_code == 401
    assert "www-authenticate" in response.headers
    response = await client.get("/mcp/artifacts/authority", headers={"Authorization": f"Bearer {private_token}"})
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_token"
    await session.refresh(grant)
    assert grant.revoked_at is None and grant.enabled


async def test_private_authority_is_excluded_before_external_device_pagination(mcp_fixture):
    client, session, _, _, _, dashboard = mcp_fixture
    await connect(mcp_fixture)
    await connect(mcp_fixture)
    external = set((await session.scalars(select(MCPGrantModel.id))).all())
    private = await private_grant(mcp_fixture)
    headers = {"Authorization": f"Bearer {dashboard}"}
    first = await client.get("/api/v1/admin/mcp/connections?limit=1", headers=headers)
    assert first.status_code == 200 and first.json()["next_offset"] == 1
    second = await client.get("/api/v1/admin/mcp/connections?limit=1&offset=1", headers=headers)
    assert second.status_code == 200 and second.json()["next_offset"] is None
    visible = {uuid.UUID(item["id"]) for page in (first, second) for item in page.json()["items"]}
    assert visible == external and private.id not in visible


async def test_external_device_mutations_cannot_change_private_authority(mcp_fixture):
    client, session, _, _, _, dashboard = mcp_fixture
    private = await private_grant(mcp_fixture)
    await session.refresh(private)
    before = {column.name: getattr(private, column.name) for column in private.__table__.columns}
    base = f"/api/v1/admin/mcp/connections/{private.id}"
    for method, path, body in [
        ("POST", base + "/revoke", None),
        ("PATCH", base + "/access", {"enabled": False}),
        ("DELETE", base, None),
        ("PATCH", base, {"name": "External renamed device", "capabilities": ["mcp:read"]}),
        ("PUT", base + "/permissions", {"expected_revision": 1, "read_enabled": False,
             "write_enabled": False, "allowed_read_sections": [], "allowed_write_sections": []}),
    ]:
        response = await client.request(method, path, json=body, headers={"Authorization": f"Bearer {dashboard}"})
        assert response.status_code == 404, (method, path, response.text)
        await session.refresh(private)
        assert {column.name: getattr(private, column.name) for column in private.__table__.columns} == before
