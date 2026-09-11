"""Synthetic company qualifier and two travelling parents for delivery tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.application.use_cases.whatsapp.message_templates import render_message
from app.core.security.jwt import create_access_token
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeModel,
)

QUALIFIER_PHONE = "+919900000001"
MOTHER_PHONE = "+919900000002"
FATHER_PHONE = "+919900000003"
WELCOME_TEXT = "Congratulations. Welcome to the company trip."
WELCOME_SUPPORT = "Travel Desk: +919900000099"


async def seed_traveller_delivery(session, client, *, phones=None, document_type="visa", role="agency_manager"):
    now = datetime.now(tz=UTC)
    agency = AgencyModel(id=uuid.uuid4(), name="Example Travel", email=f"{uuid.uuid4()}@example.test")
    user = UserModel(id=uuid.uuid4(), agency_id=agency.id if role != "super_admin" else None,
                     role=role, full_name="Operator", email=f"{uuid.uuid4()}@example.test", hashed_password="unused")
    session.add_all([agency, user])
    await session.flush()
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Company Trip",
                             token=str(uuid.uuid4()), status="active", created_by_user_id=user.id)
    source = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency.id,
        name="Company employees", recipient_opt_in_confirmed_at=now, created_by_user_id=user.id)
    session.add_all([group, source])
    await session.flush()
    qualifier = WhatsAppBroadcastRecipientModel(id=uuid.uuid4(), agency_id=agency.id,
        broadcast_group_id=source.id, name="Qualifying employee", phone_number=QUALIFIER_PHONE,
        normalized_phone_number=QUALIFIER_PHONE, imported_fields={"Employee code": "EMP001"})
    link = ClientGroupWhatsAppBroadcastLinkModel(id=uuid.uuid4(), agency_id=agency.id,
        client_group_id=group.id, broadcast_group_id=source.id, matching_field_keys=["Employee code"])
    batch = DocumentDistributionBatchModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        document_type=document_type, status="saved", saved_at=now, created_by_user_id=user.id)
    session.add_all([qualifier, link, batch])
    await session.flush()
    log = WhatsAppMessageLogModel(id=uuid.uuid4(), batch_id=uuid.uuid4(), agency_id=agency.id,
        broadcast_group_id=source.id, recipient_id=qualifier.id, message_type="welcome",
        normalized_phone_number=QUALIFIER_PHONE, status="delivered", template_name="welcome_template",
        rendered_message=render_message(message_type="welcome", group_name=group.name,
            support_contacts=WELCOME_SUPPORT, message_content=WELCOME_TEXT),
        header_parameter_values=["original-image"], template_parameter_values=[WELCOME_TEXT])
    session.add(log)
    session.add(WhatsAppPhoneWelcomeModel(id=uuid.uuid4(), agency_id=agency.id,
        normalized_phone_number=QUALIFIER_PHONE, status="delivered", attempt_id=log.id,
        attempt_kind="broadcast", delivered_at=now))
    passengers, documents = [], []
    for index, phone in enumerate(phones if phones is not None else [MOTHER_PHONE, FATHER_PHONE]):
        passenger = PassportSubmissionModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
            client_name=f"Parent {index + 1}", client_phone=phone, family_head_phone=QUALIFIER_PHONE,
            image_s3_key=f"{agency.id}/{group.id}/{uuid.uuid4()}.jpg", status="confirmed",
            confirmed_fields={"passport_number": f"P{index}000001"},
            staff_metadata={"employee_code": "EMP001"})
        session.add(passenger)
        await session.flush()
        document = DistributedDocumentModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
            batch_id=batch.id, passenger_id=passenger.id, document_type=document_type,
            original_filename=f"parent-{index + 1}.pdf", storage_key=f"documents/{uuid.uuid4()}.pdf",
            detected_type=document_type, match_status="matched", match_confidence=1.0)
        session.add(document)
        passengers.append(passenger)
        documents.append(document)
    await session.commit()
    token, _ = create_access_token(user.id, role, agency_id=user.agency_id)
    client.headers["Authorization"] = "Bearer " + token
    return SimpleNamespace(agency=agency, user=user, group=group, source=source, qualifier=qualifier,
                           batch=batch, passengers=passengers, documents=documents)
