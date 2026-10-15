"""Bounded, restart-safe historical matching preview; never grants history access.

A page uses at most 100 source rows, two indexed aggregate identity queries and
one existing-case query. Application memory is O(page size); identity work is
O(page size * log(identity rows) + matching index entries). No phone deduplication
or full-history hydration occurs. A job sees sources created by its start time;
later sources require another idempotent job. Every write shares its checkpoint
transaction, and a changed company assignment cancels the job.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast as typed_cast

from sqlalchemy import String, cast, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.reconciliation_sources import (
    ReconciliationSource,
    source_cursor,
    source_fingerprint,
    source_page,
)
from app.domain.services.traveller_verification import VerificationFailure
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerGroupReuseConfigModel,
    TravellerIdentifierModel,
    TravellerMatchCaseModel,
    TravellerPassportModel,
    TravellerProfileModel,
    TravellerReconciliationJobModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

MAX_RECONCILIATION_PAGE = 100
TRUSTED_FIELD_STATUSES = frozenset({"staff_approved", "confirmed"})
MatchMap = dict[str, tuple[int, uuid.UUID]]


@dataclass(frozen=True, slots=True)
class ReconciliationPage:
    job_id: uuid.UUID
    processed: int
    total_processed: int
    status: str


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    submission_id: uuid.UUID
    extraction_revision: int
    passport_fingerprint: str | None
    identifier_fingerprint: str | None
    source_kind: str = "passport_submission"
    source_fingerprint: str = ""


async def enqueue_reconciliation(
    session: AsyncSession, *, agency_id: uuid.UUID, company_id: uuid.UUID,
    group_id: uuid.UUID, idempotency_key: str, now: datetime | None = None,
) -> TravellerReconciliationJobModel:
    """The staff API must authorize group access before calling this service."""
    if not 1 <= len(idempotency_key) <= 128:
        raise ValueError("Invalid reconciliation idempotency key")
    group = await session.scalar(select(ClientGroupModel).where(
        ClientGroupModel.id == group_id, ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.company_id == company_id, ClientGroupModel.status != "deleted",
        ClientGroupModel.deleted_at.is_(None),
    ).with_for_update())
    # Incremental source jobs coalesce other jobs under the company lock.
    # Acquiring company before job prevents an opposite company/job lock cycle.
    await session.scalar(select(ClientOrganizationModel.id).where(
        ClientOrganizationModel.id == company_id,
        ClientOrganizationModel.agency_id == agency_id).with_for_update())
    if group is None:
        raise ValueError("Reconciliation group unavailable")
    existing = await session.scalar(select(TravellerReconciliationJobModel).where(
        TravellerReconciliationJobModel.agency_id == agency_id,
        TravellerReconciliationJobModel.company_id == company_id,
        TravellerReconciliationJobModel.group_id == group_id,
        TravellerReconciliationJobModel.idempotency_key == idempotency_key,
    ))
    if existing is not None:
        return existing
    current_time = now or datetime.now(UTC)
    job = TravellerReconciliationJobModel(
        id=uuid.uuid4(), agency_id=agency_id, company_id=company_id, group_id=group_id,
        idempotency_key=idempotency_key, expected_group_revision=group.company_revision,
        status="queued", created_at=current_time, available_at=current_time,
    )
    session.add(job)
    await session.flush()
    return job


async def reconcile_page(
    session: AsyncSession, *, job_id: uuid.UUID, crypto: TravellerReuseCrypto,
    page_size: int = MAX_RECONCILIATION_PAGE, now: datetime | None = None,
) -> ReconciliationPage | None:
    """Call inside one transaction. Rollback is the retry; no partial checkpoint.

SKIP LOCKED provides backpressure when another worker owns the job. The caller
must schedule controlled retries for infrastructure failures; this function has
no provider calls or internal retry loop.
"""
    if not 1 <= page_size <= MAX_RECONCILIATION_PAGE:
        raise ValueError("Reconciliation page must contain 1 to 100 rows")
    current_time = now or datetime.now(UTC)
    # Locate and lock only the group in one indexed join; the job itself is
    # locked after company admission to preserve group -> company -> job order.
    locator = await session.execute(select(ClientGroupModel, TravellerReconciliationJobModel.company_id)
        .join(TravellerReconciliationJobModel,
            (TravellerReconciliationJobModel.group_id == ClientGroupModel.id)
            & (TravellerReconciliationJobModel.agency_id == ClientGroupModel.agency_id))
        .where(TravellerReconciliationJobModel.id == job_id)
        .with_for_update(of=ClientGroupModel))
    location = locator.one_or_none()
    if location is None:
        return None
    group, company_id = location
    await session.scalar(select(ClientOrganizationModel.id).where(
        ClientOrganizationModel.id == company_id,
        ClientOrganizationModel.agency_id == group.agency_id).with_for_update())
    job = await session.scalar(select(TravellerReconciliationJobModel).where(
        TravellerReconciliationJobModel.id == job_id,
    ).with_for_update(skip_locked=True).execution_options(populate_existing=True))
    if job is None:
        return None
    if job.status in {"succeeded", "failed", "cancelled"}:
        return ReconciliationPage(job.id, 0, job.processed_count, job.status)
    if (group is None or group.company_id != job.company_id or group.status == "deleted"
            or group.company_revision != job.expected_group_revision):
        job.status, job.last_error_code = "cancelled", "company_assignment_changed"
        job.completed_at = current_time
        return ReconciliationPage(job.id, 0, job.processed_count, job.status)
    if job.idempotency_key.startswith("company-history:"):
        from app.application.travellers.company_history_jobs import process_company_history_page
        processed = await process_company_history_page(session, job=job, group=group, crypto=crypto, now=current_time)
        return ReconciliationPage(job.id, processed, job.processed_count, job.status)
    from app.application.travellers.incremental_history import PREFIXES, process_incremental_page
    if job.idempotency_key.startswith(PREFIXES):
        processed = await process_incremental_page(session, job=job, group=group, crypto=crypto, now=current_time)
        return ReconciliationPage(job.id, processed, job.processed_count, job.status)
    config = await session.get(TravellerGroupReuseConfigModel, group.id)
    if config is not None and (config.agency_id != job.agency_id or config.company_id != job.company_id):
        config = None
    rows = await source_page(session, job, page_size)
    page, has_more = rows[:page_size], len(rows) > page_size
    evidence = [_source_evidence(row, job, config, crypto) for row in page]
    passport_matches = await _passport_matches(session, job, evidence, crypto.key_version)
    code_matches = await _identifier_matches(session, job, evidence, config, group, crypto.key_version)
    existing = {(row.source_kind, row.source_row_key): row for row in (await session.scalars(
        select(TravellerMatchCaseModel).where(
            TravellerMatchCaseModel.agency_id == job.agency_id,
            TravellerMatchCaseModel.company_id == job.company_id,
            TravellerMatchCaseModel.group_id == job.group_id,
            TravellerMatchCaseModel.source_kind.in_({row.source_kind for row in evidence}),
            TravellerMatchCaseModel.source_row_key.in_([str(row.submission_id) for row in evidence]),
        ).with_for_update().execution_options(populate_existing=True)
    )).all()} if evidence else {}
    for source in evidence:
        source_key = str(source.submission_id)
        prior = existing.get((source.source_kind, source_key))
        # A new preview may refresh stale unresolved evidence, never a human decision.
        if prior and (prior.status in {"resolved", "purged", "pending"}
                or prior.reason_code == "authorized_replacement_candidate"):
            continue
        status, reason, person = _decision(source, passport_matches, code_matches)
        record = _case_evidence(source, job, config, crypto.key_version)
        if prior:
            if ({key: value for key, value in prior.evidence.items() if key != "job_id"}
                    == {key: value for key, value in record.items() if key != "job_id"}
                    and (prior.status, prior.reason_code, prior.traveller_id) == (status, reason, person)):
                continue
            prior.status, prior.reason_code, prior.traveller_id, prior.evidence = status, reason, person, record
            prior.revision += 1
        else:
            session.add(TravellerMatchCaseModel(
                agency_id=job.agency_id, company_id=job.company_id, group_id=job.group_id,
                traveller_id=person, source_kind=source.source_kind, source_row_key=source_key,
                status=status, reason_code=reason, evidence=record,
            ))
    if page:
        job.cursor = source_cursor(page[-1].source_kind, page[-1].id)
        job.processed_count += len(page)
    job.status = "queued" if has_more else "succeeded"
    job.attempt_count = 0
    job.lease_expires_at = None
    if not has_more:
        job.completed_at = current_time
    await session.flush()
    return ReconciliationPage(job.id, len(page), job.processed_count, job.status)


def _case_evidence(source: SourceEvidence, job: TravellerReconciliationJobModel,
    config: TravellerGroupReuseConfigModel | None, key_version: str,
) -> dict[str, object]:
    return {"job_id": str(job.id), "source_revision": source.extraction_revision,
        "passport_evidence": source.passport_fingerprint is not None,
        "individual_code_evidence": source.identifier_fingerprint is not None,
        "decision_version": 3, "source_fingerprint": source.source_fingerprint,
        "fingerprint_key_version": key_version, "group_revision": job.expected_group_revision,
        "config_revision": config.revision if config else None,
        "identifier_type": config.individual_identifier_type if config else None,
        "roster_import": source.source_kind != "passport_submission", "source_coverage": "durable_saved_rows_only"}


def _source_evidence(
    row: ReconciliationSource, job: TravellerReconciliationJobModel,
    config: TravellerGroupReuseConfigModel | None, crypto: TravellerReuseCrypto,
) -> SourceEvidence:
    passport, identifier = None, None
    # Legacy AI approval is extraction confidence, never reliable holder evidence.
    if row.status in TRUSTED_FIELD_STATUSES:
        fields = row.confirmed_fields or {}
        values = tuple(fields.get(key) for key in ("passport_number", "issuing_country", "document_type"))
        if all(isinstance(value, str) and value for value in values):
            try:
                passport = crypto.passport_fingerprint(
                    job.agency_id, job.company_id, *typed_cast(tuple[str, str, str], values),
                )
            except VerificationFailure:
                pass
    if config is not None and config.individual_identifier_type:
        value = (row.staff_metadata or {}).get(config.individual_identifier_type)
        if isinstance(value, str) and value.strip():
            identifier = crypto.scoped_digest("identifier", job.agency_id, job.company_id,
                                               config.individual_identifier_type, value.strip())
    digest = source_fingerprint(crypto, job.agency_id, job.company_id, row)
    return SourceEvidence(row.id, row.extraction_revision, passport, identifier, row.source_kind, digest)


async def _passport_matches(
    session: AsyncSession, job: TravellerReconciliationJobModel,
    sources: Sequence[SourceEvidence], key_version: str,
) -> MatchMap:
    fingerprints = {row.passport_fingerprint for row in sources if row.passport_fingerprint}
    if not fingerprints:
        return {}
    model = TravellerPassportModel
    statement = select(model.number_fingerprint, func.count(distinct(model.traveller_id)),
                       func.min(cast(model.traveller_id, String))).join(
        TravellerProfileModel, TravellerProfileModel.id == model.traveller_id,
    ).where(model.agency_id == job.agency_id, model.company_id == job.company_id,
            model.fingerprint_key_version == key_version, model.number_fingerprint.in_(fingerprints),
            model.status.in_(("accepted", "superseded")), TravellerProfileModel.status == "active",
            TravellerProfileModel.deleted_at.is_(None)).group_by(model.number_fingerprint)
    return {fingerprint: (count, uuid.UUID(first)) for fingerprint, count, first in (await session.execute(statement)).all()}


async def _identifier_matches(
    session: AsyncSession, job: TravellerReconciliationJobModel,
    sources: Sequence[SourceEvidence], config: TravellerGroupReuseConfigModel | None,
    group: ClientGroupModel, key_version: str,
) -> MatchMap:
    fingerprints = {row.identifier_fingerprint for row in sources if row.identifier_fingerprint}
    if not fingerprints or config is None or group.travel_date is None:
        return {}
    model = TravellerIdentifierModel
    statement = select(model.value_fingerprint, func.count(distinct(model.traveller_id)),
                       func.min(cast(model.traveller_id, String))).join(
        TravellerProfileModel, TravellerProfileModel.id == model.traveller_id,
    ).where(model.agency_id == job.agency_id, model.company_id == job.company_id,
            model.fingerprint_key_version == key_version, model.value_fingerprint.in_(fingerprints),
            model.identifier_type == config.individual_identifier_type, model.is_individual.is_(True),
            or_(model.effective_from.is_(None), model.effective_from <= group.travel_date),
            or_(model.effective_until.is_(None), model.effective_until >= group.travel_date),
            TravellerProfileModel.status == "active", TravellerProfileModel.deleted_at.is_(None)
    ).group_by(model.value_fingerprint)
    return {fingerprint: (count, uuid.UUID(first)) for fingerprint, count, first in (await session.execute(statement)).all()}


def _decision(
    source: SourceEvidence, passports: MatchMap, codes: MatchMap,
) -> tuple[str, str, uuid.UUID | None]:
    passport = passports.get(source.passport_fingerprint) if source.passport_fingerprint else None
    code = codes.get(source.identifier_fingerprint) if source.identifier_fingerprint else None
    if any(match and match[0] > 1 for match in (passport, code)):
        return "ambiguous", "multiple_strong_matches", None
    if passport and code and passport[1] != code[1]:
        return "conflicting", "contradictory_strong_identifiers", None
    matched = passport or code
    if matched:
        return "provisional", "exact_evidence_preview", matched[1]
    return "unmatched", "insufficient_trustworthy_evidence", None
