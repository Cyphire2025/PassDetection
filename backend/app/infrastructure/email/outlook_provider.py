"""Microsoft Graph implementation of the inbound email provider contract.

The provider uses delegated, read-only Graph permissions. OAuth credentials and
mailbox content never appear in exception text, and every provider response is
streamed through a strict size bound. Opaque Graph pagination links are accepted
only after validating the exact HTTPS host and mailbox-message path.
"""

from __future__ import annotations

import json
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
    EmailAddress,
    EmailAttachment,
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
from app.infrastructure.email.oauth import build_pkce_challenge, hash_oauth_state

_GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
_GRAPH_HOST = "graph.microsoft.com"
_LOGIN_HOST = "login.microsoftonline.com"
_OUTLOOK_SCOPES = (
    "openid",
    "profile",
    "offline_access",
    "https://graph.microsoft.com/User.Read",
    "https://graph.microsoft.com/Mail.Read",
)
_PKCE_CHALLENGE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[^\x00-\x1f\x7f]{1,2048}$")
_TENANT_PATTERN = re.compile(
    r"^(?:common|organizations|consumers|"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
_JSON_RESPONSE_MAX_BYTES = 8 * 1024 * 1024
_OAUTH_RESPONSE_MAX_BYTES = 2 * 1024 * 1024
_MAX_LIST_PAGES = 1_000
_MAX_PROVIDER_PAGE_SIZE = 250
_MAX_BODY_CHARS = 200_000

_IMMUTABLE_ID_PREFERENCE = 'IdType="ImmutableId"'
_MESSAGE_PREFERENCES = f'{_IMMUTABLE_ID_PREFERENCE}, outlook.body-content-type="text"'


class OutlookEmailProvider:
    provider_name = EmailProviderName.OUTLOOK
    # Microsoft identity does not expose an app-scoped RFC 7009 revocation
    # endpoint for delegated refresh tokens. Disconnect securely discards the
    # encrypted local credentials; users may also revoke the app in Microsoft.
    supports_remote_token_revocation = False

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._timeout = httpx.Timeout(20.0, connect=5.0, read=20.0, write=10.0)

    @property
    def requested_scopes(self) -> tuple[str, ...]:
        return _OUTLOOK_SCOPES

    def build_authorization_url(self, *, state: str, code_challenge: str) -> str:
        client_id, redirect_uri, tenant = self._public_oauth_configuration()
        hash_oauth_state(state)
        if not _PKCE_CHALLENGE_PATTERN.fullmatch(code_challenge):
            raise ValueError("PKCE challenge must be a URL-safe S256 value")
        parameters = {
            "client_id": client_id,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "response_type": "code",
            "scope": " ".join(_OUTLOOK_SCOPES),
            "state": state,
        }
        return f"https://{_LOGIN_HOST}/{tenant}/oauth2/v2.0/authorize?{urlencode(parameters)}"

    async def exchange_authorization_code(
        self,
        *,
        code: str,
        code_verifier: str,
    ) -> EmailTokenSet:
        if not code or len(code) > 8_192:
            raise EmailProviderAuthenticationError(
                "The Microsoft authorization code is invalid",
                code="EMAIL_PROVIDER_AUTH_CODE_INVALID",
            )
        build_pkce_challenge(code_verifier)
        client_id, client_secret, redirect_uri, tenant = self._private_oauth_configuration()
        payload = await self._request_json(
            "POST",
            f"https://{_LOGIN_HOST}/{tenant}/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "code_verifier": code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "scope": " ".join(_OUTLOOK_SCOPES),
            },
            max_response_bytes=_OAUTH_RESPONSE_MAX_BYTES,
            request_context="oauth",
        )
        return self._parse_token_response(payload)

    async def refresh_access_token(self, *, refresh_token: str) -> EmailTokenSet:
        if not refresh_token or len(refresh_token) > 32_768:
            raise EmailProviderAuthenticationError()
        client_id, client_secret, _, tenant = self._private_oauth_configuration()
        payload = await self._request_json(
            "POST",
            f"https://{_LOGIN_HOST}/{tenant}/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": " ".join(_OUTLOOK_SCOPES),
            },
            max_response_bytes=_OAUTH_RESPONSE_MAX_BYTES,
            request_context="oauth",
        )
        return self._parse_token_response(payload)

    async def get_account_profile(self, *, access_token: str) -> EmailAccountProfile:
        payload = await self._authorized_json(
            "GET",
            f"{_GRAPH_ROOT}/me",
            access_token=access_token,
            params={"$select": "id,displayName,mail,userPrincipalName"},
        )
        provider_account_id = _required_text(payload.get("id"), max_chars=512)
        email_address = _valid_email_text(payload.get("mail"))
        if email_address is None:
            email_address = _valid_email_text(payload.get("userPrincipalName"))
        if email_address is None:
            raise EmailProviderResponseError(
                "Microsoft did not return a usable mailbox address",
                code="EMAIL_PROVIDER_ACCOUNT_INVALID",
            )

        delta_payload = await self._authorized_json(
            "GET",
            f"{_GRAPH_ROOT}/me/mailFolders/inbox/messages/delta",
            access_token=access_token,
            params={"$deltatoken": "latest"},
            prefer=_IMMUTABLE_ID_PREFERENCE,
            request_context="history",
        )
        history_cursor = _validated_delta_link(
            delta_payload.get("@odata.deltaLink"),
            required=True,
        )
        return EmailAccountProfile(
            provider_account_id=provider_account_id,
            email_address=email_address,
            display_name=_optional_text(payload.get("displayName"), max_chars=255),
            history_cursor=history_cursor,
        )

    async def revoke_token(self, *, token: str) -> None:
        # Deliberate no-op; see supports_remote_token_revocation. The API layer
        # securely removes local encrypted credentials during disconnect.
        del token

    async def list_messages(
        self,
        *,
        access_token: str,
        lookback_days: int,
        max_messages: int,
    ) -> tuple[EmailMessageReference, ...]:
        configured_limit = _positive_setting(
            self._settings,
            "email_sync_max_messages",
            default=1_000,
        )
        if lookback_days < 1 or lookback_days > 365:
            raise ValueError("lookback_days must be between 1 and 365")
        if max_messages < 1:
            raise ValueError("max_messages must be positive")
        effective_limit = min(max_messages, configured_limit)
        received_after = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).replace(
            microsecond=0
        )

        references: list[EmailMessageReference] = []
        seen_ids: set[str] = set()
        seen_links: set[str] = set()
        next_url: str | None = f"{_GRAPH_ROOT}/me/mailFolders/inbox/messages"
        first_params: Mapping[str, str | int] | None = {
            "$filter": f"receivedDateTime ge {received_after.isoformat().replace('+00:00', 'Z')}",
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId",
            "$top": min(effective_limit, _MAX_PROVIDER_PAGE_SIZE),
        }

        for _ in range(_MAX_LIST_PAGES):
            if next_url is None or len(references) >= effective_limit:
                break
            payload = await self._authorized_json(
                "GET",
                next_url,
                access_token=access_token,
                params=first_params,
                prefer=_IMMUTABLE_ID_PREFERENCE,
            )
            first_params = None
            values = _sequence(payload.get("value"))
            for item in values:
                if not isinstance(item, Mapping):
                    raise EmailProviderResponseError()
                message_id = _required_text(item.get("id"), max_chars=512)
                if message_id in seen_ids:
                    continue
                seen_ids.add(message_id)
                references.append(
                    EmailMessageReference(
                        provider_message_id=message_id,
                        thread_id=_optional_text(
                            item.get("conversationId"),
                            max_chars=512,
                        ),
                    )
                )
                if len(references) >= effective_limit:
                    break
            next_url = _validated_messages_link(
                payload.get("@odata.nextLink"),
                required=False,
            )
            if next_url is not None:
                if next_url in seen_links:
                    raise EmailProviderResponseError(
                        "Microsoft Graph returned a repeated message page",
                        code="EMAIL_PROVIDER_PAGINATION_INVALID",
                    )
                seen_links.add(next_url)
        else:
            raise EmailProviderResponseError(
                "Microsoft Graph message pagination exceeded its safety limit",
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
        if max_results < 1:
            raise ValueError("max_results must be positive")
        request_url = _validated_delta_link(
            page_token if page_token is not None else start_history_id,
            required=True,
        )
        payload = await self._authorized_json(
            "GET",
            request_url,
            access_token=access_token,
            prefer=_IMMUTABLE_ID_PREFERENCE,
            request_context="history",
        )
        next_link = _validated_delta_link(
            payload.get("@odata.nextLink"),
            required=False,
        )
        delta_link = _validated_delta_link(
            payload.get("@odata.deltaLink"),
            required=False,
        )
        if next_link is None and delta_link is None:
            raise EmailProviderResponseError(
                "Microsoft Graph omitted the delta continuation cursor",
                code="EMAIL_PROVIDER_PAGINATION_INVALID",
            )
        resume_cursor = next_link or delta_link
        assert resume_cursor is not None

        changes: list[EmailMessageChange] = []
        for item in _sequence(payload.get("value")):
            if not isinstance(item, Mapping):
                raise EmailProviderResponseError()
            message_id = _required_text(item.get("id"), max_chars=512)
            kind = (
                EmailChangeKind.DELETED
                if isinstance(item.get("@removed"), Mapping)
                else EmailChangeKind.ADDED
            )
            changes.append(
                EmailMessageChange(
                    provider_history_id=resume_cursor,
                    provider_message_id=message_id,
                    kind=kind,
                )
            )
            # A Graph nextLink resumes after the complete current page, so
            # truncating a page here would skip changes. The bounded response
            # size and outer synchronization limit remain the safety controls.

        return EmailHistoryPage(
            changes=tuple(changes),
            next_page_token=next_link,
            latest_history_id=delta_link or next_link or start_history_id,
            resume_history_id=resume_cursor,
        )

    async def get_message(
        self,
        *,
        access_token: str,
        message_id: str,
    ) -> NormalizedEmailMessage:
        safe_message_id = quote(_safe_identifier(message_id, "message id"), safe="")
        payload = await self._authorized_json(
            "GET",
            f"{_GRAPH_ROOT}/me/mailFolders/inbox/messages/{safe_message_id}",
            access_token=access_token,
            params={
                "$select": (
                    "id,conversationId,receivedDateTime,subject,sender,toRecipients,"
                    "ccRecipients,replyTo,bodyPreview,body,parentFolderId"
                )
            },
            prefer=_MESSAGE_PREFERENCES,
        )
        attachments = await self._list_attachments(
            access_token=access_token,
            safe_message_id=safe_message_id,
        )
        return _normalize_outlook_message(payload, attachments=attachments)

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
        status_code, response_headers, content = await self._request_bytes(
            "GET",
            (
                f"{_GRAPH_ROOT}/me/mailFolders/inbox/messages/{safe_message_id}/attachments/"
                f"{safe_attachment_id}/$value"
            ),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Prefer": _IMMUTABLE_ID_PREFERENCE,
            },
            max_response_bytes=attachment_limit,
        )
        if status_code >= 300:
            _raise_provider_status(
                status_code=status_code,
                headers=response_headers,
                payload=_parse_json_object(content),
                request_context="attachment",
            )
        return content

    async def _list_attachments(
        self,
        *,
        access_token: str,
        safe_message_id: str,
    ) -> tuple[EmailAttachment, ...]:
        attachments: list[EmailAttachment] = []
        seen_links: set[str] = set()
        next_url: str | None = (
            f"{_GRAPH_ROOT}/me/mailFolders/inbox/messages/{safe_message_id}/attachments"
        )
        first_params: Mapping[str, str | int] | None = {
            "$select": "id,name,contentType,size,isInline,contentId",
            "$top": _MAX_PROVIDER_PAGE_SIZE,
        }
        max_artifacts = _positive_setting(
            self._settings,
            "email_max_artifacts_per_message",
            default=100,
        )
        for _ in range(_MAX_LIST_PAGES):
            if next_url is None or len(attachments) >= max_artifacts:
                break
            payload = await self._authorized_json(
                "GET",
                next_url,
                access_token=access_token,
                params=first_params,
                prefer=_IMMUTABLE_ID_PREFERENCE,
            )
            first_params = None
            for item in _sequence(payload.get("value")):
                if not isinstance(item, Mapping):
                    raise EmailProviderResponseError()
                graph_type = _optional_text(item.get("@odata.type"), max_chars=128)
                is_file = graph_type in {None, "#microsoft.graph.fileAttachment"}
                is_inline = item.get("isInline") is True
                attachments.append(
                    EmailAttachment(
                        provider_attachment_id=(
                            _required_text(item.get("id"), max_chars=768) if is_file else None
                        ),
                        filename=(
                            _optional_text(item.get("name"), max_chars=500) or "unnamed-attachment"
                        ),
                        content_type=(
                            _optional_text(item.get("contentType"), max_chars=255)
                            or "application/octet-stream"
                        ),
                        size_bytes=_nonnegative_int(item.get("size")),
                        disposition="inline" if is_inline else "attachment",
                        content_id=_optional_text(item.get("contentId"), max_chars=512),
                    )
                )
                if len(attachments) >= max_artifacts:
                    break
            next_url = _validated_attachment_link(
                payload.get("@odata.nextLink"),
                required=False,
            )
            if next_url is not None:
                if next_url in seen_links:
                    raise EmailProviderResponseError(
                        "Microsoft Graph returned a repeated attachment page",
                        code="EMAIL_PROVIDER_PAGINATION_INVALID",
                    )
                seen_links.add(next_url)
        else:
            raise EmailProviderResponseError(
                "Microsoft Graph attachment pagination exceeded its safety limit",
                code="EMAIL_PROVIDER_PAGINATION_INVALID",
            )
        return tuple(attachments)

    def _parse_token_response(self, payload: Mapping[str, Any]) -> EmailTokenSet:
        access_token = _required_text(payload.get("access_token"), max_chars=32_768)
        refresh_token = _optional_text(payload.get("refresh_token"), max_chars=32_768)
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
        prefer: str | None = None,
        max_response_bytes: int = _JSON_RESPONSE_MAX_BYTES,
        request_context: str = "api",
    ) -> dict[str, Any]:
        if not access_token:
            raise EmailProviderAuthenticationError()
        headers = {"Authorization": f"Bearer {access_token}"}
        if prefer:
            headers["Prefer"] = prefer
        return await self._request_json(
            method,
            url,
            headers=headers,
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
        if status_code >= 300:
            _raise_provider_status(
                status_code=status_code,
                headers=response_headers,
                payload=payload,
                request_context=request_context,
            )
        if payload is None:
            raise EmailProviderResponseError()
        return payload

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
            raise EmailProviderTransientError() from None

    @asynccontextmanager
    async def _client_context(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient() as client:
            yield client

    def _public_oauth_configuration(self) -> tuple[str, str, str]:
        client_id = _optional_setting_text(self._settings, "outlook_oauth_client_id")
        redirect_uri = _optional_setting_text(
            self._settings,
            "outlook_oauth_redirect_uri",
        )
        tenant = _optional_setting_text(self._settings, "outlook_oauth_tenant") or "common"
        if not client_id or not redirect_uri or not _TENANT_PATTERN.fullmatch(tenant):
            raise EmailProviderConfigurationError()
        if not _valid_redirect_uri(redirect_uri):
            raise EmailProviderConfigurationError(
                "Microsoft OAuth redirect URI must use HTTPS",
                code="EMAIL_PROVIDER_REDIRECT_URI_INVALID",
            )
        return client_id, redirect_uri, tenant

    def _private_oauth_configuration(self) -> tuple[str, str, str, str]:
        client_id, redirect_uri, tenant = self._public_oauth_configuration()
        client_secret = _optional_setting_text(
            self._settings,
            "outlook_oauth_client_secret",
        )
        if not client_secret:
            raise EmailProviderConfigurationError()
        return client_id, client_secret, redirect_uri, tenant


def _normalize_outlook_message(
    payload: Mapping[str, Any],
    *,
    attachments: tuple[EmailAttachment, ...],
) -> NormalizedEmailMessage:
    message_id = _required_text(payload.get("id"), max_chars=512)
    body = payload.get("body")
    body_content = ""
    if isinstance(body, Mapping):
        body_content = _optional_text(body.get("content"), max_chars=_MAX_BODY_CHARS) or ""
    return NormalizedEmailMessage(
        provider_message_id=message_id,
        thread_id=_optional_text(payload.get("conversationId"), max_chars=512),
        history_id=None,
        received_at=_parse_graph_datetime(payload.get("receivedDateTime")),
        subject=_optional_text(payload.get("subject"), max_chars=2_000) or "(no subject)",
        sender=_parse_graph_address(payload.get("sender")),
        to=_parse_graph_addresses(payload.get("toRecipients")),
        cc=_parse_graph_addresses(payload.get("ccRecipients")),
        reply_to=_parse_graph_addresses(payload.get("replyTo")),
        snippet=_optional_text(payload.get("bodyPreview"), max_chars=2_000) or "",
        plain_text_excerpt=body_content,
        labels=("INBOX",),
        attachments=attachments,
    )


def _parse_graph_address(value: Any) -> EmailAddress | None:
    if not isinstance(value, Mapping):
        return None
    email_address = value.get("emailAddress")
    if not isinstance(email_address, Mapping):
        return None
    address = _valid_email_text(email_address.get("address"))
    if address is None:
        return None
    return EmailAddress(
        address=address,
        display_name=_optional_text(email_address.get("name"), max_chars=255),
    )


def _parse_graph_addresses(value: Any) -> tuple[EmailAddress, ...]:
    addresses: list[EmailAddress] = []
    for item in _sequence(value):
        parsed = _parse_graph_address(item)
        if parsed is not None:
            addresses.append(parsed)
    return tuple(addresses)


def _parse_graph_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validated_messages_link(value: Any, *, required: bool) -> str | None:
    return _validated_graph_link(value, required=required, link_kind="messages")


def _validated_attachment_link(value: Any, *, required: bool) -> str | None:
    return _validated_graph_link(value, required=required, link_kind="attachments")


def _validated_delta_link(value: Any, *, required: bool) -> str | None:
    return _validated_graph_link(value, required=required, link_kind="delta")


def _validated_graph_link(
    value: Any,
    *,
    required: bool,
    link_kind: str,
) -> str | None:
    if value is None and not required:
        return None
    link = _optional_text(value, max_chars=16_384)
    if link is None:
        raise EmailProviderResponseError(
            "Microsoft Graph returned an invalid continuation link",
            code="EMAIL_PROVIDER_PAGINATION_INVALID",
        )
    try:
        parsed = urlsplit(link)
        port = parsed.port
    except ValueError:
        parsed = None
        port = None
    path_is_valid = {
        "messages": parsed is not None and parsed.path == "/v1.0/me/mailFolders/inbox/messages",
        "delta": parsed is not None and parsed.path == "/v1.0/me/mailFolders/inbox/messages/delta",
        "attachments": parsed is not None
        and re.fullmatch(
            r"/v1\.0/me/mailFolders/inbox/messages/[^/]+/attachments",
            parsed.path,
        )
        is not None,
    }.get(link_kind, False)
    if (
        parsed is None
        or parsed.scheme != "https"
        or parsed.hostname != _GRAPH_HOST
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not path_is_valid
    ):
        raise EmailProviderResponseError(
            "Microsoft Graph returned an invalid continuation link",
            code="EMAIL_PROVIDER_PAGINATION_INVALID",
        )
    return link


def _raise_provider_status(
    *,
    status_code: int,
    headers: httpx.Headers,
    payload: Mapping[str, Any] | None,
    request_context: str,
) -> None:
    error_code = _safe_provider_error(payload)
    if status_code == 429:
        raise EmailProviderRateLimitError(
            retry_after_seconds=_retry_after_seconds(headers.get("Retry-After")),
            status_code=status_code,
        )
    if status_code == 401 or error_code in {
        "invalid_client",
        "invalid_grant",
        "unauthorized_client",
    }:
        raise EmailProviderAuthenticationError(status_code=status_code)
    if request_context == "history" and (
        status_code in {400, 404, 410}
        or error_code
        in {
            "ErrorInvalidSyncStateData",
            "InvalidDeltaToken",
            "SyncStateNotFound",
            "syncStateNotFound",
        }
    ):
        raise EmailProviderResponseError(
            "The Microsoft mailbox cursor is no longer available",
            code="EMAIL_PROVIDER_HISTORY_CURSOR_INVALID",
            status_code=status_code,
        )
    if status_code >= 500 or error_code in {
        "temporarily_unavailable",
        "serviceNotAvailable",
    }:
        raise EmailProviderTransientError(
            retry_after_seconds=_retry_after_seconds(headers.get("Retry-After")),
            status_code=status_code,
        )
    raise EmailProviderResponseError(
        "The email provider rejected the request",
        code=(
            "EMAIL_PROVIDER_PERMISSION_DENIED"
            if status_code == 403
            else "EMAIL_PROVIDER_REQUEST_REJECTED"
        ),
        status_code=status_code,
    )


def _safe_provider_error(payload: Mapping[str, Any] | None) -> str | None:
    if payload is None:
        return None
    error = payload.get("error")
    if isinstance(error, str):
        return error[:128]
    if isinstance(error, Mapping):
        code = error.get("code")
        if isinstance(code, str):
            return code[:128]
    return None


def _parse_json_object(content: bytes) -> dict[str, Any] | None:
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _sequence(value: Any) -> Sequence[Any]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise EmailProviderResponseError()
    return value


def _required_text(value: Any, *, max_chars: int) -> str:
    normalized = _optional_text(value, max_chars=max_chars)
    if normalized is None:
        raise EmailProviderResponseError()
    return normalized


def _optional_text(value: Any, *, max_chars: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value).strip()
    if not normalized:
        return None
    return normalized[:max_chars]


def _valid_email_text(value: Any) -> str | None:
    normalized = _optional_text(value, max_chars=320)
    if (
        normalized is None
        or normalized.count("@") != 1
        or any(character.isspace() for character in normalized)
    ):
        return None
    local, domain = normalized.rsplit("@", 1)
    return normalized if local and "." in domain and not domain.startswith(".") else None


def _safe_identifier(value: str, label: str) -> str:
    if not _SAFE_IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"{label} is invalid")
    return value


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


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return max(normalized, 0)


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
        port = parsed.port
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
    if parsed.scheme == "https" and port in {None, 443}:
        return True
    return (
        parsed.scheme == "http"
        and hostname in {"localhost", "127.0.0.1", "::1"}
        and port is not None
    )
