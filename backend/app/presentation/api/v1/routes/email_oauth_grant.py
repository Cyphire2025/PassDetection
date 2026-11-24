"""Typed construction and encrypted-grant field updates shared by OAuth callbacks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from app.application.interfaces.email_provider import EmailAccountProfile, EmailTokenSet
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.email.token_encryption import EmailTokenCipher, EncryptedToken


def _new_oauth_connection(
    *,
    agency_id: uuid.UUID,
    user_id: uuid.UUID,
    provider_name: Literal["gmail", "outlook"],
    profile: EmailAccountProfile,
    token_set: EmailTokenSet,
    cipher: EmailTokenCipher,
    now: datetime,
) -> EmailConnectionModel:
    """Construct the original pending row; caller retains offline-grant and ownership checks."""

    return EmailConnectionModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        owner_user_id=user_id,
        provider=provider_name,
        provider_account_id=profile.provider_account_id,
        email_address=profile.email_address,
        normalized_email_address=profile.email_address.casefold(),
        display_name=profile.display_name,
        status="active",
        sync_state="queued",
        scopes=list(token_set.scopes),
        token_key_version=cipher.key_version,
        sync_generation=0,
        consecutive_failures=0,
        created_by_user_id=user_id,
        created_at=now,
        updated_at=now,
    )


def _apply_encrypted_oauth_grant(
    connection: EmailConnectionModel,
    *,
    profile: EmailAccountProfile,
    token_set: EmailTokenSet,
    cipher: EmailTokenCipher,
    encrypted_access: EncryptedToken,
    encrypted_refresh: EncryptedToken | None,
    now: datetime,
) -> None:
    """Apply one encrypted grant in original field order; caller owns flush/audit/commit."""

    connection.provider_account_id = profile.provider_account_id
    connection.email_address = profile.email_address
    connection.normalized_email_address = profile.email_address.casefold()
    connection.display_name = profile.display_name[:255] if profile.display_name else None
    connection.status = "active"
    connection.sync_state = "queued"
    connection.access_token_ciphertext = encrypted_access.ciphertext.encode("ascii")
    if encrypted_refresh is not None:
        connection.refresh_token_ciphertext = encrypted_refresh.ciphertext.encode("ascii")
    connection.token_key_version = cipher.key_version
    connection.token_expires_at = token_set.expires_at
    connection.scopes = list(token_set.scopes)
    connection.sync_cursor = None
    connection.sync_generation += 1
    connection.next_sync_at = now
    connection.paused_at = None
    connection.disconnected_at = None
    connection.last_error_code = None
    connection.last_error_message = None
    connection.last_error_at = None
    connection.updated_at = now
