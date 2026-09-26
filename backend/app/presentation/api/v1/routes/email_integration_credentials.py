"""Shared credential revocation protocol; callers retain transaction ownership."""

from __future__ import annotations

from datetime import datetime

from app.application.interfaces.email_provider import EmailProvider, EmailProviderError
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.email.token_encryption import (
    EmailTokenCipher,
    EncryptedToken,
    TokenEncryptionError,
)


def revocation_credential(
    connection: EmailConnectionModel,
    provider: EmailProvider,
) -> tuple[str | None, bool]:
    if not provider.supports_remote_token_revocation:
        return None, False
    try:
        cipher = EmailTokenCipher.from_settings()
        ciphertext = connection.refresh_token_ciphertext or connection.access_token_ciphertext
        token = (
            cipher.decrypt(
                EncryptedToken(
                    ciphertext=ciphertext.decode("ascii"),
                    key_version=connection.token_key_version,
                )
            )
            if ciphertext
            else None
        )
        return token, False
    except (TokenEncryptionError, UnicodeDecodeError):
        return None, True


def fence_connection_sync(connection: EmailConnectionModel, now: datetime) -> None:
    """Invalidate old worker claims before a caller commits and contacts a provider."""
    connection.status = "disconnecting"
    connection.sync_state = "blocked"
    connection.sync_generation += 1
    connection.sync_lease_token = None
    connection.sync_lease_expires_at = None
    connection.next_sync_at = None
    connection.updated_at = now


async def revoke_provider_credential(
    provider: EmailProvider,
    token: str | None,
    decryption_failed: bool,
) -> EmailProviderError | None:
    if decryption_failed:
        return EmailProviderError(
            "Stored email credentials could not be opened",
            code="EMAIL_TOKEN_DECRYPTION_FAILED",
        )
    if token:
        try:
            await provider.revoke_token(token=token)
        except EmailProviderError as error:
            # Already-invalid tokens are safe to forget; unknown outcomes are not.
            if error.status_code not in {400, 401, 404}:
                return error
    return None
