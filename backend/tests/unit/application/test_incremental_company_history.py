"""Bursts coalesce by company/group and source hooks never scan old submissions."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.application.travellers.history_schedule import (
    schedule_group_history,
    schedule_submission_history,
)
from app.application.travellers.incremental_history import (
    DIRTY,
    _validate_generation,
    queue_roster_fanout,
)
from app.application.travellers.reconciliation import reconcile_page
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerProfileModel,
    TravellerReusePolicyModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerReconciliationJobModel as Job,
)
from tests.unit.application.test_traveller_enrollment import _fixture, _source


@pytest.mark.parametrize("revision", [0, -1, True, "1", 2**31])
def test_coalescer_rejects_nonpositive_or_untyped_group_generations(revision):
    with pytest.raises(ValueError):
        _validate_generation("company-group:g:1:1", revision)


@pytest.mark.parametrize("key", ["company-roster:m:0:1", "company-fanout:f:-1",
    "company-group:g:True:1", "company-group:g:1:2", "company-fanout:f:01",
    "company-fanout:f:2147483648", "company-source:not-a-uuid:1"])
def test_coalescer_rejects_malformed_or_stale_generations(key):
    with pytest.raises(ValueError):
        _validate_generation(key, 1)


def test_private_zero_policy_and_legacy_zero_extraction_are_explicitly_supported():
    _validate_generation("company-group:g:0:1", 1)
    _validate_generation(f"company-source:{uuid.uuid4()}:0", 1)


async def targets(session, ctx, count):
    broadcast = WhatsAppBroadcastGroupModel(agency_id=ctx.group.agency_id, name="Synthetic linked roster")
    session.add(broadcast)
    await session.flush()
    groups = [ClientGroupModel(agency_id=ctx.group.agency_id, company_id=ctx.group.company_id,
        company_revision=1, token=uuid.uuid4().hex, name=f"Target {index}") for index in range(count)]
    session.add_all(groups)
    await session.flush()
    session.add_all([ClientGroupWhatsAppBroadcastLinkModel(agency_id=ctx.group.agency_id,
        client_group_id=group.id, broadcast_group_id=broadcast.id, matching_field_keys=["name"]) for group in groups])
    await session.flush()
    return groups


@pytest.mark.asyncio
async def test_source_hook_registers_only_its_exact_revision_and_queues_one_fanout(db_session):
    ctx = await _fixture(db_session)
    policy = await db_session.get(TravellerReusePolicyModel, ctx.group.company_id)
    policy.configured_by_user_id = ctx.request.actor_id
    untouched = _source(ctx.group, number="UNTOUCHED1")
    untouched.client_name = "Another Name"
    db_session.add(untouched)
    await targets(db_session, ctx, 1)
    await schedule_submission_history(db_session, agency_id=ctx.group.agency_id, group_id=ctx.group.id,
        source_submission_id=ctx.source.id, expected_extraction_revision=1, trigger="one-confirmation")
    job = await db_session.scalar(select(Job))
    assert job.idempotency_key.startswith("company-source:")
    result = await reconcile_page(db_session, job_id=job.id, crypto=ctx.crypto)
    assert result.status == "succeeded" and result.processed == 1
    assert await db_session.scalar(select(func.count()).select_from(TravellerProfileModel)) == 1
    jobs = list((await db_session.scalars(select(Job))).all())
    assert len(jobs) == 2 and sum(row.idempotency_key.startswith("company-fanout:") for row in jobs) == 1
    assert not any(row.idempotency_key.startswith("company-history:") for row in jobs)


@pytest.mark.asyncio
async def test_700_events_share_one_fanout_and_dirty_page_restarts_without_duplicate_group_jobs(db_session):
    ctx = await _fixture(db_session)
    policy = await db_session.get(TravellerReusePolicyModel, ctx.group.company_id)
    await targets(db_session, ctx, 36)
    now = datetime.now(UTC)
    for _ in range(700):
        await queue_roster_fanout(db_session, agency_id=ctx.group.agency_id,
            company_id=ctx.group.company_id, policy=policy, now=now)
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1
    fanout = await db_session.scalar(select(Job))
    first = await reconcile_page(db_session, job_id=fanout.id, crypto=ctx.crypto)
    assert first.processed == 25 and first.status == "queued"
    await queue_roster_fanout(db_session, agency_id=ctx.group.agency_id,
        company_id=ctx.group.company_id, policy=policy, now=now)
    assert fanout.last_error_code == DIRTY
    trailing = await reconcile_page(db_session, job_id=fanout.id, crypto=ctx.crypto)
    assert trailing.processed == 11 and trailing.status == "queued" and fanout.cursor is None
    await reconcile_page(db_session, job_id=fanout.id, crypto=ctx.crypto)
    final = await reconcile_page(db_session, job_id=fanout.id, crypto=ctx.crypto)
    assert final.status == "succeeded"
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 37


@pytest.mark.asyncio
async def test_group_changes_coalesce_only_that_group_even_when_reuse_disabled(db_session):
    ctx = await _fixture(db_session)
    policy = await db_session.get(TravellerReusePolicyModel, ctx.group.company_id)
    policy.enabled = False
    await db_session.flush()
    for index in range(20):
        await schedule_group_history(db_session, group=ctx.group, trigger=f"broadcast-{index}")
    job = await db_session.scalar(select(Job))
    assert job.idempotency_key == "company-group:g:0:1"
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1
    result = await reconcile_page(db_session, job_id=job.id, crypto=ctx.crypto)
    assert result.status == "succeeded"
    person = await db_session.scalar(select(TravellerProfileModel))
    assert person.reuse_permission_evidence["authority_kind"] == "private_history_v1"
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1
