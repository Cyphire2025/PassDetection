"""Secure provider adapters and attachment boundaries for email integrations."""

from app.infrastructure.email.gmail_provider import GmailEmailProvider
from app.infrastructure.email.oauth import (
    PkcePair,
    build_pkce_challenge,
    generate_oauth_state,
    generate_pkce_pair,
    hash_oauth_state,
    oauth_state_matches,
)
from app.infrastructure.email.pdf_validator import (
    EmailPdfValidationError,
    EmailPdfValidator,
    ValidatedEmailPdf,
)
from app.infrastructure.email.token_encryption import (
    EmailTokenCipher,
    EncryptedToken,
    TokenDecryptionError,
    TokenEncryptionError,
)

__all__ = [
    "EmailPdfValidationError",
    "EmailPdfValidator",
    "EmailTokenCipher",
    "EncryptedToken",
    "GmailEmailProvider",
    "PkcePair",
    "TokenDecryptionError",
    "TokenEncryptionError",
    "ValidatedEmailPdf",
    "build_pkce_challenge",
    "generate_oauth_state",
    "generate_pkce_pair",
    "hash_oauth_state",
    "oauth_state_matches",
]
