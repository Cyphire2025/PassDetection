"""Stateless application orchestration for persisted returning claims."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.audit import record_claim_action
from app.application.travellers.authority import (
    ReuseScope,
    accepted_document,
    active_scope,
    check_claim_scope,
    check_person_revision,
    eligible_person,
)
from app.application.travellers.document_challenge import (
    questions_for_claim,
    record_failed_proof,
    require_attempt_budget,
)
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.matching import resolve_passport
from app.application.travellers.passport_lookup import set_passport_identifiers
from app.core.config.settings import Settings
from app.core.config.traveller_reuse import TravellerReuseSettings
from app.domain.services.traveller_verification import CLAIM_LIFETIME, DocumentQuestion
from app.domain.value_objects.phone_number import normalize_phone_number
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel,
    TravellerDocumentRevisionModel,
    TravellerProfileModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


class ReturningClaims:
    def __init__(
        self, session: AsyncSession, settings: Settings, reuse_settings: TravellerReuseSettings,
    ) -> None:
        self.session = session
        self.settings = settings
        self.reuse_settings = reuse_settings
        if not reuse_settings.disclosure_enabled:
            raise ReuseError(ReuseReason.UNAVAILABLE)
        self.crypto = TravellerReuseCrypto(reuse_settings)

    async def start(
        self, *, group_token: str, method: Literal["phone", "passport", "code"],
        phone: str | None = None, passport_number: str | None = None, issuing_country: str | None = None,
        document_type: str = "P", individual_code: str | None = None,
    ) -> tuple[str, TravellerClaimModel]:
        scope = await active_scope(self.session, group_token=group_token)
        normalized_phone = normalize_phone_number(phone)
        if method == "phone" and normalized_phone is None:
            raise ReuseError(ReuseReason.VERIFICATION_FAILED)
        secret, secret_hash = self.crypto.new_secret("claim")
        claim = self.new_claim(scope, method=method, normalized_phone=normalized_phone,
                               secret_hash=secret_hash, idempotency_key=uuid.uuid4().hex)
        self._set_identifiers(scope, claim, passport_number, issuing_country, document_type, individual_code)
        self.session.add(claim)
        await record_claim_action(self.session, claim, "claim_started")
        await self.session.commit()
        return secret, claim

    def new_claim(
        self, scope: ReuseScope, *, method: Literal["phone", "passport", "code"],
        normalized_phone: str | None, secret_hash: str, idempotency_key: str,
    ) -> TravellerClaimModel:
        """Build one fixed-lifetime claim; caller owns persistence/transaction."""
        now = datetime.now(UTC)
        return TravellerClaimModel(
            id=uuid.uuid4(), agency_id=scope.group.agency_id, company_id=scope.company.id,
            group_id=scope.group.id, secret_hash=secret_hash, method=method,
            status="created",
            phone_ciphertext=self.crypto.encrypt(normalized_phone) if normalized_phone else None,
            phone_fingerprint=self.crypto.scoped_digest("phone", scope.group.agency_id, scope.company.id, normalized_phone) if normalized_phone else None,
            max_attempts=self.settings.mobile.otp_max_attempts, otp_attempt_count=0,
            failed_answer_sets=0, required_question_count=1, actor_kind="self", actor_evidence={},
            expected_company_revision=scope.company.revision,
            expected_group_revision=scope.group.company_revision,
            expected_policy_revision=scope.policy.revision,
            expires_at=now + CLAIM_LIFETIME, created_at=now, idempotency_key=idempotency_key,
        )

    async def locked(self, secret: str) -> tuple[TravellerClaimModel, ReuseScope]:
        if not 32 <= len(secret) <= 128:
            raise ReuseError(ReuseReason.EXPIRED)
        digest = self.crypto.digest("claim", secret)
        # Read routing metadata, then lock group -> company -> person -> claim.
        # Bulk recovery revocation takes person before other claims/grants.
        routing = (await self.session.execute(select(
            TravellerClaimModel.group_id, TravellerClaimModel.traveller_id,
        ).where(TravellerClaimModel.secret_hash == digest))).one_or_none()
        if routing is None:
            raise ReuseError(ReuseReason.EXPIRED)
        scope = await active_scope(self.session, group_id=routing.group_id)
        if routing.traveller_id is not None:
            await eligible_person(self.session, scope, routing.traveller_id, datetime.now(UTC))
        claim = await self.session.scalar(select(TravellerClaimModel).where(
            TravellerClaimModel.secret_hash == digest,
            TravellerClaimModel.agency_id == scope.group.agency_id,
            TravellerClaimModel.company_id == scope.company.id,
        ).with_for_update().execution_options(populate_existing=True))
        if claim is None:
            raise ReuseError(ReuseReason.EXPIRED)
        if claim.traveller_id != routing.traveller_id:
            # Another request bound/switched this claim while its routing read
            # was in flight. Retry from metadata rather than invert lock order.
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
        check_claim_scope(claim, scope, datetime.now(UTC))
        return claim, scope

    async def bind_passport(
        self, secret: str, *, passport_number: str | None = None,
        issuing_country: str | None = None, document_type: str = "P", individual_code: str | None = None,
    ) -> tuple[TravellerClaimModel, tuple[DocumentQuestion, ...]]:
        claim, scope = await self.locked(secret)
        if claim.status not in {"created", "otp_verified", "passport_matched"}:
            raise ReuseError(ReuseReason.VERIFICATION_FAILED)
        self._set_identifiers(scope, claim, passport_number, issuing_country, document_type, individual_code)
        now = datetime.now(UTC)
        if claim.passport_id is not None:
            await self.bound_person(claim, scope, now)
        try:
            await resolve_passport(self.session, scope, claim, self.crypto, now)
        except ReuseError as exc:
            if exc.reason == ReuseReason.VERIFICATION_FAILED:
                await record_failed_proof(self.session, claim, now)
            raise
        _, revision = await self.bound_person(claim, scope, now)
        await require_attempt_budget(self.session, claim, now)
        questions = await questions_for_claim(self.session, claim, revision, now) if claim.required_question_count else ()
        if not questions:
            claim.status = "challenge_passed"
        await self.session.commit()
        return claim, questions

    async def bound_person(
        self, claim: TravellerClaimModel, scope: ReuseScope, now: datetime,
    ) -> tuple[TravellerProfileModel, TravellerDocumentRevisionModel]:
        if claim.traveller_id is None or claim.passport_id is None:
            raise ReuseError(ReuseReason.VERIFICATION_FAILED)
        person = await eligible_person(self.session, scope, claim.traveller_id, now)
        check_person_revision(claim, person)
        _, revision = await accepted_document(self.session, agency_id=claim.agency_id,
            company_id=claim.company_id, traveller_id=person.id, passport_id=claim.passport_id)
        if revision.id != claim.document_revision_id:
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
        return person, revision

    def _set_identifiers(
        self, scope: ReuseScope, claim: TravellerClaimModel, number: str | None,
        issuer: str | None, document_type: str, code: str | None,
    ) -> None:
        if number is not None:
            set_passport_identifiers(claim, self.crypto, number, issuer, document_type)
        if code is not None:
            from app.application.travellers.identity_index import COMPANY_INDIVIDUAL_CODE
            from app.domain.services.traveller_identity import normalize_individual_code
            code = normalize_individual_code(code) if scope.config.individual_identifier_type == COMPANY_INDIVIDUAL_CODE else code.strip()
            if not scope.config.individual_identifier_type or not 1 <= len(code.strip()) <= 128:
                raise ReuseError(ReuseReason.VERIFICATION_FAILED)
            fingerprint = self.crypto.scoped_digest("identifier", claim.agency_id, claim.company_id,
                scope.config.individual_identifier_type, code.strip())
            if claim.passport_id is not None and claim.identifier_fingerprint and claim.identifier_fingerprint != fingerprint:
                raise ReuseError(ReuseReason.REVISION_CONFLICT)
            claim.identifier_fingerprint = fingerprint
        if claim.method == "passport" and not claim.supplied_passport_fingerprint:
            raise ReuseError(ReuseReason.VERIFICATION_FAILED)
        if claim.method == "code" and not claim.identifier_fingerprint:
            raise ReuseError(ReuseReason.VERIFICATION_FAILED)
