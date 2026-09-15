"""Direct Android FCM HTTP v1 delivery; acceptance is never a device receipt."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from app.application.mobile.push_provider import (
    MobilePushMessage,
    MobilePushReceipt,
    MobilePushTicket,
)
from app.core.config.settings import MobileSettings
from app.infrastructure.mobile_push.fcm_credentials import FcmCredentialError, fcm_access_token

FCM_ANDROID_PACKAGE = "com.globalconnects.groupcompanion"
_MAX_CONCURRENT_SENDS = 20


class FcmMobilePushProvider:
    name = "fcm"
    enabled = True
    supports_receipts = False

    def __init__(
        self,
        settings: MobileSettings,
        *,
        client: httpx.AsyncClient | None = None,
        access_token_provider: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._access_token_provider = access_token_provider
        self._prepared = False
        self._prepared_token: str | None = None
        self._prepared_error: FcmCredentialError | None = None

    async def prepare(self) -> None:
        """Resolve OAuth before the worker opens/locks its dispatch transaction."""
        self._prepared_token = None
        self._prepared_error = None
        try:
            token = (
                await self._access_token_provider()
                if self._access_token_provider is not None
                else await fcm_access_token(
                    self._settings.push_fcm_credentials_file,
                    self._settings.push_fcm_project_id,
                    timeout=self._settings.push_timeout_seconds,
                )
            )
            if not token or any(character.isspace() for character in token):
                raise FcmCredentialError("fcm_credentials_unavailable")
            self._prepared_token = token
        except FcmCredentialError as error:
            self._prepared_error = error
        self._prepared = True

    async def send(self, messages: list[MobilePushMessage]) -> list[MobilePushTicket]:
        if len(messages) > 100:
            raise ValueError("FCM push batches are limited to 100 messages")
        if not messages:
            return []
        # Validate the whole batch before OAuth or outbound provider work.
        payloads = [_payload(message) for message in messages]
        if not self._prepared:
            await self.prepare()
        if self._prepared_error is not None:
            error = self._prepared_error
            return [
                _ticket(
                    message,
                    error_code=error.code,
                    retryable=error.retryable,
                    retry_after_seconds=60 if error.retryable else None,
                )
                for message in messages
            ]
        token = self._prepared_token
        if token is None:
            raise RuntimeError("FCM provider preparation did not produce a result")
        client = self._client or httpx.AsyncClient(
            timeout=self._settings.push_timeout_seconds,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=_MAX_CONCURRENT_SENDS),
        )
        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SENDS)

        async def send_one(
            message: MobilePushMessage, payload: dict[str, object]
        ) -> MobilePushTicket:
            async with semaphore:
                return await self._send_one(client, token, message, payload)

        try:
            return list(
                await asyncio.gather(
                    *(
                        send_one(message, payload)
                        for message, payload in zip(messages, payloads, strict=True)
                    )
                )
            )
        finally:
            if self._client is None:
                await client.aclose()

    async def _send_one(
        self,
        client: httpx.AsyncClient,
        token: str,
        message: MobilePushMessage,
        payload: dict[str, object],
    ) -> MobilePushTicket:
        project = self._settings.push_fcm_project_id
        try:
            response = await asyncio.wait_for(
                client.post(
                    f"https://fcm.googleapis.com/v1/projects/{project}/messages:send",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self._settings.push_timeout_seconds,
                    follow_redirects=False,
                ),
                timeout=self._settings.push_timeout_seconds,
            )
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout):
            return _ticket(message, error_code="fcm_connection_unavailable", retryable=True)
        except (TimeoutError, httpx.TimeoutException, httpx.TransportError):
            # The remote server may have accepted the request. FCM provides no
            # idempotency key or per-message receipt endpoint to disambiguate it.
            return _ticket(message, error_code="provider_outcome_unknown", outcome_unknown=True)
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code == 200:
            name = data.get("name") if isinstance(data, dict) else None
            prefix = f"projects/{project}/messages/"
            if (
                isinstance(name, str)
                and name.startswith(prefix)
                and len(name) > len(prefix)
                and len(name) <= 255
                and all(32 < ord(char) < 127 for char in name)
            ):
                return _ticket(message, accepted=True, provider_ticket_id=name)
            return _ticket(message, error_code="provider_outcome_unknown", outcome_unknown=True)
        if 200 <= response.status_code < 300:
            return _ticket(message, error_code="provider_outcome_unknown", outcome_unknown=True)
        if response.status_code in {429, 503}:
            return _ticket(
                message,
                error_code="fcm_quota_exceeded"
                if response.status_code == 429
                else "fcm_unavailable",
                retryable=True,
                retry_after_seconds=_retry_after(response),
            )
        if response.status_code >= 500 or response.status_code in {408, 409}:
            return _ticket(message, error_code="provider_outcome_unknown", outcome_unknown=True)
        return _ticket(message, error_code=_error_code(data, response.status_code))

    async def get_receipts(self, provider_ticket_ids: list[str]) -> list[MobilePushReceipt]:
        del provider_ticket_ids
        raise NotImplementedError("FCM does not provide per-message delivery receipts")


def _payload(message: MobilePushMessage) -> dict[str, object]:
    message.validate_public_payload()
    if (
        not 16 <= len(message.token) <= 512
        or any(char.isspace() for char in message.token)
        or message.token.startswith(("ExpoPushToken[", "ExponentPushToken["))
    ):
        raise ValueError("FCM requires an opaque native Android registration token")
    if any(not isinstance(value, str) for value in message.data.values()):
        raise ValueError("FCM push data must contain only strings")
    if (
        isinstance(message.ttl_seconds, bool)
        or not isinstance(message.ttl_seconds, int)
        or not 0 <= message.ttl_seconds <= 3600
    ):
        raise ValueError("FCM push TTL must be between 0 and 3600 seconds")
    notification: dict[str, object] = {"title": message.title}
    if message.body:
        notification["body"] = message.body
    return {
        "message": {
            "token": message.token,
            "notification": notification,
            "data": message.data,
            "android": {
                "restricted_package_name": FCM_ANDROID_PACKAGE,
                "priority": "high" if message.priority == "high" else "normal",
                "ttl": f"{message.ttl_seconds}s",
                "notification": {
                    "channel_id": "trip-updates",
                    "tag": message.notification_id,
                    "default_sound": True,
                    "visibility": "PRIVATE",
                },
            },
        }
    }


def _ticket(
    message: MobilePushMessage,
    *,
    accepted: bool = False,
    retryable: bool = False,
    provider_ticket_id: str | None = None,
    error_code: str | None = None,
    outcome_unknown: bool = False,
    retry_after_seconds: int | None = None,
) -> MobilePushTicket:
    return MobilePushTicket(
        registration_id=message.registration_id,
        notification_id=message.notification_id,
        accepted=accepted,
        retryable=retryable,
        provider_ticket_id=provider_ticket_id,
        error_code=error_code,
        requires_receipt=False,
        outcome_unknown=outcome_unknown,
        retry_after_seconds=retry_after_seconds,
    )


def _error_code(data: object, status: int) -> str:
    error = data.get("error") if isinstance(data, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    if isinstance(details, list):
        for item in details:
            if (
                not isinstance(item, dict)
                or item.get("@type") != "type.googleapis.com/google.firebase.fcm.v1.FcmError"
            ):
                continue
            if item.get("errorCode") == "UNREGISTERED":
                return "DeviceNotRegistered"
            if item.get("errorCode") == "SENDER_ID_MISMATCH":
                return "fcm_sender_id_mismatch"
    if status in {401, 403}:
        return "fcm_authentication_failed"
    if status == 400:
        return "fcm_invalid_argument"
    return "fcm_provider_rejected"


def _retry_after(response: httpx.Response) -> int:
    minimum = 60 if response.status_code == 429 else 5
    raw = response.headers.get("Retry-After", "")
    try:
        seconds = int(raw)
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            seconds = int((when - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            seconds = minimum
    return min(3600, max(minimum, seconds))
