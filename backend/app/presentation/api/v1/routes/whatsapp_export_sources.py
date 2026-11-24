"""Durable, displaced and unidentified passenger provenance for one export."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import SubmissionMatchRow
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportRosterResolutionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSourceContactModel,
)
from app.infrastructure.export.whatsapp_filter_excel_exporter import (
    MAX_EXPORT_ROWS,
    WhatsAppExportTooLarge,
)
from app.presentation.api.v1.routes.whatsapp_export_selection import ExportSelection
from app.presentation.api.v1.routes.whatsapp_export_support import (
    _SOURCE_QUERY_BATCH,
    _SourceKey,
    _stale_rows,
)
from app.presentation.api.v1.schemas.whatsapp_export_schemas import WhatsAppFilterExportRequest
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppRecipientRosterItemResponse


@dataclass(frozen=True)
class ExportSources:
    """Source keys retain current versus explicitly displaced provenance."""

    source_by_key: dict[_SourceKey, WhatsAppBroadcastSourceContactModel]
    sources_by_recipient: dict[uuid.UUID, list[_SourceKey]]
    required_sources: set[_SourceKey]
    current_source_keys: set[_SourceKey]
    displaced_source_keys: set[_SourceKey]
    match_rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]]
    matched_source_keys: set[_SourceKey]


async def load_durable_sources(
    body: WhatsAppFilterExportRequest,
    broadcast: WhatsAppBroadcastGroupModel,
    selection: ExportSelection,
    session: AsyncSession,
) -> ExportSources:
    groups = selection.groups
    source_visible_ids = selection.source_visible_ids
    selected_recipient_ids = selection.selected_recipient_ids
    # Durable associations retain distinct travellers even when they share a number.
    sources_statement = (
        select(WhatsAppBroadcastSourceContactModel)
        .where(
            WhatsAppBroadcastSourceContactModel.broadcast_group_id == broadcast.id,
            WhatsAppBroadcastSourceContactModel.agency_id == broadcast.agency_id,
        )
        .order_by(
            WhatsAppBroadcastSourceContactModel.created_at, WhatsAppBroadcastSourceContactModel.id
        )
    )
    if body.view == "travellers":
        sources_statement = sources_statement.where(
            WhatsAppBroadcastSourceContactModel.source_group_id.in_(source_visible_ids),
        )
    else:
        sources_statement = sources_statement.where(
            WhatsAppBroadcastSourceContactModel.source_group_id.in_(groups),
            WhatsAppBroadcastSourceContactModel.recipient_id.in_(
                {item.id for item in body.items if item.kind == "recipient"}
            ),
        )
    source_rows: list[WhatsAppBroadcastSourceContactModel] = []
    if body.view == "travellers":
        # asyncpg limits bind parameters. Two UUIDs per row must be batched even
        # when the complete 20,000-row request fits the export's output budget.
        source_queries = [
            sources_statement.where(
                tuple_(
                    WhatsAppBroadcastSourceContactModel.source_group_id,
                    WhatsAppBroadcastSourceContactModel.source_submission_id,
                ).in_(
                    [
                        (item.source_group_id, item.id)
                        for item in body.items[start : start + _SOURCE_QUERY_BATCH]
                    ]
                )
            )
            for start in range(0, len(body.items), _SOURCE_QUERY_BATCH)
        ]
    else:
        source_queries = [sources_statement]
    for statement in source_queries:
        source_rows.extend(
            (await session.execute(statement.limit(MAX_EXPORT_ROWS - len(source_rows) + 1)))
            .scalars()
            .all()
        )
        if len(source_rows) > MAX_EXPORT_ROWS:
            raise WhatsAppExportTooLarge(
                "This filter contains more than 20,000 source travellers. Narrow the filter and export again."
            )
    source_by_key = {(row.source_group_id, row.source_submission_id): row for row in source_rows}
    sources_by_recipient: dict[uuid.UUID, list[_SourceKey]] = defaultdict(list)
    required_sources: set[_SourceKey] = set(source_by_key)
    current_source_keys: set[_SourceKey] = set(source_by_key)
    displaced_source_keys: set[_SourceKey] = set()
    match_rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]] = {}
    matched_source_keys: set[_SourceKey] = set()
    for source in source_rows:
        if source.recipient_id is not None:
            sources_by_recipient[source.recipient_id].append(
                (source.source_group_id, source.source_submission_id)
            )
            if body.view == "travellers":
                selected_recipient_ids.add(source.recipient_id)
    if body.view == "travellers" and any(
        (item.source_group_id, item.id) not in source_by_key for item in body.items
    ):
        raise _stale_rows()
    return ExportSources(
        source_by_key,
        sources_by_recipient,
        required_sources,
        current_source_keys,
        displaced_source_keys,
        match_rows_by_group,
        matched_source_keys,
    )


async def add_displaced_sources(
    body: WhatsAppFilterExportRequest,
    broadcast: WhatsAppBroadcastGroupModel,
    groups: dict[uuid.UUID, ClientGroupModel],
    session: AsyncSession,
    sources: ExportSources,
) -> None:
    sources_by_recipient = sources.sources_by_recipient
    required_sources = sources.required_sources
    displaced_source_keys = sources.displaced_source_keys
    replaced_ids = {item.id for item in body.items if item.kind == "replaced"}
    if replaced_ids:
        # A replacement's new traveller is not the original recipient. Only
        # explicitly recorded displaced submissions may enrich the old row.
        resolutions = (
            await session.execute(
                select(
                    WhatsAppBroadcastRecipientModel.id,
                    PassportRosterResolutionModel,
                )
                .join(
                    PassportRosterResolutionModel,
                    WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id
                    == PassportRosterResolutionModel.id,
                )
                .where(
                    WhatsAppBroadcastRecipientModel.id.in_(replaced_ids),
                    WhatsAppBroadcastRecipientModel.broadcast_group_id == broadcast.id,
                    WhatsAppBroadcastRecipientModel.agency_id == broadcast.agency_id,
                    PassportRosterResolutionModel.agency_id == broadcast.agency_id,
                    PassportRosterResolutionModel.client_group_id.in_(groups),
                    PassportRosterResolutionModel.status == "active",
                    PassportRosterResolutionModel.resolution_type == "replacement",
                )
            )
        ).all()
        for recipient_id, resolution in resolutions:
            for stored_id in resolution.excluded_submission_ids or []:
                try:
                    key = (resolution.client_group_id, uuid.UUID(str(stored_id)))
                except (ValueError, TypeError):
                    continue
                if key not in sources_by_recipient[recipient_id]:
                    sources_by_recipient[recipient_id].append(key)
                    required_sources.add(key)
                    displaced_source_keys.add(key)


def add_unidentified_sources(
    body: WhatsAppFilterExportRequest,
    roster_by_id: dict[tuple[str, uuid.UUID], WhatsAppRecipientRosterItemResponse],
    groups: dict[uuid.UUID, ClientGroupModel],
    sources: ExportSources,
) -> None:
    required_sources = sources.required_sources
    current_source_keys = sources.current_source_keys
    for item in body.items:
        if item.kind != "unidentified":
            continue
        upload = roster_by_id[(item.kind, item.id)].unidentified_upload
        assert upload is not None
        if upload.client_group_id not in groups:
            raise _stale_rows()
        required_sources.add((upload.client_group_id, upload.submission_id))
        current_source_keys.add((upload.client_group_id, upload.submission_id))
