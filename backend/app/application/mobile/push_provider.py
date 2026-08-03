"""Provider-neutral mobile push delivery with a bounded Expo implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config.settings import MobileSettings

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_PUSH_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"
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
    provider_ticket_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class MobilePushReceipt:
    """One provider receipt without provider message text or device content."""

    provider_ticket_id: str
    delivered: bool
    retryable: bool
    error_code: str | None = None


class MobilePushProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def enabled(self) -> bool: ...

    async def send(self, messages: list[MobilePushMessage]) -> list[MobilePushTicket]: ...

    async def get_receipts(
        self,
        provider_ticket_ids: list[str],
    ) -> list[MobilePushReceipt]: ...


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

    async def get_receipts(
        self,
        provider_ticket_ids: list[str],
    ) -> list[MobilePushReceipt]:
        del provider_ticket_ids
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
                raw_ticket_id = raw.get("id") if isinstance(raw, dict) else None
                ticket_id = _validated_ticket_id(raw_ticket_id)
                if ticket_id is None:
                    tickets.append(
                        _ticket(
                            message,
                            accepted=False,
                            retryable=True,
                            error_code="provider_malformed_response",
                        )
                    )
                    continue
                tickets.append(
                    _ticket(
                        message,
                        accepted=True,
                        retryable=False,
                        provider_ticket_id=ticket_id,
                    )
                )
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
        ticket_ids = [
            item.provider_ticket_id
            for item in tickets
            if item.provider_ticket_id is not None
        ]
        seen_ticket_ids: set[str] = set()
        duplicate_ids: set[str] = set()
        for ticket_id in ticket_ids:
            if ticket_id in seen_ticket_ids:
                duplicate_ids.add(ticket_id)
            seen_ticket_ids.add(ticket_id)
        if not duplicate_ids:
            return tickets
        return [
            (
                MobilePushTicket(
                    registration_id=item.registration_id,
                    notification_id=item.notification_id,
                    accepted=False,
                    retryable=True,
                    error_code="provider_malformed_response",
                )
                if item.provider_ticket_id in duplicate_ids
                else item
            )
            for item in tickets
        ]

    async def get_receipts(
        self,
        provider_ticket_ids: list[str],
    ) -> list[MobilePushReceipt]:
        if not provider_ticket_ids:
            return []
        if len(provider_ticket_ids) > 1_000:
            raise ValueError("Expo Push Service accepts at most 1,000 receipt IDs per request")
        if len(set(provider_ticket_ids)) != len(provider_ticket_ids):
            raise ValueError("Provider receipt IDs must be unique")
        if any(_validated_ticket_id(item) != item for item in provider_ticket_ids):
            raise ValueError("Provider receipt ID was malformed")

        response = await self._post_json(
            EXPO_PUSH_RECEIPTS_URL,
            payload={"ids": provider_ticket_ids},
        )
        if response is None or response.status_code == 429 or response.status_code >= 500:
            return _receipt_batch_failure(
                provider_ticket_ids,
                "provider_unavailable",
                retryable=True,
            )
        if response.status_code != 200:
            return _receipt_batch_failure(
                provider_ticket_ids,
                "provider_rejected",
                retryable=False,
            )
        try:
            payload = response.json()
            raw_receipts = payload.get("data") if isinstance(payload, dict) else None
        except ValueError:
            raw_receipts = None
        if not isinstance(raw_receipts, dict):
            return _receipt_batch_failure(
                provider_ticket_ids,
                "provider_malformed_response",
                retryable=True,
            )

        receipts: list[MobilePushReceipt] = []
        for ticket_id in provider_ticket_ids:
            raw = raw_receipts.get(ticket_id)
            if raw is None:
                receipts.append(
                    MobilePushReceipt(
                        provider_ticket_id=ticket_id,
                        delivered=False,
                        retryable=True,
                        error_code="receipt_not_ready",
                    )
                )
                continue
            status = raw.get("status") if isinstance(raw, dict) else None
            if status == "ok":
                receipts.append(
                    MobilePushReceipt(
                        provider_ticket_id=ticket_id,
                        delivered=True,
                        retryable=False,
                    )
                )
                continue
            details = raw.get("details") if isinstance(raw, dict) else None
            raw_code = details.get("error") if isinstance(details, dict) else None
            code = raw_code if isinstance(raw_code, str) else "provider_receipt_error"
            receipts.append(
                MobilePushReceipt(
                    provider_ticket_id=ticket_id,
                    delivered=False,
                    retryable=code in _RETRYABLE_EXPO_CODES,
                    error_code=_safe_error_code(code),
                )
            )
        return receipts

    async def _post_json(
        self,
        url: str,
        *,
        payload: dict[str, object],
    ) -> httpx.Response | None:
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
                return await client.post(url, headers=headers, json=payload)
            except (httpx.TimeoutException, httpx.TransportError):
                return None
        finally:
            if owns_client:
                await client.aclose()


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
    provider_ticket_id: str | None = None,
    error_code: str | None = None,
) -> MobilePushTicket:
    return MobilePushTicket(
        registration_id=message.registration_id,
        notification_id=message.notification_id,
        accepted=accepted,
        retryable=retryable,
        provider_ticket_id=provider_ticket_id,
        error_code=error_code,
    )


def _receipt_batch_failure(
    provider_ticket_ids: list[str],
    code: str,
    *,
    retryable: bool,
) -> list[MobilePushReceipt]:
    return [
        MobilePushReceipt(
            provider_ticket_id=ticket_id,
            delivered=False,
            retryable=retryable,
            error_code=code,
        )
        for ticket_id in provider_ticket_ids
    ]


def _validated_ticket_id(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 255:
        return None
    if any(character.isspace() or ord(character) < 32 for character in value):
        return None
    return value


def _safe_error_code(value: str) -> str:
    normalized = "".join(
        character for character in value if character.isalnum() or character == "_"
    )
    return normalized[:80] or "provider_ticket_error"


__all__ = [
    "DisabledMobilePushProvider",
    "ExpoMobilePushProvider",
    "MobilePushMessage",
    "MobilePushProvider",
    "MobilePushReceipt",
    "MobilePushTicket",
    "get_mobile_push_provider",
]
