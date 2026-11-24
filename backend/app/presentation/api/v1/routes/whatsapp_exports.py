"""Excel exports of exact broadcast filter snapshots, without state changes."""

from __future__ import annotations

import asyncio as asyncio
import re as re
import uuid as uuid
from collections import defaultdict as defaultdict
from typing import Any as Any
from urllib.parse import quote as quote

from fastapi import APIRouter as APIRouter
from fastapi import Depends as Depends
from fastapi import HTTPException as HTTPException
from fastapi import Response as Response
from sqlalchemy import func as func
from sqlalchemy import or_ as or_
from sqlalchemy import select as select
from sqlalchemy import tuple_ as tuple_
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy as AuthorizationPolicy
from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow as SubmissionMatchRow,
)
from app.application.use_cases.whatsapp.source_group_contacts import (
    _raw_source_phone as _raw_source_phone,
)
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES as OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
)
from app.domain.entities.entities import User as User
from app.domain.exceptions.exceptions import AuthorizationError as AuthorizationError
from app.infrastructure.database.models import ClientGroupModel as ClientGroupModel
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel as ClientGroupWhatsAppBroadcastLinkModel,
)
from app.infrastructure.database.models import (
    PassportRosterResolutionModel as PassportRosterResolutionModel,
)
from app.infrastructure.database.models import PassportSubmissionModel as PassportSubmissionModel
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel as WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel as WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastSourceContactModel as WhatsAppBroadcastSourceContactModel,
)
from app.infrastructure.database.models import WhatsAppMessageLogModel as WhatsAppMessageLogModel
from app.infrastructure.database.models import (
    WhatsAppTravellerPhoneOverrideModel as WhatsAppTravellerPhoneOverrideModel,
)
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.export.whatsapp_filter_excel_exporter import (
    MAX_EXPORT_ROWS as MAX_EXPORT_ROWS,
)
from app.infrastructure.export.whatsapp_filter_excel_exporter import (
    WhatsAppExportRow as WhatsAppExportRow,
)
from app.infrastructure.export.whatsapp_filter_excel_exporter import (
    WhatsAppExportTooLarge as WhatsAppExportTooLarge,
)
from app.infrastructure.export.whatsapp_filter_excel_exporter import (
    build_whatsapp_filter_workbook as build_whatsapp_filter_workbook,
)
from app.infrastructure.repositories.operational_roster import (
    operational_roster_member as operational_roster_member,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository as PassportSubmissionRepository,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context as load_unresolved_passport_whatsapp_match_context,
)
from app.infrastructure.whatsapp.phone_overrides import (
    load_valid_traveller_phone_overrides as load_valid_traveller_phone_overrides,
)
from app.presentation.api.v1.response_contracts import XLSX as XLSX
from app.presentation.api.v1.response_contracts import binary_responses as binary_responses
from app.presentation.api.v1.routes.passport_export_support import (
    _WHATSAPP_EMAIL_IMPORTED_KEYS as _WHATSAPP_EMAIL_IMPORTED_KEYS,
)
from app.presentation.api.v1.routes.passport_export_support import (
    _export_whatsapp_contacts as _export_whatsapp_contacts,
)
from app.presentation.api.v1.routes.passport_export_support import (
    _export_zone_names_from_match_rows as _export_zone_names_from_match_rows,
)
from app.presentation.api.v1.routes.passport_export_support import (
    _group_export_details as _group_export_details,
)
from app.presentation.api.v1.routes.passport_export_support import (
    _imported_zone_name as _imported_zone_name,
)
from app.presentation.api.v1.routes.passport_export_support import (
    _normalized_imported_field_key as _normalized_imported_field_key,
)
from app.presentation.api.v1.routes.whatsapp_export_hydration import (
    hydrate_export_sources as hydrate_export_sources,
)
from app.presentation.api.v1.routes.whatsapp_export_hydration import (
    load_export_delivery as load_export_delivery,
)
from app.presentation.api.v1.routes.whatsapp_export_matching import (
    add_manual_match_sources as add_manual_match_sources,
)
from app.presentation.api.v1.routes.whatsapp_export_matching import (
    add_phone_override_sources as add_phone_override_sources,
)
from app.presentation.api.v1.routes.whatsapp_export_projection import (
    project_export_rows as project_export_rows,
)
from app.presentation.api.v1.routes.whatsapp_export_selection import (
    select_export_rows as select_export_rows,
)
from app.presentation.api.v1.routes.whatsapp_export_sources import (
    add_displaced_sources as add_displaced_sources,
)
from app.presentation.api.v1.routes.whatsapp_export_sources import (
    add_unidentified_sources as add_unidentified_sources,
)
from app.presentation.api.v1.routes.whatsapp_export_sources import (
    load_durable_sources as load_durable_sources,
)
from app.presentation.api.v1.routes.whatsapp_export_support import (
    _MESSAGE_LABELS as _MESSAGE_LABELS,
)
from app.presentation.api.v1.routes.whatsapp_export_support import _MIME as _MIME
from app.presentation.api.v1.routes.whatsapp_export_support import (
    _SOURCE_QUERY_BATCH as _SOURCE_QUERY_BATCH,
)
from app.presentation.api.v1.routes.whatsapp_export_support import (
    _broadcast_import_contact_values as _broadcast_import_contact_values,
)
from app.presentation.api.v1.routes.whatsapp_export_support import (
    _delivery_values as _delivery_values,
)
from app.presentation.api.v1.routes.whatsapp_export_support import (
    _exportable_links as _exportable_links,
)
from app.presentation.api.v1.routes.whatsapp_export_support import (
    _latest_attempt_values as _latest_attempt_values,
)
from app.presentation.api.v1.routes.whatsapp_export_support import (
    _roster_identity as _roster_identity,
)
from app.presentation.api.v1.routes.whatsapp_export_support import _SourceKey as _SourceKey
from app.presentation.api.v1.routes.whatsapp_export_support import _stale_rows as _stale_rows
from app.presentation.api.v1.routes.whatsapp_merged_contacts import (
    merged_contacts_by_recipient as merged_contacts_by_recipient,
)
from app.presentation.api.v1.routes.whatsapp_recipient_roster import (
    get_broadcast_recipient_roster as get_broadcast_recipient_roster,
)
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES as WHATSAPP_ROLES
from app.presentation.api.v1.routes.whatsapp_shared import _agency_filter as _agency_filter
from app.presentation.api.v1.routes.whatsapp_shared import (
    _recipient_delivery_state_maps as _recipient_delivery_state_maps,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _recipient_response as _recipient_response,
)
from app.presentation.api.v1.schemas.whatsapp_export_schemas import (
    WhatsAppFilterExportRequest as WhatsAppFilterExportRequest,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppRecipientResponse as WhatsAppRecipientResponse,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppRecipientRosterItemResponse as WhatsAppRecipientRosterItemResponse,
)
from app.presentation.dependencies.auth import require_role as require_role
from app.presentation.dependencies.csrf import require_cookie_csrf as require_cookie_csrf

router = APIRouter()


async def _gather_export_rows(
    body: WhatsAppFilterExportRequest,
    broadcast: WhatsAppBroadcastGroupModel,
    user: User,
    session: AsyncSession,
) -> list[WhatsAppExportRow]:
    selection = await select_export_rows(body, broadcast, user, session)
    sources = await load_durable_sources(body, broadcast, selection, session)
    if body.view == "delivery":
        overrides = await add_phone_override_sources(
            session,
            broadcast,
            selection.groups,
            selection.selected_recipient_ids,
            sources,
        )
        await add_manual_match_sources(
            session,
            broadcast,
            selection.links,
            selection.selected_recipient_ids,
            overrides,
            sources,
        )
        await add_displaced_sources(body, broadcast, selection.groups, session, sources)
        add_unidentified_sources(body, selection.roster_by_id, selection.groups, sources)
    hydrated = await hydrate_export_sources(session, broadcast, sources)
    delivery = await load_export_delivery(
        session, broadcast, body, selection.selected_recipient_ids
    )
    return project_export_rows(
        body,
        broadcast,
        selection.groups,
        selection.roster_by_id,
        sources,
        hydrated,
        delivery,
    )


@router.post(
    "/groups/{group_id}/export",
    dependencies=[Depends(require_cookie_csrf)],
    response_class=Response,
    responses=binary_responses(XLSX),
)
async def export_broadcast_filter(
    group_id: uuid.UUID,
    body: WhatsAppFilterExportRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    broadcast = (
        await session.execute(
            select(WhatsAppBroadcastGroupModel).where(
                WhatsAppBroadcastGroupModel.id == group_id,
                *_agency_filter(current_user),
            )
        )
    ).scalar_one_or_none()
    if broadcast is None:
        raise HTTPException(404, "WhatsApp broadcast group not found")
    filename_parts = [broadcast.name[:80], body.filter_label[:60], body.view]
    if body.message_type:
        filename_parts.append(body.message_type)
    filename = (
        re.sub(r"[^\w .-]", "_", "-".join(filename_parts)).strip(" .")[:180] or "broadcast-export"
    )
    try:
        rows = await _gather_export_rows(body, broadcast, current_user, session)
        # This endpoint never calls passport export-history, mutation or send APIs.
        # Release the read transaction before serializing detached values off-loop.
        await session.rollback()
        content = await asyncio.to_thread(build_whatsapp_filter_workbook, rows)
    except WhatsAppExportTooLarge as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(
        content,
        media_type=_MIME,
        headers={
            "Content-Disposition": f"attachment; filename=\"broadcast-export.xlsx\"; filename*=UTF-8''{quote(filename + '.xlsx')}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
