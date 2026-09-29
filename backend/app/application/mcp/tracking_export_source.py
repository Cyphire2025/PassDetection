"""Bounded locks around the website tracking comparison inputs."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError
from app.domain.entities.entities import ClientGroup, PassportSubmission, User
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)

MAX_TRACKING_ROWS = 1500
MAX_TRACKING_BROADCASTS = 100


async def linked_broadcasts(session: AsyncSession, group: ClientGroup) -> list[uuid.UUID]:
    identifiers = list(
        (
            await session.scalars(
                select(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
                .join(
                    WhatsAppBroadcastGroupModel,
                    WhatsAppBroadcastGroupModel.id
                    == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
                )
                .where(
                    ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
                    ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
                    WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
                )
                .order_by(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
                .limit(MAX_TRACKING_BROADCASTS + 1)
            )
        ).all()
    )
    if len(identifiers) > MAX_TRACKING_BROADCASTS:
        raise ArtifactError("Tracking exceeds the linked broadcast limit", 413)
    return identifiers


async def lock_tracking_source(
    session: AsyncSession, *, actor: User, group: ClientGroup, broadcasts: list[uuid.UUID]
) -> list[PassportSubmission]:
    # Caller holds group UPDATE, which fences new group-linked rows. Broadcast
    # UPDATE then fences recipient insertions; NOWAIT avoids old writer order cycles.
    await session.execute(
        select(WhatsAppBroadcastGroupModel.id)
        .where(
            WhatsAppBroadcastGroupModel.id.in_(broadcasts),
            WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
        )
        .order_by(WhatsAppBroadcastGroupModel.id)
        .with_for_update(nowait=True)
    )
    await session.execute(
        select(ClientGroupWhatsAppBroadcastLinkModel)
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
        )
        .order_by(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
        .limit(MAX_TRACKING_BROADCASTS + 1)
        .with_for_update(read=True, nowait=True)
        .execution_options(populate_existing=True)
    )
    # Removed recipients may still be referenced by a retained replacement;
    # bound and lock them too instead of silently losing resolved tracking rows.
    queries = (
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(broadcasts),
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
        )
        .order_by(WhatsAppBroadcastRecipientModel.id),
        select(PassportRosterResolutionModel)
        .where(
            PassportRosterResolutionModel.client_group_id == group.id,
            PassportRosterResolutionModel.agency_id == group.agency_id,
            PassportRosterResolutionModel.status == "active",
        )
        .order_by(PassportRosterResolutionModel.id),
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == group.agency_id,
        )
        .order_by(PassportSubmissionModel.id),
    )
    for query in queries:
        rows = (
            await session.scalars(
                query.limit(MAX_TRACKING_ROWS + 1)
                .with_for_update(read=True, nowait=True)
                .execution_options(populate_existing=True)
            )
        ).all()
        if len(rows) > MAX_TRACKING_ROWS:
            raise ArtifactError("Tracking exceeds the source row limit", 413)
    # Keep the website repository's eligibility and ordering. The bound above
    # covers every underlying submission, including resolutions' excluded rows.
    return await PassportSubmissionRepository(session).list_by_group(
        group.agency_id,
        group.id,
        limit=MAX_TRACKING_ROWS + 1,
        exclude_archived_groups=True,
        visible_to_user=actor,
    )
