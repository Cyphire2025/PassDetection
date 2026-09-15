"""APNs protocol tests use generated keys and MockTransport, never live device tokens."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import ValidationError

from app.application.mobile.push_provider import MobilePushMessage, get_mobile_push_providers
from app.core.config.settings import MobileSettings
from app.infrastructure.mobile_push import apns_credentials
from app.infrastructure.mobile_push.apns_credentials import ApnsCredentialError, apns_access_token
from app.infrastructure.mobile_push.apns_provider import APNS_TOPIC, ApnsMobilePushProvider
from app.presentation.api.v1.schemas.mobile_schemas import MobilePushRegistrationRequest


def settings(**overrides):
    return MobileSettings(_env_file=None, **overrides)


def message(**overrides):
    return replace(
        MobilePushMessage(
            registration_id="synthetic-device",
            notification_id="synthetic-notification",
            token="a1" * 32,
            title="Departure update",
            body="Please check the trip details.",
            data={"route": "updates", "event_id": "synthetic-notification"},
            apns_environment="development",
        ),
        **overrides,
    )


async def send(handler, messages=None):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ApnsMobilePushProvider(
            settings(), client=client, access_token_provider=lambda: "synthetic-jwt"
        )
        return await provider.send(messages or [message()])


@pytest.mark.parametrize("stdlib_fallback", [False, True])
async def test_configured_transport_logging_never_emits_device_token_or_auth_headers(
    monkeypatch, caplog, stdlib_fallback
):
    from app.core.logging import logger as app_logging

    root = logging.getLogger()
    handlers = list(root.handlers)
    names = ("uvicorn.access", "sqlalchemy.engine", "boto3", "botocore", "httpx", "httpcore", "hpack")
    levels = {name: logging.getLogger(name).level for name in names}
    root_level = root.level
    if stdlib_fallback:
        monkeypatch.setattr(app_logging, "structlog", None)
    monkeypatch.setattr(
        app_logging, "get_settings", lambda: SimpleNamespace(is_production=False, app_debug=True)
    )
    try:
        caplog.set_level(logging.DEBUG)
        app_logging.configure_logging()
        (ticket,) = await send(lambda request: httpx.Response(200))
        logging.getLogger("httpcore.http2").debug("authorization: bearer synthetic-private-jwt")
        logging.getLogger("hpack.hpack").debug("authorization: bearer synthetic-private-jwt")
        logging.getLogger("gc.delivery").warning("bounded_delivery_failure")
        assert ticket.accepted
        assert message().token not in caplog.text
        assert "synthetic-private-jwt" not in caplog.text
        assert "bounded_delivery_failure" in caplog.text
    finally:
        for handler in list(root.handlers):
            if handler not in handlers:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(root_level)
        for name, level in levels.items():
            logging.getLogger(name).setLevel(level)


@pytest.mark.parametrize(
    "environment,host",
    [
        ("development", "api.sandbox.push.apple.com"),
        ("production", "api.push.apple.com"),
    ],
)
async def test_signed_environment_selects_endpoint_and_expo_native_tap_dictionary(
    environment, host
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200)

    (ticket,) = await send(handler, [message(apns_environment=environment)])
    request = requests[0]
    assert request.url.host == host
    assert request.headers["apns-topic"] == APNS_TOPIC
    assert request.headers["apns-push-type"] == "alert"
    assert request.headers["apns-priority"] == "10"
    assert "apns-collapse-id" not in request.headers
    assert request.headers["authorization"] == "bearer synthetic-jwt"
    payload = json.loads(request.content)
    assert payload["aps"]["alert"]["body"] == message().body
    assert payload["body"] == message().data
    assert ticket.accepted and not ticket.requires_receipt and not ticket.outcome_unknown


@pytest.mark.parametrize(
    "error,retry,unknown",
    [
        (httpx.ConnectTimeout, True, False),
        (httpx.ConnectError, True, False),
        (httpx.PoolTimeout, True, False),
        (httpx.ReadTimeout, False, True),
        (httpx.WriteError, False, True),
        (httpx.RemoteProtocolError, False, True),
    ],
)
async def test_ambiguous_transport_is_never_automatically_repeated(error, retry, unknown):
    def handler(request):
        raise error("private transport details", request=request)

    (ticket,) = await send(handler)
    assert ticket.retryable is retry and ticket.outcome_unknown is unknown
    assert not ticket.accepted and "private" not in ticket.error_code


@pytest.mark.parametrize(
    "status,reason,code,retry,delay",
    [
        (410, "Unregistered", "DeviceNotRegistered", False, None),
        (400, "BadDeviceToken", "apns_bad_device_token", False, None),
        (400, "DeviceTokenNotForTopic", "apns_token_topic_mismatch", False, None),
        (403, "InvalidProviderToken", "apns_authentication_failed", False, None),
        (429, "TooManyRequests", "apns_rate_limited", True, 60),
        (500, "InternalServerError", "apns_unavailable", True, 900),
        (503, "Shutdown", "apns_unavailable", True, 900),
    ],
)
async def test_bounded_provider_failures(status, reason, code, retry, delay):
    (ticket,) = await send(lambda _: httpx.Response(status, json={"reason": reason}))
    assert (ticket.error_code, ticket.retryable, ticket.retry_after_seconds) == (code, retry, delay)


@pytest.mark.parametrize(
    "overrides",
    [
        {"token": "ExpoPushToken[invalid]"},
        {"apns_environment": None},
        {"apns_environment": "preview"},
        {"ttl_seconds": True},
        {"data": {"route": "secret"}},
    ],
)
async def test_invalid_batch_does_not_cross_provider_boundary(overrides):
    calls = []
    with pytest.raises(ValueError):
        await send(lambda request: calls.append(request), [message(**overrides)])
    assert calls == []


def test_key_signing_uses_es256_and_reuses_token_within_apple_window(tmp_path, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "synthetic.p8"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    config = settings(
        push_apns_enabled=True,
        push_apns_key_file=str(path),
        push_apns_key_id="SYNTHKEY12",
        push_apns_team_id="SYNTHTEAM1",
    )
    now = [1_800_000_000.0]
    monkeypatch.setattr(apns_credentials.time, "time", lambda: now[0])
    token = apns_access_token(config)
    claims = jwt.decode(
        token, key.public_key(), algorithms=["ES256"], options={"verify_iat": False}
    )
    assert claims == {"iss": "SYNTHTEAM1", "iat": int(now[0])}
    assert jwt.get_unverified_header(token)["kid"] == "SYNTHKEY12"
    now[0] += 2999
    assert apns_access_token(config) == token
    now[0] += 2
    assert apns_access_token(config) != token
    path.write_text("synthetic invalid key")
    with pytest.raises(ApnsCredentialError, match="apns_credentials_unavailable"):
        apns_access_token(config)


def test_ios_configuration_independent_of_android_and_disabled_by_default():
    config = settings(push_provider="fcm", push_fcm_credentials_file="/synthetic/fcm.json")
    assert [item.name for item in get_mobile_push_providers(config)] == ["fcm"]
    with pytest.raises(ValidationError, match="Enabled APNs requires"):
        settings(push_apns_enabled=True)
    config = settings(
        push_apns_enabled=True,
        push_apns_key_file="/synthetic/apns.p8",
        push_apns_key_id="SYNTHKEY12",
        push_apns_team_id="SYNTHTEAM1",
    )
    assert [item.name for item in get_mobile_push_providers(config)] == ["apns"]


def test_registration_requires_signed_environment_and_rejects_cross_provider_metadata():
    payload = {
        "provider": "apns",
        "push_token": "ab" * 32,
        "installation_id": "synthetic-installation",
    }
    with pytest.raises(ValidationError):
        MobilePushRegistrationRequest(**payload)
    assert (
        MobilePushRegistrationRequest(**payload, apns_environment="development").apns_environment
        == "development"
    )
    payload["provider"] = "fcm"
    with pytest.raises(ValidationError):
        MobilePushRegistrationRequest(**payload, apns_environment="production")
