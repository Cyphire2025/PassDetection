"""Anonymous native requester waits for separate authenticated admin authority."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.application.mcp import connection_requests
from app.application.mcp.connection_requests import request_cookie_name
from app.infrastructure.database.mcp_models import (
    MCPAuthorizationCodeModel,
    MCPConnectionRequestModel,
    MCPControlModel,
    MCPGrantModel,
    MCPTokenModel,
)
from tests.dashboard_session_fixtures import issue_dashboard_access
from tests.integration.test_mcp_authorization import RESOURCE, VERIFIER, consent
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture
from tests.integration.test_mcp_native_oauth import CODEX
from tests.integration.test_mcp_native_oauth import (
    published_client_documents as published_client_documents,
)


async def start(fixture, *, state=None, parameters=None):
    client = fixture[0]
    body = consent()
    params = {key: value for key, value in body.items() if key not in {"name", "scopes"}}
    params.update(
        client_id=CODEX,
        redirect_uri="http://127.0.0.1:49751/callback",
        scope="mcp:read",
        response_type="code",
        code_challenge_method="S256",
    )
    if state:
        params["state"] = state
    params.update(parameters or {})
    result = await client.get(
        "/oauth/mcp/authorize", params=params, headers={"User-Agent": "Windows"}
    )
    return result, params


def identifier(response):
    return parse_qs(urlsplit(response.headers["location"]).query)["request_id"][0]


def requester_headers(fixture, value):
    return {"X-MCP-Request": value, "Origin": fixture[2].mcp.frontend_origin}


async def approve(fixture, value, body=None, dashboard=None):
    return await fixture[0].post(
        f"/api/v1/admin/mcp/connection-requests/{value}/approve",
        json=body or {},
        headers={"Authorization": f"Bearer {dashboard or fixture[5]}"},
    )


async def finalize(fixture, value):
    return await fixture[0].post(
        f"/oauth/mcp/requests/{value}/finalize", json={}, headers=requester_headers(fixture, value)
    )


async def no_credentials_created(session):
    for model in (MCPGrantModel, MCPAuthorizationCodeModel, MCPTokenModel):
        assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_anonymous_start_resume_poll_and_admin_finalization(mcp_fixture):
    client, session, settings, user, _, dashboard = mcp_fixture
    first, params = await start(mcp_fixture)
    assert first.status_code == 303, first.text
    value = identifier(first)
    assert urlsplit(first.headers["location"]).path == "/mcp/connect"
    assert set(parse_qs(urlsplit(first.headers["location"]).query)) == {"request_id"}
    cookies = first.headers.get_list("set-cookie")
    assert len(cookies) == 2 and all(
        "HttpOnly" in cookie and "SameSite=lax" in cookie for cookie in cookies
    )
    assert any(f"Path=/oauth/mcp/requests/{value}" in cookie for cookie in cookies)
    assert (
        first.headers["cache-control"] == "no-store"
        and first.headers["referrer-policy"] == "no-referrer"
    )
    await no_credentials_created(session)
    again, _ = await start(mcp_fixture)
    assert identifier(again) == value
    assert await session.scalar(select(func.count()).select_from(MCPConnectionRequestModel)) == 1
    status = await client.get(
        f"/oauth/mcp/requests/{value}", headers=requester_headers(mcp_fixture, value)
    )
    assert status.status_code == 200, status.text
    assert status.json()["name"] == "Codex device" and status.json()["device_platform"] == "Windows"
    assert status.json()["status"] == "pending"
    assert set(status.json()).isdisjoint(
        {
            "credential_hash",
            "request_token",
            "code",
            "state",
            "redirect_uri",
            "resource",
            "user_id",
            "connection_id",
        }
    )
    assert (await finalize(mcp_fixture, value)).status_code == 409
    assert (
        await client.patch(
            f"/oauth/mcp/requests/{value}",
            json={"name": "Home MacBook", "device_platform": "macOS"},
            headers=requester_headers(mcp_fixture, value),
        )
    ).status_code == 200
    listing = await client.get(
        "/api/v1/admin/mcp/connection-requests", headers={"Authorization": f"Bearer {dashboard}"}
    )
    assert listing.json()["items"][0]["comparison_code"] == status.json()["comparison_code"]
    decision = await approve(
        mcp_fixture,
        value,
        {"name": "Approved MacBook", "device_platform": "macOS", "capabilities": ["mcp:read"]},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "approved" and decision.json()["connection_id"] is None
    await no_credentials_created(session)
    complete = await finalize(mcp_fixture, value)
    assert complete.status_code == 200, complete.text
    callback = parse_qs(urlsplit(complete.json()["redirect_url"]).query)
    assert set(callback) == {"code", "state", "iss"}
    assert callback["state"] == [params["state"]] and callback["iss"] == [
        settings.mcp.public_origin
    ]
    grant = await session.scalar(select(MCPGrantModel))
    assert (
        grant.user_id == user.id
        and grant.name == "Approved MacBook"
        and grant.device_platform == "macOS"
    )
    assert grant.capabilities == ["mcp:read"] and grant.enabled is True
    assert await session.scalar(select(func.count()).select_from(MCPAuthorizationCodeModel)) == 1
    assert (await finalize(mcp_fixture, value)).status_code == 404  # Exact scoped cookies cleared.
    fields = {
        "grant_type": "authorization_code",
        "client_id": CODEX,
        "redirect_uri": params["redirect_uri"],
        "resource": RESOURCE,
        "code": callback["code"][0],
        "code_verifier": VERIFIER,
    }
    wrong = await client.post(
        "/oauth/mcp/token", data={**fields, "code_verifier": "wrong" + "x" * 43}
    )
    assert wrong.status_code == 400
    assert (await client.post("/oauth/mcp/token", data=fields)).status_code == 200
    assert (await client.post("/oauth/mcp/token", data=fields)).status_code == 400


@pytest.mark.parametrize(
    "change",
    [
        {"redirect_uri": "https://evil.example/callback"},
        {"resource": "https://evil.example/mcp"},
        {"code_challenge": "bad"},
        {"scope": "mcp:all"},
        {"response_type": "token"},
        {"state": "short"},
    ],
)
async def test_invalid_native_tuple_never_creates_pending(mcp_fixture, change):
    response, _ = await start(mcp_fixture, parameters=change)
    assert response.status_code == 400, response.text
    assert (
        await mcp_fixture[1].scalar(select(func.count()).select_from(MCPConnectionRequestModel))
        == 0
    )
    await no_credentials_created(mcp_fixture[1])


async def test_cookie_uuid_binding_cross_site_and_independent_requesters(mcp_fixture):
    client, session, *_ = mcp_fixture
    first, _ = await start(mcp_fixture)
    one = identifier(first)
    second, _ = await start(mcp_fixture, state="other-native-state-" + "x" * 32)
    two = identifier(second)
    assert one != two
    assert (await client.get(f"/oauth/mcp/requests/{one}")).status_code == 404
    assert (
        await client.get(f"/oauth/mcp/requests/{one}", headers=requester_headers(mcp_fixture, two))
    ).status_code == 404
    cookie = client.cookies.get(
        request_cookie_name(uuid.UUID(one)), path=f"/oauth/mcp/requests/{one}"
    )
    denied = await client.get(
        f"/oauth/mcp/requests/{two}",
        headers=requester_headers(mcp_fixture, two),
        cookies={request_cookie_name(uuid.UUID(two)): cookie},
    )
    assert denied.status_code == 404
    approved = await approve(mcp_fixture, one)
    assert approved.status_code == 200
    csrf = await client.post(
        f"/oauth/mcp/requests/{one}/finalize",
        headers={"X-MCP-Request": one, "Origin": "https://evil.example"},
    )
    assert csrf.status_code == 403
    await no_credentials_created(session)
    await client.post(
        f"/api/v1/admin/mcp/connection-requests/{two}/reject",
        json={},
        headers={"Authorization": f"Bearer {mcp_fixture[5]}"},
    )
    rejected = await finalize(mcp_fixture, two)
    assert rejected.status_code == 200, rejected.text
    query = parse_qs(urlsplit(rejected.json()["redirect_url"]).query)
    assert set(query) == {"error", "state", "iss"} and query["error"] == ["access_denied"]
    await no_credentials_created(session)


@pytest.mark.parametrize("changed", ["expired", "control", "role", "security", "mfa", "scope"])
async def test_approval_rechecked_at_finalize_without_new_authority(mcp_fixture, changed):
    client, session, settings, user, security, _ = mcp_fixture
    response, _ = await start(mcp_fixture)
    value = identifier(response)
    assert (await approve(mcp_fixture, value)).status_code == 200
    row = await session.get(MCPConnectionRequestModel, uuid.UUID(value))
    if changed == "expired":
        row.created_at = datetime.now(UTC) - timedelta(minutes=20)
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    elif changed == "control":
        (await session.get(MCPControlModel, 1)).enabled = False
    elif changed == "role":
        user.role = "agency_admin"
    elif changed == "security":
        security.session_version += 1
    elif changed == "mfa":
        row.mfa_at = datetime.now(UTC) - timedelta(minutes=11)
    else:
        settings.mcp.enabled_capabilities = ["mcp:export"]
    await session.commit()
    result = await finalize(mcp_fixture, value)
    assert result.status_code in {400, 403, 410, 503}, result.text
    await no_credentials_created(session)
    await session.refresh(row)
    assert row.finalized_at is None


async def test_scope_escalation_and_account_selection_rejected(mcp_fixture):
    client, session, *_ = mcp_fixture
    response, _ = await start(mcp_fixture)
    value = identifier(response)
    assert (await approve(mcp_fixture, value, {"capabilities": ["mcp:export"]})).status_code == 400
    assert (await approve(mcp_fixture, value, {"user_id": str(uuid.uuid4())})).status_code == 422
    forged = await client.patch(
        f"/oauth/mcp/requests/{value}",
        json={"name": "x", "device_platform": "Other", "user_id": str(uuid.uuid4())},
        headers=requester_headers(mcp_fixture, value),
    )
    assert forged.status_code == 422
    await no_credentials_created(session)


async def test_decision_and_finalize_replays_do_not_allocate_more_grants(mcp_fixture):
    client, session, *_ = mcp_fixture
    response, _ = await start(mcp_fixture)
    value = identifier(response)
    secret = client.cookies.get(
        request_cookie_name(uuid.UUID(value)), path=f"/oauth/mcp/requests/{value}"
    )
    assert (await approve(mcp_fixture, value)).status_code == 200
    assert (await approve(mcp_fixture, value)).status_code == 409
    assert (
        await client.post(
            f"/api/v1/admin/mcp/connection-requests/{value}/reject",
            json={},
            headers={"Authorization": f"Bearer {mcp_fixture[5]}"},
        )
    ).status_code == 409
    assert (await finalize(mcp_fixture, value)).status_code == 200
    replay = await client.post(
        f"/oauth/mcp/requests/{value}/finalize",
        headers=requester_headers(mcp_fixture, value),
        cookies={request_cookie_name(uuid.UUID(value)): secret},
    )
    assert replay.status_code == 409
    assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 1
    assert await session.scalar(select(func.count()).select_from(MCPAuthorizationCodeModel)) == 1


async def test_administrator_role_and_recent_mfa_required(mcp_fixture):
    _, session, _, user, *_ = mcp_fixture
    response, _ = await start(mcp_fixture)
    value = identifier(response)
    stale, _ = await issue_dashboard_access(
        session,
        user.id,
        "super_admin",
        session_version=1,
        authentication_methods=("pwd", "totp"),
        mfa_authenticated_at=datetime.now(UTC) - timedelta(minutes=11),
    )
    assert (await approve(mcp_fixture, value, dashboard=stale)).status_code == 403
    user.role = "agency_admin"
    await session.flush()
    assert (await approve(mcp_fixture, value)).status_code == 403
    await no_credentials_created(session)


async def test_distributed_creation_bound_and_resume_survives_quota(mcp_fixture, monkeypatch):
    monkeypatch.setattr(connection_requests, "SOURCE_CREATION_LIMIT", 1)
    first, _ = await start(mcp_fixture)
    value = identifier(first)
    assert first.status_code == 303
    same, _ = await start(mcp_fixture)
    assert same.status_code == 303 and identifier(same) == value
    other, _ = await start(mcp_fixture, state="new-state-" + "z" * 32)
    assert other.status_code == 429 and other.json()["error"] == "slow_down"
    assert (
        await mcp_fixture[1].scalar(select(func.count()).select_from(MCPConnectionRequestModel))
        == 1
    )


async def test_https_cookie_secure_and_duplicate_query_rejected(mcp_fixture):
    mcp_fixture[2].mcp.public_origin = "https://mcp.example"
    # Restore resource-consistent origin only for this isolated cookie assertion.
    response, _ = await start(mcp_fixture, parameters={"resource": "https://mcp.example/mcp"})
    assert response.status_code == 303, response.text
    assert all("Secure" in value for value in response.headers.get_list("set-cookie"))
    response = await mcp_fixture[0].get("/oauth/mcp/authorize?client_id=x&client_id=y")
    assert response.status_code == 400


async def test_creation_source_respects_trusted_proxy_without_public_header_spoofing(mcp_fixture):
    original, session, settings, *_ = mcp_fixture
    settings.trusted_proxy_networks = ["10.23.0.0/16"]
    _, params = await start(mcp_fixture)
    hashes = []
    for peer, forwarded, state in (
        ("198.51.100.8", "203.0.113.10", "direct-a"),
        ("198.51.100.8", "203.0.113.11", "direct-b"),
        ("10.23.1.2", "203.0.113.10", "proxy-a"),
        ("10.23.1.2", "203.0.113.11", "proxy-b"),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=original._transport.app, client=(peer, 1234)),
            base_url="http://localhost:8000",
        ) as caller:
            response = await caller.get(
                "/oauth/mcp/authorize",
                params={**params, "state": state + "s" * 32},
                headers={"X-Real-IP": forwarded, "X-Forwarded-For": "192.0.2.99"},
            )
            assert response.status_code == 303, response.text
            row = await session.get(MCPConnectionRequestModel, uuid.UUID(identifier(response)))
            hashes.append(row.source_hash)
    assert hashes[0] == hashes[1]
    assert hashes[2] != hashes[3]
    assert hashes[0] not in hashes[2:]


async def test_same_native_tuple_in_another_browser_does_not_recover_request_capability(
    mcp_fixture,
):
    original, session, *_ = mcp_fixture
    first, params = await start(mcp_fixture)
    first_id = identifier(first)
    async with AsyncClient(
        transport=ASGITransport(app=original._transport.app), base_url="http://localhost:8000"
    ) as stranger:
        unavailable = await stranger.get(
            f"/oauth/mcp/requests/{first_id}", headers=requester_headers(mcp_fixture, first_id)
        )
        assert unavailable.status_code == 404
        second = await stranger.get("/oauth/mcp/authorize", params=params)
        assert second.status_code == 303
        assert identifier(second) != first_id
    assert await session.scalar(select(func.count()).select_from(MCPConnectionRequestModel)) == 2


async def test_admin_approval_cookie_authentication_requires_trusted_origin(mcp_fixture):
    client, session, settings, _, _, dashboard = mcp_fixture
    first, _ = await start(mcp_fixture)
    value = identifier(first)
    client.cookies.set(settings.jwt.access_cookie_name, dashboard)
    blocked = await client.post(
        f"/api/v1/admin/mcp/connection-requests/{value}/approve",
        json={},
        headers={"Origin": "https://evil.example"},
    )
    assert blocked.status_code == 403
    await no_credentials_created(session)
    decision = await client.post(
        f"/api/v1/admin/mcp/connection-requests/{value}/approve",
        json={},
        headers={"Origin": settings.mcp.frontend_origin},
    )
    assert decision.status_code == 200, decision.text


async def test_expired_request_cannot_be_approved_and_status_poll_is_read_only(mcp_fixture):
    client, session, *_ = mcp_fixture
    first, _ = await start(mcp_fixture)
    value = identifier(first)
    row = await session.get(MCPConnectionRequestModel, uuid.UUID(value))
    row.created_at = datetime.now(UTC) - timedelta(minutes=20)
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()
    status = await client.get(
        f"/oauth/mcp/requests/{value}", headers=requester_headers(mcp_fixture, value)
    )
    assert status.status_code == 200 and status.json()["status"] == "expired"
    await session.refresh(row)
    assert row.status == "pending" and row.decided_at is None and row.finalized_at is None
    assert (await approve(mcp_fixture, value)).status_code == 410
    await no_credentials_created(session)


@pytest.mark.parametrize("terminal", ["rejected", "finalized"])
async def test_terminal_admin_decision_does_not_turn_expired_after_request_window(
    mcp_fixture, terminal
):
    client, session, _, _, _, dashboard = mcp_fixture
    first, _ = await start(mcp_fixture)
    value = identifier(first)
    if terminal == "finalized":
        assert (await approve(mcp_fixture, value)).status_code == 200
        assert (await finalize(mcp_fixture, value)).status_code == 200
    else:
        assert (
            await client.post(
                f"/api/v1/admin/mcp/connection-requests/{value}/reject",
                json={},
                headers={"Authorization": f"Bearer {dashboard}"},
            )
        ).status_code == 200
    row = await session.get(MCPConnectionRequestModel, uuid.UUID(value))
    row.created_at = datetime.now(UTC) - timedelta(minutes=20)
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await session.commit()
    listing = await client.get(
        "/api/v1/admin/mcp/connection-requests", headers={"Authorization": f"Bearer {dashboard}"}
    )
    assert listing.json()["items"][0]["status"] == terminal
