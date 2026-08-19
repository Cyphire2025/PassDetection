"""Risk-tiered server enforcement for mobile app-attestation proofs."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.app_integrity import (
    MobileIntegrityAction,
    MobileIntegrityChallenge,
    MobileIntegrityProvider,
    MobileIntegrityRejected,
    MobileIntegrityUnavailable,
    app_attest_key_registration_request_hash,
    create_mobile_integrity_challenge,
    validate_mobile_integrity_challenge,
)
from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.core.security.mobile_jwt import MobileAccessClaims, hash_mobile_lookup
from app.infrastructure.database.gc_mobile_models import (
    MobileAppAttestKeyModel,
    MobileDeviceSessionModel,
)
from app.infrastructure.security.mobile_integrity_challenges import (
    MobileIntegrityChallengeStore,
)
from app.infrastructure.security.mobile_integrity_providers import (
    MobileIntegrityProviderRegistry,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileAppAttestRegistrationRequest,
    MobileIntegrityChallengeRequest,
    MobileIntegrityProofRequest,
)

logger = get_logger(__name__)
_SAFE_REASON_PATTERN = re.compile(r"^[a-z0-9_]{1,48}$")


class MobileIntegrityService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        challenge_store: MobileIntegrityChallengeStore,
        providers: MobileIntegrityProviderRegistry,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._store = challenge_store
        self._providers = providers
        self._settings = settings or get_settings()
        self._mobile = self._settings.mobile
        self._binding_secret = self._settings.app_secret_key.encode("utf-8")

    async def issue_challenge(
        self,
        *,
        claims: MobileAccessClaims,
        request: MobileIntegrityChallengeRequest,
    ) -> MobileIntegrityChallenge | None:
        if self._mobile.app_integrity_mode == "disabled":
            return None
        device = await self._bound_device_session(
            claims=claims,
            installation_id=request.installation_id,
        )
        self._validate_provider_platform(request.provider, device.platform)
        request_hash = request.request_hash
        if request.action == "app_attest_key_register":
            if request.key_id is None:
                raise MobileIntegrityRejected("key_required")
            expected = app_attest_key_registration_request_hash(key_id=request.key_id)
            if request_hash != expected:
                raise MobileIntegrityRejected("request_hash")
        challenge = create_mobile_integrity_challenge(
            provider=request.provider,
            action=request.action,
            request_hash=request_hash,
            agency_id=claims.agency_id,
            account_id=claims.account_id,
            session_id=claims.session_id,
            device_identifier_hash=device.device_identifier_hash,
            key_id=request.key_id,
            binding_secret=self._binding_secret,
            ttl_seconds=self._mobile.app_integrity_challenge_ttl_seconds,
        )
        await self._store.put(challenge)
        return challenge

    async def register_apple_key(
        self,
        *,
        claims: MobileAccessClaims,
        request: MobileAppAttestRegistrationRequest,
    ) -> None:
        if self._mobile.app_integrity_mode == "disabled":
            raise MobileIntegrityRejected("policy_disabled")
        device = await self._bound_device_session(
            claims=claims,
            installation_id=request.installation_id,
        )
        self._validate_provider_platform("app_attest", device.platform)
        challenge = await self._consume_bound_challenge(
            challenge_id=request.challenge_id,
            provider="app_attest",
            action="app_attest_key_register",
            request_hash=app_attest_key_registration_request_hash(key_id=request.key_id),
            claims=claims,
            device=device,
            key_id=request.key_id,
        )
        if len(request.attestation_object.encode("utf-8")) > (
            self._mobile.app_integrity_proof_max_bytes
        ):
            raise MobileIntegrityRejected("proof_size")
        app_id = self._apple_app_id()
        try:
            verdict = await self._providers.apple.verify_attestation(
                attestation_object=request.attestation_object,
                key_id=request.key_id,
                server_challenge=challenge.provider_request_hash,
                app_id=app_id,
                environment=self._mobile.app_attest_environment,
            )
        except (MobileIntegrityRejected, MobileIntegrityUnavailable):
            raise
        except Exception as exc:
            raise MobileIntegrityUnavailable(
                "Apple App Attest verification is unavailable"
            ) from exc
        if (
            not 32 <= len(verdict.verification_material) <= 4_096
            or verdict.counter != 0
            or verdict.environment != self._mobile.app_attest_environment
        ):
            raise MobileIntegrityRejected("provider_attestation")

        now = datetime.now(tz=UTC)
        key_hash = hash_mobile_lookup(request.key_id, purpose="app-attest-key")
        existing = (
            await self._session.execute(
                select(MobileAppAttestKeyModel)
                .where(
                    MobileAppAttestKeyModel.agency_id == claims.agency_id,
                    MobileAppAttestKeyModel.account_id == claims.account_id,
                    MobileAppAttestKeyModel.device_identifier_hash
                    == device.device_identifier_hash,
                    MobileAppAttestKeyModel.status == "active",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing is not None and existing.key_identifier_hash == key_hash:
            existing.verification_material = verdict.verification_material
            existing.assertion_counter = 0
            existing.environment = verdict.environment
            existing.attested_at = now
            existing.updated_at = now
            return
        if existing is not None:
            existing.status = "revoked"
            existing.revoked_at = now
            existing.updated_at = now
        self._session.add(
            MobileAppAttestKeyModel(
                id=uuid.uuid4(),
                agency_id=claims.agency_id,
                account_id=claims.account_id,
                device_identifier_hash=device.device_identifier_hash,
                key_identifier_hash=key_hash,
                verification_material=verdict.verification_material,
                assertion_counter=0,
                environment=verdict.environment,
                status="active",
                attested_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise MobileIntegrityRejected("key_binding") from exc

    async def enforce_action(
        self,
        *,
        claims: MobileAccessClaims,
        action: MobileIntegrityAction,
        request_hash: str,
        proof: MobileIntegrityProofRequest | None,
    ) -> None:
        mode = self._mobile.app_integrity_mode
        if mode == "disabled":
            return
        try:
            if proof is None:
                raise MobileIntegrityRejected("proof_missing")
            device = await self._bound_device_session(
                claims=claims,
                installation_id=proof.installation_id,
            )
            self._validate_provider_platform(proof.provider, device.platform)
            if len(proof.proof.encode("utf-8")) > self._mobile.app_integrity_proof_max_bytes:
                raise MobileIntegrityRejected("proof_size")
            challenge = await self._consume_bound_challenge(
                challenge_id=proof.challenge_id,
                provider=proof.provider,
                action=action,
                request_hash=request_hash,
                claims=claims,
                device=device,
                key_id=proof.key_id,
            )
            if proof.provider == "play_integrity":
                await self._providers.play.verify(
                    integrity_token=proof.proof,
                    expected_request_hash=challenge.provider_request_hash,
                )
            else:
                await self._verify_apple_assertion(
                    claims=claims,
                    device=device,
                    challenge=challenge,
                    proof=proof,
                )
        except MobileIntegrityRejected as exc:
            self._report(action=action, outcome="rejected", reason=exc.reason)
            if mode == "enforce":
                raise
        except MobileIntegrityUnavailable:
            self._report(action=action, outcome="unavailable", reason="provider_unavailable")
            if mode == "enforce":
                raise
        except Exception as exc:
            self._report(action=action, outcome="unavailable", reason="provider_exception")
            if mode == "enforce":
                raise MobileIntegrityUnavailable(
                    "Mobile integrity verification is unavailable"
                ) from exc
        else:
            self._report(action=action, outcome="verified", reason="verified")

    async def _verify_apple_assertion(
        self,
        *,
        claims: MobileAccessClaims,
        device: MobileDeviceSessionModel,
        challenge: MobileIntegrityChallenge,
        proof: MobileIntegrityProofRequest,
    ) -> None:
        if proof.key_id is None:
            raise MobileIntegrityRejected("key_required")
        key_hash = hash_mobile_lookup(proof.key_id, purpose="app-attest-key")
        key = (
            await self._session.execute(
                select(MobileAppAttestKeyModel)
                .where(
                    MobileAppAttestKeyModel.agency_id == claims.agency_id,
                    MobileAppAttestKeyModel.account_id == claims.account_id,
                    MobileAppAttestKeyModel.device_identifier_hash
                    == device.device_identifier_hash,
                    MobileAppAttestKeyModel.key_identifier_hash == key_hash,
                    MobileAppAttestKeyModel.status == "active",
                    MobileAppAttestKeyModel.revoked_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if key is None:
            raise MobileIntegrityRejected("key_unregistered")
        if key.environment != self._mobile.app_attest_environment:
            raise MobileIntegrityRejected("key_environment")
        verdict = await self._providers.apple.verify_assertion(
            assertion_object=proof.proof,
            key_id=proof.key_id,
            client_data=challenge.provider_request_hash,
            app_id=self._apple_app_id(),
            verification_material=key.verification_material,
            previous_counter=key.assertion_counter,
        )
        if verdict.counter <= key.assertion_counter or verdict.counter > (1 << 63) - 1:
            raise MobileIntegrityRejected("assertion_counter")
        now = datetime.now(tz=UTC)
        key.assertion_counter = verdict.counter
        key.last_asserted_at = now
        key.updated_at = now

    async def _consume_bound_challenge(
        self,
        *,
        challenge_id: uuid.UUID,
        provider: MobileIntegrityProvider,
        action: MobileIntegrityAction,
        request_hash: str,
        claims: MobileAccessClaims,
        device: MobileDeviceSessionModel,
        key_id: str | None,
    ) -> MobileIntegrityChallenge:
        challenge = await self._store.consume(challenge_id)
        if challenge is None:
            raise MobileIntegrityRejected("challenge_missing_or_replayed")
        validate_mobile_integrity_challenge(
            challenge,
            provider=provider,
            action=action,
            request_hash=request_hash,
            agency_id=claims.agency_id,
            account_id=claims.account_id,
            session_id=claims.session_id,
            device_identifier_hash=device.device_identifier_hash,
            key_id=key_id,
            binding_secret=self._binding_secret,
        )
        return challenge

    async def _bound_device_session(
        self,
        *,
        claims: MobileAccessClaims,
        installation_id: str,
    ) -> MobileDeviceSessionModel:
        installation_hash = hash_mobile_lookup(
            installation_id,
            purpose="device-installation",
        )
        device = (
            await self._session.execute(
                select(MobileDeviceSessionModel).where(
                    MobileDeviceSessionModel.id == claims.session_id,
                    MobileDeviceSessionModel.agency_id == claims.agency_id,
                    MobileDeviceSessionModel.account_id == claims.account_id,
                    MobileDeviceSessionModel.session_generation == claims.session_generation,
                    MobileDeviceSessionModel.device_identifier_hash == installation_hash,
                    MobileDeviceSessionModel.status == "active",
                    MobileDeviceSessionModel.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if device is None:
            raise MobileIntegrityRejected("installation_binding")
        return device

    @staticmethod
    def _validate_provider_platform(provider: MobileIntegrityProvider, platform: str) -> None:
        expected = "android" if provider == "play_integrity" else "ios"
        if platform != expected:
            raise MobileIntegrityRejected("provider_platform")

    def _apple_app_id(self) -> str:
        team_id = self._mobile.app_attest_team_id
        if team_id is None:
            raise MobileIntegrityUnavailable("Apple App Attest identity is not configured")
        return f"{team_id}.{self._mobile.app_attest_bundle_id}"

    def _report(self, *, action: str, outcome: str, reason: str) -> None:
        safe_reason = reason if _SAFE_REASON_PATTERN.fullmatch(reason) else "unspecified"
        logger.info(
            "mobile_integrity_result",
            action=action,
            mode=self._mobile.app_integrity_mode,
            outcome=outcome,
            reason=safe_reason,
        )

__all__ = ["MobileIntegrityService"]
