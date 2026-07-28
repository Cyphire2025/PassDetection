from __future__ import annotations

import base64
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import SecretStr

from app.application.interfaces.email_provider import (
    EmailChangeKind,
    EmailProviderAuthenticationError,
    EmailProviderConfigurationError,
    EmailProviderRateLimitError,
)
from app.infrastructure.email.gmail_provider import GmailEmailProvider
from app.infrastructure.email.oauth import generate_oauth_state, generate_pkce_pair


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "gmail_oauth_client_id": "gmail-client-id.apps.googleusercontent.com",
        "gmail_oauth_client_secret": SecretStr("gmail-client-secret"),
        "gmail_oauth_redirect_uri": "https://dashboard.example.test/api/v1/email/gmail/callback",
        "email_sync_max_messages": 5,
        "email_attachment_max_bytes": 1024 * 1024,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def test_authorization_url_is_offline_read_only_pkce_and_secret_free() -> None:
    provider = GmailEmailProvider(settings=_settings())  # type: ignore[arg-type]
    state = generate_oauth_state()
    pkce = generate_pkce_pair()

    url = provider.build_authorization_url(
        state=state,
        code_challenge=pkce.challenge,
    )
    params = parse_qs(urlparse(url).query)

    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["scope"] == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert params["state"] == [state]
    assert params["code_challenge"] == [pkce.challenge]
    assert params["code_challenge_method"] == ["S256"]
    assert "gmail-client-secret" not in url


def test_authorization_url_rejects_lookalike_localhost_redirect() -> None:
    provider = GmailEmailProvider(  # type: ignore[arg-type]
        settings=_settings(gmail_oauth_redirect_uri="http://localhost.attacker.example/callback")
    )
    with pytest.raises(EmailProviderConfigurationError):
        provider.build_authorization_url(
            state=generate_oauth_state(),
            code_challenge=generate_pkce_pair().challenge,
        )


@pytest.mark.asyncio
async def test_token_exchange_refresh_profile_and_revoke_are_server_side() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/token":
            form = parse_qs(request.content.decode("ascii"))
            if form["grant_type"] == ["authorization_code"]:
                assert form["code_verifier"] == ["v" * 64]
                return httpx.Response(
                    200,
                    json={
                        "access_token": "access-one",
                        "refresh_token": "refresh-one",
                        "expires_in": 3600,
                        "scope": "https://www.googleapis.com/auth/gmail.readonly",
                        "token_type": "Bearer",
                    },
                )
            assert form["refresh_token"] == ["refresh-one"]
            return httpx.Response(
                200,
                json={
                    "access_token": "access-two",
                    "expires_in": 1800,
                    "token_type": "Bearer",
                },
            )
        if request.url.path.endswith("/users/me/profile"):
            assert request.headers["Authorization"] == "Bearer access-two"
            return httpx.Response(
                200,
                json={
                    "emailAddress": "Travel.Team@Example.com",
                    "historyId": "991",
                },
            )
        if request.url.path == "/revoke":
            assert parse_qs(request.content.decode("ascii"))["token"] == ["refresh-one"]
            return httpx.Response(200)
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GmailEmailProvider(  # type: ignore[arg-type]
            settings=_settings(),
            client=client,
        )
        initial = await provider.exchange_authorization_code(
            code="one-time-code",
            code_verifier="v" * 64,
        )
        refreshed = await provider.refresh_access_token(refresh_token="refresh-one")
        profile = await provider.get_account_profile(access_token="access-two")
        await provider.revoke_token(token="refresh-one")

    assert initial.access_token == "access-one"
    assert initial.refresh_token == "refresh-one"
    assert "access-one" not in repr(initial)
    assert "refresh-one" not in repr(initial)
    assert refreshed.access_token == "access-two"
    assert refreshed.refresh_token is None
    assert profile.provider_account_id == "travel.team@example.com"
    assert profile.email_address == "Travel.Team@Example.com"
    assert profile.history_cursor == "991"
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_message_listing_paginates_and_stops_at_configured_bound() -> None:
    seen_page_tokens: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/users/me/messages")
        seen_page_tokens.append(request.url.params.get("pageToken"))
        assert request.url.params["q"] == "after:2026/07/01"
        if request.url.params.get("pageToken") is None:
            return httpx.Response(
                200,
                json={
                    "messages": [
                        {"id": "m1", "threadId": "t1"},
                        {"id": "m2", "threadId": "t2"},
                    ],
                    "nextPageToken": "page-2",
                },
            )
        return httpx.Response(
            200,
            json={
                "messages": [
                    {"id": "m2", "threadId": "t2"},
                    {"id": "m3", "threadId": "t3"},
                    {"id": "m4", "threadId": "t4"},
                ],
                "nextPageToken": "must-not-be-requested",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GmailEmailProvider(  # type: ignore[arg-type]
            settings=_settings(email_sync_max_messages=3),
            client=client,
        )
        messages = await provider.list_messages(
            access_token="access-token",
            query="after:2026/07/01",
            max_messages=20,
        )

    assert [message.provider_message_id for message in messages] == ["m1", "m2", "m3"]
    assert seen_page_tokens == [None, "page-2"]


@pytest.mark.asyncio
async def test_history_and_nested_mime_are_normalized_without_html() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/users/me/history"):
            return httpx.Response(
                200,
                json={
                    "historyId": "105",
                    "nextPageToken": "next-history-page",
                    "history": [
                        {
                            "id": "102",
                            "messagesAdded": [{"message": {"id": "m1"}}],
                            "labelsRemoved": [{"message": {"id": "m1"}}],
                        },
                        {
                            "id": "103",
                            "messagesDeleted": [{"message": {"id": "m2"}}],
                        },
                    ],
                },
            )
        if request.url.path.endswith("/users/me/messages/m1"):
            return httpx.Response(
                200,
                json={
                    "id": "m1",
                    "threadId": "t1",
                    "historyId": "105",
                    "internalDate": "1767225600000",
                    "labelIds": ["INBOX"],
                    "snippet": "Booking documents",
                    "payload": {
                        "mimeType": "multipart/mixed",
                        "headers": [
                            {"name": "Subject", "value": "Travel documents"},
                            {
                                "name": "From",
                                "value": "Supplier <supplier@example.com>",
                            },
                            {
                                "name": "To",
                                "value": "Ops <ops@example.com>",
                            },
                        ],
                        "parts": [
                            {
                                "mimeType": "text/plain",
                                "body": {
                                    "size": 24,
                                    "data": _b64(b"Please review attachment."),
                                },
                            },
                            {
                                "mimeType": "multipart/alternative",
                                "parts": [
                                    {
                                        "mimeType": "text/html",
                                        "body": {
                                            "size": 37,
                                            "data": _b64(b"<script>do-not-expose()</script>"),
                                        },
                                    },
                                    {
                                        "mimeType": "application/pdf",
                                        "filename": "../tickets.pdf",
                                        "headers": [
                                            {
                                                "name": "Content-Disposition",
                                                "value": "attachment",
                                            }
                                        ],
                                        "body": {
                                            "attachmentId": "att-1",
                                            "size": 1234,
                                        },
                                    },
                                ],
                            },
                        ],
                    },
                },
            )
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GmailEmailProvider(  # type: ignore[arg-type]
            settings=_settings(),
            client=client,
        )
        history = await provider.list_history_page(
            access_token="access-token",
            start_history_id="100",
        )
        message = await provider.get_message(
            access_token="access-token",
            message_id="m1",
        )

    assert history.latest_history_id == "105"
    assert history.next_page_token == "next-history-page"
    assert [(change.provider_message_id, change.kind) for change in history.changes] == [
        ("m1", EmailChangeKind.ADDED),
        ("m1", EmailChangeKind.LABELS_CHANGED),
        ("m2", EmailChangeKind.DELETED),
    ]
    assert message.subject == "Travel documents"
    assert message.sender is not None
    assert message.sender.address == "supplier@example.com"
    assert message.plain_text_excerpt == "Please review attachment."
    assert "do-not-expose" not in message.plain_text_excerpt
    assert len(message.attachments) == 1
    assert message.attachments[0].filename == "tickets.pdf"
    assert message.attachments[0].provider_attachment_id == "att-1"
    assert "Travel documents" not in repr(message)
    assert "Please review attachment." not in repr(message)


@pytest.mark.asyncio
async def test_attachment_fetch_is_decoded_and_size_bounded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/attachments/att-1")
        return httpx.Response(200, json={"data": _b64(b"%PDF-test")})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = GmailEmailProvider(  # type: ignore[arg-type]
            settings=_settings(email_attachment_max_bytes=32),
            client=client,
        )
        content = await provider.get_attachment(
            access_token="access-token",
            message_id="m1",
            attachment_id="att-1",
        )

    assert content == b"%PDF-test"


@pytest.mark.asyncio
async def test_provider_errors_are_typed_retryable_and_sanitized() -> None:
    leaked_detail = "raw-provider-secret-that-must-not-leak"

    def auth_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": leaked_detail,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(auth_handler)) as client:
        provider = GmailEmailProvider(  # type: ignore[arg-type]
            settings=_settings(),
            client=client,
        )
        with pytest.raises(EmailProviderAuthenticationError) as auth_error:
            await provider.refresh_access_token(refresh_token="refresh-secret")

    assert auth_error.value.reconnect_required
    assert leaked_detail not in str(auth_error.value)
    assert "refresh-secret" not in str(auth_error.value)

    def rate_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "17"}, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(rate_handler)) as client:
        provider = GmailEmailProvider(  # type: ignore[arg-type]
            settings=_settings(),
            client=client,
        )
        with pytest.raises(EmailProviderRateLimitError) as rate_error:
            await provider.get_account_profile(access_token="access-secret")

    assert rate_error.value.transient
    assert rate_error.value.retry_after_seconds == 17
    assert "access-secret" not in str(rate_error.value)
