"""Direct FCM tests use only fake credentials and httpx MockTransport."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.application.mobile.push_provider import get_mobile_push_provider
from app.core.config.settings import MobileSettings
from app.infrastructure.mobile_push.fcm_credentials import FcmCredentialError
from app.infrastructure.mobile_push.fcm_provider import FcmMobilePushProvider
from tests.unit.application.test_mobile_push_provider import _message

PROJECT = "group-companion-c2c30"
NAME = f"projects/{PROJECT}/messages/0:synthetic-message-id"


def settings(**overrides):
    return MobileSettings(
        _env_file=None,
        push_provider="fcm",
        push_fcm_credentials_file="/synthetic/mounted.json",
        **overrides,
    )


def message(**overrides):
    return _message(token="synthetic-native-fcm-token-0001", **overrides)


async def token():
    return "synthetic-access-token"


async def send_with(handler, messages=None):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = FcmMobilePushProvider(settings(), client=client, access_token_provider=token)
        return await provider.send(messages or [message()])


def test_factory_selects_direct_fcm_and_requires_project_and_credential_configuration():
    provider = get_mobile_push_provider(settings())
    assert isinstance(provider, FcmMobilePushProvider)
    assert provider.name == "fcm" and provider.enabled
    assert provider.supports_receipts is False
    with pytest.raises(ValidationError, match="MOBILE_PUSH_FCM_CREDENTIALS_FILE"):
        MobileSettings(_env_file=None, push_provider="fcm")
    with pytest.raises(ValidationError):
        settings(push_fcm_project_id="wrong-project")


async def test_fcm_posts_safe_native_android_payload_and_reports_acceptance_only():
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"name": NAME})

    tickets = await send_with(handler, [message(priority="high")])
    assert len(captured) == 1
    request = captured[0]
    assert str(request.url) == f"https://fcm.googleapis.com/v1/projects/{PROJECT}/messages:send"
    assert request.headers["Authorization"] == "Bearer synthetic-access-token"
    payload = json.loads(request.content)["message"]
    assert payload["token"] == "synthetic-native-fcm-token-0001"
    assert payload["notification"] == {"title": "Global Connect Travels update"}
    assert set(payload["data"]) == {"route", "trip_id", "event_id"}
    assert payload["android"]["restricted_package_name"] == "com.globalconnects.groupcompanion"
    assert payload["android"]["priority"] == "high"
    assert payload["android"]["ttl"] == "3600s"
    assert payload["android"]["notification"]["channel_id"] == "trip-updates"
    assert payload["android"]["notification"]["visibility"] == "PRIVATE"
    assert tickets[0].accepted and not tickets[0].requires_receipt
    assert not tickets[0].retryable and not tickets[0].outcome_unknown
    assert tickets[0].provider_ticket_id == NAME


@pytest.mark.parametrize(
    "exception,retryable,unknown",
    [
        (httpx.ConnectTimeout, True, False),
        (httpx.ConnectError, True, False),
        (httpx.PoolTimeout, True, False),
        (httpx.ReadTimeout, False, True),
        (httpx.WriteTimeout, False, True),
        (httpx.ReadError, False, True),
        (httpx.WriteError, False, True),
        (httpx.RemoteProtocolError, False, True),
    ],
)
async def test_transport_uncertainty_never_enables_an_automatic_resend(
    exception, retryable, unknown
):
    def handler(request):
        raise exception("sensitive transport details must not propagate", request=request)

    (ticket,) = await send_with(handler)
    assert ticket.accepted is False
    assert ticket.retryable is retryable
    assert ticket.outcome_unknown is unknown
    assert "sensitive" not in ticket.error_code
    assert ticket.requires_receipt is False


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"name": ""},
        {"name": "wrong-project/message"},
        {"name": f"projects/{PROJECT}/messages/has space"},
    ],
)
async def test_malformed_success_is_unknown_not_retried(payload):
    (ticket,) = await send_with(lambda _: httpx.Response(200, json=payload))
    assert not ticket.accepted and ticket.outcome_unknown and not ticket.retryable
    assert ticket.error_code == "provider_outcome_unknown"


@pytest.mark.parametrize("status", [201, 202, 204, 408, 409, 500, 502, 504])
async def test_ambiguous_server_outcome_stops_retry(status):
    (ticket,) = await send_with(lambda _: httpx.Response(status, text="upstream details"))
    assert ticket.outcome_unknown and not ticket.retryable
    assert ticket.provider_ticket_id is None


@pytest.mark.parametrize(
    "status,header,delay",
    [
        (429, "", 60),
        (429, "1", 60),
        (429, "120", 120),
        (503, "", 5),
        (503, "90", 90),
        (503, "99999", 3600),
        (429, "Thu, 01 Jan 2099 00:00:00 GMT", 3600),
    ],
)
async def test_explicit_rejection_honors_retry_after(status, header, delay):
    (ticket,) = await send_with(lambda _: httpx.Response(status, headers={"Retry-After": header}))
    assert not ticket.accepted and ticket.retryable and not ticket.outcome_unknown
    assert ticket.retry_after_seconds == delay


@pytest.mark.parametrize(
    "status,raw_code,expected",
    [
        (404, "UNREGISTERED", "DeviceNotRegistered"),
        (403, "SENDER_ID_MISMATCH", "fcm_sender_id_mismatch"),
        (400, "INVALID_ARGUMENT", "fcm_invalid_argument"),
        (401, "THIRD_PARTY_AUTH_ERROR", "fcm_authentication_failed"),
    ],
)
async def test_fcm_error_details_are_classified_without_provider_message_text(
    status, raw_code, expected
):
    def handler(_):
        return httpx.Response(
            status,
            json={
                "error": {
                    "message": "PRIVATE token/contact should not escape",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError",
                            "errorCode": raw_code,
                        }
                    ],
                }
            },
        )

    (ticket,) = await send_with(handler)
    assert ticket.error_code == expected
    assert not ticket.retryable and not ticket.outcome_unknown
    assert "PRIVATE" not in repr(ticket)


async def test_missing_credentials_do_not_call_fcm_and_report_actionable_code():
    async def missing_token():
        raise FcmCredentialError("fcm_credentials_missing")

    def unexpected(_):
        raise AssertionError("No outbound send without credentials")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        provider = FcmMobilePushProvider(
            settings(), client=client, access_token_provider=missing_token
        )
        (ticket,) = await provider.send([message()])
    assert ticket.error_code == "fcm_credentials_missing"
    assert not ticket.retryable and not ticket.outcome_unknown


async def test_temporary_oauth_failure_retries_without_any_fcm_send():
    async def temporarily_unavailable():
        raise FcmCredentialError("fcm_credentials_unavailable", retryable=True)

    def unexpected(_):
        raise AssertionError("OAuth failure must not send to FCM")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        provider = FcmMobilePushProvider(
            settings(), client=client, access_token_provider=temporarily_unavailable
        )
        (ticket,) = await provider.send([message()])
    assert ticket.error_code == "fcm_credentials_unavailable"
    assert ticket.retryable and ticket.retry_after_seconds == 60
    assert not ticket.accepted and not ticket.outcome_unknown


@pytest.mark.parametrize("temporary_error", [False, True])
async def test_prepare_resolves_oauth_once_before_send(temporary_error):
    calls = 0

    async def prepared_token():
        nonlocal calls
        calls += 1
        if temporary_error:
            raise FcmCredentialError("fcm_credentials_unavailable", retryable=True)
        return "synthetic-access-token"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"name": NAME}),
        )
    ) as client:
        provider = FcmMobilePushProvider(
            settings(), client=client, access_token_provider=prepared_token
        )
        await provider.prepare()
        assert calls == 1
        (ticket,) = await provider.send([message()])
    assert calls == 1
    assert ticket.accepted is not temporary_error
    assert ticket.retryable is temporary_error


async def test_total_send_deadline_is_unknown_even_if_transport_never_times_out():
    async def slow_handler(_):
        await asyncio.sleep(2)
        return httpx.Response(200, json={"name": NAME})

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow_handler)) as client:
        provider = FcmMobilePushProvider(
            settings(push_timeout_seconds=1), client=client, access_token_provider=token
        )
        (ticket,) = await provider.send([message()])
    assert ticket.outcome_unknown and not ticket.retryable and not ticket.accepted


async def test_worker_cancellation_propagates_to_durable_intent_recovery():
    entered = asyncio.Event()

    async def interrupted_handler(_):
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("Interrupted send must never manufacture a response")

    async with httpx.AsyncClient(transport=httpx.MockTransport(interrupted_handler)) as client:
        provider = FcmMobilePushProvider(settings(), client=client, access_token_provider=token)
        operation = asyncio.create_task(provider.send([message()]))
        await asyncio.wait_for(entered.wait(), timeout=1)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation


async def test_fcm_has_no_fabricated_receipt_endpoint():
    provider = FcmMobilePushProvider(settings(), access_token_provider=token)
    with pytest.raises(NotImplementedError, match="does not provide"):
        await provider.get_receipts([NAME])


@pytest.mark.parametrize("ttl", [0, 1, 60, 3600])
async def test_source_expiry_caps_fcm_ttl_and_stable_notification_tag(ttl):
    captured = []

    def handler(request):
        captured.append(json.loads(request.content)["message"]["android"])
        return httpx.Response(200, json={"name": NAME})

    notification = message(ttl_seconds=ttl)
    await send_with(handler, [notification])
    assert captured[0]["ttl"] == f"{ttl}s"
    assert captured[0]["notification"]["tag"] == notification.notification_id


@pytest.mark.parametrize("ttl", [-1, 3601, True, 0.5])
async def test_invalid_fcm_ttl_is_rejected_before_send(ttl):
    provider = FcmMobilePushProvider(settings(), access_token_provider=token)
    with pytest.raises(ValueError, match="TTL"):
        await provider.send([message(ttl_seconds=ttl)])


async def test_native_payload_validation_happens_before_outbound_work():
    provider = FcmMobilePushProvider(settings(), access_token_provider=token)
    with pytest.raises(ValueError, match="native Android"):
        await provider.send([_message()])
    with pytest.raises(ValueError, match="non-allowlisted"):
        await provider.send([message(data={"route": "updates", "passport_number": "P1234567"})])
    assert await provider.send([]) == []
    with pytest.raises(ValueError, match="100"):
        await provider.send([message()] * 101)


async def test_mixed_batch_retains_per_target_outcomes_and_does_not_redirect_credentials():
    def handler(request):
        target = json.loads(request.content)["message"]["data"]["event_id"]
        if target.endswith("1"):
            return httpx.Response(200, json={"name": NAME})
        if target.endswith("2"):
            return httpx.Response(429)
        return httpx.Response(307, headers={"Location": "https://must-not-follow.example.test"})

    tickets = await send_with(
        handler, [message(data={"route": "updates", "event_id": str(i)}) for i in range(1, 4)]
    )
    assert tickets[0].accepted
    assert tickets[1].retryable
    assert tickets[2].error_code == "fcm_provider_rejected"
