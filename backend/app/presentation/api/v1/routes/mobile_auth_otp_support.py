"""Passenger OTP discovery, proof, and challenge boundaries."""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime
from typing import cast

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_identity_reconciliation import (
    reconcile_passenger_identities,
)
from app.application.mobile.passenger_phone_authority import submitted_phone_matches_identity
from app.core.security.mobile_jwt import (
    hash_mobile_otp_code,
    hash_mobile_secondary_factor,
)
from app.domain.entities.entities import GroupStatus
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileOTPChallengeModel,
    MobilePassengerIdentityModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportSubmissionModel,
)
from app.presentation.api.v1.routes.mobile_auth_phone_support import submitted_phone_rows
from app.presentation.api.v1.schemas.mobile_schemas import MobileTripClaimSummary


async def _eligible_passenger_identities(
    session: AsyncSession,
    phone_lookup_hash: str,
) -> list[tuple[MobilePassengerIdentityModel, GCGroupAccessModel, ClientGroupModel]]:
    now = datetime.now(tz=UTC)
    rows = (
        await session.execute(
            select(MobilePassengerIdentityModel, GCGroupAccessModel, ClientGroupModel, PassportSubmissionModel)
            .join(
                GCGroupAccessModel,
                GCGroupAccessModel.id == MobilePassengerIdentityModel.gc_group_access_id,
            )
            .join(ClientGroupModel, ClientGroupModel.id == MobilePassengerIdentityModel.group_id)
            .join(PassportSubmissionModel, (
                (PassportSubmissionModel.id == MobilePassengerIdentityModel.passenger_submission_id)
                & (PassportSubmissionModel.agency_id == MobilePassengerIdentityModel.agency_id)
                & (PassportSubmissionModel.group_id == MobilePassengerIdentityModel.group_id)
            ))
            .where(
                MobilePassengerIdentityModel.phone_lookup_hash == phone_lookup_hash,
                MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                MobilePassengerIdentityModel.revoked_at.is_(None),
                GCGroupAccessModel.is_enabled.is_(True),
                GCGroupAccessModel.passenger_access_enabled.is_(True),
                GCGroupAccessModel.revoked_at.is_(None),
                ClientGroupModel.status.in_((GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value)),
                ClientGroupModel.deleted_at.is_(None),
                (
                    GCGroupAccessModel.access_starts_at.is_(None)
                    | (GCGroupAccessModel.access_starts_at <= now)
                ),
                (
                    GCGroupAccessModel.access_expires_at.is_(None)
                    | (GCGroupAccessModel.access_expires_at > now)
                ),
                MobilePassengerIdentityModel.agency_id == GCGroupAccessModel.agency_id,
                MobilePassengerIdentityModel.group_id == GCGroupAccessModel.group_id,
                ClientGroupModel.agency_id == GCGroupAccessModel.agency_id,
            )
            .order_by(ClientGroupModel.travel_date.asc(), ClientGroupModel.id.asc())
            .limit(50)
        )
    ).all()
    return cast(
        list[
            tuple[
                MobilePassengerIdentityModel,
                GCGroupAccessModel,
                ClientGroupModel,
            ]
        ],
        [(identity, access, group) for identity, access, group, submission in rows
         if submitted_phone_matches_identity(identity, submission)],
    )


async def _reconcile_phone_candidate_groups(
    session: AsyncSession,
    *,
    normalized_phone: str,
    phone_lookup_hash: str,
) -> None:
    """Migrate current and legacy bindings even when this number was known.

    Current submitted contacts discover their GC groups. Old identity hashes
    additionally discover groups that must revoke a roster-derived or changed
    binding. Broadcast tables never supply authorization candidates.
    """

    submitted = await submitted_phone_rows(session, normalized_phone)
    submission_access_ids = {access.id for _, _, access in submitted if access is not None}
    legacy_access_ids = select(MobilePassengerIdentityModel.gc_group_access_id).where(
        MobilePassengerIdentityModel.phone_lookup_hash == phone_lookup_hash,
    )
    accesses = list((await session.execute(
        select(GCGroupAccessModel)
        .where(or_(
            GCGroupAccessModel.id.in_(submission_access_ids),
            GCGroupAccessModel.id.in_(legacy_access_ids),
        ))
        .order_by(GCGroupAccessModel.id)
        .limit(101)
        .with_for_update()
    )).scalars().unique())
    if len(accesses) > 100:
        raise HTTPException(503, "OTP verification is temporarily unavailable")
    for access in accesses:
        await reconcile_passenger_identities(
            session, access=access,
            actor_user_id=access.updated_by_user_id or access.created_by_user_id,
        )


def _matching_passenger_claims(
    eligible: list[tuple[MobilePassengerIdentityModel, GCGroupAccessModel, ClientGroupModel]],
    *,
    claim_id: uuid.UUID | None,
    verification_value: str | None,
) -> list[tuple[MobilePassengerIdentityModel, GCGroupAccessModel, ClientGroupModel]]:
    """Resolve OTP claims without revealing cross-group shared phone records.

    This path is reached only after direct tenant-local, unshared multi-trip
    authorization has been ruled out. Any remaining multi-row phone lookup is
    ambiguous and therefore requires a retained secondary factor. A row without
    that factor is deliberately unreachable in this state.
    """

    multiple_phone_matches = len(eligible) > 1
    candidates = (
        [row for row in eligible if row[0].id == claim_id] if claim_id is not None else eligible
    )
    matches: list[tuple[MobilePassengerIdentityModel, GCGroupAccessModel, ClientGroupModel]] = []
    for row in candidates:
        identity = row[0]
        if not multiple_phone_matches and not identity.requires_secondary_verification:
            matches.append(row)
            continue
        if verification_value is None or identity.secondary_factor_hash is None:
            continue
        candidate = hash_mobile_secondary_factor(identity.id, verification_value)
        if hmac.compare_digest(candidate, identity.secondary_factor_hash):
            matches.append(row)
    return matches


def _direct_passenger_otp_rows(
    eligible: list[
        tuple[MobilePassengerIdentityModel, GCGroupAccessModel, ClientGroupModel]
    ],
) -> list[tuple[MobilePassengerIdentityModel, GCGroupAccessModel, ClientGroupModel]]:
    """Return an exact tenant-local proof set when OTP possession is enough.

    OTP possession directly proves exactly one passenger identity.  More than
    one eligible row is ambiguous even when each row was unshared inside its
    own group: two unrelated passengers can legitimately reuse a phone across
    different groups.  Those rows must prove the same retained secondary
    factor before the server can link their trips into one mobile account.
    """

    if len(eligible) != 1:
        return []
    first_identity = eligible[0][0]
    if any(
        identity.agency_id != first_identity.agency_id
        or identity.phone_lookup_hash != first_identity.phone_lookup_hash
        or identity.is_shared_number
        or identity.requires_secondary_verification
        for identity, _access, _group in eligible
    ):
        return []
    return eligible


async def _locked_challenge(
    session: AsyncSession, challenge_id: uuid.UUID
) -> MobileOTPChallengeModel:
    challenge = (
        await session.execute(
            select(MobileOTPChallengeModel)
            .where(MobileOTPChallengeModel.id == challenge_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if challenge is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification challenge",
        )
    return challenge


async def _verify_challenge_code(
    session: AsyncSession,
    challenge: MobileOTPChallengeModel,
    code: str,
) -> None:
    now = datetime.now(tz=UTC)
    if challenge.status != "pending" or challenge.expires_at <= now:
        if challenge.status == "pending" and challenge.expires_at <= now:
            challenge.status = "expired"
            challenge.updated_at = now
            await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification code",
        )
    expected = hash_mobile_otp_code(challenge.id, code)
    if not hmac.compare_digest(expected, challenge.code_hash):
        challenge.attempt_count = min(challenge.max_attempts, challenge.attempt_count + 1)
        if challenge.attempt_count >= challenge.max_attempts:
            challenge.status = "locked"
        challenge.updated_at = now
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired verification code",
        )


def _validate_passenger_session_identities(
    *,
    selected_identity: MobilePassengerIdentityModel,
    authorized_identities: list[MobilePassengerIdentityModel],
) -> None:
    """Reject any internally inconsistent proof set before it reaches storage."""

    identity_ids = [item.id for item in authorized_identities]
    valid = (
        1 <= len(authorized_identities) <= 50
        and len(identity_ids) == len(set(identity_ids))
        and selected_identity.id in identity_ids
        and all(
            item.agency_id == selected_identity.agency_id
            and item.phone_lookup_hash == selected_identity.phone_lookup_hash
            and item.status in {"eligible", "claimed"}
            and item.revoked_at is None
            for item in authorized_identities
        )
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Passenger verification could not be completed",
        )


def _claim_summary(
    identity: MobilePassengerIdentityModel,
    group: ClientGroupModel,
) -> MobileTripClaimSummary:
    return MobileTripClaimSummary(
        claim_id=identity.id,
        group_id=group.id,
        group_name=group.name,
        destination=group.destination,
        travel_date=group.travel_date,
        return_date=group.return_date,
        timezone=group.timezone,
        requires_secondary_verification=identity.requires_secondary_verification,
    )
