"""Fresh, bounded passenger and delivery reads materialized before rollback."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, PassportSubmission
from app.infrastructure.database.models import (
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.export.whatsapp_filter_excel_exporter import (
    MAX_EXPORT_ROWS,
    WhatsAppExportTooLarge,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.routes.passport_export_support import (
    _export_whatsapp_contacts,
    _export_zone_names_from_match_rows,
)
from app.presentation.api.v1.routes.whatsapp_export_sources import ExportSources
from app.presentation.api.v1.routes.whatsapp_export_support import (
    _SOURCE_QUERY_BATCH,
    _latest_attempt_values,
    _SourceKey,
    _stale_rows,
)
from app.presentation.api.v1.routes.whatsapp_merged_contacts import merged_contacts_by_recipient
from app.presentation.api.v1.routes.whatsapp_shared import (
    _recipient_delivery_state_maps,
    _recipient_response,
)
from app.presentation.api.v1.schemas.whatsapp_export_schemas import WhatsAppFilterExportRequest
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppMergedContactResponse,
    WhatsAppRecipientResponse,
)


@dataclass(frozen=True)
class HydratedExportSources:
    entities: dict[_SourceKey, PassportSubmission]
    source_contacts: dict[uuid.UUID, dict[str, str | None]]
    source_zones: dict[uuid.UUID, str]


@dataclass(frozen=True)
class ExportDelivery:
    recipients: dict[uuid.UUID, WhatsAppRecipientResponse]
    merged_contacts: dict[uuid.UUID, list[WhatsAppMergedContactResponse]]
    latest_attempts: dict[uuid.UUID, dict[str, Any]]


async def hydrate_export_sources(
    session: AsyncSession,
    broadcast: WhatsAppBroadcastGroupModel,
    sources: ExportSources,
) -> HydratedExportSources:
    required_sources = sources.required_sources
    displaced_source_keys = sources.displaced_source_keys
    current_source_keys = sources.current_source_keys
    match_rows_by_group = sources.match_rows_by_group
    if len(required_sources) > MAX_EXPORT_ROWS:
        raise WhatsAppExportTooLarge(
            "This filter expands to more than 20,000 source travellers. Narrow the filter and export again."
        )
    submissions: list[PassportSubmissionModel] = []
    ordered_keys = sorted(required_sources, key=lambda key: (str(key[0]), str(key[1])))
    for start in range(0, len(ordered_keys), _SOURCE_QUERY_BATCH):
        keys = ordered_keys[start : start + _SOURCE_QUERY_BATCH]
        submissions.extend(
            (
                await session.execute(
                    select(PassportSubmissionModel).where(
                        PassportSubmissionModel.agency_id == broadcast.agency_id,
                        PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
                        tuple_(PassportSubmissionModel.group_id, PassportSubmissionModel.id).in_(
                            keys
                        ),
                        or_(
                            operational_roster_member(),
                            tuple_(
                                PassportSubmissionModel.group_id, PassportSubmissionModel.id
                            ).in_((displaced_source_keys - current_source_keys) & set(keys)),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
    entities = {
        (row.group_id, row.id): PassportSubmissionRepository._to_entity(row) for row in submissions
    }
    if set(entities) != required_sources:
        raise _stale_rows()
    source_contacts = _export_whatsapp_contacts(list(entities.values()), match_rows_by_group)
    source_zones = _export_zone_names_from_match_rows(list(entities.values()), match_rows_by_group)
    return HydratedExportSources(entities, source_contacts, source_zones)


async def load_export_delivery(
    session: AsyncSession,
    broadcast: WhatsAppBroadcastGroupModel,
    body: WhatsAppFilterExportRequest,
    selected_recipient_ids: set[uuid.UUID],
) -> ExportDelivery:
    recipient_models = (
        list(
            (
                await session.execute(
                    select(WhatsAppBroadcastRecipientModel).where(
                        WhatsAppBroadcastRecipientModel.broadcast_group_id == broadcast.id,
                        WhatsAppBroadcastRecipientModel.agency_id == broadcast.agency_id,
                        WhatsAppBroadcastRecipientModel.id.in_(selected_recipient_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        if selected_recipient_ids
        else []
    )
    recipient_models_by_id = {row.id: row for row in recipient_models}
    if set(recipient_models_by_id) != selected_recipient_ids:
        raise _stale_rows()
    if any(
        (item.kind == "recipient" and recipient_models_by_id[item.id].removed_at is not None)
        or (item.kind == "replaced" and recipient_models_by_id[item.id].removed_at is None)
        for item in body.items
    ):
        raise _stale_rows()
    states, resends, phone_welcome_statuses = await _recipient_delivery_state_maps(
        session, recipient_models
    )
    recipients = {
        row.id: _recipient_response(
            row,
            states.get(row.id, []),
            resends.get(row.id, {}),
            phone_welcome_statuses=phone_welcome_statuses,
        )
        for row in recipient_models
    }
    merged_contacts = await merged_contacts_by_recipient(
        session,
        agency_id=broadcast.agency_id,
        broadcast_group_id=broadcast.id,
    )
    latest_attempts = await _latest_attempt_values(session, broadcast, selected_recipient_ids)
    return ExportDelivery(recipients, merged_contacts, latest_attempts)
