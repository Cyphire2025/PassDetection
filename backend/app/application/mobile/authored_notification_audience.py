"""Current trip grants used by both reviewed audience snapshots and dispatch."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.application.mobile.group_app_availability import availability_filter
from app.application.mobile.passenger_notification_authority import _SUBMISSION_FIELDS
from app.application.mobile.passenger_phone_authority import submitted_phone_matches_identity
from app.core.security.mobile_jwt import hash_mobile_lookup
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories.coordinator_assignment_lifecycle import expired_trip_clause


@dataclass(frozen=True)
class AudienceGrant:
    agency_id: uuid.UUID
    group_id: uuid.UUID
    access_id: uuid.UUID
    principal_id: uuid.UUID
    role: str
    person_key: str
    access_generation: int
    claim_generation: int | None = None

    def signature(self) -> tuple[str, ...]:
        return (
            str(self.group_id),
            str(self.access_id),
            str(self.principal_id),
            self.role,
            self.person_key,
            str(self.access_generation),
            str(self.claim_generation),
        )


@dataclass(frozen=True)
class NotificationAudienceSnapshot:
    groups: tuple[tuple[uuid.UUID, str], ...]
    grants: tuple[AudienceGrant, ...]

    @property
    def fingerprint(self) -> str:
        value = [list(self.groups_as_strings()), sorted(grant.signature() for grant in self.grants)]
        return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()

    def groups_as_strings(self) -> tuple[tuple[str, str], ...]:
        return tuple((str(group_id), name) for group_id, name in self.groups)

    @property
    def people(self) -> dict[str, list[AudienceGrant]]:
        result: dict[str, list[AudienceGrant]] = {}
        for grant in self.grants:
            result.setdefault(grant.person_key, []).append(grant)
        return result

    @property
    def role_counts(self) -> dict[str, int]:
        names = {
            "passenger": "passengers",
            "client_manager": "client_managers",
            "coordinator": "coordinators",
        }
        counts = dict.fromkeys(names.values(), 0)
        for grants in self.people.values():
            counts[names[grants[0].role]] += 1
        return counts


def passenger_person_key(agency_id: uuid.UUID, phone: str) -> str:
    return "p:" + hash_mobile_lookup(f"{agency_id}:{phone}", purpose="authored-notification-person")


async def collect_notification_audience(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_ids: list[uuid.UUID] | None,
    now: datetime,
    principal_ids: set[uuid.UUID] | None = None,
) -> NotificationAudienceSnapshot:
    """Read current authority in bounded group pages; never reconcile or commit."""
    statement = (
        select(ClientGroupModel.id, ClientGroupModel.name, GCGroupAccessModel)
        .join(
            GCGroupAccessModel,
            and_(
                GCGroupAccessModel.group_id == ClientGroupModel.id,
                GCGroupAccessModel.agency_id == ClientGroupModel.agency_id,
            ),
        )
        .where(ClientGroupModel.agency_id == agency_id, availability_filter("active", now=now))
        .order_by(ClientGroupModel.id)
        .execution_options(populate_existing=True)
    )
    if group_ids is not None:
        statement = statement.where(ClientGroupModel.id.in_(group_ids))
    groups: list[tuple[uuid.UUID, str]] = []
    grants: list[AudienceGrant] = []
    cursor: uuid.UUID | None = None
    while True:
        page_statement = (
            statement if cursor is None else statement.where(ClientGroupModel.id > cursor)
        )
        rows = (await session.execute(page_statement.limit(250))).all()
        if not rows:
            break
        accesses = {access.id: access for _, _, access in rows}
        groups.extend((group_id, name) for group_id, name, _ in rows)
        grants.extend(await _passenger_grants(session, agency_id, accesses, principal_ids))
        grants.extend(await _staff_grants(session, agency_id, accesses, principal_ids, now))
        cursor = rows[-1][0]
    return NotificationAudienceSnapshot(
        tuple(groups), tuple(sorted(grants, key=lambda item: item.signature()))
    )


async def _passenger_grants(
    session: AsyncSession,
    agency_id: uuid.UUID,
    accesses: dict[uuid.UUID, GCGroupAccessModel],
    principal_ids: set[uuid.UUID] | None,
) -> list[AudienceGrant]:
    enabled = [item.id for item in accesses.values() if item.passenger_access_enabled]
    if not enabled:
        return []
    statement = (
        select(MobilePassengerIdentityModel, PassportSubmissionModel)
        .join(
            PassportSubmissionModel,
            PassportSubmissionModel.id == MobilePassengerIdentityModel.passenger_submission_id,
        )
        .options(load_only(*_SUBMISSION_FIELDS))
        .where(
            MobilePassengerIdentityModel.agency_id == agency_id,
            MobilePassengerIdentityModel.gc_group_access_id.in_(enabled),
            MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
            MobilePassengerIdentityModel.revoked_at.is_(None),
        )
        .order_by(MobilePassengerIdentityModel.id)
        .execution_options(populate_existing=True)
    )
    if principal_ids is not None:
        statement = statement.where(MobilePassengerIdentityModel.id.in_(principal_ids))
    result: list[AudienceGrant] = []
    rows = await session.stream(statement.execution_options(yield_per=250))
    async for identity, submission in rows:
        access = accesses[identity.gc_group_access_id]
        if identity.group_id == access.group_id and submitted_phone_matches_identity(
            identity, submission
        ):
            result.append(
                AudienceGrant(
                    agency_id,
                    access.group_id,
                    access.id,
                    identity.id,
                    "passenger",
                    passenger_person_key(agency_id, identity.normalized_phone_number),
                    access.access_generation,
                    identity.claim_generation,
                )
            )
    return result


async def _staff_grants(
    session: AsyncSession,
    agency_id: uuid.UUID,
    accesses: dict[uuid.UUID, GCGroupAccessModel],
    principal_ids: set[uuid.UUID] | None,
    now: datetime,
) -> list[AudienceGrant]:
    result: list[AudienceGrant] = []
    common = (
        UserModel.agency_id == agency_id,
        UserModel.is_active.is_(True),
        UserModel.deleted_at.is_(None),
    )
    manager_statement = (
        select(UserModel.id, ClientManagerGroupAssignmentModel.gc_group_access_id)
        .join(ClientManagerProfileModel, ClientManagerProfileModel.user_id == UserModel.id)
        .join(
            ClientManagerGroupAssignmentModel,
            ClientManagerGroupAssignmentModel.profile_id == ClientManagerProfileModel.id,
        )
        .where(
            *common,
            UserModel.role == "client_manager",
            ClientManagerProfileModel.agency_id == agency_id,
            ClientManagerProfileModel.status == "active",
            ClientManagerProfileModel.deleted_at.is_(None),
            ClientManagerGroupAssignmentModel.agency_id == agency_id,
            ClientManagerGroupAssignmentModel.gc_group_access_id.in_(
                [a.id for a in accesses.values() if a.client_manager_access_enabled]
            ),
            ClientManagerGroupAssignmentModel.is_active.is_(True),
            ClientManagerGroupAssignmentModel.revoked_at.is_(None),
        )
    )
    coordinator_statement = (
        select(UserModel.id, GCGroupAccessModel.id)
        .join(
            CoordinatorGroupAssignmentModel,
            CoordinatorGroupAssignmentModel.coordinator_user_id == UserModel.id,
        )
        .join(
            GCGroupAccessModel,
            and_(
                GCGroupAccessModel.group_id == CoordinatorGroupAssignmentModel.group_id,
                GCGroupAccessModel.agency_id == CoordinatorGroupAssignmentModel.agency_id,
            ),
        )
        .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
        .where(
            *common,
            UserModel.role == "agency_coordinator",
            CoordinatorGroupAssignmentModel.agency_id == agency_id,
            CoordinatorGroupAssignmentModel.active.is_(True),
            ~expired_trip_clause(now),
            GCGroupAccessModel.id.in_(
                [a.id for a in accesses.values() if a.coordinator_access_enabled]
            ),
        )
    )
    for role, statement in (
        ("client_manager", manager_statement),
        ("coordinator", coordinator_statement),
    ):
        if principal_ids is not None:
            statement = statement.where(UserModel.id.in_(principal_ids))
        rows = await session.stream(statement.execution_options(yield_per=250))
        async for principal_id, access_id in rows:
            access = accesses[access_id]
            result.append(
                AudienceGrant(
                    agency_id,
                    access.group_id,
                    access_id,
                    principal_id,
                    role,
                    f"u:{principal_id}",
                    access.access_generation,
                )
            )
    return result
