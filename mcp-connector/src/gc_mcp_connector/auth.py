"""Short-lived in-memory access tokens and serialized vault refresh rotation."""

import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import anyio
import httpx2

from .config import Config, ConnectorError
from .oauth import OAuthClient, Tokens
from .vault import Credential, Vault


class Authorization:
    def __init__(
        self,
        oauth: OAuthClient,
        vault: Vault,
        process_lock: Callable[[], AbstractAsyncContextManager],
    ) -> None:
        self.oauth, self.vault, self.process_lock = oauth, vault, process_lock
        self.lock = anyio.Lock()
        self.tokens: Tokens | None = None
        self.authorized_until: float | None = None

    async def remember(self, tokens: Tokens, authorized_until: float | None = None) -> None:
        async with self.lock, self.process_lock():
            until = authorized_until or time.time() + 7 * 86400
            self.vault.write(Credential(tokens.refresh_token, until))
            self.tokens = tokens
            self.authorized_until = until

    async def forget(self) -> None:
        async with self.lock, self.process_lock():
            self.tokens = None
            self.vault.delete()

    async def access_token(self) -> str:
        async with self.lock, self.process_lock():
            credential = self.vault.read()
            if credential is None or credential.authorized_until <= time.time():
                self.tokens = None
                raise ConnectorError("Sign in with gc-mcp before using this connection.")
            if (
                self.tokens
                and self.authorized_until == credential.authorized_until
                and self.tokens.expires_at > time.time() + 30
            ):
                return self.tokens.access_token
            self.tokens = None
            try:
                tokens = await self.oauth.refresh(credential.refresh_token)
                self.vault.write(Credential(tokens.refresh_token, credential.authorized_until))
            except Exception:
                # A lost response may already have consumed a rotating refresh token.
                # Never replay it: require a fresh browser sign-in instead.
                self.vault.delete()
                raise ConnectorError(
                    "Authorization could not be refreshed safely. Sign in again; no operation was retried."
                ) from None
            self.tokens = tokens
            self.authorized_until = credential.authorized_until
            return tokens.access_token


class ResourceBearerAuth(httpx2.Auth):
    def __init__(self, config: Config, authorization: Authorization) -> None:
        self.resource, self.authorization = config.resource, authorization

    async def async_auth_flow(self, request):
        # Tool content and redirects cannot turn the connector into a generic authenticated client.
        if str(request.url) != self.resource:
            raise ConnectorError("Credentials may only be sent to the configured MCP endpoint.")
        request.headers["Authorization"] = f"Bearer {await self.authorization.access_token()}"
        response = yield request
        if response.status_code in (401, 403):
            self.authorization.tokens = None
            # No transparent retry of a possibly mutating tool call.
