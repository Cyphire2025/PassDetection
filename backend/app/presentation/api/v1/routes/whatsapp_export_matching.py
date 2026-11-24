"""Exact phone corrections and configured manual-group matching provenance."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppTravellerPhoneOverrideModel,
)
from app.infrastructure.export.whatsapp_filter_excel_exporter import (
    MAX_EXPORT_ROWS,
    WhatsAppExportTooLarge,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context,
)
from app.infrastructure.whatsapp.phone_overrides import load_valid_traveller_phone_overrides
from app.presentation.api.v1.routes.whatsapp_export_sources import ExportSources


async def add_phone_override_sources(
    session: AsyncSession,
    broadcast: WhatsAppBroadcastGroupModel,
    groups: dict[uuid.UUID, ClientGroupModel],
    selected_recipient_ids: set[uuid.UUID],
    sources: ExportSources,
) -> dict[tuple[uuid.UUID, uuid.UUID], WhatsAppBroadcastRecipientModel]:
    sources_by_recipient = sources.sources_by_recipient
    required_sources = sources.required_sources
    current_source_keys = sources.current_source_keys
    overrides = await load_valid_traveller_phone_overrides(
        session,
        agency_id=broadcast.agency_id,
        broadcast_group_ids={broadcast.id},
        require_active_groups=False,
    )
    override_sources = (
        (
            await session.execute(
                select(
                    WhatsAppTravellerPhoneOverrideModel.group_id,
                    WhatsAppTravellerPhoneOverrideModel.passenger_id,
                ).where(
                    WhatsAppTravellerPhoneOverrideModel.agency_id == broadcast.agency_id,
                    WhatsAppTravellerPhoneOverrideModel.broadcast_group_id == broadcast.id,
                    WhatsAppTravellerPhoneOverrideModel.group_id.in_(groups),
                )
            )
        ).all()
        if overrides
        else []
    )
    for source_group_id, passenger_id in override_sources:
        target = overrides.get((broadcast.id, passenger_id))
        if target is None or target.id not in selected_recipient_ids:
            continue
        key = (source_group_id, passenger_id)
        if key not in sources_by_recipient[target.id]:
            sources_by_recipient[target.id].append(key)
        required_sources.add(key)
        current_source_keys.add(key)
    return overrides


async def add_manual_match_sources(
    session: AsyncSession,
    broadcast: WhatsAppBroadcastGroupModel,
    links: list[tuple[ClientGroupModel, ClientGroupWhatsAppBroadcastLinkModel]],
    selected_recipient_ids: set[uuid.UUID],
    overrides: dict[tuple[uuid.UUID, uuid.UUID], WhatsAppBroadcastRecipientModel],
    sources: ExportSources,
) -> None:
    sources_by_recipient = sources.sources_by_recipient
    required_sources = sources.required_sources
    current_source_keys = sources.current_source_keys
    match_rows_by_group = sources.match_rows_by_group
    matched_source_keys = sources.matched_source_keys
    manual_groups = [
        group for group, link in links if not (group.import_only or link.sync_contacts_from_group)
    ]
    if selected_recipient_ids and manual_groups:
        count = (
            await session.execute(
                select(func.count())
                .select_from(PassportSubmissionModel)
                .where(
                    PassportSubmissionModel.agency_id == broadcast.agency_id,
                    PassportSubmissionModel.group_id.in_([group.id for group in manual_groups]),
                    PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
                )
            )
        ).scalar_one()
        if count > MAX_EXPORT_ROWS:
            raise WhatsAppExportTooLarge(
                "The linked groups contain more than 20,000 travellers. Export a smaller source group from the Travellers view."
            )
        for group in manual_groups:
            (
                _broadcasts,
                _recipients,
                _submissions,
                match_rows,
            ) = await load_unresolved_passport_whatsapp_match_context(
                session,
                group_id=group.id,
                agency_id=broadcast.agency_id,
                broadcast_group_ids=[broadcast.id],
            )
            match_rows_by_group[group.id] = match_rows
            for match in match_rows:
                if match.status not in {"submitted", "multiple_submissions"}:
                    continue
                for recipient_id in set(match.recipient_ids) & selected_recipient_ids:
                    for submission_id in match.submission_ids:
                        corrected = overrides.get((broadcast.id, submission_id))
                        if corrected is not None and corrected.id != recipient_id:
                            continue
                        key = (group.id, submission_id)
                        matched_source_keys.add(key)
                        if key not in sources_by_recipient[recipient_id]:
                            sources_by_recipient[recipient_id].append(key)
                            required_sources.add(key)
                            current_source_keys.add(key)
