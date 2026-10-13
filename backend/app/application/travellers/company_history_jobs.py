"""Two-pass, resumable company history registration and roster matching.

At most 25 source records are processed per worker transaction. Registration
finishes across the company before the roster pass starts. Next-group admission
runs in a separate transaction after completion; it never locks another group
while retaining the previous group's company lock. Existing durable job leases,
timeouts and five-attempt backoff apply unchanged.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.historical_registration import register_historical_source
from app.application.travellers.identity_index import find_exact_identity
from app.application.travellers.reconciliation_sources import (
    ReconciliationSource,
    source_cursor,
    source_fingerprint,
    source_page,
)
from app.domain.services.traveller_identity import identity_evidence
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerMatchCaseModel,
    TravellerReconciliationJobModel,
    TravellerReusePolicyModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

CHAIN_PREFIX = "company-history:"
ADVANCE_PENDING = "chain_advance_pending"
MAX_HISTORY_PAGE = 25


async def enqueue_company_history(session: AsyncSession, *, group: ClientGroupModel,
    policy: TravellerReusePolicyModel, trigger: str,
) -> TravellerReconciliationJobModel:
    from app.application.travellers.reconciliation import enqueue_reconciliation
    cycle = hashlib.sha256(trigger.encode()).hexdigest()[:24]
    return await enqueue_reconciliation(session, agency_id=group.agency_id, company_id=policy.company_id,
        group_id=group.id, idempotency_key=f"{CHAIN_PREFIX}r:{policy.revision}:{cycle}")


async def enqueue_private_company_history(session: AsyncSession, *, group: ClientGroupModel,
    trigger: str,
) -> TravellerReconciliationJobModel:
    from app.application.travellers.reconciliation import enqueue_reconciliation
    assert group.company_id is not None
    cycle = hashlib.sha256(trigger.encode()).hexdigest()[:24]
    return await enqueue_reconciliation(session, agency_id=group.agency_id, company_id=group.company_id,
        group_id=group.id, idempotency_key=f"{CHAIN_PREFIX}p:0:{cycle}")


async def process_company_history_page(session: AsyncSession, *, job: TravellerReconciliationJobModel,
    group: ClientGroupModel, crypto: TravellerReuseCrypto, now: datetime,
) -> int:
    await session.scalar(select(ClientOrganizationModel.id).where(
        ClientOrganizationModel.id == job.company_id, ClientOrganizationModel.agency_id == job.agency_id).with_for_update())
    policy = await session.scalar(select(TravellerReusePolicyModel).where(
        TravellerReusePolicyModel.company_id == job.company_id,
        TravellerReusePolicyModel.agency_id == job.agency_id).with_for_update(read=True))
    _, phase, revision, _ = job.idempotency_key.split(":", 3)
    if phase != "p" and (policy is None or not policy.enabled or policy.revision != int(revision)):
        job.status, job.last_error_code, job.completed_at = "cancelled", "company_policy_changed", now
        return 0
    rows = await source_page(session, job, MAX_HISTORY_PAGE)
    page, more = rows[:MAX_HISTORY_PAGE], len(rows) > MAX_HISTORY_PAGE
    processed = 0
    for source in page:
        if phase in {"p", "r"} and source.source_kind == "passport_submission":
            await register_historical_source(session, group=group, source_id=source.id,
                policy=policy if phase == "r" else None, crypto=crypto, now=now)
        elif phase == "m" and source.source_kind != "passport_submission":
            if not await match_roster_source(session, job, group, source, crypto, now):
                break  # Retained copy still pending; resume exactly this row.
        job.cursor = source_cursor(source.source_kind, source.id)
        processed += 1
    job.processed_count += processed
    job.status = "queued" if more or processed < len(page) else "succeeded"
    job.attempt_count, job.lease_expires_at = 0, None
    if job.status == "succeeded":
        job.completed_at, job.last_error_code = now, ADVANCE_PENDING
    await session.flush()
    return processed


async def match_roster_source(session: AsyncSession, job: TravellerReconciliationJobModel, group: ClientGroupModel,
    source: ReconciliationSource, crypto: TravellerReuseCrypto, now: datetime,
) -> bool:
    # Import locally because reconciliation owns the source dataclass and calls
    # this handler through its existing durable job entry point.
    from app.application.travellers.operational_autoassignment import assign_operational_traveller
    evidence = identity_evidence(source.staff_metadata or {}, name=source.display_name, phone=source.phone)
    result = await find_exact_identity(session, agency_id=job.agency_id, company_id=job.company_id,
        evidence=evidence, crypto=crypto)
    case = await session.scalar(select(TravellerMatchCaseModel).where(
        TravellerMatchCaseModel.agency_id == job.agency_id, TravellerMatchCaseModel.company_id == job.company_id,
        TravellerMatchCaseModel.group_id == group.id, TravellerMatchCaseModel.source_kind == source.source_kind,
        TravellerMatchCaseModel.source_row_key == str(source.id)).with_for_update())
    if case is not None and case.status in {"resolved", "purged"}:
        return True
    if case is None:
        case = TravellerMatchCaseModel(agency_id=job.agency_id, company_id=job.company_id, group_id=group.id,
            source_kind=source.source_kind, source_row_key=str(source.id), revision=1)
        session.add(case)
    else:
        case.revision += 1
    record = {"decision_version": 4, "source_revision": source.extraction_revision,
        "source_fingerprint": source_fingerprint(crypto, job.agency_id, job.company_id, source),
        "fingerprint_key_version": crypto.key_version, "group_revision": job.expected_group_revision,
        "matching_types": list(result.matching_types), "policy_revision": int(job.idempotency_key.split(":")[2]),
        "authority_kind": "operator_exact_matching", "information_confirmed": False}
    case.status, case.reason_code, case.traveller_id = ("provisional" if result.status == "matched" else result.status), result.reason, result.traveller_id
    if result.traveller_id is not None:
        outcome = await assign_operational_traveller(session, group=group, person_id=result.traveller_id,
            source_kind=source.source_kind, source_row_key=str(source.id), evidence=record, crypto=crypto, now=now)
        if outcome == "assets_pending":
            case.status = "provisional"
            case.evidence = record
            return False
        case.status = "resolved" if outcome == "assigned" else "provisional"
        case.reason_code = "automatic_group_assignment" if outcome == "assigned" else str(outcome)
        case.resolved_at = now if outcome == "assigned" else None
    case.evidence = record
    return True


async def advance_company_history_chain(session: AsyncSession) -> bool:
    """Call in a fresh transaction; completion marker survives worker crashes."""
    from app.application.travellers.reconciliation import enqueue_reconciliation
    candidate = await session.scalar(select(TravellerReconciliationJobModel).where(
        TravellerReconciliationJobModel.status == "succeeded",
        TravellerReconciliationJobModel.last_error_code == ADVANCE_PENDING)
        .order_by(TravellerReconciliationJobModel.available_at, TravellerReconciliationJobModel.id)
        .limit(1))
    if candidate is None:
        return False
    _, phase, revision, cycle = candidate.idempotency_key.split(":", 3)
    scope = (ClientGroupModel.agency_id == candidate.agency_id, ClientGroupModel.company_id == candidate.company_id,
        ClientGroupModel.deleted_at.is_(None), ClientGroupModel.status.in_(("active", "closed", "archived")))
    next_group = await session.scalar(select(ClientGroupModel).where(*scope, ClientGroupModel.id > candidate.group_id)
        .order_by(ClientGroupModel.id).limit(1).with_for_update())
    if next_group is None and phase == "r":
        phase = "m"
        next_group = await session.scalar(select(ClientGroupModel).where(*scope)
            .order_by(ClientGroupModel.id).limit(1).with_for_update())
    if next_group is None:
        await session.scalar(select(ClientGroupModel.id).where(
            ClientGroupModel.id == candidate.group_id, ClientGroupModel.agency_id == candidate.agency_id).with_for_update())
    await session.scalar(select(ClientOrganizationModel.id).where(
        ClientOrganizationModel.id == candidate.company_id,
        ClientOrganizationModel.agency_id == candidate.agency_id).with_for_update())
    job = await session.scalar(select(TravellerReconciliationJobModel).where(
        TravellerReconciliationJobModel.id == candidate.id,
        TravellerReconciliationJobModel.status == "succeeded",
        TravellerReconciliationJobModel.last_error_code == ADVANCE_PENDING)
        .with_for_update().execution_options(populate_existing=True))
    if job is None:
        return False
    if next_group is not None:
        await enqueue_reconciliation(session, agency_id=job.agency_id, company_id=job.company_id,
            group_id=next_group.id, idempotency_key=f"{CHAIN_PREFIX}{phase}:{revision}:{cycle}",
            now=datetime.now(UTC))
    job.last_error_code = None
    return True
