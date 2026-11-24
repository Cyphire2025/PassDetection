"""Persisted synthetic broadcast/source graph for exact-filter export controls."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppMessageLogModel,
)
from app.presentation.api.v1.schemas.whatsapp_export_schemas import WhatsAppFilterExportRequest
from tests.persistence import persist_graph

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


@dataclass(frozen=True)
class ExportGraph:
    actor: User
    broadcast: WhatsAppBroadcastGroupModel
    source_group: ClientGroupModel
    manual_group: ClientGroupModel
    recipients: list[WhatsAppBroadcastRecipientModel]
    submissions: list[PassportSubmissionModel]
    sources: list[WhatsAppBroadcastSourceContactModel]
    rejected: WhatsAppBroadcastRejectedContactModel
    alias_id: uuid.UUID

    def request(
        self, *items: tuple[str, uuid.UUID], view: str = "delivery"
    ) -> WhatsAppFilterExportRequest:
        return WhatsAppFilterExportRequest.model_validate(
            {
                "view": view,
                "filter_label": "Selected / Việt Nam",
                "message_type": "welcome",
                "items": [
                    {
                        "kind": kind,
                        "id": item_id,
                        **(
                            {"source_group_id": self.source_group.id}
                            if kind == "source_contact"
                            else {}
                        ),
                    }
                    for kind, item_id in items
                ],
            }
        )


async def persist_export_graph(session: AsyncSession) -> ExportGraph:
    agency_id, actor_id, broadcast_id, alias_id = (uuid.uuid4() for _ in range(4))
    actor = User(
        id=actor_id,
        agency_id=agency_id,
        email="export@example.test",
        full_name="Export operator",
        hashed_password="unused",
        role=UserRole.AGENCY_ADMIN,
    )
    broadcast = WhatsAppBroadcastGroupModel(
        id=broadcast_id, agency_id=agency_id, name="Trip / Việt Nam 2026"
    )
    groups = [
        ClientGroupModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            name=name,
            token=uuid.uuid4().hex,
            import_only=import_only,
        )
        for name, import_only in [("Source travellers", True), ("Manual roster", False)]
    ]
    recipients = [
        WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            broadcast_group_id=broadcast_id,
            name=name,
            phone_number=phone,
            normalized_phone_number=phone,
            imported_fields={"Staff Code": code, "Email": email, "Zone Name": zone},
            created_at=NOW,
            display_order=index,
            merged_contacts=[
                {
                    "id": str(alias_id),
                    "name": "Merged colleague",
                    "imported_fields": {"Email": "alias@example.test", "Zone Name": "Alias zone"},
                }
            ]
            if index == 0
            else [],
        )
        for index, (name, phone, code, email, zone) in enumerate(
            [
                (
                    "Shared delivery",
                    "+919111111111",
                    "SOURCE",
                    "shared@example.test",
                    "Source zone",
                ),
                (
                    "Manual colleague",
                    "+919222222222",
                    "EMP-M",
                    "manual@example.test",
                    "Manual zone",
                ),
            ]
        )
    ]
    submissions = [
        PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            group_id=groups[group_index].id,
            client_name=name,
            client_phone=phone,
            client_email=f"person{index}@example.test",
            status="staff_approved",
            image_s3_key=f"synthetic/{index}.jpg",
            client_reviewed_at=NOW,
            confirmed_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            extracted_fields={"given_names": "Old extraction"},
            confirmed_fields={
                "given_names": name,
                "surname": "Person",
                "passport_number": f"00{index}",
                "date_of_birth": "1990-01-02",
                "date_of_expiry": "2030-12-31",
            },
            staff_metadata={"staff_code": code, "zone_name": f"Fallback {index}"},
        )
        for index, (name, group_index, phone, code) in enumerate(
            [
                ("First traveller", 0, "+919111111111", "SOURCE-1"),
                ("Second traveller", 0, "+919111111111", "SOURCE-2"),
                ("Manual colleague", 1, "+919333333333", "EMP-M"),
                ("Unidentified person", 1, None, "UNMATCHED"),
            ]
        )
    ]
    sources = [
        WhatsAppBroadcastSourceContactModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            broadcast_group_id=broadcast_id,
            source_group_id=groups[0].id,
            source_submission_id=submission.id,
            recipient_id=recipients[0].id,
            name=f"Source {index}",
            raw_phone_number="09111111111",
            normalized_phone_number="+919111111111",
            issue="shared_number" if index else None,
            created_at=NOW + timedelta(seconds=index),
        )
        for index, submission in enumerate(submissions[:2])
    ]
    rejected = WhatsAppBroadcastRejectedContactModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        broadcast_group_id=broadcast_id,
        source_file_name="synthetic.xlsx",
        sheet_name="Contacts",
        row_number=7,
        raw_name="Rejected colleague",
        raw_phone_number="invalid",
        reason_code="invalid_phone",
        reason="Phone needs correction",
        fingerprint="synthetic-rejected",
        imported_fields={"Email": "rejected@example.test", "Zone Name": "Rejected zone"},
        created_at=NOW,
        display_order=3,
    )
    records = [
        AgencyModel(id=agency_id, name="Synthetic export agency", email="agency@example.test"),
        UserModel(
            id=actor_id,
            agency_id=agency_id,
            email=actor.email,
            full_name=actor.full_name,
            hashed_password="unused",
            role=actor.role.value,
        ),
        broadcast,
        *groups,
        *recipients,
        *submissions,
        *sources,
        rejected,
    ]
    records.extend(
        ClientGroupWhatsAppBroadcastLinkModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            broadcast_group_id=broadcast_id,
            client_group_id=group.id,
            sync_contacts_from_group=index == 0,
            matching_field_keys=["staff_code"] if index else None,
        )
        for index, group in enumerate(groups)
    )
    records.extend(
        WhatsAppMessageLogModel(
            id=uuid.UUID(int=index + 1),
            agency_id=agency_id,
            broadcast_group_id=broadcast_id,
            recipient_id=recipients[0].id,
            message_type="welcome",
            status=status,
            normalized_phone_number=recipients[0].normalized_phone_number,
            created_at=NOW,
            status_updated_at=NOW,
            template_name="synthetic_v1",
            error_message="Synthetic provider decline" if index else None,
            rendered_message="PRIVATE_RENDERED_BODY",
            provider_message_id="PRIVATE_PROVIDER_ID",
            template_parameter_values=["PRIVATE_TEMPLATE_ARGUMENT"],
        )
        for index, status in enumerate(["sent", "failed"])
    )
    await persist_graph(session, records)
    await session.commit()
    return ExportGraph(
        actor, broadcast, groups[0], groups[1], recipients, submissions, sources, rejected, alias_id
    )
