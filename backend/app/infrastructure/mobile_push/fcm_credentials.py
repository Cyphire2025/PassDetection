"""Bounded service-account OAuth for direct FCM; no credential material in errors."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from google.auth.exceptions import RefreshError
from google.auth.transport import Request, Response
from google.oauth2 import service_account

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


class FcmCredentialError(Exception):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class _Response(Response):
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    @property
    def status(self) -> int:
        return self._response.status_code

    @property
    def headers(self) -> httpx.Headers:
        return self._response.headers

    @property
    def data(self) -> bytes:
        return self._response.content


class _Request(Request):
    def __init__(self, deadline: float) -> None:
        self._deadline = deadline

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Response:
        del timeout, kwargs
        remaining = self._deadline - time.monotonic()
        if url != _TOKEN_URI:
            raise FcmCredentialError("fcm_credentials_project_or_type_mismatch")
        if remaining <= 0:
            raise FcmCredentialError("fcm_credentials_unavailable", retryable=True)
        try:
            with httpx.Client(timeout=remaining, follow_redirects=False) as client:
                response = client.request(method, url, content=body, headers=headers)
        except httpx.HTTPError:
            raise FcmCredentialError("fcm_credentials_unavailable", retryable=True) from None
        if response.status_code in {429, 500, 502, 503, 504}:
            raise FcmCredentialError("fcm_credentials_unavailable", retryable=True)
        if response.status_code in {401, 403}:
            raise FcmCredentialError("fcm_authentication_failed")
        return _Response(response)


@dataclass
class _CachedCredentials:
    credentials: service_account.Credentials
    lock: threading.Lock


@lru_cache(maxsize=4)
def _credentials(path: str, project_id: str, mtime_ns: int, size: int) -> _CachedCredentials:
    del mtime_ns
    if not 1 <= size <= 65_536:
        raise FcmCredentialError("fcm_credentials_invalid")
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(65_537)
        if len(raw) > 65_536:
            raise FcmCredentialError("fcm_credentials_invalid")
        info = json.loads(raw)
        if (
            not isinstance(info, dict)
            or info.get("type") != "service_account"
            or info.get("project_id") != project_id
            or info.get("token_uri") != _TOKEN_URI
        ):
            raise FcmCredentialError("fcm_credentials_project_or_type_mismatch")
        credentials = service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
            info,
            scopes=[FCM_SCOPE],
        )
        return _CachedCredentials(credentials, threading.Lock())
    except FcmCredentialError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise FcmCredentialError("fcm_credentials_invalid") from None


def _access_token(path: str, project_id: str, timeout: float) -> str:
    try:
        file = Path(path)
        if not file.is_absolute():
            raise FcmCredentialError("fcm_credentials_path_must_be_absolute")
        stat = file.stat()
    except OSError:
        raise FcmCredentialError("fcm_credentials_missing") from None
    cached = _credentials(path, project_id, stat.st_mtime_ns, stat.st_size)
    deadline = time.monotonic() + timeout
    if not cached.lock.acquire(timeout=timeout):
        raise FcmCredentialError("fcm_credentials_unavailable", retryable=True)
    try:
        if not cached.credentials.valid:
            cached.credentials.refresh(_Request(deadline))  # type: ignore[no-untyped-call]
        token = cached.credentials.token
        if not isinstance(token, str) or not token:
            raise FcmCredentialError("fcm_credentials_unavailable")
        return token
    except FcmCredentialError:
        raise
    except RefreshError:
        raise FcmCredentialError("fcm_authentication_failed") from None
    except Exception:
        raise FcmCredentialError("fcm_credentials_unavailable") from None
    finally:
        cached.lock.release()


async def fcm_access_token(path: str | None, project_id: str, *, timeout: float) -> str:
    if not path:
        raise FcmCredentialError("fcm_credentials_missing")
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_access_token, path, project_id, timeout),
            timeout=timeout + 1,
        )
    except TimeoutError:
        raise FcmCredentialError("fcm_credentials_unavailable", retryable=True) from None
