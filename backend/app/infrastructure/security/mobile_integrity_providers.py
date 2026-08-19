"""Authoritative server-side mobile integrity provider adapters.

Play Integrity verdicts are decrypted by Google over authenticated REST using
Application Default Credentials. Apple attestations and assertions are verified
locally against Apple's trust anchors through the maintained ``pyattest`` core and
the application's strict wire/policy adapter.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import quote

import httpx

from app.application.mobile.app_integrity import (
    AppleAppAttestAssertionVerdict,
    AppleAppAttestRegistrationVerdict,
    AppleAppAttestVerifier,
    MobileIntegrityRejected,
    MobileIntegrityUnavailable,
)
from app.core.config.settings import MobileSettings, get_settings
from app.infrastructure.security.apple_app_attest_verifier import (
    PyAttestAppleAppAttestVerifier,
)

_PLAY_INTEGRITY_SCOPE = "https://www.googleapis.com/auth/playintegrity"


class _RefreshableCredentials(Protocol):
    token: str | None

    def refresh(self, request: object) -> None: ...


class GooglePlayIntegrityVerifier:
    def __init__(
        self,
        *,
        settings: MobileSettings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings().mobile
        self._client = client

    async def verify(self, *, integrity_token: str, expected_request_hash: str) -> None:
        if not integrity_token or len(integrity_token.encode("utf-8")) > (
            self._settings.app_integrity_proof_max_bytes
        ):
            raise MobileIntegrityRejected("proof_size")
        access_token = await self._application_default_access_token()
        endpoint = (
            "https://playintegrity.googleapis.com/v1/"
            f"{quote(self._settings.play_integrity_package_name, safe='.')}:"
            "decodeIntegrityToken"
        )
        try:
            if self._client is not None:
                response = await self._client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"integrityToken": integrity_token},
                    timeout=self._settings.play_integrity_timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(
                    follow_redirects=False,
                    timeout=self._settings.play_integrity_timeout_seconds,
                ) as client:
                    response = await client.post(
                        endpoint,
                        headers={"Authorization": f"Bearer {access_token}"},
                        json={"integrityToken": integrity_token},
                    )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise MobileIntegrityUnavailable("Play Integrity verification is unavailable") from exc

        if response.status_code in {400, 404}:
            raise MobileIntegrityRejected("provider_token")
        if response.status_code in {401, 403, 408, 409, 425, 429} or response.status_code >= 500:
            raise MobileIntegrityUnavailable("Play Integrity verification is unavailable")
        if response.status_code != 200:
            raise MobileIntegrityRejected("provider_response")
        try:
            payload: object = response.json()
        except ValueError as exc:
            raise MobileIntegrityUnavailable("Play Integrity returned malformed data") from exc
        self._validate_payload(payload, expected_request_hash=expected_request_hash)

    async def _application_default_access_token(self) -> str:
        def refresh() -> str:
            # Keep the optional provider client off the import path when the
            # app-integrity rollout is disabled or Apple-only.
            import google.auth
            from google.auth.transport.requests import Request as GoogleAuthRequest

            raw_credentials, _project = google.auth.default(scopes=[_PLAY_INTEGRITY_SCOPE])
            credentials = cast(_RefreshableCredentials, raw_credentials)
            credentials.refresh(GoogleAuthRequest())
            if not credentials.token or not isinstance(credentials.token, str):
                raise RuntimeError("ADC did not return an access token")
            return credentials.token

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(refresh),
                timeout=self._settings.play_integrity_timeout_seconds,
            )
        except Exception as exc:
            raise MobileIntegrityUnavailable(
                "Play Integrity server credentials are unavailable"
            ) from exc

    def _validate_payload(self, payload: object, *, expected_request_hash: str) -> None:
        if not isinstance(payload, dict):
            raise MobileIntegrityUnavailable("Play Integrity returned malformed data")
        token_payload = payload.get("tokenPayloadExternal")
        if not isinstance(token_payload, dict):
            raise MobileIntegrityRejected("provider_payload")
        request = token_payload.get("requestDetails")
        app = token_payload.get("appIntegrity")
        device = token_payload.get("deviceIntegrity")
        account = token_payload.get("accountDetails")
        if (
            not isinstance(request, dict)
            or not isinstance(app, dict)
            or not isinstance(device, dict)
            or not isinstance(account, dict)
        ):
            raise MobileIntegrityRejected("provider_verdict_shape")

        if request.get("requestHash") != expected_request_hash:
            raise MobileIntegrityRejected("provider_request_hash")
        if request.get("requestPackageName") != self._settings.play_integrity_package_name:
            raise MobileIntegrityRejected("provider_package")
        timestamp = request.get("timestampMillis")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, str)):
            raise MobileIntegrityRejected("provider_timestamp")
        try:
            timestamp_ms = int(timestamp)
        except (TypeError, ValueError) as exc:
            raise MobileIntegrityRejected("provider_timestamp") from exc
        maximum_age_ms = (self._settings.app_integrity_challenge_ttl_seconds + 30) * 1_000
        if abs(int(time.time() * 1_000) - timestamp_ms) > maximum_age_ms:
            raise MobileIntegrityRejected("provider_timestamp")

        if app.get("appRecognitionVerdict") != "PLAY_RECOGNIZED":
            raise MobileIntegrityRejected("provider_app_recognition")
        if app.get("packageName") != self._settings.play_integrity_package_name:
            raise MobileIntegrityRejected("provider_app_package")
        configured = self._allowed_certificate_digests()
        returned = app.get("certificateSha256Digest")
        if configured is None:
            if self._settings.app_integrity_mode == "enforce":
                raise MobileIntegrityUnavailable("Play signing certificates are not configured")
        elif not isinstance(returned, list) or not configured.intersection(
            item.rstrip("=") for item in returned if isinstance(item, str)
        ):
            raise MobileIntegrityRejected("provider_certificate")

        labels = device.get("deviceRecognitionVerdict")
        if not isinstance(labels, list) or (
            self._settings.play_integrity_required_device_verdict not in labels
        ):
            raise MobileIntegrityRejected("provider_device_integrity")
        if self._settings.play_integrity_require_licensed and (
            account.get("appLicensingVerdict") != "LICENSED"
        ):
            raise MobileIntegrityRejected("provider_licensing")

    def _allowed_certificate_digests(self) -> set[str] | None:
        encoded = self._settings.play_integrity_allowed_certificate_digests_json
        if encoded is None:
            return None
        parsed: object = json.loads(encoded)
        if not isinstance(parsed, list):
            raise MobileIntegrityUnavailable("Play signing certificates are misconfigured")
        return {item.rstrip("=") for item in parsed if isinstance(item, str)}


class UnavailableAppleAppAttestVerifier:
    """Fail-closed placeholder until audited Apple verification is deployed."""

    async def verify_attestation(
        self,
        *,
        attestation_object: str,
        key_id: str,
        server_challenge: str,
        app_id: str,
        environment: str,
    ) -> AppleAppAttestRegistrationVerdict:
        del attestation_object, key_id, server_challenge, app_id, environment
        raise MobileIntegrityUnavailable("Apple App Attest verification is not configured")

    async def verify_assertion(
        self,
        *,
        assertion_object: str,
        key_id: str,
        client_data: str,
        app_id: str,
        verification_material: bytes,
        previous_counter: int,
    ) -> AppleAppAttestAssertionVerdict:
        del (
            assertion_object,
            key_id,
            client_data,
            app_id,
            verification_material,
            previous_counter,
        )
        raise MobileIntegrityUnavailable("Apple App Attest verification is not configured")


@dataclass(frozen=True, slots=True)
class MobileIntegrityProviderRegistry:
    play: GooglePlayIntegrityVerifier
    apple: AppleAppAttestVerifier


_default_registry: MobileIntegrityProviderRegistry | None = None


def get_mobile_integrity_provider_registry() -> MobileIntegrityProviderRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = MobileIntegrityProviderRegistry(
            play=GooglePlayIntegrityVerifier(),
            apple=PyAttestAppleAppAttestVerifier(),
        )
    return _default_registry


__all__ = [
    "GooglePlayIntegrityVerifier",
    "MobileIntegrityProviderRegistry",
    "PyAttestAppleAppAttestVerifier",
    "UnavailableAppleAppAttestVerifier",
    "get_mobile_integrity_provider_registry",
]
