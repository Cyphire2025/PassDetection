"""Database-backed coverage of spreadsheet matching and reminder targeting."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import BytesIO

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.passports.correct_client_details import correct_client_details
from app.application.use_cases.whatsapp.private_delivery_identity import is_private_delivery_match
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context,
)
from app.presentation.api.v1.routes.whatsapp_contact_import import _parse_excel_contact_bytes
from app.presentation.api.v1.routes.whatsapp_reminder_audience import resolve_reminder_audience

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("answer_source", ["confirmed", "custom_detail", "custom_answer"])
@pytest.mark.parametrize("traveller_count", [1, 2])
async def test_imported_producer_code_identifies_and_excludes_from_reminders(
    db_session: AsyncSession,
    answer_source: str,
    traveller_count: int,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["Name", "Mobile", "DOB", "Producer Code", "Location", "Unused Heading"])
    sheet.append(["Spreadsheet Alice", "9876543210", "10/01/1990", "PROD-0042", "Delhi", None])
    sheet.append(["Spreadsheet Bob", "9876543211", "11/02/1991", "PROD-0043", "Mumbai", None])
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    parsed = _parse_excel_contact_bytes(payload.getvalue(), filename="roster.xlsx")
    assert parsed.field_keys == [
        "name",
        "phone_number",
        "dob",
        "producer_code",
        "location",
        "unused_heading",
    ]
    assert len(parsed.contacts) == 2
    assert parsed.contacts[0].imported_fields["location"] == "Delhi"
    assert parsed.contacts[0].imported_fields["dob"] == "10/01/1990"

    agency = AgencyModel(id=uuid.uuid4(), name="Test agency", email="roster@example.test")
    group = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        name="Test upload group",
        token=str(uuid.uuid4()),
        status="active",
        agent_employee_code_enabled=True,
        departure_cities=[],
        created_at=NOW,
    )
    broadcast = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        name="Imported roster",
        organizing_company_name="Test agency",
        imported_field_keys=parsed.field_keys,
        created_at=NOW,
        updated_at=NOW,
    )
    link = ClientGroupWhatsAppBroadcastLinkModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        client_group_id=group.id,
        broadcast_group_id=broadcast.id,
        matching_field_keys=["name", "phone_number", "producer_code"],
        created_at=NOW,
    )
    recipients = [
        WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            broadcast_group_id=broadcast.id,
            name=contact.name,
            phone_number=contact.phone_number,
            normalized_phone_number=contact.phone_number,
            imported_fields=contact.imported_fields,
            created_at=NOW,
        )
        for contact in parsed.contacts
    ]
    submission = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        group_id=group.id,
        client_name="Completely different submitted name",
        client_phone="9000000000",
        image_s3_key="test/passport.jpg",
        status="submitted",
        confirmed_fields=(
            {"agent_employee_code": "AIGPROD0042"} if answer_source == "confirmed" else {}
        ),
        custom_detail_answers=(
            [{"label": "Producer Code", "value": "PROD0042"}]
            if answer_source == "custom_detail"
            else []
        ),
        custom_answers=(
            [{"label": "Producer Code", "value": "PROD0042"}]
            if answer_source == "custom_answer"
            else []
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add_all([agency, group, broadcast, link, *recipients, submission])
    if traveller_count == 2:
        db_session.add(
            PassportSubmissionModel(
                id=uuid.uuid4(),
                agency_id=agency.id,
                group_id=group.id,
                client_name="Spreadsheet Alice",
                client_phone=recipients[0].normalized_phone_number,
                image_s3_key="test/qualifier-passport.jpg",
                status="submitted",
                confirmed_fields={"agent_employee_code": "PROD0042", "passport_number": "X1234567"},
                created_at=NOW,
                updated_at=NOW,
            )
        )
    await db_session.flush()

    if answer_source == "confirmed":
        # Prefixes remain distinct until staff explicitly correct the saved value.
        _, _, _, before = await load_unresolved_passport_whatsapp_match_context(
            db_session, group_id=group.id, agency_id=agency.id,
        )
        assert next(row for row in before if submission.id in row.submission_ids).status == "unmatched_submission"
        submission_repo = PassportSubmissionRepository(db_session)
        saved = await submission_repo.get_by_id(submission.id)
        saved_group = await ClientGroupRepository(db_session).get_by_id(group.id)
        assert saved is not None and saved_group is not None
        corrected, changed = correct_client_details(
            saved, saved_group, {"agent_employee_code": "PROD0042"},
        )
        assert changed == ("agent_employee_code",)
        assert corrected.status == saved.status
        await submission_repo.update(corrected)
        await db_session.flush()

    _, _, _, rows = await load_unresolved_passport_whatsapp_match_context(
        db_session,
        group_id=group.id,
        agency_id=agency.id,
    )
    identified = next(row for row in rows if submission.id in row.submission_ids)
    assert identified.status == "submitted"
    assert len(identified.submission_ids) == traveller_count
    assert identified.duplicate_submission_ids == ()
    assert identified.recipient_ids == (recipients[0].id,)
    assert {
        evidence.kind for evidence in identified.match_evidence
        if evidence.submission_id == submission.id
    } == {"agent_employee_code"}
    # Broad roster identification must not become a new private-item permission.
    assert is_private_delivery_match(identified) is False

    targeted = await resolve_reminder_audience(
        db_session,
        broadcast_group=broadcast,
        recipients=recipients,
        audience="not_submitted",
        audience_client_group_id=group.id,
    )
    assert [recipient.id for recipient in targeted.recipients] == [recipients[1].id]
    assert targeted.excluded_submitted_count == 1
    assert targeted.excluded_needs_review_count == 0

    everyone = await resolve_reminder_audience(
        db_session,
        broadcast_group=broadcast,
        recipients=recipients,
        audience="all",
        audience_client_group_id=None,
    )
    assert everyone.recipients == tuple(recipients)

    # A submission arriving after preview changes the authoritative audience.
    db_session.add(
        PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            group_id=group.id,
            client_name="Another different name",
            client_phone="9000000001",
            image_s3_key="test/late-passport.jpg",
            status="submitted",
            confirmed_fields={"agent_employee_code": "PROD0043"},
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await db_session.flush()
    with pytest.raises(HTTPException, match="no not-submitted audience"):
        await resolve_reminder_audience(
            db_session,
            broadcast_group=broadcast,
            recipients=recipients,
            audience="not_submitted",
            audience_client_group_id=group.id,
        )
