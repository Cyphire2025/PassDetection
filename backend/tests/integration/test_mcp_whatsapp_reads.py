"""Live relational audiences and provider-state evidence without actual sends."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.whatsapp_reads import MCPWhatsAppReadService
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
)


@pytest.fixture
async def whatsapp_reads(db_session):
    actor = UserModel(id=uuid.uuid4(), email="wa-reader@example.test", hashed_password="fixture",
                      full_name="Reader", role="super_admin", is_active=True)
    first = AgencyModel(id=uuid.uuid4(), name="First", email="first@example.test")
    second = AgencyModel(id=uuid.uuid4(), name="Second", email="second@example.test")
    db_session.add_all([actor, first, second])
    await db_session.flush()
    lists = [WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Shared",
              created_at=datetime.now(UTC) - timedelta(minutes=2)) for agency in (first, second)]
    db_session.add_all(lists)
    await db_session.flush()
    return db_session, actor, first, second, lists, MCPWhatsAppReadService(db_session, cursor_secret="test-whatsapp-cursor")


def recipient(group, index=0, **fields):
    return WhatsAppBroadcastRecipientModel(id=uuid.uuid4(), broadcast_group_id=group.id,
        agency_id=group.agency_id, name=f"Recipient {index}", phone_number=f"+919800{index:06}",
        normalized_phone_number=f"919800{index:06}", created_at=datetime.now(UTC) - timedelta(minutes=1), **fields)


@pytest.mark.asyncio
async def test_empty_duplicate_named_broadcasts_and_agency_filters(whatsapp_reads):
    _, actor, first, second, _, service = whatsapp_reads
    result = await service.list_broadcasts(user_id=actor.id, name="shared")
    assert result["names_are_not_unique"] is True and len(result["items"]) == 2
    assert {row["agency_id"] for row in result["items"]} == {str(first.id), str(second.id)}
    assert all(all(count == 0 for count in row["counts"].values()) for row in result["items"])
    filtered = await service.list_broadcasts(user_id=actor.id, agency_id=first.id)
    assert len(filtered["items"]) == 1
    assert "recipient_opt_in_confirmed_at" not in filtered["items"][0]


@pytest.mark.asyncio
async def test_count_rosters_import_only_archive_and_tenant_consistent_links(whatsapp_reads):
    session, actor, first, second, lists, service = whatsapp_reads
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=first.id, name="Import", token=uuid.uuid4().hex, import_only=True)
    session.add(group)
    await session.flush()
    passports = [PassportSubmissionModel(id=uuid.uuid4(), group_id=group.id, agency_id=first.id,
                 client_name=f"Person {index}", image_s3_key=f"fixture/{index}") for index in range(2)]
    active, removed = recipient(lists[0]), recipient(lists[0], 1, removed_at=datetime.now(UTC))
    session.add_all([*passports, active, removed])
    await session.flush()
    for target in lists:
        session.add(ClientGroupWhatsAppBroadcastLinkModel(client_group_id=group.id,
                    broadcast_group_id=target.id, agency_id=first.id))
    for passport in passports:
        session.add(WhatsAppBroadcastSourceContactModel(id=uuid.uuid4(), agency_id=first.id,
                    broadcast_group_id=lists[0].id, source_group_id=group.id, source_submission_id=passport.id,
                    recipient_id=active.id, name=passport.client_name))
    session.add(WhatsAppBroadcastRejectedContactModel(id=uuid.uuid4(), agency_id=first.id,
        broadcast_group_id=lists[0].id, source_file_name="fixture.xlsx", sheet_name="Sheet1",
        row_number=3, reason_code="invalid_phone", reason="Invalid", fingerprint="a" * 64))
    # A corrupt cross-agency recipient row must not inflate the requested agency.
    session.add(WhatsAppBroadcastRecipientModel(id=uuid.uuid4(), agency_id=second.id,
        broadcast_group_id=lists[0].id, phone_number="+919999999999", normalized_phone_number="919999999999"))
    await session.flush()
    result = await service.list_broadcasts(user_id=actor.id, group_id=group.id)
    assert len(result["items"]) == 1
    assert result["items"][0]["has_import_only_source"] is True
    assert result["items"][0]["counts"] == {"active_recipient_entries": 1, "source_traveller_rows": 2, "rejected_contact_rows": 1}
    source = await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id, kind="source_contacts")
    assert len(source["items"]) == 2 and source["items"][0]["recipient_id"] == str(active.id)
    rejected = await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id, kind="rejected_contacts")
    assert rejected["items"][0]["reason_code"] == "invalid_phone"
    lists[0].archived_at = datetime.now(UTC)
    await session.flush()
    assert not (await service.list_broadcasts(user_id=actor.id, group_id=group.id))["items"]
    assert len((await service.list_broadcasts(user_id=actor.id, group_id=group.id, include_archived=True))["items"]) == 1


@pytest.mark.asyncio
async def test_audience_contacts_are_opt_in_audited_and_never_send_eligibility(whatsapp_reads):
    session, actor, _, second, lists, service = whatsapp_reads
    active, removed = recipient(lists[0]), recipient(lists[0], 1, removed_at=datetime.now(UTC))
    session.add_all([active, removed])
    await session.flush()
    page = await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id)
    assert len(page["items"]) == 1 and "normalized_phone_number" not in page["items"][0]
    assert page["send_eligibility_evaluated"] is False
    detailed = await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id,
                                          include_removed=True, include_contact_details=True)
    assert len(detailed["items"]) == 2 and detailed["items"][0]["normalized_phone_number"]
    audit = (await session.execute(select(AuditLogModel).where(AuditLogModel.action == "mcp.whatsapp.contact_read"))).scalar_one()
    assert audit.metadata_json == {"authorized_result_count": 2}
    assert active.normalized_phone_number not in json.dumps(audit.metadata_json)
    with pytest.raises(ValueError, match="agency"):
        await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id, agency_id=second.id)


@pytest.mark.asyncio
async def test_saved_support_contacts_are_bounded_scoped_and_not_message_recipients(whatsapp_reads):
    session, actor, first, second, lists, service = whatsapp_reads
    created = datetime.now(UTC) - timedelta(minutes=1)
    contacts = [WhatsAppBroadcastSupportContactModel(
        id=uuid.uuid4(), broadcast_group_id=lists[0].id, agency_id=first.id,
        name="Shared support name", phone_number=f"+9198765432{index:02}",
        normalized_phone_number=f"9198765432{index:02}", sort_order=index,
        created_at=created,
    ) for index in range(3)]
    # Even a corrupt cross-agency row must not leak through the broadcast filter.
    session.add_all([*contacts, WhatsAppBroadcastSupportContactModel(
        id=uuid.uuid4(), broadcast_group_id=lists[0].id, agency_id=second.id,
        name="Other agency private support", phone_number="+919999999999",
        normalized_phone_number="919999999999",
    )])
    await session.flush()
    page = await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id,
        agency_id=first.id, kind="support_contacts", page_size=1)
    first_cursor, rows = page["next_cursor"], []
    while True:
        assert page["audience_kind"] == "support_contacts"
        assert page["send_eligibility_evaluated"] is False
        assert "not message recipients" in page["notice"]
        rows.extend(page["items"])
        if not page["has_more"]:
            assert page["completeness"] == "complete"
            break
        assert page["completeness"] == "partial" and len(page["items"]) == 1
        page = await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id,
            agency_id=first.id, kind="support_contacts", page_size=1, cursor=page["next_cursor"])
    assert {row["id"] for row in rows} == {str(contact.id) for contact in contacts}
    assert len(rows) == 3
    assert all(set(row) == {"id", "created_at", "name", "sort_order"} for row in rows)
    assert "9198765432" not in json.dumps(rows) and "Other agency" not in json.dumps(rows)
    for changes in ({"kind": "recipients"}, {"include_contact_details": True}):
        args = dict(user_id=actor.id, broadcast_id=lists[0].id, agency_id=first.id,
                    kind="support_contacts", page_size=1, cursor=first_cursor)
        with pytest.raises(ValueError):
            await service.list_audience(**(args | changes))
    empty = await service.list_audience(user_id=actor.id, broadcast_id=lists[1].id,
                                       kind="support_contacts")
    assert empty["items"] == [] and empty["completeness"] == "complete"
    assert not (await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id))["items"]


@pytest.mark.asyncio
async def test_support_phone_opt_in_is_audited_and_current_authority_is_required(whatsapp_reads):
    session, actor, first, second, lists, service = whatsapp_reads
    contact = WhatsAppBroadcastSupportContactModel(
        id=uuid.uuid4(), broadcast_group_id=lists[0].id, agency_id=first.id,
        name="Help desk", phone_number="+919876543299", normalized_phone_number="919876543299",
    )
    session.add(contact)
    await session.flush()
    detailed = await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id,
                                         kind="support_contacts", include_contact_details=True)
    assert detailed["items"][0]["normalized_phone_number"] == contact.normalized_phone_number
    audit = (await session.execute(select(AuditLogModel).where(
        AuditLogModel.action == "mcp.whatsapp.contact_read"))).scalar_one()
    assert audit.metadata_json == {"authorized_result_count": 1}
    assert contact.normalized_phone_number not in json.dumps(audit.metadata_json)
    with pytest.raises(ValueError, match="agency"):
        await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id,
                                   agency_id=second.id, kind="support_contacts")
    with pytest.raises(ValueError, match="removed"):
        await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id,
                                   kind="support_contacts", include_removed=True)
    actor.role = "agency_admin"
    await session.flush()
    with pytest.raises(MCPAuthError):
        await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id,
                                   kind="support_contacts")


@pytest.mark.asyncio
async def test_batch_exact_receipts_stalled_unknown_and_original_destination(whatsapp_reads):
    session, actor, _, _, lists, service = whatsapp_reads
    people = [recipient(lists[0], index) for index in range(9)]
    session.add_all(people)
    await session.flush()
    batch = uuid.uuid4()
    statuses = ["queued", "processing", "submitted", "sent", "delivered", "read", "failed", "delivery_unknown", "new_unknown"]
    logs = [WhatsAppMessageLogModel(id=uuid.uuid4(), batch_id=batch, broadcast_group_id=lists[0].id,
        agency_id=lists[0].agency_id, recipient_id=person.id, message_type="passport_link", status=status,
        normalized_phone_number="919700000000", error_message="SECRET_PROVIDER_ERROR", rendered_message="SECRET_CONTENT",
        provider_message_id="SECRET_PROVIDER_ID", status_updated_at=datetime.now(UTC) - timedelta(minutes=31 if status == "processing" else 1),
        created_at=datetime.now(UTC) - timedelta(minutes=40)) for status, person in zip(statuses, people, strict=True)]
    session.add_all(logs)
    await session.flush()
    result = await service.batch_status(user_id=actor.id, broadcast_id=lists[0].id, batch_id=batch)
    assert result["total_message_attempts"] == 9
    assert result["confirmed_delivery_count"] == 2
    assert result["status_counts"]["submitted"] == result["status_counts"]["sent"] == 1
    assert result["status_counts"]["stalled"] == 1 and result["status_counts"]["processing"] == 0
    assert result["stored_status_counts"]["processing"] == 1 and logs[1].status == "processing"
    assert result["status_counts"]["unrecognized"] == 1
    assert "SECRET" not in json.dumps(result) and "normalized_phone_number" not in result["items"][0]
    detailed = await service.batch_status(user_id=actor.id, broadcast_id=lists[0].id, batch_id=batch,
                                          include_contact_details=True)
    assert {row["normalized_phone_number"] for row in detailed["items"]} == {"919700000000"}
    with pytest.raises(ValueError, match="batch"):
        await service.batch_status(user_id=actor.id, broadcast_id=lists[1].id, batch_id=batch)
    # Reconciliation changes only the live evidence; no inferred completion.
    logs[6].status = "delivered"
    await session.flush()
    updated = await service.batch_status(user_id=actor.id, broadcast_id=lists[0].id, batch_id=batch)
    assert updated["confirmed_delivery_count"] == 3 and updated["status_counts"]["failed"] == 0


@pytest.mark.asyncio
async def test_ten_recipient_batch_with_three_failures_remains_seven_delivered(whatsapp_reads):
    session, actor, _, _, lists, service = whatsapp_reads
    batch = uuid.uuid4()
    people = [recipient(lists[0], index) for index in range(10)]
    session.add_all(people)
    await session.flush()
    session.add_all([WhatsAppMessageLogModel(id=uuid.uuid4(), batch_id=batch, broadcast_group_id=lists[0].id,
        agency_id=lists[0].agency_id, recipient_id=person.id, message_type="welcome",
        status="failed" if index < 3 else "delivered") for index, person in enumerate(people)])
    await session.flush()
    result = await service.batch_status(user_id=actor.id, broadcast_id=lists[0].id, batch_id=batch)
    assert result["status_counts"]["failed"] == 3 and result["confirmed_delivery_count"] == 7


@pytest.mark.asyncio
async def test_audience_keysets_ties_contact_scope_actor_and_new_rows(whatsapp_reads):
    session, actor, _, _, lists, service = whatsapp_reads
    stamp = datetime.now(UTC) - timedelta(minutes=3)
    people = [recipient(lists[0], index) for index in range(113)]
    for index, person in enumerate(people):
        person.created_at = stamp
        person.id = uuid.UUID(f"bbbbbbbb-bbbb-bbbb-bbbb-{index + 1:012x}")
    session.add_all(people)
    await session.flush()
    page = await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id, page_size=17)
    first_cursor = page["next_cursor"]
    later = recipient(lists[0], 999)
    later.created_at = datetime.now(UTC) + timedelta(seconds=1)
    session.add(later)
    await session.flush()
    seen = [row["id"] for row in page["items"]]
    while page["has_more"]:
        page = await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id, page_size=17, cursor=page["next_cursor"])
        seen.extend(row["id"] for row in page["items"])
    assert len(seen) == len(set(seen)) == 113 and str(later.id) not in seen
    for changed in ({"include_contact_details": True}, {"kind": "source_contacts"}, {"include_removed": True}):
        with pytest.raises(ValueError, match="scoped cursor"):
            await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id, page_size=17, cursor=first_cursor, **changed)
    with pytest.raises(ValueError, match="cursor"):
        await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id, page_size=17, cursor=first_cursor[:-1] + ("0" if first_cursor[-1] != "0" else "1"))
    state = service.cursors.read(first_cursor, dict(query="audience", user_id=actor.id, broadcast_id=lists[0].id,
        agency_id=None, kind="recipients", include_removed=False, include_contact_details=False, page_size=17))
    state["expires"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError, match="expired"):
        await service.list_audience(user_id=actor.id, broadcast_id=lists[0].id, page_size=17, cursor=service.cursors.encode(state))


@pytest.mark.asyncio
async def test_active_role_bounds_and_literal_name_search(whatsapp_reads):
    session, actor, _, _, lists, service = whatsapp_reads
    lists[0].name = "100%_Tour"
    await session.flush()
    result = await service.list_broadcasts(user_id=actor.id, name="%_")
    assert [row["id"] for row in result["items"]] == [str(lists[0].id)]
    for size in (0, 101, True, 1.5):
        with pytest.raises(ValueError):
            await service.list_broadcasts(user_id=actor.id, page_size=size)
    actor.role = "agency_staff"
    await session.flush()
    with pytest.raises(MCPAuthError):
        await service.list_broadcasts(user_id=actor.id)
    actor.role, actor.is_active = "super_admin", False
    await session.flush()
    with pytest.raises(MCPAuthError):
        await service.list_broadcasts(user_id=actor.id)


def test_existing_receipt_symbols_reexport_the_same_shared_constants():
    from app.domain import whatsapp_delivery_status as shared
    from app.presentation.api.v1.routes import whatsapp_delivery_support as existing
    for name in ("WHATSAPP_ACCEPTED_STATUSES", "WHATSAPP_ACCEPTED_STATUS_RANK", "WHATSAPP_WEBHOOK_STATUSES",
                 "WHATSAPP_IN_PROGRESS_STATUSES", "WHATSAPP_UNCERTAIN_STATUSES", "WHATSAPP_STALE_CLAIM_AGE"):
        assert getattr(existing, name) is getattr(shared, name)
