from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.application.interfaces.email_provider import (
    EmailChangeKind,
    EmailProviderConfigurationError,
    EmailProviderResponseError,
)
from app.infrastructure.email.oauth import generate_oauth_state, generate_pkce_pair
from app.infrastructure.email.outlook_provider import OutlookEmailProvider


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "outlook_oauth_client_id": "client-id",
        "outlook_oauth_client_secret": SecretStr("client-secret"),
        "outlook_oauth_redirect_uri": (
            "https://dashboard.example.test/api/v1/email-integrations/oauth/outlook/callback"
        ),
        "outlook_oauth_tenant": "common",
        "email_attachment_max_bytes": 1024 * 1024,
        "email_max_artifacts_per_message": 100,
        "email_sync_max_messages": 500,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_authorization_url_uses_common_pkce_and_read_only_scopes() -> None:
    provider = OutlookEmailProvider(settings=_settings())  # type: ignore[arg-type]
    pkce = generate_pkce_pair()
    state = generate_oauth_state()

    url = httpx.URL(
        provider.build_authorization_url(
            state=state,
            code_challenge=pkce.challenge,
        )
    )
    query = parse_qs(url.query.decode())

    assert url.host == "login.microsoftonline.com"
    assert url.path == "/common/oauth2/v2.0/authorize"
    assert query["state"] == [state]
    assert query["code_challenge_method"] == ["S256"]
    assert "offline_access" in query["scope"][0]
    assert "https://graph.microsoft.com/Mail.Read" in query["scope"][0]
    assert "Mail.ReadWrite" not in query["scope"][0]


def test_authorization_url_rejects_untrusted_redirects_and_tenants() -> None:
    pkce = generate_pkce_pair()
    state = generate_oauth_state()
    provider = OutlookEmailProvider(  # type: ignore[arg-type]
        settings=_settings(outlook_oauth_redirect_uri="http://localhost.attacker.example/callback")
    )
    with pytest.raises(EmailProviderConfigurationError):
        provider.build_authorization_url(state=state, code_challenge=pkce.challenge)

    provider = OutlookEmailProvider(  # type: ignore[arg-type]
        settings=_settings(outlook_oauth_tenant="../common")
    )
    with pytest.raises(EmailProviderConfigurationError):
        provider.build_authorization_url(state=state, code_challenge=pkce.challenge)


@pytest.mark.asyncio
async def test_refresh_rotates_refresh_token_without_logging_provider_payload() -> None:
    seen_form: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_form.update(parse_qs(request.content.decode(), strict_parsing=True))
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
                "scope": "openid offline_access Mail.Read",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OutlookEmailProvider(settings=_settings(), client=client)  # type: ignore[arg-type]
        tokens = await provider.refresh_access_token(refresh_token="old-refresh")

    assert seen_form["grant_type"] == ["refresh_token"]
    assert seen_form["refresh_token"] == ["old-refresh"]
    assert seen_form["client_secret"] == ["client-secret"]
    assert tokens.access_token == "new-access"
    assert tokens.refresh_token == "new-refresh"
    assert "new-access" not in repr(tokens)


@pytest.mark.asyncio
async def test_profile_uses_stable_id_and_snapshots_delta_cursor() -> None:
    requests: list[httpx.Request] = []
    delta_link = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?%24deltatoken=opaque"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/me"):
            return httpx.Response(
                200,
                json={
                    "id": "stable-user-id",
                    "displayName": "Travel Desk",
                    "mail": None,
                    "userPrincipalName": "desk@example.com",
                },
            )
        return httpx.Response(200, json={"value": [], "@odata.deltaLink": delta_link})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OutlookEmailProvider(settings=_settings(), client=client)  # type: ignore[arg-type]
        profile = await provider.get_account_profile(access_token="access")

    assert profile.provider_account_id == "stable-user-id"
    assert profile.email_address == "desk@example.com"
    assert profile.history_cursor == delta_link
    assert requests[1].headers["Prefer"] == 'IdType="ImmutableId"'


@pytest.mark.asyncio
async def test_initial_listing_is_bounded_paginated_and_uses_immutable_ids() -> None:
    seen_requests: list[httpx.Request] = []
    next_link = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?%24skiptoken=opaque"

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        if len(seen_requests) == 1:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"id": "m1", "conversationId": "c1"},
                        {"id": "m2", "conversationId": "c2"},
                    ],
                    "@odata.nextLink": next_link,
                },
            )
        return httpx.Response(
            200,
            json={"value": [{"id": "m2"}, {"id": "m3", "conversationId": "c3"}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OutlookEmailProvider(  # type: ignore[arg-type]
            settings=_settings(email_sync_max_messages=3),
            client=client,
        )
        messages = await provider.list_messages(
            access_token="access",
            lookback_days=7,
            max_messages=20,
        )

    assert [message.provider_message_id for message in messages] == ["m1", "m2", "m3"]
    assert all(request.headers["Prefer"] == 'IdType="ImmutableId"' for request in seen_requests)
    assert "$filter" in seen_requests[0].url.params
    assert "$filter" not in seen_requests[1].url.params


@pytest.mark.asyncio
async def test_delta_page_is_resumable_and_rejects_external_links() -> None:
    start_link = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?%24deltatoken=start"
    )
    next_link = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?%24skiptoken=next"
    )

    def valid_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    {"id": "new-message"},
                    {"id": "removed-message", "@removed": {"reason": "deleted"}},
                ],
                "@odata.nextLink": next_link,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(valid_handler)) as client:
        provider = OutlookEmailProvider(settings=_settings(), client=client)  # type: ignore[arg-type]
        page = await provider.list_history_page(
            access_token="access",
            start_history_id=start_link,
        )

    assert page.next_page_token == next_link
    assert page.resume_history_id == next_link
    assert [change.kind for change in page.changes] == [
        EmailChangeKind.ADDED,
        EmailChangeKind.DELETED,
    ]

    def malicious_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [],
                "@odata.nextLink": "https://attacker.example/steal",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(malicious_handler)) as client:
        provider = OutlookEmailProvider(settings=_settings(), client=client)  # type: ignore[arg-type]
        with pytest.raises(EmailProviderResponseError) as captured:
            await provider.list_history_page(
                access_token="access",
                start_history_id=start_link,
            )
    assert captured.value.code == "EMAIL_PROVIDER_PAGINATION_INVALID"

    def cross_resource_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [],
                "@odata.nextLink": (
                    "https://graph.microsoft.com/v1.0/me/drive/root/children"
                    "?%24skiptoken=unexpected"
                ),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(cross_resource_handler)) as client:
        provider = OutlookEmailProvider(settings=_settings(), client=client)  # type: ignore[arg-type]
        with pytest.raises(EmailProviderResponseError) as captured:
            await provider.list_history_page(
                access_token="access",
                start_history_id=start_link,
            )
    assert captured.value.code == "EMAIL_PROVIDER_PAGINATION_INVALID"


@pytest.mark.asyncio
async def test_message_and_pdf_attachment_are_normalized_as_plain_text() -> None:
    request_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_paths.append(request.url.path)
        if request.url.path.endswith("/attachments"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "@odata.type": "#microsoft.graph.fileAttachment",
                            "id": "attachment-1",
                            "name": "visa.pdf",
                            "contentType": "application/pdf",
                            "size": 8,
                            "isInline": False,
                        }
                    ]
                },
            )
        if request.url.path.endswith("/$value"):
            return httpx.Response(200, content=b"%PDF-1.7")
        return httpx.Response(
            200,
            json={
                "id": "message-1",
                "conversationId": "conversation-1",
                "receivedDateTime": "2026-07-29T12:00:00Z",
                "subject": "Visa attached",
                "sender": {
                    "emailAddress": {
                        "address": "sender@example.com",
                        "name": "Sender",
                    }
                },
                "toRecipients": [{"emailAddress": {"address": "desk@example.com"}}],
                "bodyPreview": "Please see attached",
                "body": {"contentType": "text", "content": "Please see attached."},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OutlookEmailProvider(settings=_settings(), client=client)  # type: ignore[arg-type]
        message = await provider.get_message(
            access_token="access",
            message_id="message-1",
        )
        content = await provider.get_attachment(
            access_token="access",
            message_id="message-1",
            attachment_id="attachment-1",
        )

    assert message.labels == ("INBOX",)
    assert all("/mailFolders/inbox/messages/" in path for path in request_paths)
    assert message.plain_text_excerpt == "Please see attached."
    assert message.sender is not None
    assert message.sender.address == "sender@example.com"
    assert message.attachments[0].filename == "visa.pdf"
    assert content == b"%PDF-1.7"
