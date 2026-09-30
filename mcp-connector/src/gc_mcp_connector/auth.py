"""Short-lived in-memory access tokens and serialized vault refresh rotation."""

import hashlib
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
        self._failed_refresh_digest: bytes | None = None

    async def remember(self, tokens: Tokens, authorized_until: float | None = None) -> None:
        async with self.lock, self.process_lock():
            until = authorized_until or time.time() + 7 * 86400
            self.vault.write(Credential(tokens.refresh_token, until))
            self.tokens = tokens
            self.authorized_until = until
            self._failed_refresh_digest = None

    def _discard_uncertain_refresh(self, refresh_token: str) -> None:
        self.tokens = None
        self.authorized_until = None
        # If native deletion fails, this consumer must never replay this value.
        # A separate CLI sign-in can save a new value and recover the consumer.
        self._failed_refresh_digest = hashlib.sha256(refresh_token.encode()).digest()
        try:
            self.vault.delete()
        except Exception:
            # Preserve the refresh failure/cancellation without exposing cleanup errors.
            # Cancellation raised by cleanup itself is deliberately not caught.
            pass

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
            if self._failed_refresh_digest is not None:
                digest = hashlib.sha256(credential.refresh_token.encode()).digest()
                if digest == self._failed_refresh_digest:
                    raise ConnectorError("Sign in with gc-mcp before using this connection.")
                self._failed_refresh_digest = None
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
            except anyio.get_cancelled_exc_class():
                # Cleanup is synchronous while both locks are held. A cancelled
                # response may already have consumed the rotating refresh token.
                self._discard_uncertain_refresh(credential.refresh_token)
                raise
            except Exception:
                # A lost response may already have consumed a rotating refresh token.
                # Never replay it: require a fresh browser sign-in instead.
                self._discard_uncertain_refresh(credential.refresh_token)
                raise ConnectorError(
                    "Authorization could not be refreshed safely. Sign in again; no operation was retried."
                ) from None
            self.tokens = tokens
            self.authorized_until = credential.authorized_until
            # A cancellation pending after the saved successor is a known result:
            # propagate it before dispatch, but keep the safely rotated value.
            await anyio.lowlevel.checkpoint()
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
