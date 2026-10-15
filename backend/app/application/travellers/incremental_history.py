"""Incremental single-source registration and coalesced 25-group roster fanout.
Company locks serialize admission; group -> company -> job locks fence workers."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.application.travellers.historical_registration import register_historical_source
from app.application.travellers.reconciliation_sources import source_cursor, source_page
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerReconciliationJobModel as Job,
)
from app.infrastructure.database.traveller_reuse_models import TravellerReusePolicyModel
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

PREFIXES = ("company-source:", "company-group:", "company-roster:", "company-fanout:")
DIRTY = "refresh_dirty"
PAGE_SIZE = 25


def _validate_generation(key: str, group_revision: int) -> None:
    """Internal durable payload: bounded canonical integers, never booleans."""
    if type(group_revision) is not int or not 1 <= group_revision <= 2**31 - 1 or len(key) > 128:
        raise ValueError("invalid_history_generation")
    parts = key.split(":")
    if parts[0] == "company-source" and len(parts) == 3:
        if str(uuid.UUID(parts[1])) != parts[1]:
            raise ValueError("invalid_source_identity")
        generations = [(parts[2], 0)]  # Existing unextracted source revisions begin at zero.
    elif parts[0] in {"company-group", "company-roster"} and len(parts) == 4:
        expected_phase = "g" if parts[0] == "company-group" else "m"
        if parts[1] != expected_phase or parts[3] != str(group_revision):
            raise ValueError("invalid_group_generation")
        generations = [(parts[2], 0 if parts[0] == "company-group" else 1)]
    elif parts[0] == "company-fanout" and len(parts) == 3 and parts[1] == "f":
        generations = [(parts[2], 1)]
    else:
        raise ValueError("invalid_history_job_key")
    for value, minimum in generations:
        if not value.isascii() or not value.isdecimal() or str(int(value)) != value or not minimum <= int(value) <= 2**31 - 1:
            raise ValueError("invalid_history_generation")


async def coalesce_job(session: AsyncSession, *, agency_id: uuid.UUID, company_id: uuid.UUID,
    group_id: uuid.UUID, group_revision: int, key: str, now: datetime,
) -> Job:
    """Caller holds company lock; no target-group lock or dataset is loaded."""
    _validate_generation(key, group_revision)
    job = await session.scalar(select(Job).where(Job.agency_id == agency_id, Job.company_id == company_id,
        Job.group_id == group_id, Job.idempotency_key == key).with_for_update())
    if job is None:
        job = Job(agency_id=agency_id, company_id=company_id, group_id=group_id,
            expected_group_revision=group_revision, idempotency_key=key, created_at=now, available_at=now)
        session.add(job)
        await session.flush()
    else:
        refresh_job(job, group_revision=group_revision, now=now)
    return job


def refresh_job(job: Job, *, group_revision: int, now: datetime) -> None:
    """Refresh an already locked job; shared by source and roster admissions."""
    if job.status in {"queued", "running"} and job.expected_group_revision == group_revision:
        if job.cursor is not None:
            job.last_error_code = DIRTY
        else:
            job.created_at = now  # Pending first page includes newly linked/source rows.
    else:
        job.status, job.cursor, job.last_error_code = "queued", None, None
        job.created_at, job.available_at, job.completed_at = now, now, None
        job.attempt_count, job.processed_count, job.lease_expires_at = 0, 0, None
        job.expected_group_revision = group_revision


async def queue_group_refresh(session: AsyncSession, group: ClientGroupModel,
    policy: TravellerReusePolicyModel | None, now: datetime,
) -> None:
    assert group.company_id is not None
    revision = policy.revision if policy is not None and policy.enabled else 0
    await coalesce_job(session, agency_id=group.agency_id, company_id=group.company_id, group_id=group.id,
        group_revision=group.company_revision, key=f"company-group:g:{revision}:{group.company_revision}", now=now)


async def queue_roster_fanout(session: AsyncSession, *, agency_id: uuid.UUID,
    company_id: uuid.UUID, policy: TravellerReusePolicyModel, now: datetime,
) -> None:
    anchor = (await session.execute(select(ClientGroupModel.id, ClientGroupModel.company_revision).where(
        *_active_linked_groups(agency_id, company_id)).order_by(ClientGroupModel.id).limit(1))).one_or_none()
    if anchor is not None:
        await coalesce_job(session, agency_id=agency_id, company_id=company_id, group_id=anchor.id,
            group_revision=anchor.company_revision, key=f"company-fanout:f:{policy.revision}", now=now)


def _active_linked_groups(agency_id: uuid.UUID, company_id: uuid.UUID) -> tuple[ColumnElement[bool], ...]:
    linked = select(ClientGroupWhatsAppBroadcastLinkModel.id).where(
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        ClientGroupWhatsAppBroadcastLinkModel.client_group_id == ClientGroupModel.id).exists()
    return (ClientGroupModel.agency_id == agency_id, ClientGroupModel.company_id == company_id,
        ClientGroupModel.status == "active", ClientGroupModel.deleted_at.is_(None), linked)


async def process_incremental_page(session: AsyncSession, *, job: Job, group: ClientGroupModel,
    crypto: TravellerReuseCrypto, now: datetime,
) -> int:
    _validate_generation(job.idempotency_key, job.expected_group_revision)
    policy = await session.scalar(select(TravellerReusePolicyModel).where(
        TravellerReusePolicyModel.agency_id == job.agency_id, TravellerReusePolicyModel.company_id == job.company_id))
    enabled = policy if policy is not None and policy.enabled else None
    if job.idempotency_key.startswith("company-source:"):
        _, source_id, revision = job.idempotency_key.split(":")
        current = await session.scalar(select(PassportSubmissionModel.extraction_revision).where(
            PassportSubmissionModel.id == uuid.UUID(source_id), PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == job.agency_id))
        if current == int(revision):
            await register_historical_source(session, group=group, source_id=uuid.UUID(source_id),
                policy=enabled, crypto=crypto, now=now)
            if enabled is not None:
                await queue_roster_fanout(session, agency_id=job.agency_id, company_id=job.company_id, policy=enabled, now=now)
        _finish_page(job, 1, False, now)
        return 1
    expected = int(job.idempotency_key.split(":")[2])
    if expected != (enabled.revision if enabled is not None else 0):
        job.status, job.last_error_code, job.completed_at = "cancelled", "company_policy_changed", now
        return 0
    if job.idempotency_key.startswith("company-fanout:"):
        return await _fanout_page(session, job, now)
    return await _group_page(session, job, group, enabled, crypto, now)


async def _fanout_page(session: AsyncSession, job: Job, now: datetime) -> int:
    query = select(ClientGroupModel.id, ClientGroupModel.company_revision).where(
        *_active_linked_groups(job.agency_id, job.company_id))
    if job.cursor is not None:
        query = query.where(ClientGroupModel.id > uuid.UUID(job.cursor))
    groups = (await session.execute(query.order_by(ClientGroupModel.id).limit(PAGE_SIZE + 1))).all()
    policy_revision = int(job.idempotency_key.split(":")[2])
    for group in groups[:PAGE_SIZE]:
        await coalesce_job(session, agency_id=job.agency_id, company_id=job.company_id,
            group_id=group.id, group_revision=group.company_revision,
            key=f"company-roster:m:{policy_revision}:{group.company_revision}", now=now)
        job.cursor = str(group.id)
    count = min(PAGE_SIZE, len(groups))
    _finish_page(job, count, len(groups) > PAGE_SIZE, now)
    return count


async def _group_page(session: AsyncSession, job: Job, group: ClientGroupModel,
    policy: TravellerReusePolicyModel | None, crypto: TravellerReuseCrypto, now: datetime,
) -> int:
    from app.application.travellers.company_history_jobs import match_roster_source
    roster_only = job.idempotency_key.startswith("company-roster:")
    rows = await source_page(session, job, PAGE_SIZE, roster_only=roster_only)
    processed, registered = 0, False
    for source in rows[:PAGE_SIZE]:
        if source.source_kind == "passport_submission":
            person_id = await register_historical_source(session, group=group, source_id=source.id,
                policy=policy, crypto=crypto, now=now)
            registered |= person_id is not None
        elif policy is not None and not await match_roster_source(session, job, group, source, crypto, now):
            break
        job.cursor = source_cursor(source.source_kind, source.id)
        processed += 1
    if registered and policy is not None:
        # Retry rosters checked before this history was ready, once per page.
        # Roster-only work cannot recurse; private registration cannot authorize reuse.
        await queue_roster_fanout(session, agency_id=job.agency_id,
            company_id=job.company_id, policy=policy, now=now)
    _finish_page(job, processed, len(rows) > PAGE_SIZE or processed < min(PAGE_SIZE, len(rows)), now)
    return processed


def _finish_page(job: Job, count: int, more: bool, now: datetime) -> None:
    job.processed_count += count
    job.attempt_count, job.lease_expires_at = 0, None
    if not more and job.last_error_code == DIRTY:
        job.cursor, job.last_error_code, job.created_at = None, None, now
        more = True
    job.status = "queued" if more else "succeeded"
    if not more:
        job.completed_at = now
