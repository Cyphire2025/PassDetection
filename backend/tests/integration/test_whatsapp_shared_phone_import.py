"""Real XLSX source preservation beyond the small UI preview; no messages sent."""

import uuid
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from openpyxl import Workbook
from sqlalchemy import func, select

from app.application.mcp.contact_mapping import ContactColumnMapping, map_contacts
from app.application.use_cases.whatsapp.contact_import_limits import MAX_WHATSAPP_EXCEL_ROWS
from app.infrastructure.database.models import UserModel, WhatsAppBroadcastRecipientModel, WhatsAppBroadcastRejectedContactModel
from app.infrastructure.security.contact_spreadsheet_security import snapshot_workbook
from app.presentation.api.v1.routes.whatsapp_contact_import import _parse_excel_contact_bytes
from app.presentation.api.v1.routes.whatsapp_contact_sources import excel_rejected_contacts, recover_excel_duplicate_sources
from app.presentation.api.v1.routes.whatsapp_contact_support import _excel_contact_preview_response
from app.presentation.api.v1.routes.whatsapp_creation import create_new_broadcast
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSupportContactInput
from app.presentation.mcp.contact_import_support import CONTACT_IMPORT_SUPPORT
from tests.unit.application.test_traveller_reconciliation import _seed_scope


def shared_phone_workbook(count: int) -> bytes:
    workbook, output = Workbook(), BytesIO()
    sheet = workbook.active
    sheet.title = "Travellers"
    sheet.append(["Name", "Mobile", "Staff code", "Passport number", "Email"])
    for index in range(count):
        sheet.append([f"Synthetic Person {index}", "9876543210", f"EMP{index:06d}", f"P{index:07d}", f"person{index}@example.com"])
    workbook.save(output)
    workbook.close()
    return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["dashboard", "mcp"])
async def test_700_people_one_phone_retain_all_individual_sources(db_session, adapter):
    agency, _, _ = await _seed_scope(db_session)
    actor = UserModel(id=uuid.uuid4(), agency_id=agency.id, email=f"{uuid.uuid4()}@example.com",
                      full_name="Synthetic importer", hashed_password="synthetic", role="agency_admin")
    db_session.add(actor)
    await db_session.flush()
    content = shared_phone_workbook(700)
    if adapter == "dashboard":
        parsed = _parse_excel_contact_bytes(content, filename="shared-phone.xlsx")
        contacts, field_keys = parsed.contacts, parsed.field_keys
        rejected = excel_rejected_contacts(parsed)
        # The original workbook and its displayed preview can be submitted
        # together; source fingerprints must prevent duplicate persistence.
        rejected = excel_rejected_contacts(parsed, rejected[:500])
        preview = _excel_contact_preview_response(parsed.contacts, parsed.rejected_rows,
            rejected_count=parsed.rejected_count)
        assert len(preview.rejected_rows) == 500
        assert preview.rejected_count == 699 and preview.omitted_rejected_count == 199
        assert preview.rejected_rows_truncated
        assert preview.rejected_counts == {"duplicate_phone": 699}
    else:
        parsed = map_contacts(snapshot_workbook(content), filename="shared-phone.xlsx",
            mappings=[ContactColumnMapping(sheet_name="Travellers", header_row=1, name_column=1, phone_column=2)],
            support=CONTACT_IMPORT_SUPPORT.mapping)
        contacts, rejected, field_keys = parsed.contacts, parsed.rejected, parsed.field_keys
        preview = parsed.preview(CONTACT_IMPORT_SUPPORT.mapping)
        assert len(preview["rejected_rows"]) == 500
        assert preview["omitted_rejected_count"] == 199 and preview["rejected_rows_truncated"]
    assert len(contacts) == 1 and len(rejected) == 699
    assert contacts[0].imported_fields["staff_code"] == "EMP000000"
    assert contacts[0].imported_fields["passport_number"] == "P0000000"
    assert len(contacts[0].imported_fields) < 20
    group = await create_new_broadcast(db_session, agency_id=agency.id, actor_id=actor.id,
        name="Synthetic shared phone import", organizing_company_name="Synthetic Company",
        contacts=contacts, rejected_contacts=rejected, recipient_opt_in_confirmed=True,
        support_contacts=[WhatsAppSupportContactInput(name="Synthetic support", phone_number="9876543211")],
        declared_field_keys=field_keys)
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(WhatsAppBroadcastRecipientModel).where(
        WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id)) == 1
    retained = list((await db_session.scalars(select(WhatsAppBroadcastRejectedContactModel).where(
        WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group.id))).all())
    assert len(retained) == 699
    assert {row.imported_fields["staff_code"] for row in retained} == {f"EMP{index:06d}" for index in range(1, 700)}
    assert len({row.fingerprint for row in retained}) == 699
    assert sorted(row.display_order for row in retained) == list(range(2, 701))


def test_full_workbook_row_budget_is_preserved():
    with pytest.raises(HTTPException) as error:
        _parse_excel_contact_bytes(shared_phone_workbook(MAX_WHATSAPP_EXCEL_ROWS), filename="over-budget.xlsx")
    assert error.value.status_code == 400
    assert "2000 rows" in error.value.detail


@pytest.mark.asyncio
async def test_duplicate_source_files_recover_omitted_rows_without_reintroducing_delivery_contacts():
    original = shared_phone_workbook(700)
    parsed = _parse_excel_contact_bytes(original, filename="family.xlsx")
    visible_rejected = excel_rejected_contacts(parsed)[:500]
    recovered = await recover_excel_duplicate_sources(
        [UploadFile(file=BytesIO(original), filename="family.xlsx")], visible_rejected)
    assert len(recovered) == 699
    assert all(row.reason_code == "duplicate_phone" for row in recovered)
    assert len({row.imported_fields["staff_code"] for row in recovered}) == 699
    assert "EMP000000" not in {row.imported_fields["staff_code"] for row in recovered}


@pytest.mark.asyncio
async def test_duplicate_source_files_validate_total_entries_before_persistence():
    original = shared_phone_workbook(1001)
    with pytest.raises(HTTPException) as error:
        await recover_excel_duplicate_sources([
            UploadFile(file=BytesIO(original), filename="one.xlsx"),
            UploadFile(file=BytesIO(original), filename="two.xlsx"),
        ], [])
    assert "2000 contact entries" in error.value.detail
