"""Direct HTTP/2 iOS alerts. APNs acceptance is not proof of a phone banner."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import Callable

import httpx

from app.application.mobile.push_provider import (
    MobilePushMessage,
    MobilePushReceipt,
    MobilePushTicket,
)
from app.core.config.settings import MobileSettings
from app.infrastructure.mobile_push.apns_credentials import ApnsCredentialError, apns_access_token

APNS_TOPIC = "com.globalconnects.groupcompanion"
_HOSTS = {"development": "api.sandbox.push.apple.com", "production": "api.push.apple.com"}
_TOKEN = re.compile(r"^[0-9a-fA-F]{16,512}$")


class ApnsMobilePushProvider:
    name = "apns"
    enabled = True
    supports_receipts = False

    def __init__(
        self,
        settings: MobileSettings,
        *,
        client: httpx.AsyncClient | None = None,
        access_token_provider: Callable[[], str] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._access_token_provider = access_token_provider
        self._token: str | None = None
        self._credential_failed = False

    async def prepare(self) -> None:
        self._token = None
        self._credential_failed = False
        try:
            self._token = (
                self._access_token_provider()
                if self._access_token_provider
                else await asyncio.to_thread(apns_access_token, self._settings)
            )
            if not self._token or any(char.isspace() for char in self._token):
                raise ApnsCredentialError("apns_credentials_unavailable")
        except ApnsCredentialError:
            self._credential_failed = True

    async def send(self, messages: list[MobilePushMessage]) -> list[MobilePushTicket]:
        if len(messages) > 100:
            raise ValueError("APNs batches are limited to 100 messages")
        payloads = [_payload(message) for message in messages]
        if not messages:
            return []
        if self._token is None and not self._credential_failed:
            await self.prepare()
        if self._credential_failed:
            return [
                _ticket(message, error_code="apns_credentials_unavailable") for message in messages
            ]
        client = self._client or httpx.AsyncClient(
            http2=True,
            timeout=self._settings.push_timeout_seconds,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=20),
        )
        semaphore = asyncio.Semaphore(20)

        async def one(message: MobilePushMessage, payload: bytes) -> MobilePushTicket:
            async with semaphore:
                return await self._send_one(client, message, payload)

        try:
            return list(
                await asyncio.gather(
                    *(
                        one(message, payload)
                        for message, payload in zip(messages, payloads, strict=True)
                    )
                )
            )
        finally:
            if self._client is None:
                await client.aclose()

    async def _send_one(
        self, client: httpx.AsyncClient, message: MobilePushMessage, payload: bytes
    ) -> MobilePushTicket:
        # The environment is extracted from the installed signed profile, not APP_ENV.
        host = _HOSTS[message.apns_environment or ""]
        request_id = str(uuid.uuid4())
        try:
            response = await asyncio.wait_for(
                client.post(
                    f"https://{host}/3/device/{message.token}",
                    content=payload,
                    headers={
                        "authorization": f"bearer {self._token}",
                        "apns-topic": APNS_TOPIC,
                        "apns-push-type": "alert",
                        "apns-priority": "10",
                        "apns-id": request_id,
                        "apns-expiration": str(int(time.time()) + message.ttl_seconds)
                        if message.ttl_seconds
                        else "0",
                        "content-type": "application/json",
                    },
                    timeout=self._settings.push_timeout_seconds,
                    follow_redirects=False,
                ),
                timeout=self._settings.push_timeout_seconds,
            )
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout):
            return _ticket(message, error_code="apns_connection_unavailable", retryable=True)
        except (TimeoutError, httpx.TimeoutException, httpx.TransportError):
            return _ticket(message, error_code="provider_outcome_unknown", outcome_unknown=True)
        if response.status_code == 200:
            # APNs echoes this identifier; it is diagnostic, not a delivery receipt or dedupe key.
            return _ticket(message, accepted=True, provider_ticket_id=request_id)
        if 200 <= response.status_code < 300:
            return _ticket(message, error_code="provider_outcome_unknown", outcome_unknown=True)
        if response.status_code == 429 or response.status_code >= 500:
            delay = 900 if response.status_code >= 500 else 60
            try:
                delay = max(delay, min(3600, int(response.headers.get("retry-after", "0"))))
            except ValueError:
                pass
            return _ticket(
                message,
                error_code="apns_unavailable"
                if response.status_code >= 500
                else "apns_rate_limited",
                retryable=True,
                retry_after_seconds=delay,
            )
        try:
            data = response.json()
        except ValueError:
            data = None
        reason = data.get("reason") if isinstance(data, dict) else None
        # Topic/environment misconfiguration must not revoke an otherwise valid device token.
        code = {
            "Unregistered": "DeviceNotRegistered",
            "BadDeviceToken": "apns_bad_device_token",
            "DeviceTokenNotForTopic": "apns_token_topic_mismatch",
            "ExpiredProviderToken": "apns_authentication_failed",
            "InvalidProviderToken": "apns_authentication_failed",
            "BadTopic": "apns_topic_configuration",
            "TopicDisallowed": "apns_topic_configuration",
            "PayloadTooLarge": "apns_payload_too_large",
        }.get(reason if isinstance(reason, str) else "", "apns_provider_rejected")
        return _ticket(message, error_code=code)

    async def get_receipts(self, provider_ticket_ids: list[str]) -> list[MobilePushReceipt]:
        raise NotImplementedError("APNs does not provide per-message delivery receipts")


def _payload(message: MobilePushMessage) -> bytes:
    message.validate_public_payload()
    if not _TOKEN.fullmatch(message.token) or len(message.token) % 2:
        raise ValueError("APNs requires a native hexadecimal device token")
    if message.apns_environment not in _HOSTS:
        raise ValueError("APNs requires the signed provisioning environment")
    if (
        isinstance(message.ttl_seconds, bool)
        or not isinstance(message.ttl_seconds, int)
        or not 0 <= message.ttl_seconds <= 3600
    ):
        raise ValueError("APNs TTL must be between 0 and 3600 seconds")
    alert = {"title": message.title}
    if message.body:
        alert["body"] = message.body
    # expo-notifications reads remote notification content.data from userInfo['body'].
    # This dictionary is separate from aps.alert.body, which contains the visible text.
    payload = json.dumps(
        {"aps": {"alert": alert, "sound": "default"}, "body": message.data},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > 4096:
        raise ValueError("APNs payload exceeds 4096 bytes")
    return payload


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
