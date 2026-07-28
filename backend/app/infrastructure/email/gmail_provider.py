"""Gmail implementation of the provider-neutral inbound email contract."""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx

from app.application.interfaces.email_provider import (
    EmailAccountProfile,
    EmailChangeKind,
    EmailHistoryPage,
    EmailMessageChange,
    EmailMessageReference,
    EmailProviderAuthenticationError,
    EmailProviderConfigurationError,
    EmailProviderName,
    EmailProviderRateLimitError,
    EmailProviderResponseError,
    EmailProviderTransientError,
    EmailTokenSet,
    NormalizedEmailMessage,
)
from app.core.config.settings import Settings, get_settings
from app.infrastructure.email.mime import normalize_gmail_message
from app.infrastructure.email.oauth import build_pkce_challenge, hash_oauth_state

_GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REVOCATION_URL = "https://oauth2.googleapis.com/revoke"
_GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1"
_PKCE_CHALLENGE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[^\x00-\x1f\x7f]{1,2048}$")
_JSON_RESPONSE_MAX_BYTES = 8 * 1024 * 1024
_OAUTH_RESPONSE_MAX_BYTES = 2 * 1024 * 1024
_MAX_LIST_PAGES = 1_000
_MAX_PROVIDER_PAGE_SIZE = 500


class GmailEmailProvider:
    provider_name = EmailProviderName.GMAIL

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._timeout = httpx.Timeout(20.0, connect=5.0, read=20.0, write=10.0)

    def build_authorization_url(self, *, state: str, code_challenge: str) -> str:
        client_id, redirect_uri = self._public_oauth_configuration()
        # Validation also guarantees the state is suitable for hash-only
        # persistence and exact callback comparison.
        hash_oauth_state(state)
        if not _PKCE_CHALLENGE_PATTERN.fullmatch(code_challenge):
            raise ValueError("PKCE challenge must be a URL-safe S256 value")
        parameters = {
            "access_type": "offline",
            "client_id": client_id,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "consent",
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _GMAIL_SCOPE,
            "state": state,
        }
        return f"{_AUTHORIZATION_URL}?{urlencode(parameters)}"

    async def exchange_authorization_code(
        self,
        *,
        code: str,
        code_verifier: str,
    ) -> EmailTokenSet:
        if not code or len(code) > 8_192:
            raise EmailProviderAuthenticationError(
                "The Gmail authorization code is invalid",
                code="EMAIL_PROVIDER_AUTH_CODE_INVALID",
                reconnect_required=True,
            )
        build_pkce_challenge(code_verifier)
        client_id, client_secret, redirect_uri = self._private_oauth_configuration()
        payload = await self._request_json(
            "POST",
            _TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            max_response_bytes=_OAUTH_RESPONSE_MAX_BYTES,
            request_context="oauth",
        )
        return self._parse_token_response(payload)

    async def refresh_access_token(self, *, refresh_token: str) -> EmailTokenSet:
        if not refresh_token:
            raise EmailProviderAuthenticationError()
        client_id, client_secret, _ = self._private_oauth_configuration()
        payload = await self._request_json(
            "POST",
            _TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            max_response_bytes=_OAUTH_RESPONSE_MAX_BYTES,
            request_context="oauth",
        )
        return self._parse_token_response(payload)

    async def get_account_profile(self, *, access_token: str) -> EmailAccountProfile:
        payload = await self._authorized_json(
            "GET",
            f"{_GMAIL_API_ROOT}/users/me/profile",
            access_token=access_token,
        )
        email_address = _required_text(payload.get("emailAddress"), max_chars=320)
        history_cursor = _optional_text(payload.get("historyId"), max_chars=128)
        return EmailAccountProfile(
            provider_account_id=email_address.casefold(),
            email_address=email_address,
            display_name=None,
            history_cursor=history_cursor,
        )

    async def revoke_token(self, *, token: str) -> None:
        if not token:
            return
        await self._request_empty(
            "POST",
            _REVOCATION_URL,
            data={"token": token},
            max_response_bytes=_OAUTH_RESPONSE_MAX_BYTES,
            request_context="revoke",
        )

    async def list_messages(
        self,
        *,
        access_token: str,
        query: str | None,
        max_messages: int,
    ) -> tuple[EmailMessageReference, ...]:
        configured_limit = _positive_setting(
            self._settings,
            "email_sync_max_messages",
            default=1_000,
        )
        if max_messages < 1:
            raise ValueError("max_messages must be positive")
        effective_limit = min(max_messages, configured_limit)
        normalized_query = _bounded_query(query)

        references: list[EmailMessageReference] = []
        seen_ids: set[str] = set()
        seen_page_tokens: set[str] = set()
        page_token: str | None = None

        for _ in range(_MAX_LIST_PAGES):
            remaining = effective_limit - len(references)
            if remaining <= 0:
                break
            params: dict[str, str | int] = {
                "maxResults": min(remaining, _MAX_PROVIDER_PAGE_SIZE),
            }
            if normalized_query:
                params["q"] = normalized_query
            if page_token:
                params["pageToken"] = page_token

            payload = await self._authorized_json(
                "GET",
                f"{_GMAIL_API_ROOT}/users/me/messages",
                access_token=access_token,
                params=params,
            )
            messages = payload.get("messages", [])
            if not isinstance(messages, Sequence) or isinstance(
                messages,
                (str, bytes, bytearray),
            ):
                raise EmailProviderResponseError()
            for item in messages:
                if not isinstance(item, Mapping):
                    raise EmailProviderResponseError()
                message_id = _required_text(item.get("id"), max_chars=512)
                if message_id in seen_ids:
                    continue
                seen_ids.add(message_id)
                references.append(
                    EmailMessageReference(
                        provider_message_id=message_id,
                        thread_id=_optional_text(item.get("threadId"), max_chars=512),
                    )
                )
                if len(references) >= effective_limit:
                    break

            next_page_token = _optional_text(
                payload.get("nextPageToken"),
                max_chars=2_048,
            )
            if not next_page_token or len(references) >= effective_limit:
                break
            if next_page_token in seen_page_tokens:
                raise EmailProviderResponseError(
                    "Gmail returned a repeated message page token",
                    code="EMAIL_PROVIDER_PAGINATION_INVALID",
                )
            seen_page_tokens.add(next_page_token)
            page_token = next_page_token
        else:
            raise EmailProviderResponseError(
                "Gmail message pagination exceeded its safety limit",
                code="EMAIL_PROVIDER_PAGINATION_INVALID",
            )

        return tuple(references)

    async def list_history_page(
        self,
        *,
        access_token: str,
        start_history_id: str,
        page_token: str | None = None,
        max_results: int = 100,
    ) -> EmailHistoryPage:
        normalized_cursor = _safe_identifier(start_history_id, "history cursor")
        if max_results < 1:
            raise ValueError("max_results must be positive")
        params: dict[str, str | int] = {
            "startHistoryId": normalized_cursor,
            "maxResults": min(max_results, _MAX_PROVIDER_PAGE_SIZE),
        }
        if page_token is not None:
            params["pageToken"] = _safe_identifier(page_token, "history page token")

        payload = await self._authorized_json(
            "GET",
            f"{_GMAIL_API_ROOT}/users/me/history",
            access_token=access_token,
            params=params,
            request_context="history",
        )
        latest_history_id = _required_text(payload.get("historyId"), max_chars=128)
        history_entries = payload.get("history", [])
        if not isinstance(history_entries, Sequence) or isinstance(
            history_entries,
            (str, bytes, bytearray),
        ):
            raise EmailProviderResponseError()

        changes: list[EmailMessageChange] = []
        seen_changes: set[tuple[str, str, EmailChangeKind]] = set()
        for entry in history_entries:
            if not isinstance(entry, Mapping):
                raise EmailProviderResponseError()
            provider_history_id = _required_text(entry.get("id"), max_chars=128)
            _append_history_changes(
                changes,
                seen_changes,
                entry=entry,
                collection_name="messagesAdded",
                kind=EmailChangeKind.ADDED,
                provider_history_id=provider_history_id,
            )
            _append_history_changes(
                changes,
                seen_changes,
                entry=entry,
                collection_name="messagesDeleted",
                kind=EmailChangeKind.DELETED,
                provider_history_id=provider_history_id,
            )
            for collection_name in ("labelsAdded", "labelsRemoved"):
                _append_history_changes(
                    changes,
                    seen_changes,
                    entry=entry,
                    collection_name=collection_name,
                    kind=EmailChangeKind.LABELS_CHANGED,
                    provider_history_id=provider_history_id,
                )

        return EmailHistoryPage(
            changes=tuple(changes),
            next_page_token=_optional_text(
                payload.get("nextPageToken"),
                max_chars=2_048,
            ),
            latest_history_id=latest_history_id,
        )

    async def get_message(
        self,
        *,
        access_token: str,
        message_id: str,
    ) -> NormalizedEmailMessage:
        safe_message_id = quote(_safe_identifier(message_id, "message id"), safe="")
        attachment_limit = _positive_setting(
            self._settings,
            "email_attachment_max_bytes",
            default=25 * 1024 * 1024,
        )
        max_json_bytes = min(
            max(_JSON_RESPONSE_MAX_BYTES, attachment_limit * 2),
            64 * 1024 * 1024,
        )
        payload = await self._authorized_json(
            "GET",
            f"{_GMAIL_API_ROOT}/users/me/messages/{safe_message_id}",
            access_token=access_token,
            params={"format": "full"},
            max_response_bytes=max_json_bytes,
        )
        return normalize_gmail_message(
            payload,
            attachment_max_bytes=attachment_limit,
        )

    async def get_attachment(
        self,
        *,
        access_token: str,
        message_id: str,
        attachment_id: str,
    ) -> bytes:
        safe_message_id = quote(_safe_identifier(message_id, "message id"), safe="")
        safe_attachment_id = quote(
            _safe_identifier(attachment_id, "attachment id"),
            safe="",
        )
        attachment_limit = _positive_setting(
            self._settings,
            "email_attachment_max_bytes",
            default=25 * 1024 * 1024,
        )
        encoded_limit = math.ceil(attachment_limit / 3) * 4
        payload = await self._authorized_json(
            "GET",
            (
                f"{_GMAIL_API_ROOT}/users/me/messages/{safe_message_id}/"
                f"attachments/{safe_attachment_id}"
            ),
            access_token=access_token,
            max_response_bytes=encoded_limit + 64 * 1024,
        )
        data = payload.get("data")
        if not isinstance(data, str):
            raise EmailProviderResponseError()
        return _decode_attachment(data, max_bytes=attachment_limit)

    def _parse_token_response(self, payload: Mapping[str, Any]) -> EmailTokenSet:
        access_token = _required_text(payload.get("access_token"), max_chars=16_384)
        refresh_token = _optional_text(payload.get("refresh_token"), max_chars=16_384)
        token_type = _optional_text(payload.get("token_type"), max_chars=64) or "Bearer"
        expires_in = _positive_int(payload.get("expires_in"), default=3_600)
        scope_value = payload.get("scope")
        scopes = (
            tuple(scope for scope in scope_value.split() if scope)
            if isinstance(scope_value, str)
            else ()
        )
        return EmailTokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=token_type,
            expires_at=datetime.now(timezone.utc).replace(microsecond=0)
            + timedelta(seconds=expires_in),
            scopes=scopes,
        )

    async def _authorized_json(
        self,
        method: str,
        url: str,
        *,
        access_token: str,
        params: Mapping[str, str | int] | None = None,
        max_response_bytes: int = _JSON_RESPONSE_MAX_BYTES,
        request_context: str = "api",
    ) -> dict[str, Any]:
        if not access_token:
            raise EmailProviderAuthenticationError()
        return await self._request_json(
            method,
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            max_response_bytes=max_response_bytes,
            request_context=request_context,
        )

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str | int] | None = None,
        data: Mapping[str, str] | None = None,
        max_response_bytes: int,
        request_context: str,
    ) -> dict[str, Any]:
        status_code, response_headers, content = await self._request_bytes(
            method,
            url,
            headers=headers,
            params=params,
            data=data,
            max_response_bytes=max_response_bytes,
        )
        payload = _parse_json_object(content)
        if status_code >= 400:
            _raise_provider_status(
                status_code=status_code,
                headers=response_headers,
                payload=payload,
                request_context=request_context,
            )
        if payload is None:
            raise EmailProviderResponseError()
        return payload

    async def _request_empty(
        self,
        method: str,
        url: str,
        *,
        data: Mapping[str, str],
        max_response_bytes: int,
        request_context: str,
    ) -> None:
        status_code, response_headers, content = await self._request_bytes(
            method,
            url,
            data=data,
            max_response_bytes=max_response_bytes,
        )
        if status_code >= 400:
            _raise_provider_status(
                status_code=status_code,
                headers=response_headers,
                payload=_parse_json_object(content),
                request_context=request_context,
            )

    async def _request_bytes(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str | int] | None = None,
        data: Mapping[str, str] | None = None,
        max_response_bytes: int,
    ) -> tuple[int, httpx.Headers, bytes]:
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        try:
            async with self._client_context() as client:
                async with client.stream(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    data=data,
                    follow_redirects=False,
                    timeout=self._timeout,
                ) as response:
                    content_length = _content_length(response.headers)
                    if content_length is not None and content_length > max_response_bytes:
                        raise EmailProviderResponseError(
                            "The email provider response exceeded its size limit",
                            code="EMAIL_PROVIDER_RESPONSE_TOO_LARGE",
                            status_code=response.status_code,
                        )
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > max_response_bytes:
                            raise EmailProviderResponseError(
                                "The email provider response exceeded its size limit",
                                code="EMAIL_PROVIDER_RESPONSE_TOO_LARGE",
                                status_code=response.status_code,
                            )
                    return response.status_code, response.headers, bytes(content)
        except EmailProviderResponseError:
            raise
        except httpx.RequestError:
            # Do not chain an exception carrying an Authorization header or
            # token-exchange form body into logs/Sentry.
            raise EmailProviderTransientError() from None

    @asynccontextmanager
    async def _client_context(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient() as client:
            yield client

    def _public_oauth_configuration(self) -> tuple[str, str]:
        client_id = _optional_setting_text(self._settings, "gmail_oauth_client_id")
        redirect_uri = _optional_setting_text(self._settings, "gmail_oauth_redirect_uri")
        if not client_id or not redirect_uri:
            raise EmailProviderConfigurationError()
        if not _valid_redirect_uri(redirect_uri):
            raise EmailProviderConfigurationError(
                "Gmail OAuth redirect URI must use HTTPS",
                code="EMAIL_PROVIDER_REDIRECT_URI_INVALID",
            )
        return client_id, redirect_uri

    def _private_oauth_configuration(self) -> tuple[str, str, str]:
        client_id, redirect_uri = self._public_oauth_configuration()
        client_secret = _optional_setting_text(
            self._settings,
            "gmail_oauth_client_secret",
        )
        if not client_secret:
            raise EmailProviderConfigurationError()
        return client_id, client_secret, redirect_uri


def _append_history_changes(
    changes: list[EmailMessageChange],
    seen: set[tuple[str, str, EmailChangeKind]],
    *,
    entry: Mapping[str, Any],
    collection_name: str,
    kind: EmailChangeKind,
    provider_history_id: str,
) -> None:
    collection = entry.get(collection_name, [])
    if not isinstance(collection, Sequence) or isinstance(
        collection,
        (str, bytes, bytearray),
    ):
        raise EmailProviderResponseError()
    for change in collection:
        if not isinstance(change, Mapping):
            raise EmailProviderResponseError()
        message = change.get("message")
        if not isinstance(message, Mapping):
            raise EmailProviderResponseError()
        message_id = _required_text(message.get("id"), max_chars=512)
        key = (provider_history_id, message_id, kind)
        if key in seen:
            continue
        seen.add(key)
        changes.append(
            EmailMessageChange(
                provider_history_id=provider_history_id,
                provider_message_id=message_id,
                kind=kind,
            )
        )


def _raise_provider_status(
    *,
    status_code: int,
    headers: httpx.Headers,
    payload: Mapping[str, Any] | None,
    request_context: str,
) -> None:
    safe_error_code = _safe_oauth_error(payload)
    if status_code == 429:
        raise EmailProviderRateLimitError(
            retry_after_seconds=_retry_after_seconds(headers.get("Retry-After")),
            status_code=status_code,
        )
    if status_code in {401, 403} or safe_error_code in {
        "invalid_client",
        "invalid_grant",
        "unauthorized_client",
    }:
        raise EmailProviderAuthenticationError(status_code=status_code)
    if request_context == "history" and status_code == 404:
        raise EmailProviderResponseError(
            "The Gmail history cursor is no longer available",
            code="EMAIL_PROVIDER_HISTORY_CURSOR_INVALID",
            status_code=status_code,
        )
    if status_code >= 500 or safe_error_code == "temporarily_unavailable":
        raise EmailProviderTransientError(
            retry_after_seconds=_retry_after_seconds(headers.get("Retry-After")),
            status_code=status_code,
        )
    raise EmailProviderResponseError(
        "The email provider rejected the request",
        code="EMAIL_PROVIDER_REQUEST_REJECTED",
        status_code=status_code,
    )


def _safe_oauth_error(payload: Mapping[str, Any] | None) -> str | None:
    if payload is None:
        return None
    value = payload.get("error")
    if not isinstance(value, str):
        return None
    allowed = {
        "invalid_client",
        "invalid_grant",
        "temporarily_unavailable",
        "unauthorized_client",
    }
    return value if value in allowed else None


def _parse_json_object(content: bytes) -> dict[str, Any] | None:
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _decode_attachment(value: str, *, max_bytes: int) -> bytes:
    if len(value) > math.ceil(max_bytes / 3) * 4 + 4:
        raise EmailProviderResponseError(
            "The Gmail attachment exceeds the configured size limit",
            code="EMAIL_PROVIDER_CONTENT_TOO_LARGE",
        )
    padded = value + ("=" * (-len(value) % 4))
    try:
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise EmailProviderResponseError() from None
    if len(decoded) > max_bytes:
        raise EmailProviderResponseError(
            "The Gmail attachment exceeds the configured size limit",
            code="EMAIL_PROVIDER_CONTENT_TOO_LARGE",
        )
    return decoded


def _required_text(value: Any, *, max_chars: int) -> str:
    normalized = _optional_text(value, max_chars=max_chars)
    if normalized is None:
        raise EmailProviderResponseError()
    return normalized


def _optional_text(value: Any, *, max_chars: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()[:max_chars]
    return normalized or None


def _safe_identifier(value: str, label: str) -> str:
    if not _SAFE_IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"{label} is invalid")
    return value


def _bounded_query(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\x00-\x1f\x7f]", "", value).strip()
    if len(normalized) > 1_024:
        raise ValueError("Gmail query is too long")
    return normalized or None


def _optional_setting_text(settings: Any, name: str) -> str | None:
    value = getattr(settings, name, None)
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        value = getter()
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _positive_setting(settings: Any, name: str, *, default: int) -> int:
    value = getattr(settings, name, default)
    return (
        value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default
    )


def _positive_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return normalized if normalized > 0 else default


def _content_length(headers: httpx.Headers) -> int | None:
    value = headers.get("Content-Length")
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _retry_after_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if stripped.isdigit():
        return min(int(stripped), 86_400)
    try:
        parsed = parsedate_to_datetime(stripped)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delay = int((parsed - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None
    return min(max(delay, 0), 86_400)


def _valid_redirect_uri(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError:
        return False
    if (
        not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and hostname in {"localhost", "127.0.0.1", "::1"}
