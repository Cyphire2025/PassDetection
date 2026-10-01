"""Complete compact comparisons, shared matching policy and read authority."""
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.phone_difference_reads import (
    MCPPhoneDifferenceReadService,
    compare_matched_phones,
    difference_page,
)
from app.application.use_cases.whatsapp.group_submission_matching import SubmissionMatchRow
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from tests.integration.test_mcp_dashboard_detail_reads import detail_fixture as detail_fixture


def pair(submission_phone, broadcast_phone, *, status="submitted", confidence="high"):
    submission_id, recipient_id, broadcast_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    submission = SimpleNamespace(id=submission_id, client_name="A Traveller", client_phone=submission_phone,
        confirmed_fields={"Staff Code": "confirmed"}, extracted_fields={}, staff_metadata={"staff_code": "old"})
    recipient = SimpleNamespace(id=recipient_id, broadcast_group_id=broadcast_id, name="A T",
        phone_number=broadcast_phone, imported_fields={"Staff Code": "confirmed"})
    row = SubmissionMatchRow(status=status, confidence=confidence, match_basis="selected_field",
        normalized_phone=None, recipient_ids=(recipient_id,), submission_ids=(submission_id,),
        broadcast_ids=(broadcast_id,), broadcast_names=("Broadcast",), recipient_names=("A T",),
        submission_names=("A Traveller",), updated_at=datetime.now(UTC))
    return [row], {submission_id: submission}, {recipient_id: recipient}, broadcast_id


@pytest.mark.parametrize("first,second,category", [
    ("9876543210", "+91 98765 43210", "same_phone_pairs"),
    ("0091-9876543210", "+919876543210", "same_phone_pairs"),
    ("+919876543210", "+919876543211", "different_phone_pairs"),
    (None, "+919876543211", "missing_phone_pairs"),
    ("not-a-phone", "+919876543211", "invalid_phone_pairs"),
])
def test_phone_comparison_normalizes_and_distinguishes_missing_invalid(first, second, category):
    items, counts = compare_matched_phones(*pair(first, second))
    assert counts[category] == 1 and counts["compared_match_pairs"] == 1
    if items:
        assert items[0]["staff_code"] == "confirmed"
        assert items[0]["staff_code_source"] == "confirmed_fields.Staff Code"
        assert items[0]["broadcast_staff_code"] == "confirmed"


@pytest.mark.parametrize("status,confidence", [
    ("multiple_submissions", "high"), ("needs_review", "medium"),
    ("replacement", "high"), ("rejected_upload", "high"), ("submitted", "medium"),
])
def test_no_new_matches_or_guesses_from_review_manual_or_ambiguous_rows(status, confidence):
    items, counts = compare_matched_phones(*pair("9876543210", "9876543211", status=status, confidence=confidence))
    assert items == [] and counts["compared_match_pairs"] == 0


def test_duplicate_rows_do_not_duplicate_comparison_pairs():
    rows, submissions, recipients, broadcast = pair("9876543210", "9876543211")
    items, counts = compare_matched_phones([*rows, *rows], submissions, recipients, broadcast)
    assert len(items) == 1 and counts["unique_people_with_differences"] == 1


def test_utf8_and_json_escape_budget_preserves_full_rows_with_continuation():
    items = [{"name": "旅\\\"" * 300, "id": index} for index in range(30)]
    ids, offset = [], 0
    while True:
        page, following = difference_page(items, offset=offset, page_size=100)
        assert len(json.dumps(page, ensure_ascii=True).encode()) <= 24000
        ids.extend(item["id"] for item in page)
        if following is None:
            break
        offset = following
    assert ids == list(range(30))


async def seed(fixture, count=2):
    session, _, _, agency, _, group, passport, _, _ = fixture
    passport.staff_metadata = {"staff_code": "unmatched-fixture"}
    broadcast = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Phone comparison")
    session.add(broadcast)
    await session.flush()
    session.add(ClientGroupWhatsAppBroadcastLinkModel(id=uuid.uuid4(), agency_id=agency.id,
        client_group_id=group.id, broadcast_group_id=broadcast.id, matching_field_keys=["staff_code"]))
    submissions, recipients = [], []
    for index in range(count):
        raw = f"+919900{index:06d}"
        different = index < 9
        submissions.append(PassportSubmissionModel(id=uuid.uuid4(), group_id=group.id, agency_id=agency.id,
            client_name=f"Passenger {index:04d}", client_phone=f"+918800{index:06d}" if different else raw,
            image_s3_key="private/fixture", status="staff_approved", staff_metadata={"staff_code": str(10000 + index)}))
        recipients.append(WhatsAppBroadcastRecipientModel(id=uuid.uuid4(), agency_id=agency.id,
            broadcast_group_id=broadcast.id, name=f"P {index:04d}", phone_number=raw,
            normalized_phone_number=raw, imported_fields={"Staff Code": str(10000 + index)}))
    session.add_all([*submissions, *recipients])
    await session.flush()
    return broadcast, submissions, recipients


async def test_bulk_comparison_returns_only_nine_differences_without_field_references(detail_fixture):
    broadcast, submissions, recipients = await seed(detail_fixture, 666)
    session, _, user, agency, _, group, _, _, _ = detail_fixture
    service = MCPPhoneDifferenceReadService(session, cursor_secret="fixture-secret")
    before = [item.client_phone for item in submissions]
    result = await service.read(user_id=user.id, group_id=group.id, broadcast_id=broadcast.id)
    assert result["total"] == 9 and len(result["items"]) == 9, result["counts"]
    assert result["counts"]["compared_match_pairs"] == 666
    assert result["counts"]["same_phone_pairs"] == 657
    assert result["counts"]["different_phone_pairs"] == 9
    assert result["completeness"] == "complete" and result["next_offset"] is None
    assert "_mcp_read_reference" not in json.dumps(result)
    assert [item.client_phone for item in submissions] == before
    assert result["agency_id"] == str(agency.id)
    assert len(recipients) == 666


async def test_continuation_is_complete_and_rejects_changed_matching_inputs(detail_fixture):
    broadcast, submissions, _ = await seed(detail_fixture)
    session, _, user, _, _, group, _, _, _ = detail_fixture
    service = MCPPhoneDifferenceReadService(session, cursor_secret="fixture-secret")
    first = await service.read(user_id=user.id, group_id=group.id, page_size=1)
    assert len(first["items"]) == 1 and first["has_more"] is True
    second = await service.read(user_id=user.id, group_id=group.id, page_size=1,
        offset=first["next_offset"], snapshot_revision=first["snapshot_revision"])
    assert not second["has_more"] and first["items"][0]["submission_id"] != second["items"][0]["submission_id"]
    with pytest.raises(ValueError, match="snapshot_revision"):
        await service.read(user_id=user.id, group_id=group.id, offset=1)
    submissions[0].client_phone = "+919900000000"
    await session.flush()
    with pytest.raises(ValueError, match="changed"):
        await service.read(user_id=user.id, group_id=group.id, offset=1, snapshot_revision=first["snapshot_revision"])
    assert broadcast.name == "Phone comparison"


async def test_unlinked_broadcast_agency_and_live_role_are_checked(detail_fixture):
    broadcast, _, _ = await seed(detail_fixture)
    session, _, user, agency, other, group, _, _, _ = detail_fixture
    service = MCPPhoneDifferenceReadService(session, cursor_secret="fixture-secret")
    with pytest.raises(ValueError, match="linked"):
        await service.read(user_id=user.id, group_id=group.id, broadcast_id=uuid.uuid4())
    with pytest.raises(ValueError, match="scope"):
        await service.read(user_id=user.id, group_id=group.id, agency_id=other.id)
    user.role = "agency_admin"
    await session.flush()
    with pytest.raises(MCPAuthError):
        await service.read(user_id=user.id, group_id=group.id, broadcast_id=broadcast.id, agency_id=agency.id)
