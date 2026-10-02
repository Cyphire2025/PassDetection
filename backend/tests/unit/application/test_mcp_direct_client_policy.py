"""Native OAuth admission rejects spoofed clients and callbacks before credentials exist."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.application.mcp import client_policy as policy
from app.application.mcp.credentials import MCPAuthError
from app.core.config.mcp import MCPSettings

CHATGPT = "https://chatgpt.com/oauth/client.json"
CODEX = "https://chatgpt.com/oauth/codex/client.json"
CHATGPT_REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"
CODEX_REDIRECT = "http://127.0.0.1/callback"


def document(client_id=CODEX, **changes):
    result = {
        "client_id": client_id,
        "redirect_uris": [CHATGPT_REDIRECT]
        if client_id == CHATGPT
        else [CODEX_REDIRECT, "http://localhost/callback"],
        "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"],
        "token_endpoint_auth_method": "private_key_jwt",
    }
    return {**result, **changes}


@pytest.fixture(autouse=True)
def isolated_metadata_cache():
    policy._metadata_cache.clear()
    yield
    policy._metadata_cache.clear()


@pytest.fixture
def settings():
    return MCPSettings(_env_file=None)


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    requests = []

    def factory(**options):
        assert options == {
            "follow_redirects": False,
            "trust_env": False,
            "timeout": policy._METADATA_TIMEOUT_SECONDS,
        }

        async def respond(request):
            requests.append(request)
            response = handler(request)
            return await response if asyncio.iscoroutine(response) else response

        return original(transport=httpx.MockTransport(respond), **options)

    monkeypatch.setattr(policy.httpx, "AsyncClient", factory)
    return requests


def test_existing_configured_client_and_grant_checks_need_no_network(settings, monkeypatch):
    def no_network(**_options):
        pytest.fail("Grant identity checks must not use outbound HTTP")

    monkeypatch.setattr(policy.httpx, "AsyncClient", no_network)
    policy.validate_client(settings, "global-connects-desktop", "http://127.0.0.1:8765/callback")
    policy.validate_client(settings, CODEX)
    policy.validate_client(settings, CHATGPT)
    with pytest.raises(MCPAuthError, match="invalid_client"):
        policy.validate_client(settings, CODEX, CODEX_REDIRECT)


@pytest.mark.parametrize(
    "client_id",
    [
        "https://chatgpt.com.evil.example/oauth/client.json",
        "https://chatgpt.com/oauth/client.json?other=1",
        "https://chatgpt.com/oauth/client.json#other",
        "https://chatgpt.com:443/oauth/client.json",
        "https://user@chatgpt.com/oauth/client.json",
        "http://chatgpt.com/oauth/client.json",
        "https://127.0.0.1/oauth/client.json",
    ],
)
async def test_spoofed_client_ids_are_rejected_without_fetch(settings, monkeypatch, client_id):
    requests = transport(monkeypatch, lambda _: pytest.fail("Untrusted URLs must not be fetched"))
    with pytest.raises(MCPAuthError, match="invalid_client"):
        await policy.validate_authorization_client(settings, client_id, CODEX_REDIRECT)
    with pytest.raises(MCPAuthError, match="invalid_client"):
        await policy._fetch_metadata(client_id)
    assert requests == []


@pytest.mark.parametrize(
    "redirect",
    [
        "http://127.0.0.1:0/callback",
        "http://127.0.0.1:65536/callback",
        "http://127.0.0.1:invalid/callback",
        "http://127.0.0.1:/callback",
        "http://127.0.0.1/callback?other=1",
        "http://127.0.0.1/callback?",
        "http://127.0.0.1/callback#fragment",
        "http://name:secret@127.0.0.1/callback",
        "http://localhost/callback",
        "http://[::1]/callback",
        "http://127.0.0.2/callback",
        "http://127.0.0.1.evil.example/callback",
        "http://127.0.0.1/callback/another-server",
        "http://127.0.0.1/%63allback",
        "http://127.0.0.1\\@evil.example/callback",
        "http://127.0.0.1\n/callback",
        "https://127.0.0.1/callback",
        "http://10.0.0.1/callback",
    ],
)
async def test_forged_native_redirects_rejected_before_fetch(settings, monkeypatch, redirect):
    requests = transport(
        monkeypatch, lambda _: pytest.fail("Bad callbacks must not trigger fetching")
    )
    with pytest.raises(MCPAuthError, match="invalid_client"):
        await policy.validate_authorization_client(settings, CODEX, redirect)
    assert requests == []


@pytest.mark.parametrize("port", [None, 1, 43117, 65535])
async def test_native_loopback_port_varies_but_host_and_path_do_not(settings, monkeypatch, port):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=document()))
    callback = CODEX_REDIRECT if port is None else f"http://127.0.0.1:{port}/callback"
    await policy.validate_authorization_client(settings, CODEX, callback)
    assert len(requests) == 1
    assert str(requests[0].url) == CODEX
    assert requests[0].headers["accept"] == "application/json"


async def test_chatgpt_plural_method_permits_public_pkce_despite_legacy_preference(
    settings, monkeypatch
):
    transport(monkeypatch, lambda _: httpx.Response(200, json=document(CHATGPT)))
    await policy.validate_authorization_client(settings, CHATGPT, CHATGPT_REDIRECT)
    with pytest.raises(MCPAuthError, match="invalid_client"):
        await policy.validate_authorization_client(
            settings, CHATGPT, "https://chatgpt.com/connector/oauth/other"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"client_id": "https://evil.example/client.json"},
        {"client_id": None},
        {"token_endpoint_auth_methods_supported": ["private_key_jwt"]},
        {"token_endpoint_auth_methods_supported": "none"},
        {"token_endpoint_auth_methods_supported": None, "token_endpoint_auth_method": "none"},
        {"token_endpoint_auth_methods_supported": ["none", 3]},
        {"redirect_uris": []},
        {"redirect_uris": CODEX_REDIRECT},
        {"redirect_uris": [CODEX_REDIRECT, 3]},
        {"redirect_uris": ["http://10.0.0.1/callback"]},
        {"redirect_uris": ["http://localhost/callback"]},
        {"redirect_uris": ["http://127.0.0.1/callback?redirect=evil"]},
        {"redirect_uris": ["http://name:secret@127.0.0.1/callback"]},
    ],
)
async def test_invalid_document_never_creates_cached_policy(settings, monkeypatch, changes):
    transport(monkeypatch, lambda _: httpx.Response(200, json=document(**changes)))
    with pytest.raises(MCPAuthError, match="invalid_client"):
        await policy.validate_authorization_client(settings, CODEX, CODEX_REDIRECT)
    assert CODEX not in policy._metadata_cache


async def test_legacy_document_method_and_omitted_client_id_are_supported(settings, monkeypatch):
    payload = document(token_endpoint_auth_method="none")
    del payload["token_endpoint_auth_methods_supported"]
    del payload["client_id"]
    transport(monkeypatch, lambda _: httpx.Response(200, json=payload))
    await policy.validate_authorization_client(settings, CODEX, CODEX_REDIRECT)


async def test_expired_cache_failure_does_not_restore_old_redirects(settings, monkeypatch):
    healthy = True

    def respond(_request):
        return httpx.Response(200, json=document()) if healthy else httpx.Response(503)

    requests = transport(monkeypatch, respond)
    await policy.validate_authorization_client(settings, CODEX, CODEX_REDIRECT)
    await policy.validate_authorization_client(settings, CODEX, "http://127.0.0.1:50001/callback")
    assert len(requests) == 1
    expiry, redirects = policy._metadata_cache[CODEX]
    assert 0 < expiry - policy.time.monotonic() <= 300
    policy._metadata_cache[CODEX] = (0, redirects)
    healthy = False
    for _ in range(2):
        with pytest.raises(MCPAuthError, match="temporarily_unavailable") as denied:
            await policy.validate_authorization_client(settings, CODEX, CODEX_REDIRECT)
        assert denied.value.status_code == 503
        assert CODEX not in policy._metadata_cache
    assert len(requests) == 3


@pytest.mark.parametrize("status", [301, 302, 307, 308])
async def test_metadata_redirects_are_never_followed(settings, monkeypatch, status):
    requests = transport(
        monkeypatch,
        lambda _: httpx.Response(status, headers={"location": "http://169.254.169.254/"}),
    )
    with pytest.raises(MCPAuthError, match="invalid_client"):
        await policy.validate_authorization_client(settings, CODEX, CODEX_REDIRECT)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content="{not json", headers={"content-type": "application/json"}),
        httpx.Response(200, content="{}", headers={"content-type": "text/html"}),
        httpx.Response(200, json=["not a metadata object"]),
        httpx.Response(200, content=b" " * 16385, headers={"content-type": "application/json"}),
    ],
)
async def test_malformed_wrong_type_or_oversized_metadata_fails_closed(
    settings, monkeypatch, response
):
    transport(monkeypatch, lambda _: response)
    with pytest.raises(MCPAuthError, match="invalid_client"):
        await policy.validate_authorization_client(settings, CODEX, CODEX_REDIRECT)
    assert CODEX not in policy._metadata_cache


async def test_timeout_is_retryable_and_does_not_get_negative_cached(settings, monkeypatch):
    def respond(request):
        raise httpx.ReadTimeout("test timeout", request=request)

    requests = transport(monkeypatch, respond)
    for _ in range(2):
        with pytest.raises(MCPAuthError, match="temporarily_unavailable") as denied:
            await policy.validate_authorization_client(settings, CODEX, CODEX_REDIRECT)
        assert denied.value.status_code == 503
    assert len(requests) == 2


async def test_whole_fetch_deadline_bounds_slow_responses(settings, monkeypatch):
    async def respond(_request):
        await asyncio.Event().wait()
        pytest.fail("The metadata deadline should cancel an incomplete response")

    monkeypatch.setattr(policy, "_METADATA_TIMEOUT_SECONDS", 0.01)
    requests = transport(monkeypatch, respond)
    with pytest.raises(MCPAuthError, match="temporarily_unavailable") as denied:
        await policy.validate_authorization_client(settings, CODEX, CODEX_REDIRECT)
    assert denied.value.status_code == 503
    assert len(requests) == 1
    assert CODEX not in policy._metadata_cache


async def test_oversized_stream_stops_reading_and_closes_response(settings, monkeypatch):
    class CountingStream(httpx.AsyncByteStream):
        consumed = 0
        closed = False

        async def __aiter__(self):
            for _ in range(100):
                self.consumed += 1
                yield b" " * 1024

        async def aclose(self):
            self.closed = True

    stream = CountingStream()
    transport(
        monkeypatch,
        lambda _: httpx.Response(200, headers={"content-type": "application/json"}, stream=stream),
    )
    with pytest.raises(MCPAuthError, match="invalid_client"):
        await policy.validate_authorization_client(settings, CODEX, CODEX_REDIRECT)
    assert stream.consumed == 17
    assert stream.closed is True


async def test_configured_direct_id_does_not_bypass_metadata_authority(monkeypatch):
    configured = MCPSettings(
        _env_file=None, approved_clients={CODEX: ["https://other.example/callback"]}
    )
    requests = transport(
        monkeypatch, lambda _: pytest.fail("Configured aliases cannot broaden CIMD")
    )
    with pytest.raises(MCPAuthError, match="invalid_client"):
        await policy.validate_authorization_client(
            configured, CODEX, "https://other.example/callback"
        )
    assert requests == []


async def test_available_policy_overview_fetches_both_clients_concurrently(monkeypatch):
    began = []
    both_started = asyncio.Event()

    async def respond(request):
        began.append(str(request.url))
        if len(began) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return httpx.Response(200, json=document(str(request.url)))

    transport(monkeypatch, respond)
    assert await policy.get_direct_client_metadata() == policy.DIRECT_CLIENT_REDIRECTS


async def test_available_policy_omits_unavailable_client_without_stale_data(monkeypatch):
    transport(
        monkeypatch,
        lambda request: (
            httpx.Response(503)
            if str(request.url) == CHATGPT
            else httpx.Response(200, json=document())
        ),
    )
    assert await policy.get_direct_client_metadata() == {CODEX: [CODEX_REDIRECT]}
