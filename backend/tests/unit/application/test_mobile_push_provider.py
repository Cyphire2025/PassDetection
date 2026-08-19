from __future__ import annotations

import json

import httpx
import pytest

from app.application.mobile.push_provider import (
    DisabledMobilePushProvider,
    ExpoMobilePushProvider,
    MobilePushMessage,
)
from app.core.config.settings import MobileSettings


def _message(**overrides: object) -> MobilePushMessage:
    values: dict[str, object] = {
        "registration_id": "00000000-0000-4000-8000-000000000001",
        "notification_id": "00000000-0000-4000-8000-000000000002",
        "token": "ExponentPushToken[abcdefghijklmnopqrstuv]",
        "title": "Global Connect Travels update",
        "body": None,
        "data": {
            "route": "updates",
            "trip_id": "00000000-0000-4000-8000-000000000003",
            "event_id": "00000000-0000-4000-8000-000000000004",
        },
    }
    values.update(overrides)
    return MobilePushMessage(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_disabled_provider_is_fail_closed() -> None:
    provider = DisabledMobilePushProvider()

    assert provider.name == "disabled"
    assert provider.enabled is False
    assert await provider.send([_message()]) == []


def test_message_rejects_non_allowlisted_push_data() -> None:
    message = _message(
        data={
            "route": "updates",
            "trip_id": "00000000-0000-4000-8000-000000000003",
            "passport_number": "P1234567",
        }
    )

    with pytest.raises(ValueError, match="non-allowlisted"):
        message.expo_payload()


@pytest.mark.asyncio
async def test_expo_provider_sends_only_lock_screen_safe_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"status": "ok", "id": "ticket"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ExpoMobilePushProvider(
        MobileSettings(push_provider="expo", push_access_token="provider-secret"),
        client=client,
    )
    try:
        tickets = await provider.send([_message()])
    finally:
        await client.aclose()

    assert tickets[0].accepted is True
    assert tickets[0].provider_ticket_id == "ticket"
    assert captured["authorization"] == "Bearer provider-secret"
    payload = captured["payload"]
    assert isinstance(payload, list)
    assert payload[0]["title"] == "Global Connect Travels update"
    assert "body" not in payload[0]
    assert set(payload[0]["data"]) == {"route", "trip_id", "event_id"}


@pytest.mark.asyncio
async def test_expo_provider_classifies_revoked_device_ticket() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "status": "error",
                        "message": "redacted",
                        "details": {"error": "DeviceNotRegistered"},
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ExpoMobilePushProvider(MobileSettings(push_provider="expo"), client=client)
    try:
        tickets = await provider.send([_message()])
    finally:
        await client.aclose()

    assert tickets[0].accepted is False
    assert tickets[0].retryable is False
    assert tickets[0].error_code == "DeviceNotRegistered"


@pytest.mark.asyncio
async def test_expo_provider_retries_bounded_service_failure() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(503))
    )
    provider = ExpoMobilePushProvider(MobileSettings(push_provider="expo"), client=client)
    try:
        tickets = await provider.send([_message()])
    finally:
        await client.aclose()

    assert tickets[0].accepted is False
    assert tickets[0].retryable is True
    assert tickets[0].error_code == "provider_unavailable"


@pytest.mark.asyncio
async def test_expo_provider_requires_ticket_id_for_accepted_submission() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"data": [{"status": "ok"}]})
        )
    )
    provider = ExpoMobilePushProvider(MobileSettings(push_provider="expo"), client=client)
    try:
        tickets = await provider.send([_message()])
    finally:
        await client.aclose()

    assert tickets[0].accepted is False
    assert tickets[0].retryable is True
    assert tickets[0].provider_ticket_id is None
    assert tickets[0].error_code == "provider_malformed_response"


@pytest.mark.asyncio
async def test_expo_provider_rejects_duplicate_ticket_ids_fail_closed() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "data": [
                        {"status": "ok", "id": "duplicate-ticket"},
                        {"status": "ok", "id": "duplicate-ticket"},
                    ]
                },
            )
        )
    )
    provider = ExpoMobilePushProvider(MobileSettings(push_provider="expo"), client=client)
    try:
        tickets = await provider.send(
            [
                _message(),
                _message(
                    registration_id="00000000-0000-4000-8000-000000000005",
                    notification_id="00000000-0000-4000-8000-000000000006",
                ),
            ]
        )
    finally:
        await client.aclose()

    assert all(item.accepted is False for item in tickets)
    assert all(item.retryable is True for item in tickets)
    assert all(item.provider_ticket_id is None for item in tickets)
    assert all(item.error_code == "provider_malformed_response" for item in tickets)


@pytest.mark.asyncio
async def test_expo_provider_maps_receipts_without_retaining_provider_message() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": {
                    "ticket-ok": {"status": "ok"},
                    "ticket-revoked": {
                        "status": "error",
                        "message": "contains provider-specific device details",
                        "details": {"error": "DeviceNotRegistered"},
                    },
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ExpoMobilePushProvider(MobileSettings(push_provider="expo"), client=client)
    try:
        receipts = await provider.get_receipts(
            ["ticket-ok", "ticket-revoked", "ticket-not-ready"]
        )
    finally:
        await client.aclose()

    assert captured["payload"] == {
        "ids": ["ticket-ok", "ticket-revoked", "ticket-not-ready"]
    }
    assert receipts[0].delivered is True
    assert receipts[0].error_code is None
    assert receipts[1].delivered is False
    assert receipts[1].retryable is False
    assert receipts[1].error_code == "DeviceNotRegistered"
    assert receipts[2].delivered is False
    assert receipts[2].retryable is True
    assert receipts[2].error_code == "receipt_not_ready"


@pytest.mark.asyncio
async def test_expo_provider_receipt_outage_is_bounded_and_retryable() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(503))
    )
    provider = ExpoMobilePushProvider(MobileSettings(push_provider="expo"), client=client)
    try:
        receipts = await provider.get_receipts(["ticket-one", "ticket-two"])
    finally:
        await client.aclose()

    assert [item.provider_ticket_id for item in receipts] == [
        "ticket-one",
        "ticket-two",
    ]
    assert all(item.retryable for item in receipts)
    assert all(item.error_code == "provider_unavailable" for item in receipts)
