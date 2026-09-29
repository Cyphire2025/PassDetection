"""Bounded, locked source for one additive group-to-broadcast link."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.additive_mobile import AdditiveMobilePlan, prepare_additive_mobile_plan
from app.application.mcp.change_context import require_change_actor, require_change_group
from app.application.mcp.operations import MCPDatabaseContext, MCPOperationError
from app.application.use_cases.whatsapp.source_group_contacts import build_source_contacts
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppTravellerPhoneOverrideModel,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member

MAX_SOURCE_ROWS = 5000
MAX_LINKS = 100


@dataclass(frozen=True, slots=True)
class BroadcastLinkSource:
    group: ClientGroupModel
    broadcast: WhatsAppBroadcastGroupModel
    links: list[ClientGroupWhatsAppBroadcastLinkModel]
    contacts: list[WhatsAppBroadcastSourceContactModel]
    recipients: list[WhatsAppBroadcastRecipientModel]
    snapshot: dict[str, Any]
    mobile: AdditiveMobilePlan | None
    blocked_phones: set[str]

    @property
    def existing_link(self) -> ClientGroupWhatsAppBroadcastLinkModel | None:
        return next(
            (row for row in self.links if row.broadcast_group_id == self.broadcast.id), None
        )


def _values(row: Any, fields: tuple[str, ...]) -> list[Any]:
    return [getattr(row, field) for field in fields]


def link_source_revision(source: BroadcastLinkSource) -> str:
    mobile = source.mobile
    data = {
        "group": _values(
            source.group, ("id", "agency_id", "status", "name", "import_only", "roster_revision")
        ),
        "broadcast": _values(
            source.broadcast, ("id", "agency_id", "name", "archived_at", "imported_field_keys")
        ),
        "links": [
            _values(
                row,
                (
                    "id",
                    "client_group_id",
                    "broadcast_group_id",
                    "matching_field_keys",
                    "sync_contacts_from_group",
                ),
            )
            for row in source.links
        ],
        "contacts": [
            _values(
                row,
                (
                    "id",
                    "source_group_id",
                    "source_submission_id",
                    "recipient_id",
                    "name",
                    "raw_phone_number",
                    "normalized_phone_number",
                    "issue",
                    "imported_fields",
                ),
            )
            for row in source.contacts
        ],
        "recipients": [
            _values(
                row,
                (
                    "id",
                    "name",
                    "phone_number",
                    "normalized_phone_number",
                    "imported_fields",
                    "display_order",
                    "is_source_managed",
                    "removed_at",
                    "merged_into_recipient_id",
                    "suppressed_by_roster_resolution_id",
                ),
            )
            for row in source.recipients
        ],
        "source": source.snapshot["preview_revision"],
        "blocked_phones": sorted(source.blocked_phones),
        "mobile": None
        if mobile is None
        else {
            "access": [mobile.access.id, mobile.access.revision],
            "existing": [
                _values(
                    row,
                    (
                        "id",
                        "passenger_submission_id",
                        "normalized_phone_number",
                        "secondary_factor_type",
                        "secondary_factor_hash",
                        "is_shared_number",
                        "requires_secondary_verification",
                        "status",
                        "claim_generation",
                    ),
                )
                for row in mobile.existing
            ],
            "desired": [
                [
                    row.passenger_submission_id,
                    row.normalized_phone,
                    row.is_shared_number,
                    row.requires_secondary_verification,
                    row.secondary_factor_type,
                    row.secondary_factor_value,
                ]
                for row in mobile.plan.candidates
            ],
        },
    }
    return hashlib.sha256(
        json.dumps(data, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def _bounded(
    session: AsyncSession, statement: Any, maximum: int = MAX_SOURCE_ROWS
) -> list[Any]:
    rows = list(
        (
            await session.scalars(
                statement.limit(maximum + 1).execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(rows) > maximum:
        raise MCPOperationError("broadcast_link_scope_too_large")
    return rows


async def load_link_source(
    context: MCPDatabaseContext,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    broadcast_id: uuid.UUID,
) -> BroadcastLinkSource:
    session = context.session
    actor = await require_change_actor(context, agency_id)
    group = await require_change_group(context, actor, group_id, agency_id, exclusive=True)
    if group.status == "archived":
        raise MCPOperationError("broadcast_link_unavailable")
    links = await _bounded(
        session,
        select(ClientGroupWhatsAppBroadcastLinkModel)
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
        )
        .order_by(ClientGroupWhatsAppBroadcastLinkModel.id),
        MAX_LINKS,
    )
    broadcast = await session.scalar(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.agency_id == agency_id,
            WhatsAppBroadcastGroupModel.id == broadcast_id,
            WhatsAppBroadcastGroupModel.archived_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if broadcast is None:
        raise MCPOperationError("broadcast_link_unavailable")
    recipients = await _bounded(
        session,
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.agency_id == agency_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id == broadcast_id,
        )
        .order_by(WhatsAppBroadcastRecipientModel.id)
        .with_for_update(),
    )
    contacts = await _bounded(
        session,
        select(WhatsAppBroadcastSourceContactModel)
        .where(
            WhatsAppBroadcastSourceContactModel.agency_id == agency_id,
            WhatsAppBroadcastSourceContactModel.broadcast_group_id == broadcast_id,
        )
        .order_by(WhatsAppBroadcastSourceContactModel.id)
        .with_for_update(),
    )
    statement = (
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        )
        .order_by(PassportSubmissionModel.created_at, PassportSubmissionModel.id)
    )
    all_submissions = await _bounded(session, statement)
    operational = await _bounded(session, statement.where(operational_roster_member()))
    snapshot = build_source_contacts(
        group_id, group.name, operational, import_only=group.import_only
    )
    overrides = await session.scalar(
        select(WhatsAppTravellerPhoneOverrideModel.id)
        .where(
            WhatsAppTravellerPhoneOverrideModel.agency_id == agency_id,
            WhatsAppTravellerPhoneOverrideModel.group_id == group_id,
            WhatsAppTravellerPhoneOverrideModel.broadcast_group_id == broadcast_id,
        )
        .limit(1)
    )
    if overrides is not None:
        raise MCPOperationError("broadcast_link_retained_override")
    # Include the proposed source link when deciding whether a new link would
    # suppress an existing recipient under canonical replacement policy.
    linked = select(ClientGroupWhatsAppBroadcastLinkModel.client_group_id).where(
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == broadcast_id,
    )
    resolutions = await _bounded(
        session,
        select(PassportRosterResolutionModel)
        .where(
            PassportRosterResolutionModel.agency_id == agency_id,
            PassportRosterResolutionModel.status == "active",
            PassportRosterResolutionModel.resolution_type == "replacement",
            or_(
                PassportRosterResolutionModel.client_group_id == group_id,
                PassportRosterResolutionModel.client_group_id.in_(linked),
            ),
        )
        .order_by(PassportRosterResolutionModel.id),
    )
    mobile = await prepare_additive_mobile_plan(
        session,
        agency_id=agency_id,
        group_id=group_id,
        submissions=all_submissions,
        maximum=MAX_SOURCE_ROWS,
    )
    return BroadcastLinkSource(
        group,
        broadcast,
        links,
        contacts,
        recipients,
        snapshot,
        mobile,
        {
            row.replaced_recipient_normalized_phone
            for row in resolutions
            if row.replaced_recipient_normalized_phone
        },
    )
