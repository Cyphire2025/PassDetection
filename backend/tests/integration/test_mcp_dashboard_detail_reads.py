"""Real read parity, warmed-cache hydration, deep continuation and no business DML."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import func, select, update

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.delivery_reads import MCPDeliveryReadService
from app.application.mcp.read_projection import ReadProjection, scrub_read
from app.application.mcp.roster_reads import MCPRosterReadService
from app.domain.mcp_dashboard_reads import DASHBOARD_READS
from app.domain.mcp_read_sections import SUPPORTED_READ_SECTIONS
from app.infrastructure.database.mcp_models import MCPControlModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
    PassengerQRTokenModel,
    PassengerQrWhatsAppDeliveryModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeAttemptModel,
)
from app.infrastructure.passports.roster_cache_codec import decode, encode
from app.presentation.mcp.dashboard_read_tools import dashboard_parameters, read_dashboard
from app.presentation.mcp.observational_session import NonObservationalDashboardRead


@pytest.fixture
async def detail_fixture(db_session, test_settings):
    user = UserModel(id=uuid.uuid4(), email="details@example.test", hashed_password="fixture",
        full_name="Reader", role="super_admin", is_active=True)
    agency = AgencyModel(id=uuid.uuid4(), name="Details", email="details-agency@example.test")
    other = AgencyModel(id=uuid.uuid4(), name="Other", email="other-details@example.test")
    control = await db_session.get(MCPControlModel, 1)
    if control is None:
        control = MCPControlModel(id=1)
        db_session.add(control)
    control.enabled = True
    control.allowed_read_sections = sorted(SUPPORTED_READ_SECTIONS)
    control.read_access_revision = 1
    db_session.add_all([user, agency, other])
    await db_session.flush()
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Live", token="private-upload-token",
        travel_date=datetime.now(UTC).date() + timedelta(days=20))
    db_session.add(group)
    await db_session.flush()
    passport = PassportSubmissionModel(id=uuid.uuid4(), group_id=group.id, agency_id=agency.id,
        client_name="Example traveller", client_email="traveller@example.test", client_phone="+919876543211",
        image_s3_key="private/image", status="staff_approved", staff_metadata={"staff_code": "25748", "designation": "Agent"},
        extracted_fields={"date_of_expiry": "1999-01-01", "passport_number": "EXAMPLE123"},
        custom_answers=[{"question_id": str(uuid.uuid4()), "value": "Vegetarian"}])
    db_session.add(passport)
    await db_session.flush()
    principal = MCPPrincipal(uuid.uuid4(), user.id, "codex-desktop", ("mcp:read",),
        datetime.now(UTC) + timedelta(hours=1), "https://example.test/mcp")
    return db_session, test_settings, user, agency, other, group, passport, principal, control


async def dashboard(fixture, view, parameters, **kwargs):
    session, settings, _, _, _, _, _, principal, _ = fixture
    return await read_dashboard(FastAPI(), settings, session, principal, view=view,
        parameters=parameters, agency_id=kwargs.pop("agency_id", None),
        data_path=kwargs.pop("data_path", []), page_size=kwargs.pop("page_size", 100),
        cursor=kwargs.pop("cursor", None))


def test_every_reviewed_view_has_a_valid_input_schema_and_no_mutation_selector():
    assert {"whatsapp_tracking", "passport_details", "document_review", "audit_logs", "platform_settings"} <= DASHBOARD_READS.keys()
    for definition in DASHBOARD_READS.values():
        schema = dashboard_parameters(definition)
        assert schema["additionalProperties"] is False
        assert not {"current_user", "session", "request", "use_case", "claims"} & schema["properties"].keys()


async def test_full_passport_fields_and_canonical_expiry_without_business_changes(detail_fixture):
    session, _, user, _, other, group, passport, _, _ = detail_fixture
    before = passport.updated_at
    data = await dashboard(detail_fixture, "passport_details", {"submission_id": str(passport.id)}, data_path=["staff_metadata"])
    assert data["data"] == {"designation": "Agent", "staff_code": "25748"}
    custom = await dashboard(detail_fixture, "passport_details", {"submission_id": str(passport.id)}, data_path=["custom_answers"])
    assert custom["data"][0]["value"] == "Vegetarian"
    expires = await dashboard(detail_fixture, "passport_view", {"group_id": str(group.id)}, data_path=["expiry_alerts"])
    assert expires["data"][0]["status"] == "expired"
    assert expires["data"][0]["date_of_expiry"] == "1999-01-01"
    assert passport.updated_at == before and passport.staff_metadata["staff_code"] == "25748"
    with pytest.raises(ValueError, match="agency"):
        # The public error is wrapped by the presentation adapter.
        await dashboard(detail_fixture, "passport_details", {"submission_id": str(passport.id)}, agency_id=other.id)
    assert await session.scalar(select(func.count()).select_from(AuditLogModel)) >= 2


async def test_roster_hydrates_real_identity_only_cache_and_retains_revision_fence(detail_fixture, monkeypatch):
    session, _, user, agency, _, group, passport, _, _ = detail_fixture
    second = PassportSubmissionModel(id=uuid.uuid4(), group_id=group.id, agency_id=agency.id,
        client_name="Zed", image_s3_key="private/second", status="staff_approved")
    session.add(second)
    await session.flush()
    from app.application.mcp import roster_reads
    original = roster_reads.prepared_roster
    cipher = Fernet(Fernet.generate_key())

    async def warmed(*args, **kwargs):
        prepared, revision = await original(*args, **kwargs)
        cached = decode(encode(prepared, cipher, "fixture"), cipher, "fixture")
        assert type(cached.pages[0][0].submission).__name__ == "SubmissionViewIdentity"
        return cached, revision

    monkeypatch.setattr(roster_reads, "prepared_roster", warmed)
    service = MCPRosterReadService(session, cursor_secret="cursor")
    first = await service.list_passports(user_id=user.id, group_id=group.id, page_size=1)
    assert first["items"][0]["staff_code"] == "25748"
    assert first["items"][0]["passport_expiry_alert"] == "expired"
    last = await service.list_passports(user_id=user.id, group_id=group.id, page_size=1, cursor=first["next_cursor"])
    assert last["items"][0]["client_name"] == "Zed" and not last["has_more"]
    assert {first["items"][0]["submission_id"], last["items"][0]["submission_id"]} == {str(passport.id), str(second.id)}


async def test_whatsapp_dashboard_unidentified_and_imported_fields_are_canonical(detail_fixture):
    session, _, _, agency, _, group, passport, _, _ = detail_fixture
    broadcast = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Tracking")
    session.add(broadcast)
    await session.flush()
    recipient = WhatsAppBroadcastRecipientModel(id=uuid.uuid4(), agency_id=agency.id,
        broadcast_group_id=broadcast.id, name="Imported person", phone_number="+919876543210",
        normalized_phone_number="919876543210", imported_fields={"staff_code": "25612", "department": "Sales"})
    session.add_all([recipient, ClientGroupWhatsAppBroadcastLinkModel(agency_id=agency.id,
        client_group_id=group.id, broadcast_group_id=broadcast.id)])
    await session.flush()
    from app.infrastructure.repositories.user_repository import UserRepository
    from app.presentation.api.v1.routes.whatsapp_recipient_roster import (
        get_broadcast_recipient_roster,
    )
    actor = await UserRepository(session).get_by_id(detail_fixture[2].id)
    website = await get_broadcast_recipient_roster(broadcast.id, current_user=actor, session=session)
    result = await dashboard(detail_fixture, "whatsapp_tracking", {"group_id": str(broadcast.id)}, data_path=["items"])
    assert result["data"] == json.loads(website.model_dump_json())["items"]
    imported = [item for item in result["data"] if item["kind"] == "recipient"]
    assert imported[0]["recipient"]["imported_fields"]["department"] == "Sales"
    unidentified = [item for item in result["data"] if item["kind"] == "unidentified"]
    assert len(unidentified) == 1 and unidentified[0]["unidentified_upload"]["submission_id"] == str(passport.id)


async def test_section_denial_and_role_loss_stop_before_data(detail_fixture):
    session, _, user, _, _, group, passport, _, control = detail_fixture
    control.allowed_read_sections = sorted(SUPPORTED_READ_SECTIONS - {"whatsapp"})
    await session.flush()
    with pytest.raises(MCPAuthError) as error:
        await dashboard(detail_fixture, "group_whatsapp_matches", {"link_id": str(group.id)})
    assert error.value.error == "read_section_denied"
    assert "whatsapp" in error.value.required_sections
    user.role = "agency_admin"
    await session.flush()
    with pytest.raises(MCPAuthError):
        await dashboard(detail_fixture, "passport_details", {"submission_id": str(passport.id)})


async def test_staff_code_search_matches_saved_editor_precedence_and_explicit_clear(detail_fixture):
    session, _, user, _, _, group, passport, _, _ = detail_fixture
    service = MCPRosterReadService(session, cursor_secret="cursor")
    metadata = await service.list_passports(user_id=user.id, group_id=group.id, search="25748")
    assert metadata["items"][0]["staff_code"] == "25748"
    assert metadata["items"][0]["staff_code_source"] == "staff_metadata.staff_code"
    passport.confirmed_fields = {"Staff Code": "Confirmed-42"}
    await session.flush()
    confirmed = await service.list_passports(user_id=user.id, group_id=group.id, search="Example traveller")
    assert confirmed["items"][0]["staff_code"] == "Confirmed-42"
    assert confirmed["items"][0]["staff_code_source"] == "confirmed_fields.Staff Code"
    passport.confirmed_fields = {"staff_code": ""}
    await session.flush()
    cleared = await service.list_passports(user_id=user.id, group_id=group.id)
    assert cleared["items"][0]["staff_code"] == ""


async def test_all_stored_whatsapp_imports_removed_contacts_and_provenance_are_paged(detail_fixture):
    session, _, _, agency, other, group, passport, _, _ = detail_fixture
    broadcast = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency.id,
        name="Full stored broadcast", organizing_company_name="Company",
        imported_field_keys=["Staff Code", "Custom Column", "Empty Column", "Token"])
    session.add(broadcast)
    await session.flush()
    before = broadcast.updated_at
    imported = {"Staff Code": "A-5", "Custom Column": "Stored original value", "Empty Column": "", "Token": "Business identifier"}
    recipients = [WhatsAppBroadcastRecipientModel(id=uuid.uuid4(), agency_id=agency.id,
        broadcast_group_id=broadcast.id, name=f"Recipient {index}", phone_number=f"+919876{index:06d}",
        normalized_phone_number=f"919876{index:06d}", imported_fields=imported,
        merged_contacts=[{"name": "Merged person", "imported_fields": {"Branch": "West"}}] if index == 0 else [],
        removed_at=datetime.now(UTC) if index == 0 else None) for index in range(107)]
    rejected = WhatsAppBroadcastRejectedContactModel(id=uuid.uuid4(), agency_id=agency.id,
        broadcast_group_id=broadcast.id, source_file_name="contacts.xlsx", sheet_name="Sheet1", row_number=4,
        raw_name="Rejected original name", raw_phone_number="invalid", reason_code="invalid_phone",
        reason="Invalid number", fingerprint="fixture-rejection", imported_fields=imported)
    source = WhatsAppBroadcastSourceContactModel(id=uuid.uuid4(), agency_id=agency.id,
        broadcast_group_id=broadcast.id, source_group_id=group.id, source_submission_id=passport.id,
        name="Source traveller", raw_phone_number="raw-number", issue="invalid_phone", imported_fields=imported)
    session.add_all([*recipients, rejected, source])
    await session.flush()
    stored = await dashboard(detail_fixture, "whatsapp_broadcast_stored", {"group_id": str(broadcast.id)}, data_path=["broadcast"])
    assert stored["data"]["imported_field_keys"] == broadcast.imported_field_keys
    assert stored["data"]["organizing_company_name"] == "Company"
    ids, offset = set(), 0
    while True:
        page = await dashboard(detail_fixture, "whatsapp_broadcast_records",
            {"group_id": str(broadcast.id), "kind": "recipients", "limit": 20, "offset": offset}, data_path=["items"])
        ids.update(item["id"] for item in page["data"])
        if not page["website_pagination"]["has_more"]:
            break
        offset = page["website_pagination"]["next_offset"]
    assert ids == {str(row.id) for row in recipients}
    removed = await dashboard(detail_fixture, "whatsapp_broadcast_records",
        {"group_id": str(broadcast.id), "kind": "recipients", "record_id": str(recipients[0].id)}, data_path=["items", 0])
    assert removed["data"]["removed_at"] and removed["data"]["merged_contacts"][0]["imported_fields"]["Branch"] == "West"
    assert removed["data"]["imported_fields"] == imported
    for kind, expected in (("rejected_contacts", rejected), ("source_contacts", source)):
        result = await dashboard(detail_fixture, "whatsapp_broadcast_records",
            {"group_id": str(broadcast.id), "kind": kind, "imported_field": "Custom Column", "imported_value": "Stored original value"}, data_path=["items", 0])
        assert result["data"]["id"] == str(expected.id) and result["data"]["imported_fields"] == imported
    with pytest.raises(ValueError, match="agency"):
        await dashboard(detail_fixture, "whatsapp_broadcast_records",
            {"group_id": str(broadcast.id), "kind": "recipients"}, agency_id=other.id)
    assert broadcast.updated_at == before
    assert await session.scalar(select(func.count()).select_from(WhatsAppBroadcastRecipientModel)) == 107


async def test_qr_and_welcome_observation_never_issues_tokens_or_recovers_delivery(detail_fixture, monkeypatch):
    session, _, _, _, _, group, _, _, _ = detail_fixture
    from app.presentation.api.v1.routes import (
        tour_operations_qr_delivery,
        tour_operations_qr_helpers,
    )

    async def forbidden(*args, **kwargs):
        raise AssertionError("A dashboard read cannot issue or recover")

    monkeypatch.setattr(tour_operations_qr_helpers, "issue_passenger_qr", forbidden)
    monkeypatch.setattr(tour_operations_qr_delivery, "_recover_stale_qr_deliveries", forbidden)
    qr = await dashboard(detail_fixture, "group_qr_metadata", {"group_id": str(group.id)}, data_path=["passengers"])
    assert qr["data"][0]["qr_status"] == "not_generated"
    assert not qr["data"][0]["qr_payload"]
    eligibility = await dashboard(detail_fixture, "qr_delivery_eligibility", {"group_id": str(group.id)}, data_path=["recipients"])
    assert eligibility["data"][0]["qr_status"] == "not_generated"
    welcome = await dashboard(detail_fixture, "welcome_delivery_eligibility", {"group_id": str(group.id)})
    assert "preview_token" not in json.dumps(welcome)
    assert await session.scalar(select(func.count()).select_from(PassengerQRTokenModel)) == 0


async def test_document_review_and_delivery_eligibility_are_pure_without_storage(detail_fixture, monkeypatch):
    session, _, _, agency, _, group, passport, _, _ = detail_fixture
    from app.presentation.api.v1.routes import document_distribution_responses

    def forbidden(*args, **kwargs):
        raise AssertionError("Read-only document metadata cannot create file capabilities")

    monkeypatch.setattr(document_distribution_responses, "MinioStorageRepository", forbidden)
    batch = DocumentDistributionBatchModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        document_type="visa", status="saved", uploaded_count=1, matched_count=1, saved_at=datetime.now(UTC))
    session.add(batch)
    await session.flush()
    document = DistributedDocumentModel(id=uuid.uuid4(), batch_id=batch.id, agency_id=agency.id,
        group_id=group.id, passenger_id=passport.id, document_type="visa", detected_type="visa",
        original_filename="visa.pdf", storage_key="private-credential-storage", match_status="matched",
        match_confidence=0.99, extracted_name=passport.client_name, extracted_passport_number="EXAMPLE123")
    session.add(document)
    await session.flush()
    before = document.updated_at
    review = await dashboard(detail_fixture, "document_review", {"group_id": str(group.id), "document_type": "visa"}, data_path=["review_rows", 0, "documents"])
    assert review["data"][0]["id"] == str(document.id) and review["data"][0]["url"] is None
    assert review["data"][0]["extracted_name"] == passport.client_name
    eligibility = await dashboard(detail_fixture, "document_delivery_eligibility",
        {"group_id": str(group.id), "document_type": "visa"}, data_path=["recipients"])
    assert eligibility["data"][0]["passenger_id"] == str(passport.id)
    assert "private-credential-storage" not in json.dumps([review, eligibility])
    assert document.updated_at == before
    assert await session.scalar(select(func.count()).select_from(DocumentWhatsAppDeliveryModel)) == 0


async def test_image_library_and_ai_job_reads_do_not_ensure_original_or_dispatch(detail_fixture, monkeypatch):
    session, _, _, _, _, _, passport, _, _ = detail_fixture
    from app.infrastructure.database.passport_image_library_model import (
        PassportImageLibraryItemModel,
    )
    from app.presentation.api.v1.routes import passport_image_library
    from app.presentation.api.v1.routes.passport_routes import visa_ai_jobs

    async def forbidden(*args, **kwargs):
        raise AssertionError("A metadata read cannot prepare or restart image work")

    monkeypatch.setattr(passport_image_library, "_ensure_original_item", forbidden)
    monkeypatch.setattr(visa_ai_jobs, "_recover_and_dispatch_visa_ai_job", forbidden)
    passport.passport_photo_s3_key = "private/photo"
    await session.flush()
    images = await dashboard(detail_fixture, "passport_image_metadata",
        {"submission_id": str(passport.id), "image_type": "passport_front"}, data_path=["items"])
    assert images["data"] == []
    job = await dashboard(detail_fixture, "passport_active_ai_image_job", {"submission_id": str(passport.id)})
    assert job["data"] is None
    assert await session.scalar(select(func.count()).select_from(PassportImageLibraryItemModel)) == 0


async def test_all_delivery_kinds_preserve_saved_statuses_content_and_tenant_scope(detail_fixture):
    session, _, user, agency, other, group, passport, _, _ = detail_fixture
    broadcast = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Delivery")
    session.add(broadcast)
    await session.flush()
    recipient = WhatsAppBroadcastRecipientModel(id=uuid.uuid4(), agency_id=agency.id,
        broadcast_group_id=broadcast.id, phone_number="+919876543211", normalized_phone_number="919876543211")
    token = PassengerQRTokenModel(id=uuid.uuid4(), agency_id=agency.id, passenger_id=passport.id,
        token_hash="fixture-hash", qr_payload="private-qr-credential", token_version=1,
        expires_at=datetime.now(UTC) + timedelta(days=1), is_active=True)
    session.add_all([recipient, token])
    await session.flush()
    batch_id = uuid.uuid4()
    qr = PassengerQrWhatsAppDeliveryModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        passenger_id=passport.id, qr_token_id=token.id, send_batch_id=batch_id, template_name="qr-template",
        passenger_name=passport.client_name, phone_number=recipient.phone_number,
        normalized_phone_number=recipient.normalized_phone_number, template_parameter_values=[], status="processing",
        created_at=datetime.now(UTC) - timedelta(hours=2), status_updated_at=datetime.now(UTC) - timedelta(hours=2))
    log = WhatsAppMessageLogModel(id=uuid.uuid4(), agency_id=agency.id, broadcast_group_id=broadcast.id,
        recipient_id=recipient.id, batch_id=batch_id, message_type="welcome", status="delivered",
        rendered_message="Saved welcome text", template_name="welcome", normalized_phone_number=recipient.normalized_phone_number)
    welcome = WhatsAppPhoneWelcomeAttemptModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        broadcast_group_id=broadcast.id, batch_id=batch_id, normalized_phone_number=recipient.normalized_phone_number,
        passenger_ids=[str(passport.id)], template_name="welcome", rendered_message="Traveller welcome",
        header_parameter_values=[], template_parameter_values=[], status="submitted")
    session.add_all([qr, log, welcome])
    await session.flush()
    service = MCPDeliveryReadService(session, cursor_secret="cursor")
    for kind, row in (("qr", qr), ("broadcast", log), ("welcome", welcome)):
        listing = await service.list_records(user_id=user.id, kind=kind, agency_id=agency.id,
            batch_id=batch_id, include_contact_details=True)
        assert listing["items"][0]["id"] == str(row.id)
        assert listing["items"][0]["status"] == row.status
        foreign = await service.list_records(user_id=user.id, kind=kind, agency_id=other.id, batch_id=batch_id)
        assert foreign["items"] == []
        detail = await dashboard(detail_fixture, "delivery_record", {"kind": kind, "record_id": str(row.id)})
        assert "private-qr-credential" not in json.dumps(detail)
    assert qr.status == "processing" and log.status == "delivered" and welcome.status == "submitted"


async def test_regressed_reader_cannot_write_or_commit(detail_fixture, monkeypatch):
    session, _, _, _, _, _, passport, _, _ = detail_fixture
    from app.presentation.mcp import dashboard_read_tools

    async def malicious_read(current_user, session):
        await session.execute(update(PassportSubmissionModel).values(client_name="Tampered"))
        return {}

    monkeypatch.setattr(dashboard_read_tools, "dashboard_handler", lambda _: malicious_read)
    with pytest.raises(NonObservationalDashboardRead):
        await dashboard(detail_fixture, "platform_settings", {})
    assert await session.scalar(select(PassportSubmissionModel.client_name).where(PassportSubmissionModel.id == passport.id)) == "Example traveller"

    async def committing_read(current_user, session):
        await session.commit()
        return {}

    monkeypatch.setattr(dashboard_read_tools, "dashboard_handler", lambda _: committing_read)
    with pytest.raises(NonObservationalDashboardRead, match="commit"):
        await dashboard(detail_fixture, "platform_settings", {})


def test_large_text_nested_fields_and_all_rows_remain_readable_with_bound_cursors():
    projection = ReadProjection("secret")
    value = {"rows": [{"name": f"Person {index}", "details": "long content " * 4000} for index in range(51)]}
    first = projection.page(value, binding={"actor": "one"}, data_path=["rows"], page_size=5)
    assert first["completeness"] == "partial" and first["references"]
    ids, page = [], first
    while True:
        ids.extend(reference["data_path"][-1] for reference in page["references"])
        if not page["has_more"]:
            break
        page = projection.page(value, binding={"actor": "one"}, data_path=["rows"], page_size=5, cursor=page["next_cursor"])
    assert ids == list(range(51))
    pieces, text_page = [], projection.page(value, binding={"actor": "one"}, data_path=["rows", 0, "details"], page_size=5)
    while True:
        pieces.append(text_page["data"])
        if not text_page["has_more"]:
            break
        text_page = projection.page(value, binding={"actor": "one"}, data_path=["rows", 0, "details"], page_size=5, cursor=text_page["next_cursor"])
    assert "".join(pieces) == value["rows"][0]["details"]
    with pytest.raises(ValueError, match="scoped"):
        projection.page(value, binding={"actor": "two"}, data_path=["rows"], page_size=5, cursor=first["next_cursor"])
    value["rows"][0]["name"] = "Changed"
    with pytest.raises(ValueError, match="changed"):
        projection.page(value, binding={"actor": "one"}, data_path=["rows"], page_size=5, cursor=first["next_cursor"])
    clean, _ = scrub_read({"token": "credential", "rendered_message": "Use https://example.test/upload/credential to submit"})
    assert "credential" not in json.dumps(clean)


def test_projection_size_counts_long_paths_and_all_rows_stay_reachable():
    path = ["\\" * 255 for _ in range(18)]
    rows = [{"label": "large " * 20000, "token": "protected"} for _ in range(100)]
    root = rows
    for key in reversed(path):
        root = {key: root}
    projection = ReadProjection("secret")
    page = projection.page(root, binding={}, data_path=path, page_size=100)
    reached = []
    while True:
        assert len(json.dumps(page, ensure_ascii=False)) < 64000
        reached.extend(row["data_path"][-1] for row in page["references"])
        if not page["has_more"]:
            break
        page = projection.page(root, binding={}, data_path=path, page_size=100, cursor=page["next_cursor"])
    assert reached == list(range(100))


async def test_complete_delivery_history_passes_one_hundred_rows_and_filters(detail_fixture):
    session, _, user, agency, other, group, passport, _, _ = detail_fixture
    created = datetime.now(UTC) - timedelta(minutes=1)
    deliveries = [DocumentWhatsAppDeliveryModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        passenger_id=passport.id, send_batch_id=uuid.uuid4(), document_type="visa", document_filename="visa.pdf",
        template_name="document_template",
        passenger_name=passport.client_name, phone_number=passport.client_phone,
        normalized_phone_number="919876543211", status="read" if index % 2 else "submitted",
        created_at=created, status_updated_at=created) for index in range(107)]
    session.add_all(deliveries)
    await session.flush()
    service = MCPDeliveryReadService(session, cursor_secret="delivery")
    seen, page = [], await service.list_records(user_id=user.id, kind="document", group_id=group.id, page_size=25)
    assert page["status_counts"] == {"submitted": 54, "read": 53}
    while True:
        seen.extend(item["id"] for item in page["items"])
        assert all("phone_number" not in item for item in page["items"])
        if not page["has_more"]:
            break
        page = await service.list_records(user_id=user.id, kind="document", group_id=group.id, page_size=25, cursor=page["next_cursor"])
    assert len(seen) == len(set(seen)) == 107
    filtered = await service.list_records(user_id=user.id, kind="document", group_id=group.id,
        status="read", include_contact_details=True)
    assert filtered["total_matching_attempts"] == 53 and filtered["items"][0]["phone_number"]
    with pytest.raises(ValueError, match="scope"):
        await service.list_records(user_id=user.id, kind="document", group_id=group.id, agency_id=other.id)
    full = await dashboard(detail_fixture, "delivery_record", {"kind": "document", "record_id": str(deliveries[0].id)}, data_path=["document_filename"])
    assert full["data"] == "visa.pdf"


@pytest.mark.parametrize("view,parameters,scoped", [
    ("platform_settings", {}, False),
    ("whatsapp_templates", {}, False),
    ("menu_workspace", {}, True),
    ("rooming_workspace", {}, True),
    ("rooming_priority_fields", {}, True),
    ("tour_passengers", {}, True),
    ("tour_architecture", {}, False),
    ("coordinators", {}, False),
    ("managed_accounts", {}, False),
    ("staff_accounts", {}, False),
    ("email_connections", {}, False),
    ("email_activity", {}, False),
    ("email_reviews", {"review_status": "all"}, False),
    ("email_review_options", {}, False),
    ("personal_notifications", {}, False),
    ("audit_logs", {}, False),
    ("gc_agencies", {"limit": 10}, False),
    ("global_search", {"q": "Example"}, False),
])
async def test_dashboard_domains_execute_canonical_reads_without_business_changes(detail_fixture, view, parameters, scoped):
    session, _, _, agency, _, group, passport, _, _ = detail_fixture
    parameters = dict(parameters)
    definition = DASHBOARD_READS[view]
    if scoped and definition.group_parameter:
        parameters[definition.group_parameter] = str(group.id)
    before = passport.updated_at
    result = await dashboard(detail_fixture, view, parameters,
        agency_id=agency.id if scoped else None, page_size=5)
    assert result["view"] == view and result["content_trust"] == "untrusted_business_data"
    assert passport.updated_at == before


async def test_common_document_native_pages_reach_beyond_previous_two_hundred_cap(detail_fixture):
    from app.infrastructure.database.gc_mobile_models import (
        GCCommonDocumentModel,
        GCGroupAccessModel,
    )

    session, _, _, agency, _, group, _, _, _ = detail_fixture
    access = GCGroupAccessModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id)
    session.add(access)
    await session.flush()
    records = [GCCommonDocumentModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        gc_group_access_id=access.id, version=1, category="other", title=f"Document {index}",
        storage_key=f"private/common-{index}.pdf", safe_filename="common.pdf", media_type="application/pdf",
        byte_size=10, checksum_sha256="a" * 64, status="published", published_at=datetime.now(UTC), passenger_visible=True, sort_order=index)
        for index in range(207)]
    session.add_all(records)
    await session.flush()
    seen, offset = set(), 0
    while True:
        result = await dashboard(detail_fixture, "gc_common_documents",
            {"group_id": str(group.id), "offset": offset, "limit": 10}, data_path=["items"])
        seen.update(row["id"] for row in result["data"])
        next_offset = result["website_pagination"]["next_offset"]
        if next_offset is None:
            break
        assert result["completeness"] == "partial"
        offset = next_offset
    assert seen == {str(row.id) for row in records}


async def test_qr_root_cursor_ignores_query_clock_and_reaches_every_field(detail_fixture):
    group = detail_fixture[5]
    args = {"group_id": str(group.id)}
    result = await dashboard(detail_fixture, "group_qr_metadata", args, page_size=1)
    keys = set(result["data"])
    while result["has_more"]:
        result = await dashboard(detail_fixture, "group_qr_metadata", args, page_size=1, cursor=result["next_cursor"])
        keys.update(result["data"])
    assert "passengers" in keys and "group_id" in keys


async def test_owner_email_review_pages_reach_beyond_previous_two_hundred_fifty_cap(detail_fixture):
    from app.infrastructure.database.email_models import EmailReviewItemModel
    from tests.integration.test_mcp_content_reads import mailbox

    session, _, user, agency, _, _, _, _, _ = detail_fixture
    _, messages = await mailbox(session, user, agency, count=257)
    reviews = [EmailReviewItemModel(id=uuid.uuid4(), agency_id=agency.id, owner_user_id=user.id,
        message_id=message.id, review_type="possible_revision", proposed_action="review",
        proposed_payload={}, evidence={}, status="open") for message in messages]
    session.add_all(reviews)
    await session.flush()
    seen, offset = set(), 0
    while True:
        result = await dashboard(detail_fixture, "email_reviews",
            {"review_status": "all", "offset": offset, "limit": 10}, data_path=["items"])
        seen.update(row["id"] for row in result["data"])
        next_offset = result["website_pagination"]["next_offset"]
        if next_offset is None:
            break
        offset = next_offset
    assert seen == {str(row.id) for row in reviews}


@pytest.mark.parametrize("text_value", ["🌏" * 40000, "\n\\\"" * 40000], ids=["unicode", "escaped-text"])
def test_long_imported_text_bounds_encoded_bytes_and_retains_every_character(text_value):
    projection = ReadProjection("secret")
    args = dict(binding={"actor": "one"}, data_path=["imported_fields", "Original column"], page_size=10)
    value = {"imported_fields": {"Original column": text_value}}
    result = projection.page(value, **args)
    pieces = []
    while True:
        assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) < 64000
        pieces.append(result["data"])
        if not result["has_more"]:
            break
        result = projection.page(value, **args, cursor=result["next_cursor"])
    assert "".join(pieces) == text_value
