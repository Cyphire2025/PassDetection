"""Provider-neutral password-recovery notification contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class IdentityRecoveryNotification:
    recipient: str
    purpose: str
    recovery_url: str
    expires_at: datetime
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class IdentityNotificationDelivery:
    provider_message_id: str


class IdentityNotificationProvider(Protocol):
    async def deliver(
        self,
        notification: IdentityRecoveryNotification,
    ) -> IdentityNotificationDelivery: ...


class IdentityNotificationProviderError(RuntimeError):
    """A bounded provider attempt failed without exposing recipient or token."""


class IdentityNotificationDeliveryDisabled(IdentityNotificationProviderError):
    """This deployment deliberately has no recovery delivery provider."""


__all__ = [
    "IdentityNotificationDelivery",
    "IdentityNotificationDeliveryDisabled",
    "IdentityNotificationProvider",
    "IdentityNotificationProviderError",
    "IdentityRecoveryNotification",
]
