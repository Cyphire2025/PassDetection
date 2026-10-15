"""Malformed JSON must not grant operational authority or crash a SQL lookup."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.application.travellers.enrollment import enroll_submission
from app.application.travellers.retained_authority import (
    has_retained_authority,
    retained_authority_predicate,
)
from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel
from tests.unit.application.test_traveller_enrollment import _fixture


@pytest.mark.asyncio
async def test_sql_and_object_authority_agree_for_malformed_evidence(db_session):
    ctx = await _fixture(db_session)
    result = await enroll_submission(db_session, ctx.request, ctx.crypto)
    person = await db_session.get(TravellerProfileModel, result.traveller_id)
    history = {"authority_kind": "operator_history_v1", "actor_user_id": "staff", "policy_revision": 1}
    staff = {"authority_kind": "operator_staff_record_v1", "actor_user_id": "staff", "reason": "edit", "source": "record"}
    cases = [(history, True), (staff, True), ({}, False), ([], False), ([history], False), ("evidence", False)]
    for value in [None, True, False, 0, -1, 2147483648, 1.0, "1", " ", "999999999999999999999", {}, []]:
        cases.append(({**history, "policy_revision": value}, False))
    cases.append(({**history, "policy_revision": 2147483647}, True))
    for key in ["actor_user_id", "reason", "source"]:
        for value in [None, "", " \t\n", 1, True, {}, []]:
            cases.append(({**staff, key: value}, False))
    for evidence, expected in cases:
        person.reuse_permission_status = "unknown"
        person.reuse_permission_evidence = evidence
        person.status = "active"
        await db_session.flush()
        found = await db_session.scalar(select(TravellerProfileModel.id).where(
            TravellerProfileModel.id == person.id, retained_authority_predicate()))
        assert has_retained_authority(person) is expected, evidence
        assert (found is not None) is expected, evidence
    for permission, status, deleted, expected in [
        ("granted", "active", None, True), ("withdrawn", "active", None, False),
        ("unknown", "blocked", None, False), ("unknown", "review_required", None, False),
        ("unknown", "active", datetime.now(UTC), False),
    ]:
        person.reuse_permission_status, person.status, person.deleted_at = permission, status, deleted
        person.reuse_permission_evidence = history
        await db_session.flush()
        found = await db_session.scalar(select(TravellerProfileModel.id).where(
            TravellerProfileModel.id == person.id, retained_authority_predicate()))
        assert has_retained_authority(person) is expected
        assert (found is not None) is expected


def test_postgres_guarded_numeric_cast_does_not_cast_untrusted_json_directly():
    compiled = str(retained_authority_predicate().compile(dialect=postgresql.dialect()))
    assert "CASE WHEN jsonb_typeof" in compiled
    assert "^[1-9][0-9]{0,9}$" in compiled
    assert "AS bigint) BETWEEN 1 AND 2147483647 ELSE false END" in compiled
