"""Reconcile strong WhatsApp/passport evidence into mobile passenger identities.

Names alone are never sufficient. Shared phone numbers are provisioned only
when every passenger has a distinct, user-knowable secondary factor.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.sync_journal import append_mobile_sync_change
from app.application.use_cases.whatsapp.contact_normalization import (
    normalize_whatsapp_phone,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
)
from app.core.security.mobile_jwt import (
    hash_mobile_lookup,
    hash_mobile_secondary_factor,
)
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobilePassengerIdentityModel,
    MobilePassengerSessionIdentityModel,
    MobileRefreshTokenModel,
)
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    TARGETED_MATCH_CLUSTER_LIMIT,
    load_targeted_unresolved_passport_whatsapp_match_context,
    load_unresolved_passport_whatsapp_match_context,
)

_STRONG_MATCH_KINDS = frozenset(
    {"phone", "email", "passport_number", "staff_code"}
)
_SECONDARY_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "employee_code",
        ("agent_employee_code", "employee_code", "employee_id", "staff_code", "staff_id"),
    ),
    (
        "booking_code",
        ("booking_code", "booking_id", "pnr", "reservation_code"),
    ),
    (
        "passenger_identifier",
        ("passenger_identifier", "passenger_id", "registration_id"),
    ),
    ("date_of_birth", ("date_of_birth", "dob")),
)
_TARGETED_RECONCILIATION_INPUT_LIMIT = 8
_TARGETED_RECONCILIATION_MAX_ROUNDS = 4


@dataclass(frozen=True, slots=True)
class PassengerIdentityCandidate:
    passenger_submission_id: uuid.UUID
    normalized_phone: str
    is_shared_number: bool
    requires_secondary_verification: bool
    secondary_factor_type: str | None
    secondary_factor_value: str | None


@dataclass(frozen=True, slots=True)
class PassengerIdentityPlan:
    candidates: tuple[PassengerIdentityCandidate, ...]
    skipped_ambiguous: int
    skipped_without_secondary_factor: int


@dataclass(frozen=True, slots=True)
class PassengerIdentityReconciliationResult:
    created: int
    updated: int
    unchanged: int
    revoked: int
    skipped_ambiguous: int
    skipped_without_secondary_factor: int

    @property
    def changed(self) -> int:
        return self.created + self.updated + self.revoked


def plan_passenger_identities(
    rows: list[SubmissionMatchRow],
    submissions: list[PassportSubmissionModel],
    *,
    agency_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
) -> PassengerIdentityPlan:
    """Create a deterministic fail-closed plan from existing matching output."""

    by_id = {
        submission.id: submission
        for submission in submissions
        if (agency_id is None or submission.agency_id == agency_id)
        and (group_id is None or submission.group_id == group_id)
    }
    provisional: list[
        tuple[uuid.UUID, str, tuple[str, str] | None]
    ] = []
    skipped_ambiguous = 0

    for row in rows:
        if row.status not in {"submitted", "multiple_submissions"}:
            if row.candidate_submission_ids:
                skipped_ambiguous += len(row.candidate_submission_ids)
            continue
        phone = normalize_whatsapp_phone(row.normalized_phone)
        if phone is None:
            skipped_ambiguous += len(row.submission_ids)
            continue
        for submission_id in row.submission_ids:
            submission = by_id.get(submission_id)
            evidence_kinds = {
                evidence.kind
                for evidence in row.match_evidence
                if evidence.submission_id == submission_id
            }
            if submission is None or not (evidence_kinds & _STRONG_MATCH_KINDS):
                skipped_ambiguous += 1
                continue
            provisional.append((submission_id, phone, _secondary_factor(submission)))

    # A passenger-entered phone on the authoritative submission is itself
    # strong ownership evidence once the user proves control of that number by
    # OTP.  Keep WhatsApp roster matches authoritative when both sources are
    # present, and use this source only for submissions that were not already
    # resolved by the matching engine.  This closes the gap where a newly
    # added passenger belongs to a GC-enabled group but its broadcast link has
    # not yet been rebuilt.
    provisioned_submission_ids = {
        submission_id for submission_id, _phone, _factor in provisional
    }
    for submission_id in sorted(by_id, key=str):
        if submission_id in provisioned_submission_ids:
            continue
        submission = by_id[submission_id]
        phone = normalize_whatsapp_phone(getattr(submission, "client_phone", None))
        if phone is None:
            continue
        provisional.append((submission_id, phone, _secondary_factor(submission)))

    phone_counts = Counter(phone for _submission_id, phone, _factor in provisional)
    factor_counts = Counter(
        (phone, factor[0], _normalize_factor(factor[1]))
        for _submission_id, phone, factor in provisional
        if factor is not None
    )
    candidates: list[PassengerIdentityCandidate] = []
    skipped_without_secondary = 0
    for submission_id, phone, factor in provisional:
        is_shared = phone_counts[phone] > 1
        factor_type: str | None = None
        factor_value: str | None = None
        if is_shared:
            if factor is None:
                skipped_without_secondary += 1
                continue
            factor_type, factor_value = factor
            if factor_counts[(phone, factor_type, _normalize_factor(factor_value))] != 1:
                skipped_without_secondary += 1
                continue
        elif factor is not None:
            # Preserve a strong, user-knowable factor even for a currently
            # unambiguous group binding.  OTP lookup is agency-wide: the same
            # phone may later resolve to another trip, at which point both
            # identities must prove a factor before either claim is revealed.
            factor_type, factor_value = factor
        candidates.append(
            PassengerIdentityCandidate(
                passenger_submission_id=submission_id,
                normalized_phone=phone,
                is_shared_number=is_shared,
                requires_secondary_verification=is_shared,
                secondary_factor_type=factor_type,
                secondary_factor_value=factor_value,
            )
        )

    return PassengerIdentityPlan(
        candidates=tuple(sorted(candidates, key=lambda item: str(item.passenger_submission_id))),
        skipped_ambiguous=skipped_ambiguous,
        skipped_without_secondary_factor=skipped_without_secondary,
    )


async def reconcile_passenger_identities(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    actor_user_id: uuid.UUID | None,
) -> PassengerIdentityReconciliationResult:
    """Apply a tenant/group-scoped identity plan and revoke stale sessions."""

    _linked, _recipients, submissions, rows = (
        await load_unresolved_passport_whatsapp_match_context(
            session,
            group_id=access.group_id,
            agency_id=access.agency_id,
        )
    )
    plan = plan_passenger_identities(
        rows,
        submissions,
        agency_id=access.agency_id,
        group_id=access.group_id,
    )
    existing = list(
        (
            await session.execute(
                select(MobilePassengerIdentityModel)
                .where(
                    MobilePassengerIdentityModel.agency_id == access.agency_id,
                    MobilePassengerIdentityModel.group_id == access.group_id,
                    MobilePassengerIdentityModel.gc_group_access_id == access.id,
                )
                .with_for_update()
            )
        ).scalars()
    )
    return await _apply_passenger_identity_plan(
        session,
        access=access,
        actor_user_id=actor_user_id,
        plan=plan,
        existing=existing,
    )


async def reconcile_passenger_identities_for_changes(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    actor_user_id: uuid.UUID | None,
    passenger_submission_ids: tuple[uuid.UUID, ...],
) -> PassengerIdentityReconciliationResult:
    """Use a bounded component for explicit edits, then fail closed to full."""

    seed_ids = tuple(sorted(set(passenger_submission_ids), key=str))
    if 0 < len(seed_ids) <= _TARGETED_RECONCILIATION_INPUT_LIMIT:
        targeted = await _reconcile_passenger_identities_targeted(
            session,
            access=access,
            actor_user_id=actor_user_id,
            passenger_submission_ids=seed_ids,
        )
        if targeted is not None:
            return targeted
    return await reconcile_passenger_identities(
        session,
        access=access,
        actor_user_id=actor_user_id,
    )


async def _reconcile_passenger_identities_targeted(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    actor_user_id: uuid.UUID | None,
    passenger_submission_ids: tuple[uuid.UUID, ...],
) -> PassengerIdentityReconciliationResult | None:
    """Reconcile only a proven-complete identity/evidence connected component."""

    seed_ids = frozenset(passenger_submission_ids)
    seed_phones: frozenset[str] = frozenset()
    context = None
    related_identities: list[MobilePassengerIdentityModel] = []

    for _round in range(_TARGETED_RECONCILIATION_MAX_ROUNDS):
        identity_conditions = [
            MobilePassengerIdentityModel.passenger_submission_id.in_(tuple(seed_ids))
        ]
        if seed_phones:
            identity_conditions.append(
                MobilePassengerIdentityModel.normalized_phone_number.in_(
                    tuple(seed_phones)
                )
            )
        related_identities = list(
            (
                await session.execute(
                    select(MobilePassengerIdentityModel)
                    .where(
                        MobilePassengerIdentityModel.agency_id == access.agency_id,
                        MobilePassengerIdentityModel.group_id == access.group_id,
                        MobilePassengerIdentityModel.gc_group_access_id == access.id,
                        or_(*identity_conditions),
                    )
                    .limit(TARGETED_MATCH_CLUSTER_LIMIT + 1)
                )
            ).scalars()
        )
        if len(related_identities) > TARGETED_MATCH_CLUSTER_LIMIT:
            return None
        expanded_ids = seed_ids | frozenset(
            identity.passenger_submission_id for identity in related_identities
        )
        expanded_phones = seed_phones | frozenset(
            identity.normalized_phone_number for identity in related_identities
        )
        context = await load_targeted_unresolved_passport_whatsapp_match_context(
            session,
            group_id=access.group_id,
            agency_id=access.agency_id,
            seed_submission_ids=tuple(sorted(expanded_ids, key=str)),
            seed_phone_numbers=expanded_phones,
        )
        if context is None:
            return None
        next_ids = expanded_ids | context.affected_submission_ids
        next_phones = expanded_phones | context.affected_phone_numbers
        if next_ids == seed_ids and next_phones == seed_phones:
            break
        if len(next_ids) > TARGETED_MATCH_CLUSTER_LIMIT:
            return None
        seed_ids = next_ids
        seed_phones = next_phones
    else:
        return None

    if context is None:
        return None
    locked_conditions = [
        MobilePassengerIdentityModel.passenger_submission_id.in_(
            tuple(context.affected_submission_ids)
        )
    ]
    if context.affected_phone_numbers:
        locked_conditions.append(
            MobilePassengerIdentityModel.normalized_phone_number.in_(
                tuple(context.affected_phone_numbers)
            )
        )
    locked_existing = list(
        (
            await session.execute(
                select(MobilePassengerIdentityModel)
                .where(
                    MobilePassengerIdentityModel.agency_id == access.agency_id,
                    MobilePassengerIdentityModel.group_id == access.group_id,
                    MobilePassengerIdentityModel.gc_group_access_id == access.id,
                    or_(*locked_conditions),
                )
                .limit(TARGETED_MATCH_CLUSTER_LIMIT + 1)
                .with_for_update()
            )
        ).scalars()
    )
    if len(locked_existing) > TARGETED_MATCH_CLUSTER_LIMIT:
        return None
    # Any previously unseen old binding means the graph changed while it was
    # prepared.  Do not apply a partial plan; the full reconciler will retry
    # under the established group lock.
    if any(
        identity.passenger_submission_id not in context.affected_submission_ids
        or identity.normalized_phone_number not in context.affected_phone_numbers
        for identity in locked_existing
    ):
        return None

    plan = plan_passenger_identities(
        list(context.rows),
        list(context.submissions),
        agency_id=access.agency_id,
        group_id=access.group_id,
    )
    return await _apply_passenger_identity_plan(
        session,
        access=access,
        actor_user_id=actor_user_id,
        plan=plan,
        existing=locked_existing,
    )


async def _apply_passenger_identity_plan(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    actor_user_id: uuid.UUID | None,
    plan: PassengerIdentityPlan,
    existing: list[MobilePassengerIdentityModel],
) -> PassengerIdentityReconciliationResult:
    """Apply a complete full-group or bounded-component plan identically."""

    desired = {item.passenger_submission_id: item for item in plan.candidates}
    by_passenger = {item.passenger_submission_id: item for item in existing}
    now = datetime.now(tz=UTC)
    created = updated_count = unchanged = revoked = 0
    changed_identities: list[MobilePassengerIdentityModel] = []

    for passenger_id, candidate in desired.items():
        identity = by_passenger.get(passenger_id)
        if identity is None:
            identity_id = uuid.uuid4()
            identity = MobilePassengerIdentityModel(
                id=identity_id,
                agency_id=access.agency_id,
                group_id=access.group_id,
                gc_group_access_id=access.id,
                passenger_submission_id=passenger_id,
                normalized_phone_number=candidate.normalized_phone,
                phone_lookup_hash=hash_mobile_lookup(
                    candidate.normalized_phone, purpose="passenger-phone"
                ),
                status="eligible",
                is_shared_number=candidate.is_shared_number,
                requires_secondary_verification=(
                    candidate.requires_secondary_verification
                ),
                secondary_factor_type=candidate.secondary_factor_type,
                secondary_factor_hash=(
                    hash_mobile_secondary_factor(
                        identity_id,
                        candidate.secondary_factor_value or "",
                    )
                    if candidate.secondary_factor_type is not None
                    else None
                ),
                claim_generation=0,
                claimed_at=None,
                last_verified_at=None,
                revoked_at=None,
                created_by_user_id=actor_user_id,
                created_at=now,
                updated_at=now,
            )
            session.add(identity)
            created += 1
            changed_identities.append(identity)
            continue

        secondary_hash = (
            hash_mobile_secondary_factor(
                identity.id, candidate.secondary_factor_value or ""
            )
            if candidate.secondary_factor_type is not None
            else None
        )
        binding_changed = any(
            (
                identity.normalized_phone_number != candidate.normalized_phone,
                identity.secondary_factor_type != candidate.secondary_factor_type,
                identity.secondary_factor_hash != secondary_hash,
                identity.is_shared_number != candidate.is_shared_number,
                identity.requires_secondary_verification
                != candidate.requires_secondary_verification,
                identity.status == "revoked",
            )
        )
        if not binding_changed:
            unchanged += 1
            continue
        await _revoke_passenger_identity_sessions(
            session, access.agency_id, identity.id, "passenger_identity_changed"
        )
        identity.normalized_phone_number = candidate.normalized_phone
        identity.phone_lookup_hash = hash_mobile_lookup(
            candidate.normalized_phone, purpose="passenger-phone"
        )
        identity.is_shared_number = candidate.is_shared_number
        identity.requires_secondary_verification = (
            candidate.requires_secondary_verification
        )
        identity.secondary_factor_type = candidate.secondary_factor_type
        identity.secondary_factor_hash = secondary_hash
        identity.status = "eligible"
        identity.claimed_at = None
        identity.last_verified_at = None
        identity.revoked_at = None
        identity.claim_generation += 1
        identity.updated_at = now
        updated_count += 1
        changed_identities.append(identity)

    for identity in existing:
        if identity.passenger_submission_id in desired or identity.status == "revoked":
            continue
        await _revoke_passenger_identity_sessions(
            session, access.agency_id, identity.id, "passenger_identity_revoked"
        )
        identity.status = "revoked"
        identity.revoked_at = now
        identity.claimed_at = None
        identity.claim_generation += 1
        identity.updated_at = now
        revoked += 1
        changed_identities.append(identity)

    if changed_identities:
        access.manifest_version += 1
        access.revision += 1
        access.updated_by_user_id = actor_user_id
        access.updated_at = now
        await session.flush()
        for identity in changed_identities:
            await append_mobile_sync_change(
                session,
                access=access,
                audience="passenger",
                passenger_identity_id=identity.id,
                entity_type="passenger_identity",
                entity_id=identity.id,
                operation=("revoke" if identity.status == "revoked" else "upsert"),
                version=access.manifest_version,
                changed_by_user_id=actor_user_id,
                payload={
                    "resource_path": f"/api/v1/mobile/trips/{access.group_id}/manifest",
                    "purge_required": identity.status == "revoked",
                },
            )

    return PassengerIdentityReconciliationResult(
        created=created,
        updated=updated_count,
        unchanged=unchanged,
        revoked=revoked,
        skipped_ambiguous=plan.skipped_ambiguous,
        skipped_without_secondary_factor=plan.skipped_without_secondary_factor,
    )


def _secondary_factor(
    submission: PassportSubmissionModel,
) -> tuple[str, str] | None:
    sources = (
        dict(submission.confirmed_fields or {}),
        dict(submission.staff_metadata or {}),
    )
    for factor_type, keys in _SECONDARY_FIELDS:
        for source in sources:
            for key in keys:
                value = _clean_factor(source.get(key))
                if value is not None:
                    return factor_type, value
    return None


def _clean_factor(value: object) -> str | None:
    normalized = " ".join(str(value or "").strip().split())
    if len(normalized) < 2 or len(normalized) > 128:
        return None
    return normalized


def _normalize_factor(value: str) -> str:
    return " ".join(value.casefold().split())


async def _revoke_passenger_identity_sessions(
    session: AsyncSession,
    agency_id: uuid.UUID,
    identity_id: uuid.UUID,
    reason: str,
) -> None:
    now = datetime.now(tz=UTC)
    authorized_session_ids = select(
        MobilePassengerSessionIdentityModel.session_id
    ).where(
        MobilePassengerSessionIdentityModel.agency_id == agency_id,
        MobilePassengerSessionIdentityModel.passenger_identity_id == identity_id,
    )
    session_ids = select(MobileDeviceSessionModel.id).where(
        MobileDeviceSessionModel.agency_id == agency_id,
        or_(
            MobileDeviceSessionModel.passenger_identity_id == identity_id,
            MobileDeviceSessionModel.id.in_(authorized_session_ids),
        ),
        MobileDeviceSessionModel.status == "active",
    )
    await session.execute(
        update(MobileRefreshTokenModel)
        .where(
            MobileRefreshTokenModel.agency_id == agency_id,
            MobileRefreshTokenModel.session_id.in_(session_ids),
            MobileRefreshTokenModel.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason=reason)
    )
    await session.execute(
        update(MobileDeviceSessionModel)
        .where(MobileDeviceSessionModel.id.in_(session_ids))
        .values(
            status="revoked",
            session_generation=MobileDeviceSessionModel.session_generation + 1,
            revoked_at=now,
            revoke_reason=reason,
            updated_at=now,
        )
    )
