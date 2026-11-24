"""Ordered roster, manual alias and passenger projections without SQL or sends."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.application.use_cases.whatsapp.source_group_contacts import _raw_source_phone
from app.infrastructure.database.models import ClientGroupModel, WhatsAppBroadcastGroupModel
from app.infrastructure.export.whatsapp_filter_excel_exporter import (
    MAX_EXPORT_ROWS,
    WhatsAppExportRow,
    WhatsAppExportTooLarge,
)
from app.presentation.api.v1.routes.passport_export_support import _group_export_details
from app.presentation.api.v1.routes.whatsapp_export_hydration import (
    ExportDelivery,
    HydratedExportSources,
)
from app.presentation.api.v1.routes.whatsapp_export_sources import ExportSources
from app.presentation.api.v1.routes.whatsapp_export_support import (
    _MESSAGE_LABELS,
    _broadcast_import_contact_values,
    _delivery_values,
    _SourceKey,
)
from app.presentation.api.v1.schemas.whatsapp_export_schemas import (
    WhatsAppExportItem,
    WhatsAppFilterExportRequest,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppMergedContactResponse,
    WhatsAppRecipientRosterItemResponse,
)


@dataclass(frozen=True)
class SelectedExportValues:
    values: dict[str, Any]
    imported_fields: dict[str, Any]
    source_keys: list[_SourceKey]
    delivery_recipient_id: uuid.UUID | None


def select_export_values(
    body: WhatsAppFilterExportRequest,
    broadcast: WhatsAppBroadcastGroupModel,
    item: WhatsAppExportItem,
    roster_by_id: dict[tuple[str, uuid.UUID], WhatsAppRecipientRosterItemResponse],
    sources: ExportSources,
    delivery: ExportDelivery,
) -> SelectedExportValues:
    source_by_key = sources.source_by_key
    sources_by_recipient = sources.sources_by_recipient
    recipients = delivery.recipients
    latest_attempts = delivery.latest_attempts
    values: dict[str, Any] = {
        "Broadcast": broadcast.name,
        "Export view": body.view,
        "Filter": body.filter_label,
        "Filter message type": body.message_type,
        "Roster row type": item.kind,
        "Roster row ID": str(item.id),
    }
    imported_fields: dict[str, Any] = {}
    source_keys: list[_SourceKey] = []
    delivery_recipient_id: uuid.UUID | None = None
    if item.kind == "source_contact":
        assert item.source_group_id is not None
        key = (item.source_group_id, item.id)
        source = source_by_key[key]
        source_keys = [key]
        delivery_recipient_id = source.recipient_id
        values.update(
            {
                "Source contact name": source.name,
                "Source phone": source.raw_phone_number,
                "Source normalized phone": source.normalized_phone_number,
                "Source issue": source.issue,
            }
        )
    else:
        roster_row = roster_by_id[(item.kind, item.id)]
        if roster_row.recipient is not None:
            delivery_recipient_id = item.id
        elif roster_row.rejected_contact is not None:
            rejected = roster_row.rejected_contact
            imported_fields = dict(rejected.imported_fields)
            values.update(
                {
                    "Broadcast contact name": rejected.raw_name,
                    "Broadcast phone": rejected.raw_phone_number,
                    "Rejection reason": rejected.reason,
                    "Rejection code": rejected.reason_code,
                    "Import filename": rejected.source_file_name,
                    "Import sheet": rejected.sheet_name,
                    "Import row": rejected.row_number,
                }
            )
        elif roster_row.replaced_recipient is not None:
            replacement = roster_row.replaced_recipient
            delivery_recipient_id = item.id
            imported_fields = dict(replacement.imported_fields)
            values.update(
                {
                    "Broadcast contact name": replacement.name,
                    "Broadcast phone": replacement.phone_number,
                    "Broadcast normalized phone": replacement.normalized_phone_number,
                    "Replacement name": replacement.replacement_name,
                    "Replacement phone": replacement.replacement_phone,
                    "Replaced at": replacement.replaced_at,
                }
            )
        else:
            upload = roster_row.unidentified_upload
            assert upload is not None
            source_keys = [(upload.client_group_id, upload.submission_id)]
    recipient = recipients.get(delivery_recipient_id) if delivery_recipient_id else None
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
    return SelectedExportValues(values, imported_fields, source_keys, delivery_recipient_id)


def append_merged_contact_rows(
    item: WhatsAppExportItem,
    selected: SelectedExportValues,
    merged_contacts: dict[uuid.UUID, list[WhatsAppMergedContactResponse]],
    output: list[WhatsAppExportRow],
) -> None:
    values = selected.values
    delivery_recipient_id = selected.delivery_recipient_id
    if item.kind == "recipient" and delivery_recipient_id:
        for contact in merged_contacts.get(delivery_recipient_id, []):
            alias_fields = dict(contact.imported_fields)
            output.append(
                WhatsAppExportRow(
                    values={
                        **values,
                        "Roster row ID": str(contact.id),
                        "Broadcast contact name": contact.name,
                        "Shared delivery number": True,
                        **_broadcast_import_contact_values(alias_fields),
                    },
                    broadcast_fields=alias_fields,
                )
            )


def append_source_rows(
    selected: SelectedExportValues,
    groups: dict[uuid.UUID, ClientGroupModel],
    sources: ExportSources,
    hydrated: HydratedExportSources,
    details: dict[uuid.UUID, dict[str, Any]],
    output: list[WhatsAppExportRow],
) -> None:
    values = selected.values
    imported_fields = selected.imported_fields
    source_keys = selected.source_keys
    source_by_key = sources.source_by_key
    matched_source_keys = sources.matched_source_keys
    entities = hydrated.entities
    source_contacts = hydrated.source_contacts
    source_zones = hydrated.source_zones
    for key in source_keys:
        group = groups[key[0]]
        submission = entities[key]
        matched_source = source_by_key.get(key)
        source_values = {**values, "Source import only": group.import_only}
        if key in matched_source_keys:
            source_values["WhatsApp Email"] = source_contacts.get(submission.id, {}).get("email")
            source_values["Zone Name"] = source_zones.get(submission.id)
        if not source_values.get("Zone Name"):
            source_values["Zone Name"] = (
                " ".join(str((submission.staff_metadata or {}).get("zone_name") or "").split())
                or None
            )
        if matched_source is not None:
            source_values.update(
                {
                    "Source contact name": matched_source.name,
                    "Source phone": matched_source.raw_phone_number,
                    "Source normalized phone": matched_source.normalized_phone_number,
                    "Source issue": matched_source.issue,
                }
            )
        else:
            fields = submission.confirmed_fields or submission.extracted_fields or {}
            source_values.update(
                {
                    "Source contact name": " ".join(
                        str(fields.get(field) or "").strip() for field in ("given_names", "surname")
                    ).strip()
                    or submission.client_name,
                    "Source phone": _raw_source_phone(submission),
                }
            )
        output.append(
            WhatsAppExportRow(
                values=source_values,
                broadcast_fields=imported_fields,
                submission=submission,
                group_details=details[key[0]],
            )
        )


def project_export_rows(
    body: WhatsAppFilterExportRequest,
    broadcast: WhatsAppBroadcastGroupModel,
    groups: dict[uuid.UUID, ClientGroupModel],
    roster_by_id: dict[tuple[str, uuid.UUID], WhatsAppRecipientRosterItemResponse],
    sources: ExportSources,
    hydrated: HydratedExportSources,
    delivery: ExportDelivery,
) -> list[WhatsAppExportRow]:
    details = {group_id: _group_export_details(group) for group_id, group in groups.items()}
    output: list[WhatsAppExportRow] = []
    for item in body.items:
        selected = select_export_values(body, broadcast, item, roster_by_id, sources, delivery)
        if not selected.source_keys:
            output.append(
                WhatsAppExportRow(values=selected.values, broadcast_fields=selected.imported_fields)
            )
        append_merged_contact_rows(item, selected, delivery.merged_contacts, output)
        append_source_rows(selected, groups, sources, hydrated, details, output)
        if len(output) > MAX_EXPORT_ROWS:
            raise WhatsAppExportTooLarge(
                "This filter expands to more than 20,000 rows. Narrow the filter and export again."
            )
    return output
