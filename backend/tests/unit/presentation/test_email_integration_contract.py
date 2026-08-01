from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_models import (
    EmailArtifactModel,
    EmailConnectionModel,
    EmailReviewItemModel,
)
from app.presentation.api.v1.routes.email_integrations import (
    EMAIL_INTEGRATION_ROLES,
    _agency_scope,
    _allowed_connection_actions,
    _allowed_review_actions,
    _email_owner_filters,
    _email_removal_confirmation_matches,
    _oauth_return_url,
    _original_email_url,
    _owned_connection,
    _provider_configured,
    _require_provider_account_owner,
    router,
)
from app.presentation.api.v1.schemas.email_integration_schemas import (
    ResolveEmailReviewRequest,
)


def test_oauth_return_contract_strips_provider_secrets() -> None:
    settings = SimpleNamespace(
        email_oauth_frontend_return_url=(
            "https://dashboard.example/email-integrations?state=leak&code=leak&error=leak&keep=yes"
        )
    )

    result = _oauth_return_url(settings, "connected")  # type: ignore[arg-type]

    assert result == (
        "https://dashboard.example/email-integrations"
        "?keep=yes&email_oauth=connected&email_provider=gmail"
    )


def test_oauth_return_contract_rejects_unknown_status() -> None:
    settings = SimpleNamespace(
        email_oauth_frontend_return_url=("https://dashboard.example/email-integrations")
    )

    result = _oauth_return_url(settings, "provider_text")  # type: ignore[arg-type]

    assert result.endswith("?email_oauth=failed&email_provider=gmail")
    assert "provider_text" not in result


def test_original_email_urls_are_server_derived_and_provider_allowlisted() -> None:
    gmail = _original_email_url(
        provider="gmail",
        account_email="owner+ops@example.test",
        provider_message_id="18f/opaque id",
    )
    outlook = _original_email_url(
        provider="outlook",
        account_email="owner@example.test",
        provider_message_id="AAMk+/opaque id",
    )

    assert gmail == (
        "https://mail.google.com/mail/u/owner%2Bops@example.test/#all/18f%2Fopaque%20id"
    )
    assert outlook == ("https://outlook.office.com/mail/deeplink/read/AAMk%2B%2Fopaque%20id")
    assert (
        _original_email_url(
            provider="unknown",
            account_email="owner@example.test",
            provider_message_id="provider-id",
        )
        is None
    )


def test_provider_configuration_requires_nonempty_secrets() -> None:
    configured = SimpleNamespace(
        gmail_oauth_client_id="client",
        gmail_oauth_client_secret=SecretStr("secret"),
        gmail_oauth_redirect_uri="https://api.example/callback",
        email_token_encryption_key=SecretStr("key"),
    )
    missing_secret = SimpleNamespace(
        gmail_oauth_client_id="client",
        gmail_oauth_client_secret=SecretStr(""),
        gmail_oauth_redirect_uri="https://api.example/callback",
        email_token_encryption_key=SecretStr("key"),
    )

    assert _provider_configured(configured) is True  # type: ignore[arg-type]
    assert _provider_configured(missing_secret) is False  # type: ignore[arg-type]


def test_outlook_configuration_is_independent_from_gmail() -> None:
    configured = SimpleNamespace(
        outlook_oauth_client_id="client",
        outlook_oauth_client_secret=SecretStr("secret"),
        outlook_oauth_redirect_uri="https://api.example/oauth/outlook/callback",
        email_token_encryption_key=SecretStr("key"),
    )

    assert _provider_configured(configured, "outlook") is True  # type: ignore[arg-type]
    assert _provider_configured(configured, "gmail") is False  # type: ignore[arg-type]


def test_gmail_and_outlook_oauth_routes_are_registered_separately() -> None:
    paths = {route.path for route in router.routes}

    assert "/oauth/gmail/authorize" in paths
    assert "/oauth/gmail/callback" in paths
    assert "/oauth/outlook/authorize" in paths
    assert "/oauth/outlook/callback" in paths
    assert "/connections/{connection_id}/data" in paths


def test_account_removal_confirmation_requires_selected_mailbox() -> None:
    assert _email_removal_confirmation_matches(
        confirmation_email="  OPS@Example.com ",
        connection_email="ops@example.com",
    )
    assert not _email_removal_confirmation_matches(
        confirmation_email="other@example.com",
        connection_email="ops@example.com",
    )


def test_super_admin_email_scope_is_personal_even_without_an_agency() -> None:
    user = User.create(
        email="super-admin@example.com",
        hashed_password="not-used",
        full_name="Super Admin",
        role=UserRole.SUPER_ADMIN,
    )

    assert UserRole.SUPER_ADMIN in EMAIL_INTEGRATION_ROLES
    assert _agency_scope(user) is None
    filters = _email_owner_filters(
        EmailConnectionModel.owner_user_id,
        EmailConnectionModel.agency_id,
        user,
    )
    assert len(filters) == 1
    assert filters[0].right.value == user.id


def test_staff_can_connect_personal_email_but_coordinator_cannot() -> None:
    assert UserRole.AGENCY_STAFF in EMAIL_INTEGRATION_ROLES
    assert UserRole.AGENCY_COORDINATOR not in EMAIL_INTEGRATION_ROLES


def test_manager_email_access_remains_scoped_to_own_organization() -> None:
    agency_id = uuid.uuid4()
    user = User.create(
        email="manager@example.com",
        hashed_password="not-used",
        full_name="Manager",
        role=UserRole.AGENCY_MANAGER,
        agency_id=agency_id,
    )

    assert _agency_scope(user) == agency_id


def test_connection_actions_follow_lifecycle() -> None:
    settings = SimpleNamespace(
        email_integrations_enabled=True,
        email_sync_enabled=True,
        gmail_oauth_client_id="client",
        gmail_oauth_client_secret=SecretStr("secret"),
        gmail_oauth_redirect_uri="https://api.example/callback",
        email_token_encryption_key=SecretStr("key"),
    )
    connection = EmailConnectionModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        provider="gmail",
        provider_account_id="account",
        email_address="ops@example.com",
        status="active",
    )

    assert _allowed_connection_actions(connection, settings) == [
        "sync",
        "pause",
        "reconnect",
        "disconnect",
        "remove",
    ]
    connection.status = "paused"
    assert _allowed_connection_actions(connection, settings) == [
        "resume",
        "reconnect",
        "disconnect",
        "remove",
    ]
    settings.email_sync_enabled = False
    assert _allowed_connection_actions(connection, settings) == [
        "reconnect",
        "disconnect",
        "remove",
    ]
    connection.status = "disconnecting"
    assert _allowed_connection_actions(connection, settings) == [
        "disconnect",
        "remove",
    ]


def test_review_actions_require_a_staged_assignable_document() -> None:
    owner_user_id = uuid.uuid4()
    review = EmailReviewItemModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=owner_user_id,
        message_id=uuid.uuid4(),
        review_type="relevance",
        status="open",
        proposed_action="classify_document",
        revision=1,
    )
    artifact = EmailArtifactModel(
        id=uuid.uuid4(),
        agency_id=review.agency_id,
        owner_user_id=owner_user_id,
        message_id=review.message_id,
        provider_artifact_id="attachment",
        kind="attachment",
        storage_key="email-integrations/staged.pdf",
        detected_type="unknown",
    )

    assert _allowed_review_actions(review, artifact) == [
        "assign",
        "defer",
        "mark_unrelated",
        "reject",
    ]
    assert _allowed_review_actions(review, None) == [
        "defer",
        "mark_unrelated",
        "reject",
    ]


async def test_same_agency_user_cannot_load_another_users_connection() -> None:
    session = AsyncMock()
    session.scalar.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        await _owned_connection(
            session,
            connection_id=uuid.uuid4(),
            owner_user_id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 404
    statement = session.scalar.await_args.args[0]
    assert "email_connections.owner_user_id" in str(statement)


def test_oauth_provider_account_cannot_be_taken_over_within_same_agency() -> None:
    agency_id = uuid.uuid4()
    connection = EmailConnectionModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        owner_user_id=uuid.uuid4(),
        provider="gmail",
        provider_account_id="provider-account",
        email_address="ops@example.com",
    )

    with pytest.raises(ValueError, match="another owner"):
        _require_provider_account_owner(
            connection,
            agency_id=agency_id,
            owner_user_id=uuid.uuid4(),
        )


def test_human_review_can_supply_a_supported_document_type() -> None:
    request = ResolveEmailReviewRequest(
        action="assign",
        group_id=uuid.uuid4(),
        passenger_id=uuid.uuid4(),
        document_type="flight_ticket",
        expected_revision=1,
    )

    assert request.document_type == "flight_ticket"
