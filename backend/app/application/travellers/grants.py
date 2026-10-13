"""Scoped, revocable historical access; every read checks live authority.

The user-selected phone route requires OTP+passport. Passport/date and individual
code/passport routes are knowledge checks without routine OTP. These are not
identity proofing. The proof reference remains bound even if review uses a newer
accepted passport. All mutation methods require transaction ownership by caller.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.application.companies.data_exports import invalidate_company_exports
from app.application.travellers.audit import record_claim_action
from app.application.travellers.authority import ReuseScope, active_scope, eligible_person
from app.application.travellers.claims import ReturningClaims
from app.application.travellers.errors import ReuseError, ReuseReason
from app.domain.services.traveller_verification import (
    GRANT_ABSOLUTE_LIFETIME,
    GRANT_IDLE_LIFETIME,
    DisclosureEvidence,
    require_disclosure,
    utc,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel,
    TravellerClaimModel,
    TravellerContactBindingModel,
    TravellerHistoryGrantModel,
    TravellerProfileModel,
)


async def confirm_claim(
    service: ReturningClaims, secret: str, *, acting_for: str,
    contact_change_confirmed: bool,
) -> str:
    claim, scope = await service.locked(secret)
    now = datetime.now(UTC)
    person, _ = await service.bound_person(claim, scope, now)
    if acting_for not in {"self", "family"}:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    if claim.status == "authorized":
        token = service.crypto.digest("issued-grant-secret", claim.secret_hash)
        await require_grant(service, token, "history:read")
        return token
    require_disclosure(DisclosureEvidence(
        eligible=True, uniquely_resolved=True, otp_verified=claim.otp_verified_at is not None,
        passport_matched=claim.passport_id is not None,
        questions_passed=claim.status in {"challenge_passed", "recovery_confirmation"},
        authority_current=True, actor_authorized=True, claim_expires_at=claim.expires_at,
        otp_required=claim.method == "phone",
    ), now)
    if claim.status == "recovery_confirmation":
        if not contact_change_confirmed:
            raise ReuseError(ReuseReason.VERIFICATION_FAILED)
        await recover_contact(service, claim, person, now)
        await record_claim_action(service.session, claim, "contact_recovered")
    claim.actor_kind = "self" if acting_for == "self" else "delegate"
    claim.actor_evidence = {
        "declaration": acting_for,
        "policy": "user_selected_phone_or_passport_or_individual_code_v2",
        "ownership_proven": False,
    }
    grant_token = service.crypto.digest("issued-grant-secret", claim.secret_hash)
    service.session.add(TravellerHistoryGrantModel(
        id=uuid.uuid4(), agency_id=claim.agency_id, company_id=claim.company_id,
        group_id=claim.group_id, claim_id=claim.id, traveller_id=person.id,
        passport_id=claim.passport_id, document_revision_id=claim.document_revision_id,
        secret_hash=service.crypto.digest("grant", grant_token),
        profile_revision=person.revision, contact_revision=person.contact_revision,
        authorization_version=person.authorization_version,
        company_revision=scope.company.revision, group_revision=scope.group.company_revision,
        policy_revision=scope.policy.revision, actor_kind=claim.actor_kind,
        actor_evidence=claim.actor_evidence,
        allowed_actions=["history:read", "document:read", "participation:submit", "contact:change"],
        created_at=now, last_used_at=now, inactivity_expires_at=now + GRANT_IDLE_LIFETIME,
        absolute_expires_at=now + GRANT_ABSOLUTE_LIFETIME,
    ))
    claim.status = "authorized"
    await record_claim_action(service.session, claim, "claim_authorized")
    await service.session.commit()
    return grant_token


async def require_grant(
    service: ReturningClaims, token: str, action: str,
) -> tuple[TravellerHistoryGrantModel, ReuseScope, TravellerProfileModel]:
    if not 32 <= len(token) <= 128:
        raise ReuseError(ReuseReason.EXPIRED)
    digest = service.crypto.digest("grant", token)
    routing = (await service.session.execute(select(
        TravellerHistoryGrantModel.group_id, TravellerHistoryGrantModel.traveller_id,
    ).where(TravellerHistoryGrantModel.secret_hash == digest))).one_or_none()
    if routing is None:
        raise ReuseError(ReuseReason.EXPIRED)
    scope = await active_scope(service.session, group_id=routing.group_id)
    now = datetime.now(UTC)
    # Recovery holds person -> grants. Use the same lock order, then re-read
    # authoritative grant state to prevent deadlocks and stale metadata use.
    person = await eligible_person(service.session, scope, routing.traveller_id, now)
    grant = await service.session.scalar(select(TravellerHistoryGrantModel).where(
        TravellerHistoryGrantModel.secret_hash == digest,
        TravellerHistoryGrantModel.agency_id == scope.group.agency_id,
        TravellerHistoryGrantModel.company_id == scope.company.id,
    ).with_for_update().execution_options(populate_existing=True))
    if grant is None or grant.revoked_at is not None or action not in grant.allowed_actions:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    if utc(grant.inactivity_expires_at) <= now or utc(grant.absolute_expires_at) <= now:
        raise ReuseError(ReuseReason.EXPIRED)
    source_claim = await service.session.scalar(select(TravellerClaimModel.id).where(
        TravellerClaimModel.id == grant.claim_id,
        TravellerClaimModel.agency_id == grant.agency_id,
        TravellerClaimModel.company_id == grant.company_id,
        TravellerClaimModel.group_id == grant.group_id,
        TravellerClaimModel.traveller_id == person.id,
        TravellerClaimModel.status == "authorized",
        TravellerClaimModel.revoked_at.is_(None),
    ))
    if source_claim is None:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    if (
        grant.company_revision != scope.company.revision or grant.group_revision != scope.group.company_revision
        or grant.policy_revision != scope.policy.revision or grant.profile_revision != person.revision
        or grant.contact_revision != person.contact_revision or grant.authorization_version != person.authorization_version
    ):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    # Recheck proof revision/status, not merely the presence of an opaque token.
    from app.application.travellers.authority import accepted_document
    _, revision = await accepted_document(service.session, agency_id=grant.agency_id,
        company_id=grant.company_id, traveller_id=person.id, passport_id=grant.passport_id)
    if revision.id != grant.document_revision_id:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    grant.last_used_at = now
    grant.inactivity_expires_at = min(now + GRANT_IDLE_LIFETIME, utc(grant.absolute_expires_at))
    return grant, scope, person


async def recover_contact(
    service: ReturningClaims, claim: TravellerClaimModel, person: TravellerProfileModel, now: datetime,
) -> None:
    """Person-row lock + expected revisions prevent simultaneous recoveries."""
    if claim.otp_verified_at is None or not claim.phone_ciphertext or not claim.phone_fingerprint:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    if person.contact_revision != claim.expected_contact_revision:
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
    await service.session.execute(update(TravellerContactBindingModel).where(
        TravellerContactBindingModel.agency_id == claim.agency_id,
        TravellerContactBindingModel.company_id == claim.company_id,
        TravellerContactBindingModel.traveller_id == person.id,
        TravellerContactBindingModel.kind == "phone", TravellerContactBindingModel.status == "current",
    ).values(status="historical"))
    await invalidate_company_exports(service.session, person.agency_id, person.company_id)
    person.contact_revision += 1
    person.authorization_version += 1
    from app.application.travellers.identity_index import replace_phone_identity_evidence
    await replace_phone_identity_evidence(service.session, person=person,
        normalized_phone=service.crypto.decrypt(claim.phone_ciphertext), crypto=service.crypto,
        source={"claim_id": str(claim.id), "contact_revision": person.contact_revision, "method": "whatsapp_otp"})
    service.session.add(TravellerContactBindingModel(
        id=uuid.uuid4(), agency_id=claim.agency_id, company_id=claim.company_id,
        traveller_id=person.id, kind="phone", status="current", revision=person.contact_revision,
        value_ciphertext=claim.phone_ciphertext, value_fingerprint=claim.phone_fingerprint,
        fingerprint_key_version=service.crypto.key_version, verified_at=claim.otp_verified_at,
        verification_evidence={"method": "whatsapp_otp", "claim_id": str(claim.id)},
        is_shared=False,
    ))
    await service.session.execute(update(TravellerHistoryGrantModel).where(
        TravellerHistoryGrantModel.agency_id == claim.agency_id,
        TravellerHistoryGrantModel.company_id == claim.company_id,
        TravellerHistoryGrantModel.traveller_id == person.id,
        TravellerHistoryGrantModel.revoked_at.is_(None),
    ).values(revoked_at=now))
    await service.session.execute(update(TravellerClaimModel).where(
        TravellerClaimModel.agency_id == claim.agency_id,
        TravellerClaimModel.company_id == claim.company_id,
        TravellerClaimModel.traveller_id == person.id,
        TravellerClaimModel.id != claim.id, TravellerClaimModel.revoked_at.is_(None),
    ).values(revoked_at=now, status="revoked"))
    service.session.add(TravellerChangeEventModel(
        id=uuid.uuid4(), agency_id=claim.agency_id, company_id=claim.company_id,
        traveller_id=person.id, event_type="contact_recovered", aggregate_id=person.id,
        aggregate_revision=person.contact_revision, idempotency_key=f"contact:{claim.id}",
        reason_code="verified_contact_change",
    ))
    claim.expected_contact_revision = person.contact_revision
    claim.expected_authorization_version = person.authorization_version
