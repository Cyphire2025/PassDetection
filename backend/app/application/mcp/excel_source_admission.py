"""Complete canonical passport Excel source families, admitted before ORM reads."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.application.mcp.export_source_budget import ExportSourceBudget
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportExportHistoryModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.passport_ecr_models import PassportEcrCheckModel


async def admit_excel_sources(
    budget: ExportSourceBudget,
    *,
    agency_id: uuid.UUID,
    group_ids: list[uuid.UUID],
    submission_ids: list[uuid.UUID] | None,
    baseline_export_id: uuid.UUID | None,
) -> None:
    """Caller owns group UPDATE locks and already charged their complete columns.

Groups -> broadcasts -> links -> recipients -> passports -> resolutions/ECR.
NOWAIT avoids cycles with existing delivery and roster writers. Removed/draft
rows count conservatively: an update cannot add an unmeasured row to a helper's
later status-filtered read. Operational resolution JSON stays database-side.
"""
    links = ClientGroupWhatsAppBroadcastLinkModel
    linked = select(links.broadcast_group_id).where(
        links.client_group_id.in_(group_ids), links.agency_id == agency_id
    )
    broadcasts = await budget.retain(
        WhatsAppBroadcastGroupModel,
        WhatsAppBroadcastGroupModel.id.in_(linked),
        WhatsAppBroadcastGroupModel.agency_id == agency_id,
        update=True,
    )
    await budget.retain(links, links.client_group_id.in_(group_ids), links.agency_id == agency_id)
    if broadcasts:
        await budget.retain(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(broadcasts),
            WhatsAppBroadcastRecipientModel.agency_id == agency_id,
        )
    predicates: list[Any] = [
        PassportSubmissionModel.agency_id == agency_id,
        PassportSubmissionModel.group_id.in_(group_ids),
    ]
    if submission_ids is not None:
        predicates.append(PassportSubmissionModel.id.in_(submission_ids))
    passports = await budget.retain(PassportSubmissionModel, *predicates, update=True)
    await budget.retain(
        PassportRosterResolutionModel,
        PassportRosterResolutionModel.agency_id == agency_id,
        PassportRosterResolutionModel.client_group_id.in_(group_ids),
    )
    if passports:
        await budget.retain(AgencyModel, AgencyModel.id == agency_id)
        await budget.retain(
            PassportEcrCheckModel, PassportEcrCheckModel.submission_id.in_(passports)
        )
    if baseline_export_id is not None:
        await budget.retain(
            PassportExportHistoryModel,
            PassportExportHistoryModel.id == baseline_export_id,
            PassportExportHistoryModel.agency_id == agency_id,
            PassportExportHistoryModel.group_id.in_(group_ids),
        )
