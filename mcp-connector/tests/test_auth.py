import asyncio
import sys
import time
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx2
import pytest

from gc_mcp_connector.auth import Authorization, ResourceBearerAuth
from gc_mcp_connector.config import CLIENT_ID, REDIRECT_URI, Config, ConnectorError
from gc_mcp_connector.oauth import AuthorizationAttempt, OAuthClient, Tokens, callback_code
from gc_mcp_connector.vault import Credential, WindowsCredentialLock, WindowsVault


@asynccontextmanager
async def unlocked():
    yield


class MemoryVault:
    def __init__(self, credential=None):
        self.credential = credential
        self.writes = []

    def read(self):
        return self.credential

    def write(self, credential):
        self.credential = credential
        self.writes.append(credential)

    def delete(self):
        self.credential = None


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:secret@app.test",
        "http://app.test",
        "https://app.test/path",
        "https://app.test?redirect=bad",
        "https://app.test\n",
        "file:///x",
    ],
)
def test_rejects_unsafe_origins(origin):
    with pytest.raises(ConnectorError):
        Config(origin)


def test_pkce_and_callback_are_bound_to_attempt():
    attempt = AuthorizationAttempt.create()
    oauth = OAuthClient(Config("https://app.test"), None)
    query = parse_qs(oauth.authorization_url(attempt, ["mcp:read"]).split("?", 1)[1])
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["resource"] == ["https://app.test/mcp"]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 43
    code = "code-value-long-enough-for-test"
    valid = f"/callback?code={code}&state={attempt.state}"
    assert callback_code(valid, attempt, "https://app.test") == code
    for bad in (
        valid + "&state=extra",
        valid.replace(attempt.state, "bad"),
        valid + "&iss=https://attacker.test",
        valid.replace("/callback", "/wrong"),
        valid.replace(attempt.state, "%C3%A9"),
    ):
        with pytest.raises(ValueError):
            callback_code(bad, attempt, "https://app.test")
    with pytest.raises(ConnectorError, match="declined"):
        callback_code(
            f"/callback?state={attempt.state}&error=access_denied", attempt, "https://app.test"
        )


async def test_metadata_cannot_redirect_credentials_or_authorization():
    def respond(request):
        if "protected-resource" in request.url.path:
            return httpx2.Response(
                200,
                json={
                    "resource": "https://app.test/mcp",
                    "authorization_servers": ["https://app.test"],
                },
            )
        return httpx2.Response(
            200,
            json={
                "issuer": "https://app.test",
                "authorization_endpoint": "https://evil.test/authorize",
                "token_endpoint": "https://app.test/oauth/mcp/token",
                "code_challenge_methods_supported": ["S256"],
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        with pytest.raises(ConnectorError, match="configured application"):
            await OAuthClient(Config("https://app.test"), http).discover()


async def test_code_exchange_sends_only_bound_oauth_form_and_validates_lifetime():
    observed = []

    def respond(request):
        observed.append(parse_qs(request.content.decode()))
        return httpx2.Response(
            200,
            json={
                "token_type": "Bearer",
                "access_token": "a" * 32,
                "refresh_token": "r" * 32,
                "expires_in": 900,
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        attempt = AuthorizationAttempt.create()
        tokens = await OAuthClient(Config("https://app.test"), http).exchange("c" * 32, attempt)
    assert observed == [
        {
            "grant_type": ["authorization_code"],
            "code": ["c" * 32],
            "code_verifier": [attempt.verifier],
            "redirect_uri": [REDIRECT_URI],
            "client_id": [CLIENT_ID],
            "resource": ["https://app.test/mcp"],
        }
    ]
    assert tokens.access_token == "a" * 32
    assert "a" * 32 not in repr(tokens)


async def test_concurrent_refresh_rotates_once_and_never_extends_authorization():
    calls = []

    async def refresh(token):
        calls.append(token)
        await asyncio.sleep(0.01)
        return Tokens("a" * 32, "new" * 16, time.time() + 900)

    until = time.time() + 6000
    vault = MemoryVault(Credential("old" * 16, until))
    auth = Authorization(SimpleNamespace(refresh=refresh), vault, unlocked)
    assert await asyncio.gather(*(auth.access_token() for _ in range(10))) == ["a" * 32] * 10
    assert calls == ["old" * 16]
    assert vault.credential.authorized_until == until
    assert vault.credential.refresh_token == "new" * 16


async def test_uncertain_refresh_discards_consumable_token_and_never_replays():
    calls = []

    async def refresh(token):
        calls.append(token)
        raise RuntimeError("sensitive provider text and secret-token")

    vault = MemoryVault(Credential("old" * 16, time.time() + 6000))
    auth = Authorization(SimpleNamespace(refresh=refresh), vault, unlocked)
    with pytest.raises(ConnectorError, match="no operation was retried") as error:
        await auth.access_token()
    assert "secret-token" not in str(error.value)
    assert vault.credential is None
    with pytest.raises(ConnectorError, match="Sign in"):
        await auth.access_token()
    assert len(calls) == 1


async def test_expired_local_authorization_fails_before_http():
    auth = Authorization(None, MemoryVault(Credential("r" * 32, time.time() - 1)), unlocked)
    with pytest.raises(ConnectorError, match="Sign in"):
        await auth.access_token()


async def test_other_process_refresh_does_not_force_rotation_of_still_valid_access_tokens():
    calls = []

    async def refresh(token):
        calls.append(token)
        return Tokens(f"access-{len(calls)}" * 5, f"refresh-{len(calls)}" * 5, time.time() + 900)

    vault = MemoryVault(Credential("old" * 16, time.time() + 6000))
    first = Authorization(SimpleNamespace(refresh=refresh), vault, unlocked)
    second = Authorization(SimpleNamespace(refresh=refresh), vault, unlocked)
    first_access = await first.access_token()
    second_access = await second.access_token()
    assert first_access != second_access
    assert await first.access_token() == first_access
    assert await second.access_token() == second_access
    assert len(calls) == 2


async def test_bearer_token_is_not_sent_to_other_paths_and_401_is_not_retried():
    calls = []
    vault = MemoryVault(Credential("r" * 32, time.time() + 6000))
    auth = Authorization(None, vault, unlocked)
    auth.tokens = Tokens("a" * 32, "r" * 32, time.time() + 900)
    auth.authorized_until = vault.credential.authorized_until

    def respond(request):
        calls.append(str(request.url))
        assert request.headers["Authorization"] == f"Bearer {'a' * 32}"
        return httpx2.Response(401)

    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(respond),
        auth=ResourceBearerAuth(Config("https://app.test"), auth),
    ) as http:
        with pytest.raises(ConnectorError, match="configured MCP endpoint"):
            await http.get("https://app.test/other")
        assert (await http.post("https://app.test/mcp", json={})).status_code == 401
    assert calls == ["https://app.test/mcp"]
    assert auth.tokens is None


def test_vault_unavailable_has_no_plaintext_fallback(monkeypatch):
    monkeypatch.setattr("gc_mcp_connector.vault.sys.platform", "linux")
    with pytest.raises(ConnectorError, match="requires Windows"):
        WindowsVault("test-key")


def test_vault_uses_only_its_named_credential_and_propagates_failures():
    calls = []
    api = SimpleNamespace(
        CRED_TYPE_GENERIC=1,
        CRED_PERSIST_LOCAL_MACHINE=2,
        CredWrite=lambda record, flags: calls.append(record),
        CredRead=lambda key, kind: {"CredentialBlob": calls[-1]["CredentialBlob"].encode("utf-16-le")},
        CredDelete=lambda key, kind, flags: calls.append(key),
    )
    vault = object.__new__(WindowsVault)
    vault.api, vault.key = api, "GlobalConnects:MCP:v1:test"
    credential = Credential("r" * 32, time.time() + 6000)
    vault.write(credential)
    assert vault.read() == credential
    assert calls[0]["TargetName"] == vault.key
    assert isinstance(calls[0]["CredentialBlob"], str)
    assert "access_token" not in calls[0]["CredentialBlob"]
    vault.delete()
    assert calls[-1] == vault.key

    def broken(_record, _flags):
        raise OSError("raw vault error with sensitive details")

    vault.api.CredWrite = broken
    with pytest.raises(ConnectorError, match="Cannot save"):
        vault.write(credential)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows kernel mutex qualification")
async def test_native_rotation_mutex_excludes_other_threads_and_releases_after_failure():
    import win32api
    import win32event

    lock = WindowsCredentialLock(f"GlobalConnects:MCP:test:{uuid.uuid4().hex}")

    def probe():
        handle = win32event.CreateMutex(None, False, lock.name)
        try:
            result = win32event.WaitForSingleObject(handle, 0)
            if result == win32event.WAIT_OBJECT_0:
                win32event.ReleaseMutex(handle)
            return result
        finally:
            win32api.CloseHandle(handle)

    with pytest.raises(RuntimeError):
        async with lock():
            assert await asyncio.to_thread(probe) == win32event.WAIT_TIMEOUT
            raise RuntimeError("fixture interruption")
    assert await asyncio.to_thread(probe) == win32event.WAIT_OBJECT_0
