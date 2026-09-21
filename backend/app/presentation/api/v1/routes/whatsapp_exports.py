"""Excel exports of exact broadcast filter snapshots, without state changes."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections import defaultdict
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.whatsapp.group_submission_matching import SubmissionMatchRow
from app.application.use_cases.whatsapp.source_group_contacts import _raw_source_phone
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.whatsapp_filter_excel_exporter import (
    MAX_EXPORT_ROWS,
    WhatsAppExportRow,
    WhatsAppExportTooLarge,
    build_whatsapp_filter_workbook,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.infrastructure.repositories.passport_submission_repository import PassportSubmissionRepository
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context,
)
from app.presentation.api.v1.routes.passport_export_support import (
    _WHATSAPP_EMAIL_IMPORTED_KEYS,
    _export_whatsapp_contacts,
    _export_zone_names_from_match_rows,
    _group_export_details,
    _imported_zone_name,
    _normalized_imported_field_key,
)
from app.presentation.api.v1.routes.whatsapp_recipient_roster import get_broadcast_recipient_roster
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ROLES,
    _agency_filter,
    _recipient_delivery_state_maps,
    _recipient_response,
)
from app.presentation.api.v1.schemas.whatsapp_export_schemas import WhatsAppFilterExportRequest
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppRecipientResponse,
    WhatsAppRecipientRosterItemResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MESSAGE_LABELS = {
    "welcome": "Welcome", "passport_link": "Passport link",
    "reminder": "Reminder", "group_invite": "Group invite",
}
_SourceKey = tuple[uuid.UUID, uuid.UUID]
_SOURCE_QUERY_BATCH = 1_000


def _stale_rows() -> HTTPException:
    return HTTPException(409, "One or more export rows changed or are not accessible. Refresh the roster and export again.")


def _roster_identity(row: WhatsAppRecipientRosterItemResponse) -> tuple[str, uuid.UUID]:
    if row.recipient is not None:
        return "recipient", row.recipient.id
    if row.rejected_contact is not None:
        return "rejected", row.rejected_contact.id
    if row.replaced_recipient is not None:
        return "replaced", row.replaced_recipient.recipient_id
    assert row.unidentified_upload is not None
    return "unidentified", row.unidentified_upload.submission_id


async def _exportable_links(
    session: AsyncSession, broadcast: WhatsAppBroadcastGroupModel, user: User,
) -> list[tuple[ClientGroupModel, ClientGroupWhatsAppBroadcastLinkModel]]:
    statement = select(ClientGroupModel, ClientGroupWhatsAppBroadcastLinkModel).join(
        ClientGroupWhatsAppBroadcastLinkModel,
        ClientGroupWhatsAppBroadcastLinkModel.client_group_id == ClientGroupModel.id,
    ).where(
        ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == broadcast.id,
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == broadcast.agency_id,
        ClientGroupModel.agency_id == broadcast.agency_id,
        ClientGroupModel.deleted_at.is_(None),
    ).order_by(ClientGroupModel.name, ClientGroupModel.id)
    rows = (await session.execute(
        AuthorizationPolicy.apply_group_visibility_scope(statement, user)
    )).all()
    policy = AuthorizationPolicy(session)
    result = []
    for group, link in rows:
        try:
            await policy.require_export_data(user, group)
        except AuthorizationError:
            continue
        result.append((group, link))
    return result


async def _latest_attempt_values(
    session: AsyncSession, broadcast: WhatsAppBroadcastGroupModel, recipient_ids: set[uuid.UUID],
) -> dict[uuid.UUID, dict[str, Any]]:
    if not recipient_ids:
        return {}
    # Select scalars only: media IDs, bodies and tokens never enter this export.
    ranked = select(
        WhatsAppMessageLogModel.recipient_id, WhatsAppMessageLogModel.message_type,
        WhatsAppMessageLogModel.status, WhatsAppMessageLogModel.error_message,
        WhatsAppMessageLogModel.created_at, WhatsAppMessageLogModel.template_name,
        WhatsAppMessageLogModel.normalized_phone_number,
        func.row_number().over(
            partition_by=(WhatsAppMessageLogModel.recipient_id, WhatsAppMessageLogModel.message_type),
            order_by=(WhatsAppMessageLogModel.created_at.desc(), WhatsAppMessageLogModel.id.desc()),
        ).label("position"),
    ).where(
        WhatsAppMessageLogModel.broadcast_group_id == broadcast.id,
        WhatsAppMessageLogModel.agency_id == broadcast.agency_id,
        WhatsAppMessageLogModel.recipient_id.in_(recipient_ids),
    ).subquery()
    result: dict[uuid.UUID, dict[str, Any]] = defaultdict(dict)
    for row in (await session.execute(select(ranked).where(ranked.c.position == 1))).all():
        label = _MESSAGE_LABELS.get(row.message_type, row.message_type)
        result[row.recipient_id].update({
            f"{label} latest attempt status": row.status,
            f"{label} latest attempt error": row.error_message,
            f"{label} latest attempt at": row.created_at,
            f"{label} latest attempt template": row.template_name,
            f"{label} latest attempt phone": row.normalized_phone_number,
        })
    return dict(result)


def _delivery_values(recipient: WhatsAppRecipientResponse | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    statuses = {state.message_type: state for state in recipient.message_statuses} if recipient else {}
    for message_type, label in _MESSAGE_LABELS.items():
        state = statuses.get(message_type)
        values[f"{label} status"] = state.status if state else "not_sent"
        values[f"{label} latest resend status"] = state.latest_resend_status if state else None
        values[f"{label} already sent"] = state.already_sent if state else False
        values[f"{label} resend blocked"] = state.resend_blocked if state else False
        values[f"{label} status updated at"] = state.status_updated_at if state else None
    return values


def _broadcast_import_contact_values(fields: dict[str, Any]) -> dict[str, Any]:
    """Unambiguous contact context for this exact broadcast row, never a phone match."""
    emails: dict[str, str] = {}
    for key, value in fields.items():
        if _normalized_imported_field_key(str(key)) not in _WHATSAPP_EMAIL_IMPORTED_KEYS:
            continue
        email = " ".join(str(value or "").strip().split())
        if email and email.casefold() not in {"null", "none", "n/a", "na"}:
            emails.setdefault(email.casefold(), email)
    return {
        "WhatsApp Email": next(iter(emails.values())) if len(emails) == 1 else None,
        "Zone Name": _imported_zone_name(fields),
    }


async def _gather_export_rows(
    body: WhatsAppFilterExportRequest, broadcast: WhatsAppBroadcastGroupModel,
    user: User, session: AsyncSession,
) -> list[WhatsAppExportRow]:
    links = await _exportable_links(session, broadcast, user)
    groups = {group.id: group for group, _link in links}
    source_visible_ids = {
        group.id for group, link in links
        if group.status == "active" and (group.import_only or link.sync_contacts_from_group)
    }
    roster_by_id: dict[tuple[str, uuid.UUID], WhatsAppRecipientRosterItemResponse] = {}
    selected_recipient_ids: set[uuid.UUID] = set()
    if body.view == "delivery":
        roster = await get_broadcast_recipient_roster(broadcast.id, user, session)
        roster_by_id = {_roster_identity(row): row for row in roster.items}
        if any((item.kind, item.id) not in roster_by_id for item in body.items):
            raise _stale_rows()
        selected_recipient_ids = {item.id for item in body.items if item.kind in {"recipient", "replaced"}}

    # Durable source associations retain shared numbers and non-sendable travellers.
    sources_statement = select(WhatsAppBroadcastSourceContactModel).where(
        WhatsAppBroadcastSourceContactModel.broadcast_group_id == broadcast.id,
        WhatsAppBroadcastSourceContactModel.agency_id == broadcast.agency_id,
    ).order_by(WhatsAppBroadcastSourceContactModel.created_at, WhatsAppBroadcastSourceContactModel.id)
    if body.view == "travellers":
        sources_statement = sources_statement.where(
            WhatsAppBroadcastSourceContactModel.source_group_id.in_(source_visible_ids),
        )
    else:
        sources_statement = sources_statement.where(
            WhatsAppBroadcastSourceContactModel.source_group_id.in_(groups),
            WhatsAppBroadcastSourceContactModel.recipient_id.in_(
                {item.id for item in body.items if item.kind == "recipient"}
            )
        )
    source_rows: list[WhatsAppBroadcastSourceContactModel] = []
    if body.view == "travellers":
        # asyncpg limits bind parameters. Two UUIDs per row must be batched even
        # when the complete 20,000-row request fits the export's output budget.
        source_queries = [sources_statement.where(tuple_(
            WhatsAppBroadcastSourceContactModel.source_group_id,
            WhatsAppBroadcastSourceContactModel.source_submission_id,
        ).in_([(item.source_group_id, item.id) for item in body.items[start:start + _SOURCE_QUERY_BATCH]]))
            for start in range(0, len(body.items), _SOURCE_QUERY_BATCH)]
    else:
        source_queries = [sources_statement]
    for statement in source_queries:
        source_rows.extend((await session.execute(
            statement.limit(MAX_EXPORT_ROWS - len(source_rows) + 1)
        )).scalars().all())
        if len(source_rows) > MAX_EXPORT_ROWS:
            raise WhatsAppExportTooLarge("This filter contains more than 20,000 source travellers. Narrow the filter and export again.")
    source_by_key = {(row.source_group_id, row.source_submission_id): row for row in source_rows}
    sources_by_recipient: dict[uuid.UUID, list[_SourceKey]] = defaultdict(list)
    required_sources: set[_SourceKey] = set(source_by_key)
    current_source_keys: set[_SourceKey] = set(source_by_key)
    displaced_source_keys: set[_SourceKey] = set()
    match_rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]] = {}
    matched_source_keys: set[_SourceKey] = set()
    for source in source_rows:
        if source.recipient_id is not None:
            sources_by_recipient[source.recipient_id].append((source.source_group_id, source.source_submission_id))
            if body.view == "travellers":
                selected_recipient_ids.add(source.recipient_id)
    if body.view == "travellers" and any(
        (item.source_group_id, item.id) not in source_by_key for item in body.items
    ):
        raise _stale_rows()

    if body.view == "delivery":
        # Normal manually linked groups have no durable source-contact rows. Use
        # their configured matching policy; ambiguous candidates are never exported.
        manual_groups = [group for group, link in links if not (group.import_only or link.sync_contacts_from_group)]
        if selected_recipient_ids and manual_groups:
            count = (await session.execute(select(func.count()).select_from(PassportSubmissionModel).where(
                PassportSubmissionModel.agency_id == broadcast.agency_id,
                PassportSubmissionModel.group_id.in_([group.id for group in manual_groups]),
                PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
            ))).scalar_one()
            if count > MAX_EXPORT_ROWS:
                raise WhatsAppExportTooLarge("The linked groups contain more than 20,000 travellers. Export a smaller source group from the Travellers view.")
            for group in manual_groups:
                _broadcasts, _recipients, _submissions, match_rows = await load_unresolved_passport_whatsapp_match_context(
                    session, group_id=group.id, agency_id=broadcast.agency_id,
                    broadcast_group_ids=[broadcast.id],
                )
                match_rows_by_group[group.id] = match_rows
                for match in match_rows:
                    if match.status not in {"submitted", "multiple_submissions"}:
                        continue
                    for recipient_id in set(match.recipient_ids) & selected_recipient_ids:
                        for submission_id in match.submission_ids:
                            key = (group.id, submission_id)
                            matched_source_keys.add(key)
                            if key not in sources_by_recipient[recipient_id]:
                                sources_by_recipient[recipient_id].append(key)
                                required_sources.add(key)
                                current_source_keys.add(key)
        replaced_ids = {item.id for item in body.items if item.kind == "replaced"}
        if replaced_ids:
            # A replacement's new traveller is not the original recipient. Only
            # explicitly recorded displaced submissions may enrich the old row.
            resolutions = (await session.execute(select(
                WhatsAppBroadcastRecipientModel.id, PassportRosterResolutionModel,
            ).join(PassportRosterResolutionModel,
                   WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id == PassportRosterResolutionModel.id,
            ).where(
                WhatsAppBroadcastRecipientModel.id.in_(replaced_ids),
                WhatsAppBroadcastRecipientModel.broadcast_group_id == broadcast.id,
                WhatsAppBroadcastRecipientModel.agency_id == broadcast.agency_id,
                PassportRosterResolutionModel.agency_id == broadcast.agency_id,
                PassportRosterResolutionModel.client_group_id.in_(groups),
                PassportRosterResolutionModel.status == "active",
                PassportRosterResolutionModel.resolution_type == "replacement",
            ))).all()
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
        for item in body.items:
            if item.kind != "unidentified":
                continue
            upload = roster_by_id[(item.kind, item.id)].unidentified_upload
            assert upload is not None
            if upload.client_group_id not in groups:
                raise _stale_rows()
            required_sources.add((upload.client_group_id, upload.submission_id))
            current_source_keys.add((upload.client_group_id, upload.submission_id))

    if len(required_sources) > MAX_EXPORT_ROWS:
        raise WhatsAppExportTooLarge("This filter expands to more than 20,000 source travellers. Narrow the filter and export again.")
    submissions: list[PassportSubmissionModel] = []
    ordered_keys = sorted(required_sources, key=lambda key: (str(key[0]), str(key[1])))
    for start in range(0, len(ordered_keys), _SOURCE_QUERY_BATCH):
        keys = ordered_keys[start:start + _SOURCE_QUERY_BATCH]
        submissions.extend((await session.execute(select(PassportSubmissionModel).where(
            PassportSubmissionModel.agency_id == broadcast.agency_id,
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
            tuple_(PassportSubmissionModel.group_id, PassportSubmissionModel.id).in_(keys),
            or_(
                operational_roster_member(),
                tuple_(PassportSubmissionModel.group_id, PassportSubmissionModel.id).in_(
                    (displaced_source_keys - current_source_keys) & set(keys)
                ),
            ),
        ))).scalars().all())
    entities = {(row.group_id, row.id): PassportSubmissionRepository._to_entity(row) for row in submissions}
    # Any disappearing relation fails the whole snapshot; never omit requested rows.
    if set(entities) != required_sources:
        raise _stale_rows()
    source_contacts = _export_whatsapp_contacts(list(entities.values()), match_rows_by_group)
    source_zones = _export_zone_names_from_match_rows(list(entities.values()), match_rows_by_group)
    recipient_models = list((await session.execute(select(WhatsAppBroadcastRecipientModel).where(
        WhatsAppBroadcastRecipientModel.broadcast_group_id == broadcast.id,
        WhatsAppBroadcastRecipientModel.agency_id == broadcast.agency_id,
        WhatsAppBroadcastRecipientModel.id.in_(selected_recipient_ids),
    ))).scalars().all()) if selected_recipient_ids else []
    recipient_models_by_id = {row.id: row for row in recipient_models}
    if set(recipient_models_by_id) != selected_recipient_ids:
        raise _stale_rows()
    if any(
        (item.kind == "recipient" and recipient_models_by_id[item.id].removed_at is not None)
        or (item.kind == "replaced" and recipient_models_by_id[item.id].removed_at is None)
        for item in body.items
    ):
        raise _stale_rows()
    states, resends = await _recipient_delivery_state_maps(session, recipient_models)
    recipients = {row.id: _recipient_response(row, states.get(row.id, []), resends.get(row.id, {})) for row in recipient_models}
    latest_attempts = await _latest_attempt_values(session, broadcast, selected_recipient_ids)
    details = {group_id: _group_export_details(group) for group_id, group in groups.items()}
    output: list[WhatsAppExportRow] = []
    for item in body.items:
        values: dict[str, Any] = {
            "Broadcast": broadcast.name, "Export view": body.view,
            "Filter": body.filter_label, "Filter message type": body.message_type,
            "Roster row type": item.kind, "Roster row ID": str(item.id),
        }
        imported_fields: dict[str, Any] = {}
        source_keys: list[_SourceKey] = []
        recipient_id: uuid.UUID | None = None
        if item.kind == "source_contact":
            assert item.source_group_id is not None
            key = (item.source_group_id, item.id)
            source = source_by_key[key]
            source_keys = [key]
            recipient_id = source.recipient_id
            values.update({"Source contact name": source.name, "Source phone": source.raw_phone_number,
                           "Source normalized phone": source.normalized_phone_number, "Source issue": source.issue})
        else:
            roster_row = roster_by_id[(item.kind, item.id)]
            if roster_row.recipient is not None:
                recipient_id = item.id
            elif roster_row.rejected_contact is not None:
                rejected = roster_row.rejected_contact
                imported_fields = dict(rejected.imported_fields)
                values.update({"Broadcast contact name": rejected.raw_name, "Broadcast phone": rejected.raw_phone_number,
                               "Rejection reason": rejected.reason, "Rejection code": rejected.reason_code,
                               "Import filename": rejected.source_file_name, "Import sheet": rejected.sheet_name,
                               "Import row": rejected.row_number})
            elif roster_row.replaced_recipient is not None:
                replacement = roster_row.replaced_recipient
                recipient_id = item.id
                imported_fields = dict(replacement.imported_fields)
                values.update({"Broadcast contact name": replacement.name, "Broadcast phone": replacement.phone_number,
                               "Broadcast normalized phone": replacement.normalized_phone_number,
                               "Replacement name": replacement.replacement_name,
                               "Replacement phone": replacement.replacement_phone, "Replaced at": replacement.replaced_at})
            else:
                upload = roster_row.unidentified_upload
                assert upload is not None
                source_keys = [(upload.client_group_id, upload.submission_id)]
        recipient = recipients.get(recipient_id) if recipient_id else None
        if recipient is not None:
            values.setdefault("Broadcast contact name", recipient.name)
            values.setdefault("Broadcast phone", recipient.phone_number)
            values.setdefault("Broadcast normalized phone", recipient.normalized_phone_number)
            values["Delivery recipient ID"] = str(recipient.id)
            if item.kind != "replaced":
                imported_fields = dict(recipient.imported_fields)
            if item.kind != "source_contact":
                source_keys = sources_by_recipient.get(recipient.id, [])
            values.update(latest_attempts.get(recipient.id, {}))
        values.update(_delivery_values(recipient))
        values.update(_broadcast_import_contact_values(imported_fields))
        if body.message_type:
            values["Selected message status"] = values.get(
                f"{_MESSAGE_LABELS[body.message_type]} status", "not_sent"
            )
        if not source_keys:
            output.append(WhatsAppExportRow(values=values, broadcast_fields=imported_fields))
        for key in source_keys:
            group = groups[key[0]]
            submission = entities[key]
            source = source_by_key.get(key)
            source_values = {**values, "Source import only": group.import_only}
            if key in matched_source_keys:
                source_values["WhatsApp Email"] = source_contacts.get(submission.id, {}).get("email")
                source_values["Zone Name"] = source_zones.get(submission.id)
            if not source_values.get("Zone Name"):
                source_values["Zone Name"] = " ".join(
                    str((submission.staff_metadata or {}).get("zone_name") or "").split()
                ) or None
            if source is not None:
                source_values.update({"Source contact name": source.name, "Source phone": source.raw_phone_number,
                                      "Source normalized phone": source.normalized_phone_number, "Source issue": source.issue})
            else:
                fields = submission.confirmed_fields or submission.extracted_fields or {}
                source_values.update({
                    "Source contact name": " ".join(
                        str(fields.get(field) or "").strip() for field in ("given_names", "surname")
                    ).strip() or submission.client_name,
                    "Source phone": _raw_source_phone(submission),
                })
            output.append(WhatsAppExportRow(
                values=source_values, broadcast_fields=imported_fields,
                submission=submission, group_details=details[key[0]],
            ))
        if len(output) > MAX_EXPORT_ROWS:
            raise WhatsAppExportTooLarge("This filter expands to more than 20,000 rows. Narrow the filter and export again.")
    return output


@router.post("/groups/{group_id}/export", dependencies=[Depends(require_cookie_csrf)])
async def export_broadcast_filter(
    group_id: uuid.UUID, body: WhatsAppFilterExportRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    broadcast = (await session.execute(select(WhatsAppBroadcastGroupModel).where(
        WhatsAppBroadcastGroupModel.id == group_id, *_agency_filter(current_user),
    ))).scalar_one_or_none()
    if broadcast is None:
        raise HTTPException(404, "WhatsApp broadcast group not found")
    filename_parts = [broadcast.name[:80], body.filter_label[:60], body.view]
    if body.message_type:
        filename_parts.append(body.message_type)
    filename = re.sub(r"[^\w .-]", "_", "-".join(filename_parts)).strip(" .")[:180] or "broadcast-export"
    try:
        rows = await _gather_export_rows(body, broadcast, current_user, session)
        # This endpoint never calls passport export-history, mutation or send APIs.
        # Release the read transaction before serializing detached values off-loop.
        await session.rollback()
        content = await asyncio.to_thread(build_whatsapp_filter_workbook, rows)
    except WhatsAppExportTooLarge as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(content, media_type=_MIME, headers={
        "Content-Disposition": f"attachment; filename=\"broadcast-export.xlsx\"; filename*=UTF-8''{quote(filename + '.xlsx')}",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })
