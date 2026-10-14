"""Broadcast edits wake matching atomically, with bounded and current scope."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select

from app.application.travellers.broadcast_history_schedule import (
    finish_broadcast_history_refresh,
    prepare_broadcast_history_refresh,
    require_current_broadcast_history_scope,
)
from app.application.travellers.incremental_history import DIRTY
from app.application.travellers.reconciliation import reconcile_page
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.models import (
    ClientGroupModel,
)
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel as Link,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel as Broadcast,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel as Recipient,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerReconciliationJobModel as Job,
)
from app.infrastructure.database.traveller_reuse_models import TravellerReusePolicyModel
from tests.unit.application.test_traveller_enrollment import _fixture


async def linked(session, ctx, count=1):
    broadcast = Broadcast(agency_id=ctx.group.agency_id, name="Synthetic import")
    session.add(broadcast)
    groups = [ctx.group]
    for index in range(1, count):
        groups.append(ClientGroupModel(agency_id=ctx.group.agency_id, company_id=ctx.group.company_id,
            name=f"Synthetic target {index}", token=uuid.uuid4().hex, company_revision=1))
    session.add_all(groups)
    await session.flush()
    session.add_all([Link(agency_id=group.agency_id, client_group_id=group.id,
        broadcast_group_id=broadcast.id) for group in groups])
    await session.flush()
    return broadcast, groups


async def prepare(session, broadcast):
    result = await prepare_broadcast_history_refresh(session,
        agency_id=broadcast.agency_id, broadcast_id=broadcast.id)
    await require_current_broadcast_history_scope(session, result)
    return result


async def test_99_new_rows_restart_completed_roster_without_historical_rescan(db_session):
    ctx = await _fixture(db_session)
    broadcast, _ = await linked(db_session, ctx)
    initial = await prepare(db_session, broadcast)
    await finish_broadcast_history_refresh(db_session, initial)
    job = initial.jobs[0]
    assert (await reconcile_page(db_session, job_id=job.id, crypto=ctx.crypto)).status == "succeeded"
    admission = await prepare(db_session, broadcast)
    db_session.add_all([Recipient(agency_id=broadcast.agency_id, broadcast_group_id=broadcast.id,
        name=f"Synthetic {index}", phone_number=f"+919000{index:06d}", normalized_phone_number=f"+919000{index:06d}")
        for index in range(99)])
    await finish_broadcast_history_refresh(db_session, admission)
    assert admission.jobs[0].id == job.id and job.status == "queued"
    assert job.idempotency_key.startswith("company-roster:m:")
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1
    pages = [await reconcile_page(db_session, job_id=job.id, crypto=ctx.crypto) for _ in range(4)]
    assert [page.processed for page in pages] == [25, 25, 25, 24]
    assert job.status == "succeeded" and job.processed_count == 99


async def test_in_progress_mutation_marks_one_trailing_pass(db_session):
    ctx = await _fixture(db_session)
    broadcast, _ = await linked(db_session, ctx)
    first = await prepare(db_session, broadcast)
    job = first.jobs[0]
    job.cursor = f"v2:whatsapp_recipient:{uuid.uuid4()}"
    await db_session.flush()
    again = await prepare(db_session, broadcast)
    await finish_broadcast_history_refresh(db_session, again)
    assert job.last_error_code == DIRTY and job.cursor is not None
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 1


@pytest.mark.parametrize("change", ["disabled", "closed", "deleted", "import_only", "unassigned", "wrong_tenant"])
async def test_ineligible_scopes_never_enqueue(db_session, change):
    ctx = await _fixture(db_session)
    broadcast, _ = await linked(db_session, ctx)
    if change == "disabled":
        policy = await db_session.get(TravellerReusePolicyModel, ctx.group.company_id)
        policy.enabled = False
    elif change == "closed":
        ctx.group.status = "closed"
    elif change == "deleted":
        ctx.group.deleted_at = datetime.now(UTC)
    elif change == "import_only":
        ctx.group.import_only = True
    elif change == "unassigned":
        ctx.group.company_id = None
    await db_session.flush()
    result = await prepare_broadcast_history_refresh(db_session,
        agency_id=uuid.uuid4() if change == "wrong_tenant" else broadcast.agency_id, broadcast_id=broadcast.id)
    assert result.jobs == ()
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0


async def test_scope_change_rejects_and_rollback_removes_admission(db_session):
    ctx = await _fixture(db_session)
    broadcast, _ = await linked(db_session, ctx)
    with pytest.raises(ConflictError, match="linked groups changed"):
        async with db_session.begin_nested():
            prepared = await prepare_broadcast_history_refresh(db_session,
                agency_id=broadcast.agency_id, broadcast_id=broadcast.id)
            await db_session.execute(delete(Link).where(Link.broadcast_group_id == broadcast.id))
            await require_current_broadcast_history_scope(db_session, prepared)
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Link)) == 1


@pytest.mark.parametrize("count", [100, 101])
async def test_explicit_100_group_admission_budget(db_session, count):
    ctx = await _fixture(db_session)
    broadcast, _ = await linked(db_session, ctx, count)
    if count == 101:
        with pytest.raises(ConflictError, match="more than 100 groups"):
            await prepare(db_session, broadcast)
        assert await db_session.scalar(select(func.count()).select_from(Job)) == 0
    else:
        prepared = await prepare(db_session, broadcast)
        assert len(prepared.jobs) == len(prepared.group_ids) == 100
