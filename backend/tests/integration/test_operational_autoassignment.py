"""An operator match is usable immediately and never fakes a traveller action."""
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.application.travellers.operational_autoassignment import assign_operational_traveller
from app.domain.services.traveller_suitability import add_calendar_months
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import TravellerParticipationModel
from tests.integration.traveller_reuse_fixtures import reuse_context, seed_person


async def assign(service, group, person):
    return await assign_operational_traveller(service.session, group=group, person_id=person.profile.id,
        source_kind="whatsapp_recipient", source_row_key=str(uuid.uuid4()),
        evidence={"matched_fields": ["name", "passport_number", "date_of_birth"]},
        crypto=service.crypto, now=datetime.now(UTC))


@pytest.mark.asyncio
async def test_autoassignment_is_immediate_idempotent_and_keeps_confirmation_separate(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    person.profile.reuse_permission_status = "unknown"
    person.profile.reuse_permission_evidence = {"authority_kind": "operator_history_v1", "actor_user_id": str(uuid.uuid4()), "policy_revision": 1}
    await db_session.flush()
    assert await assign(service, group, person) == "assigned"
    participation = await db_session.scalar(select(TravellerParticipationModel))
    source = await db_session.get(PassportSubmissionModel, participation.source_submission_id)
    assert participation.status == "accepted" and participation.accepted_at is not None
    assert participation.confirmations["information_confirmed"] is False
    assert source.status == "confirmed" and source.client_reviewed_at is None
    assert source.staff_metadata["reuse_assignment"] == "automatic"
    assert source.image_s3_key == person.asset.object_key
    assert source.client_phone == person.phone
    assert source.confirmed_fields["passport_number"] == person.number
    assert "s3_key" not in source.confirmed_fields and "unapproved_internal_field" not in source.confirmed_fields
    assert person.profile.reuse_permission_status == "unknown" and "consent" not in person.profile.reuse_permission_evidence
    assert await assign(service, group, person) == "assigned"
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changed,expected", [("expiry", "replacement_required"), ("missing_asset", "replacement_required"),
    ("withdrawn", "unavailable"), ("wrong_company", "unavailable"), ("closed", "unavailable"),
    ("pending_asset", "assets_pending"), ("no_authority", "unavailable")])
async def test_autoassignment_denies_unsafe_or_out_of_scope_sources(db_session, test_settings, changed, expected):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    if changed == "expiry":
        person.document.expiry_date = add_calendar_months(group.travel_date, 6)
    elif changed == "missing_asset":
        person.asset.availability = "unreadable"
    elif changed == "withdrawn":
        person.profile.reuse_permission_status = "withdrawn"
    elif changed == "no_authority":
        person.profile.reuse_permission_status = "unknown"
        person.profile.reuse_permission_evidence = {}
    elif changed == "pending_asset":
        person.asset.availability = "pending"
    elif changed == "wrong_company":
        _, _, different = await reuse_context(db_session, test_settings)
        group = different
    elif changed == "closed":
        group.status = "closed"
    await db_session.flush()
    assert await assign(service, group, person) == expected
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    member = await db_session.scalar(select(TravellerParticipationModel))
    if expected == "replacement_required":
        assert member is not None and member.status == "pending"
        assert member.source_submission_id is None and member.document_revision_id is None
        assert member.accepted_at is None and member.confirmations["information_confirmed"] is False
        assert await assign(service, group, person) == expected
        assert await db_session.scalar(select(func.count()).select_from(TravellerParticipationModel)) == 1
    else:
        assert member is None
