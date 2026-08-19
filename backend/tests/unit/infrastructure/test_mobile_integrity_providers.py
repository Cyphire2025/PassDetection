from __future__ import annotations

import copy
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app.application.mobile.app_integrity import (
    MobileIntegrityRejected,
    MobileIntegrityUnavailable,
)
from app.core.config.settings import MobileSettings
from app.infrastructure.security import mobile_integrity_providers
from app.infrastructure.security.apple_app_attest_verifier import (
    PyAttestAppleAppAttestVerifier,
)
from app.infrastructure.security.mobile_integrity_providers import (
    GooglePlayIntegrityVerifier,
    UnavailableAppleAppAttestVerifier,
    get_mobile_integrity_provider_registry,
)

PACKAGE_NAME = "com.globalconnects.groupcompanion"
CERTIFICATE_DIGEST = "C" * 43
REQUEST_HASH = "R" * 43


def _settings(*, mode: str = "enforce", certificates: bool = True) -> MobileSettings:
    return MobileSettings(
        app_integrity_mode=mode,
        play_integrity_package_name=PACKAGE_NAME,
        play_integrity_allowed_certificate_digests_json=(
            json.dumps([f"{CERTIFICATE_DIGEST}="]) if certificates else None
        ),
    )


def _valid_payload() -> dict[str, object]:
    return {
        "tokenPayloadExternal": {
            "requestDetails": {
                "requestPackageName": PACKAGE_NAME,
                "requestHash": REQUEST_HASH,
                "timestampMillis": str(int(time.time() * 1_000)),
            },
            "appIntegrity": {
                "appRecognitionVerdict": "PLAY_RECOGNIZED",
                "packageName": PACKAGE_NAME,
                "certificateSha256Digest": [CERTIFICATE_DIGEST],
            },
            "deviceIntegrity": {
                "deviceRecognitionVerdict": ["MEETS_DEVICE_INTEGRITY"],
            },
            "accountDetails": {"appLicensingVerdict": "LICENSED"},
        }
    }


@pytest.mark.asyncio
async def test_play_integrity_uses_official_server_request_shape_and_checks_verdict() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_valid_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = GooglePlayIntegrityVerifier(settings=_settings(), client=client)
        verifier._application_default_access_token = AsyncMock(  # type: ignore[method-assign]
            return_value="server-access-token"
        )
        await verifier.verify(
            integrity_token="opaque-platform-token-value",
            expected_request_hash=REQUEST_HASH,
        )

    assert captured == {
        "url": (f"https://playintegrity.googleapis.com/v1/{PACKAGE_NAME}:decodeIntegrityToken"),
        "authorization": "Bearer server-access-token",
        "body": {"integrityToken": "opaque-platform-token-value"},
    }


@pytest.mark.parametrize(
    ("section", "field", "replacement", "reason"),
    [
        ("requestDetails", "requestHash", "W" * 43, "provider_request_hash"),
        ("requestDetails", "requestPackageName", "com.attacker.clone", "provider_package"),
        (
            "appIntegrity",
            "appRecognitionVerdict",
            "UNRECOGNIZED_VERSION",
            "provider_app_recognition",
        ),
        ("appIntegrity", "certificateSha256Digest", ["X" * 43], "provider_certificate"),
        (
            "deviceIntegrity",
            "deviceRecognitionVerdict",
            ["MEETS_BASIC_INTEGRITY"],
            "provider_device_integrity",
        ),
        ("accountDetails", "appLicensingVerdict", "UNLICENSED", "provider_licensing"),
    ],
)
@pytest.mark.asyncio
async def test_play_integrity_rejects_each_required_verdict_boundary(
    section: str,
    field: str,
    replacement: object,
    reason: str,
) -> None:
    payload = copy.deepcopy(_valid_payload())
    payload["tokenPayloadExternal"][section][field] = replacement  # type: ignore[index]

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = GooglePlayIntegrityVerifier(settings=_settings(), client=client)
        verifier._application_default_access_token = AsyncMock(  # type: ignore[method-assign]
            return_value="server-access-token"
        )
        with pytest.raises(MobileIntegrityRejected) as caught:
            await verifier.verify(
                integrity_token="opaque-platform-token-value",
                expected_request_hash=REQUEST_HASH,
            )

    assert caught.value.reason == reason


@pytest.mark.asyncio
async def test_play_provider_outage_and_missing_enforcement_config_fail_closed() -> None:
    async def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
        verifier = GooglePlayIntegrityVerifier(settings=_settings(), client=client)
        verifier._application_default_access_token = AsyncMock(  # type: ignore[method-assign]
            return_value="server-access-token"
        )
        with pytest.raises(MobileIntegrityUnavailable):
            await verifier.verify(
                integrity_token="opaque-platform-token-value",
                expected_request_hash=REQUEST_HASH,
            )

    async def valid(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_valid_payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(valid)) as client:
        verifier = GooglePlayIntegrityVerifier(
            settings=_settings(certificates=False),
            client=client,
        )
        verifier._application_default_access_token = AsyncMock(  # type: ignore[method-assign]
            return_value="server-access-token"
        )
        with pytest.raises(MobileIntegrityUnavailable):
            await verifier.verify(
                integrity_token="opaque-platform-token-value",
                expected_request_hash=REQUEST_HASH,
            )


@pytest.mark.asyncio
async def test_default_apple_adapter_never_accepts_a_client_verdict() -> None:
    verifier = UnavailableAppleAppAttestVerifier()

    with pytest.raises(MobileIntegrityUnavailable):
        await verifier.verify_attestation(
            attestation_object="opaque-attestation",
            key_id="K" * 48,
            server_challenge=REQUEST_HASH,
            app_id=f"ABCDEFGHIJ.{PACKAGE_NAME}",
            environment="production",
        )
    with pytest.raises(MobileIntegrityUnavailable):
        await verifier.verify_assertion(
            assertion_object="opaque-assertion",
            key_id="K" * 48,
            client_data=REQUEST_HASH,
            app_id=f"ABCDEFGHIJ.{PACKAGE_NAME}",
            verification_material=b"public-material" * 3,
            previous_counter=1,
        )


def test_default_registry_uses_authoritative_apple_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mobile_integrity_providers, "_default_registry", None)

    registry = get_mobile_integrity_provider_registry()

    assert isinstance(registry.apple, PyAttestAppleAppAttestVerifier)
