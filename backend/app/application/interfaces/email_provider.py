"""Provider-neutral contracts for inbound email integrations.

The application layer deliberately receives normalized, bounded data instead
of provider payload dictionaries. Sensitive fields are excluded from object
representations so routine debug output cannot disclose mailbox content or
OAuth credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, Protocol


class EmailProviderName(str, Enum):
    GMAIL = "gmail"
    OUTLOOK = "outlook"


@dataclass(frozen=True, slots=True)
class EmailAddress:
    address: str = field(repr=False)
    display_name: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class EmailTokenSet:
    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    token_type: str = "Bearer"
    expires_at: datetime | None = None
    scopes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EmailAccountProfile:
    provider_account_id: str = field(repr=False)
    email_address: str = field(repr=False)
    display_name: str | None = field(default=None, repr=False)
    history_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class EmailMessageReference:
    provider_message_id: str
    thread_id: str | None = None


@dataclass(frozen=True, slots=True)
class EmailAttachment:
    provider_attachment_id: str | None
    filename: str = field(repr=False)
    content_type: str
    size_bytes: int
    disposition: Literal["attachment", "inline", "unspecified"] = "unspecified"
    content_id: str | None = field(default=None, repr=False)
    inline_content: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class NormalizedEmailMessage:
    provider_message_id: str
    thread_id: str | None
    history_id: str | None
    received_at: datetime | None
    subject: str = field(repr=False)
    sender: EmailAddress | None = field(repr=False)
    to: tuple[EmailAddress, ...] = field(default=(), repr=False)
    cc: tuple[EmailAddress, ...] = field(default=(), repr=False)
    reply_to: tuple[EmailAddress, ...] = field(default=(), repr=False)
    snippet: str = field(default="", repr=False)
    plain_text_excerpt: str = field(default="", repr=False)
    labels: tuple[str, ...] = field(default=(), repr=False)
    attachments: tuple[EmailAttachment, ...] = field(default=(), repr=False)


class EmailChangeKind(str, Enum):
    ADDED = "added"
    DELETED = "deleted"
    LABELS_CHANGED = "labels_changed"


@dataclass(frozen=True, slots=True)
class EmailMessageChange:
    provider_history_id: str
    provider_message_id: str
    kind: EmailChangeKind


@dataclass(frozen=True, slots=True)
class EmailHistoryPage:
    changes: tuple[EmailMessageChange, ...]
    next_page_token: str | None
    latest_history_id: str
    resume_history_id: str | None = None


class EmailProviderError(Exception):
    """Safe provider exception that never includes response payloads or tokens."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        transient: bool = False,
        reconnect_required: bool = False,
        retry_after_seconds: int | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.transient = transient
        self.reconnect_required = reconnect_required
        self.retry_after_seconds = retry_after_seconds
        self.status_code = status_code


class EmailProviderConfigurationError(EmailProviderError):
    def __init__(
        self,
        message: str = "Email provider configuration is incomplete",
        *,
        code: str = "EMAIL_PROVIDER_NOT_CONFIGURED",
    ) -> None:
        super().__init__(message, code=code)


class EmailProviderAuthenticationError(EmailProviderError):
    def __init__(
        self,
        message: str = "The email provider authorization is no longer valid",
        *,
        code: str = "EMAIL_PROVIDER_AUTH_FAILED",
        reconnect_required: bool = True,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            message,
            code=code,
            reconnect_required=reconnect_required,
            status_code=status_code,
        )


class EmailProviderRateLimitError(EmailProviderError):
    def __init__(
        self,
        message: str = "The email provider temporarily rate-limited this request",
        *,
        code: str = "EMAIL_PROVIDER_RATE_LIMITED",
        retry_after_seconds: int | None = None,
        status_code: int | None = 429,
    ) -> None:
        super().__init__(
            message,
            code=code,
            transient=True,
            retry_after_seconds=retry_after_seconds,
            status_code=status_code,
        )


class EmailProviderTransientError(EmailProviderError):
    def __init__(
        self,
        message: str = "The email provider is temporarily unavailable",
        *,
        code: str = "EMAIL_PROVIDER_UNAVAILABLE",
        retry_after_seconds: int | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(
            message,
            code=code,
            transient=True,
            retry_after_seconds=retry_after_seconds,
            status_code=status_code,
        )


class EmailProviderResponseError(EmailProviderError):
    def __init__(
        self,
        message: str = "The email provider returned an invalid response",
        *,
        code: str = "EMAIL_PROVIDER_RESPONSE_INVALID",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code)


class EmailProvider(Protocol):
    provider_name: EmailProviderName
    supports_remote_token_revocation: bool

    def build_authorization_url(self, *, state: str, code_challenge: str) -> str:
        """Build a provider authorization URL for a persisted one-time state."""
        ...

    async def exchange_authorization_code(
        self,
        *,
        code: str,
        code_verifier: str,
    ) -> EmailTokenSet:
        """Exchange one authorization code after state has been atomically consumed."""
        ...

    async def refresh_access_token(self, *, refresh_token: str) -> EmailTokenSet:
        """Refresh an access token without exposing credentials to the browser."""
        ...

    async def get_account_profile(self, *, access_token: str) -> EmailAccountProfile:
        """Return the connected provider account identity and current cursor."""
        ...

    async def revoke_token(self, *, token: str) -> None:
        """Revoke a provider token during disconnect."""
        ...

    async def list_messages(
        self,
        *,
        access_token: str,
        lookback_days: int,
        max_messages: int,
    ) -> tuple[EmailMessageReference, ...]:
        """Return a fully paginated message reference list, bounded by max_messages."""
        ...

    async def list_history_page(
        self,
        *,
        access_token: str,
        start_history_id: str,
        page_token: str | None = None,
        max_results: int = 100,
    ) -> EmailHistoryPage:
        """Return one resumable incremental-history page."""
        ...

    async def get_message(
        self,
        *,
        access_token: str,
        message_id: str,
    ) -> NormalizedEmailMessage:
        """Return one normalized full message."""
        ...

    async def get_attachment(
        self,
        *,
        access_token: str,
        message_id: str,
        attachment_id: str,
    ) -> bytes:
        """Return one attachment after enforcing the configured byte limit."""
        ...
