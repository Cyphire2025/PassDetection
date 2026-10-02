"""Native URL-only OAuth discovery, consent, PKCE and actual MCP authentication."""

# Pytest discovers the imported yield fixture; test parameters intentionally shadow it.
# ruff: noqa: F811

from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select

from app.application.mcp import client_policy
from app.infrastructure.database.mcp_models import MCPGrantModel
from tests.integration.test_mcp_authorization import (
    RESOURCE,
    VERIFIER,
    call_mcp,
    consent,
    mcp_fixture,  # noqa: F401
)

CODEX = "https://chatgpt.com/oauth/codex/client.json"
CHATGPT = "https://chatgpt.com/oauth/client.json"


@pytest.fixture(autouse=True)
def published_client_documents(monkeypatch):
    """Substitute only external metadata I/O; run real client policy and OAuth."""
    client_policy._metadata_cache.clear()

    async def fetch(client_id):
        return {
            "client_id": client_id,
            "redirect_uris": client_policy.DIRECT_CLIENT_REDIRECTS[client_id],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "private_key_jwt" if client_id == CHATGPT else "none",
            "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"] if client_id == CHATGPT else ["none"],
        }

    monkeypatch.setattr(client_policy, "_fetch_metadata", fetch)
    yield
    client_policy._metadata_cache.clear()


def native_consent(client_id, redirect, platform="Windows"):
    return {
        **consent(), "client_id": client_id, "redirect_uri": redirect,
        "scopes": ["mcp:read"], "device_platform": platform,
        "name": "My MacBook" if platform == "macOS" else "Office Windows",
    }


@pytest.mark.parametrize("client_id,redirect,platform", [
    (CODEX, "http://127.0.0.1:49751/callback", "Windows"),
    (CODEX, "http://127.0.0.1:53127/callback", "macOS"),
    (CHATGPT, "https://chatgpt.com/connector_platform_oauth_redirect", "macOS"),
])
async def test_native_discovery_consent_exchange_and_mcp(mcp_fixture, client_id, redirect, platform):
    client, session, settings, _, _, dashboard = mcp_fixture
    discovery = (await client.get("/.well-known/oauth-authorization-server")).json()
    assert discovery["client_id_metadata_document_supported"] is True
    assert discovery["authorization_response_iss_parameter_supported"] is True
    assert discovery["token_endpoint_auth_methods_supported"] == ["none"]
    assert discovery["code_challenge_methods_supported"] == ["S256"]
    body = native_consent(client_id, redirect, platform)
    start = await client.get("/oauth/mcp/authorize", params={
        key: value for key, value in {
            **body, "scope": "mcp:read", "response_type": "code", "code_challenge_method": "S256",
        }.items() if key not in {"name", "scopes", "device_platform"}
    })
    assert start.status_code == 303, start.text
    location = urlsplit(start.headers["location"])
    assert location.path == "/mcp/connect"
    assert set(parse_qs(location.query)) == {"request_id"}
    response = await client.post("/api/v1/admin/mcp/authorize", json=body,
                                 headers={"Authorization": f"Bearer {dashboard}"})
    assert response.status_code == 200, response.text
    callback = urlsplit(response.json()["redirect_url"])
    query = parse_qs(callback.query)
    assert set(query) == {"code", "state", "iss"}
    assert query["iss"] == [settings.mcp.public_origin]
    assert query["state"] == [body["state"]]
    exchange = await client.post("/oauth/mcp/token", data={
        "grant_type": "authorization_code", "client_id": client_id, "redirect_uri": redirect,
        "resource": RESOURCE, "code": query["code"][0], "code_verifier": VERIFIER,
    })
    assert exchange.status_code == 200, exchange.text
    tokens = exchange.json()
    assert tokens["scope"] == "mcp:read"
    assert (await call_mcp(client, tokens["access_token"])).status_code == 200
    grant = await session.scalar(select(MCPGrantModel))
    assert grant.device_platform == platform
    assert grant.enabled is True
    assert grant.name == body["name"]
    overview = (await client.get("/api/v1/admin/mcp", headers={"Authorization": f"Bearer {dashboard}"})).json()
    assert overview["direct_clients"][client_id]
    assert overview["client_names"][client_id] in {"ChatGPT", "Codex"}


@pytest.mark.parametrize("client_id,redirect", [
    (CODEX, "http://127.0.0.1:49751/evil"),
    (CODEX, "http://192.168.1.4:49751/callback"),
    (CODEX + "?client=attacker", "http://127.0.0.1:49751/callback"),
    (CHATGPT, "https://evil.example/connector_platform_oauth_redirect"),
    (CHATGPT, "https://chatgpt.com/connector_platform_oauth_redirect?next=evil"),
])
async def test_native_forged_callback_cannot_create_connection(mcp_fixture, client_id, redirect):
    client, session, _, _, _, dashboard = mcp_fixture
    response = await client.post("/api/v1/admin/mcp/authorize",
        json=native_consent(client_id, redirect), headers={"Authorization": f"Bearer {dashboard}"})
    assert response.status_code == 400
    assert "redirect_url" not in response.json()
    assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 0


async def test_native_code_cannot_exchange_on_another_loopback_port(mcp_fixture):
    client, _, _, _, _, dashboard = mcp_fixture
    redirect = "http://127.0.0.1:49751/callback"
    response = await client.post("/api/v1/admin/mcp/authorize", json=native_consent(CODEX, redirect),
                                headers={"Authorization": f"Bearer {dashboard}"})
    code = parse_qs(urlsplit(response.json()["redirect_url"]).query)["code"][0]
    fields = {"grant_type": "authorization_code", "client_id": CODEX,
              "resource": RESOURCE, "code": code, "code_verifier": VERIFIER}
    wrong = await client.post("/oauth/mcp/token", data={**fields, "redirect_uri": "http://127.0.0.1:49752/callback"})
    assert wrong.status_code == 400
    correct = await client.post("/oauth/mcp/token", data={**fields, "redirect_uri": redirect})
    assert correct.status_code == 200
    reused = await client.post("/oauth/mcp/token", data={**fields, "redirect_uri": redirect})
    assert reused.status_code == 400
