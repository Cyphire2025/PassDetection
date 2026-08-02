"""Provider-neutral mobile push delivery with a bounded Expo implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config.settings import MobileSettings

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_ALLOWED_DATA_KEYS = frozenset({"route", "trip_id", "event_id"})
_ALLOWED_ROUTES = frozenset(
    {"trip", "documents", "qr", "updates", "readiness", "attendance", "passengers"}
)
_RETRYABLE_EXPO_CODES = frozenset({"MessageRateExceeded", "TOO_MANY_REQUESTS"})


@dataclass(frozen=True, slots=True)
class MobilePushMessage:
    """A lock-screen-safe message addressed to one encrypted registration."""

    registration_id: str
    notification_id: str
    token: str
    title: str
    body: str | None
    data: dict[str, str]
    priority: str = "default"

    def expo_payload(self) -> dict[str, object]:
        if set(self.data) - _ALLOWED_DATA_KEYS:
            raise ValueError("Push data contained a non-allowlisted key")
        if self.data.get("route") not in _ALLOWED_ROUTES:
            raise ValueError("Push data contained an invalid route")
        if len(self.title) > 120 or (self.body is not None and len(self.body) > 240):
            raise ValueError("Push lock-screen content exceeded its safe bound")
        payload: dict[str, object] = {
            "to": self.token,
            "title": self.title,
            "data": self.data,
            "priority": self.priority,
            "channelId": "trip-updates",
        }
        if self.body:
            payload["body"] = self.body
        return payload


@dataclass(frozen=True, slots=True)
class MobilePushTicket:
    registration_id: str
    notification_id: str
    accepted: bool
    retryable: bool
    error_code: str | None = None


class MobilePushProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    async def send(self, messages: list[MobilePushMessage]) -> list[MobilePushTicket]: ...


class DisabledMobilePushProvider:
    """Fail-closed default: durable notifications stay queued."""

    @property
    def name(self) -> str:
        return "disabled"

    @property
    def enabled(self) -> bool:
        return False

    async def send(self, messages: list[MobilePushMessage]) -> list[MobilePushTicket]:
        del messages
        return []


class ExpoMobilePushProvider:
    """Bounded HTTPS adapter for Expo Push Service tickets."""

    def __init__(
        self,
        settings: MobileSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client

    @property
    def name(self) -> str:
        return "expo"

    @property
    def enabled(self) -> bool:
        return True

    async def send(self, messages: list[MobilePushMessage]) -> list[MobilePushTicket]:
        if not messages:
            return []
        if len(messages) > 100:
            raise ValueError("Expo Push Service accepts at most 100 messages per request")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._settings.push_access_token is not None:
            headers["Authorization"] = (
                f"Bearer {self._settings.push_access_token.get_secret_value()}"
            )
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(self._settings.push_timeout_seconds),
            follow_redirects=False,
        )
        try:
            try:
                response = await client.post(
                    EXPO_PUSH_URL,
                    headers=headers,
                    json=[message.expo_payload() for message in messages],
                )
            except (httpx.TimeoutException, httpx.TransportError):
                return _batch_failure(messages, "provider_unavailable", retryable=True)
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code == 429 or response.status_code >= 500:
            return _batch_failure(messages, "provider_unavailable", retryable=True)
        if response.status_code != 200:
            return _batch_failure(messages, "provider_rejected", retryable=False)
        try:
            payload = response.json()
            raw_tickets = payload.get("data") if isinstance(payload, dict) else None
        except ValueError:
            raw_tickets = None
        if not isinstance(raw_tickets, list) or len(raw_tickets) != len(messages):
            return _batch_failure(messages, "provider_malformed_response", retryable=True)

        tickets: list[MobilePushTicket] = []
        for message, raw in zip(messages, raw_tickets, strict=True):
            status = raw.get("status") if isinstance(raw, dict) else None
            if status == "ok":
                tickets.append(_ticket(message, accepted=True, retryable=False))
                continue
            details = raw.get("details") if isinstance(raw, dict) else None
            raw_code = details.get("error") if isinstance(details, dict) else None
            code = raw_code if isinstance(raw_code, str) else "provider_ticket_error"
            tickets.append(
                _ticket(
                    message,
                    accepted=False,
                    retryable=code in _RETRYABLE_EXPO_CODES,
                    error_code=_safe_error_code(code),
                )
            )
        return tickets


def get_mobile_push_provider(settings: MobileSettings) -> MobilePushProvider:
    if settings.push_provider == "expo":
        return ExpoMobilePushProvider(settings)
    return DisabledMobilePushProvider()


def _batch_failure(
    messages: list[MobilePushMessage],
    code: str,
    *,
    retryable: bool,
) -> list[MobilePushTicket]:
    return [
        _ticket(message, accepted=False, retryable=retryable, error_code=code)
        for message in messages
    ]


def _ticket(
    message: MobilePushMessage,
    *,
    accepted: bool,
    retryable: bool,
    error_code: str | None = None,
) -> MobilePushTicket:
    return MobilePushTicket(
        registration_id=message.registration_id,
        notification_id=message.notification_id,
        accepted=accepted,
        retryable=retryable,
        error_code=error_code,
    )


def _safe_error_code(value: str) -> str:
    normalized = "".join(character for character in value if character.isalnum() or character == "_")
    return normalized[:80] or "provider_ticket_error"


__all__ = [
    "DisabledMobilePushProvider",
    "ExpoMobilePushProvider",
    "MobilePushMessage",
    "MobilePushProvider",
    "MobilePushTicket",
    "get_mobile_push_provider",
]
