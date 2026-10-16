"""Exact matching reuse never treats timestamps as complete source revisions."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientForComparison,
    SubmissionForComparison,
)
from app.infrastructure.repositories import passport_whatsapp_comparison_cache as module


@pytest.fixture
def source():
    agency_id, group_id, broadcast_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(UTC)
    recipient = RecipientForComparison(
        id=uuid.uuid4(), broadcast_id=broadcast_id, broadcast_name="Synthetic roster",
        name="Synthetic recipient", phone="+919876543210", updated_at=now,
        imported_fields={"staff_code": "EMP1"}, matching_field_keys=("staff_code",),
    )
    submission = SubmissionForComparison(
        id=uuid.uuid4(), name="Synthetic submission", client_phone="+919876543210",
        family_head_phone=None, updated_at=now,
        staff_metadata={"staff_code": "EMP1", "nested": {"value": "before"}},
        custom_answers=({"key": "department", "value": "before"},),
        has_public_collection_contact=True,
    )
    return agency_id, group_id, recipient, submission


async def test_unchanged_inputs_reuse_comparison_and_nested_edits_invalidate(source, monkeypatch):
    agency_id, group_id, recipient, submission = source
    compare = Mock(wraps=module.compare_group_submissions)
    monkeypatch.setattr(module, "compare_group_submissions", compare)
    cache = module.PassportWhatsAppComparisonCache()

    async def load():
        return await cache.compare(agency_id=agency_id, group_id=group_id,
                                   recipients=[recipient], submissions=[submission])

    first = await load()
    assert await load() == first
    assert compare.call_count == 1
    submission.staff_metadata["nested"]["value"] = "after"
    await load()
    assert compare.call_count == 2
    submission.custom_answers[0]["value"] = "after"
    await load()
    assert compare.call_count == 3
    recipient.imported_fields["staff_code"] = "EMP2"
    await load()
    assert compare.call_count == 4
    # Every edit above deliberately retained both timestamps.
    assert recipient.updated_at == submission.updated_at


async def test_policy_membership_ambiguity_resolution_and_scope_invalidate(source, monkeypatch):
    agency_id, group_id, recipient, submission = source
    compare = Mock(wraps=module.compare_group_submissions)
    monkeypatch.setattr(module, "compare_group_submissions", compare)
    cache = module.PassportWhatsAppComparisonCache()

    async def load(recipients, submissions, *, scoped_group=group_id):
        return await cache.compare(agency_id=agency_id, group_id=scoped_group,
                                   recipients=recipients, submissions=submissions)

    await load([recipient], [submission])
    changed_policy = replace(recipient, matching_field_keys=("passport_number",))
    await load([changed_policy], [submission])
    assert compare.call_count == 2
    duplicate = replace(submission, id=uuid.uuid4())
    duplicate_recipient = replace(recipient, id=uuid.uuid4(), phone="+919876543211")
    ambiguous = await load([recipient, duplicate_recipient], [submission])
    assert compare.call_count == 3
    assert any(row.status == "needs_review" for row in ambiguous)
    # A current roster resolution excludes a submission before cache lookup.
    await load([recipient], [duplicate])
    assert compare.call_count == 4
    await load([], [duplicate])
    assert compare.call_count == 5
    await load([], [duplicate], scoped_group=uuid.uuid4())
    assert compare.call_count == 6


async def test_input_order_does_not_recompute_or_share_mutable_match_results(source, monkeypatch):
    agency_id, group_id, recipient, submission = source
    second = replace(recipient, id=uuid.uuid4(), phone="+919876543211",
                     imported_fields={"staff_code": "EMP2"})
    compare = Mock(wraps=module.compare_group_submissions)
    monkeypatch.setattr(module, "compare_group_submissions", compare)
    cache = module.PassportWhatsAppComparisonCache()
    first = await cache.compare(agency_id=agency_id, group_id=group_id,
                                recipients=[recipient, second], submissions=[submission])
    second_result = await cache.compare(agency_id=agency_id, group_id=group_id,
                                       recipients=[second, recipient], submissions=[submission])
    assert first == second_result and compare.call_count == 1
    for row in first:
        for fields in row.recipient_fields:
            fields.fields.clear()
    third = await cache.compare(agency_id=agency_id, group_id=group_id,
                               recipients=[recipient, second], submissions=[submission])
    assert third == second_result
