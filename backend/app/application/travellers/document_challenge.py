"""Persisted question selection and cross-session abuse budgets.

The caller holds the person row lock, serializing selection and failures across
claims, phones and entry methods. No answers/hashes leave this module.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.audit import record_claim_action
from app.application.travellers.errors import ReuseError, ReuseReason
from app.domain.services.traveller_verification import (
    MAX_FAILURES,
    QUESTION_WINDOW,
    DocumentQuestion,
    FailureBudget,
    VerificationFailure,
    answers_match,
    choose_questions,
    utc,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerAttemptBudgetModel,
    TravellerChallengeSelectionModel,
    TravellerClaimModel,
    TravellerDocumentRevisionModel,
    TravellerProfileModel,
)


def reliable_answers(revision: TravellerDocumentRevisionModel) -> dict[DocumentQuestion, date]:
    """OCR output alone is insufficient: explicit accepted provenance is required."""
    answers: dict[DocumentQuestion, date] = {}
    for question in DocumentQuestion:
        provenance = revision.reliable_fields.get(question.value)
        value = getattr(revision, question.value)
        if (
            isinstance(value, date) and not isinstance(value, datetime)
            and isinstance(provenance, dict) and provenance.get("accepted") is True
            and provenance.get("source") in {"staff_review", "verified_import"}
        ):
            answers[question] = value
    return answers


async def questions_for_claim(
    session: AsyncSession, claim: TravellerClaimModel,
    revision: TravellerDocumentRevisionModel, now: datetime,
) -> tuple[DocumentQuestion, ...]:
    if claim.traveller_id is None or (claim.method == "phone" and claim.otp_verified_at is None) or claim.document_revision_id != revision.id:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    row = await session.scalar(select(TravellerChallengeSelectionModel).where(
        TravellerChallengeSelectionModel.agency_id == claim.agency_id,
        TravellerChallengeSelectionModel.company_id == claim.company_id,
        TravellerChallengeSelectionModel.traveller_id == claim.traveller_id,
        TravellerChallengeSelectionModel.document_revision_id == revision.id,
        TravellerChallengeSelectionModel.purpose == "history_reuse",
    ).with_for_update())
    existing = tuple(DocumentQuestion(value) for value in row.fields) if row is not None and utc(row.expires_at) > now else ()
    try:
        selected = choose_questions(tuple(reliable_answers(revision)), recovery=claim.required_question_count == 2, existing=existing)
    except VerificationFailure as exc:
        raise ReuseError(ReuseReason.INSUFFICIENT_EVIDENCE) from exc
    if row is None:
        row = TravellerChallengeSelectionModel(
            id=uuid.uuid4(), agency_id=claim.agency_id, company_id=claim.company_id,
            traveller_id=claim.traveller_id, passport_id=claim.passport_id,
            document_revision_id=revision.id, purpose="history_reuse",
            fields=[q.value for q in selected], expires_at=now + QUESTION_WINDOW,
        )
        session.add(row)
    else:
        if utc(row.expires_at) <= now:
            row.expires_at = now + QUESTION_WINDOW
        row.fields = [q.value for q in selected]
    return selected


async def require_attempt_budget(
    session: AsyncSession, claim: TravellerClaimModel, now: datetime,
) -> TravellerAttemptBudgetModel:
    if (claim.method == "phone" and claim.otp_verified_at is None) or claim.traveller_id is None:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    row = await session.scalar(select(TravellerAttemptBudgetModel).where(
        TravellerAttemptBudgetModel.traveller_id == claim.traveller_id,
        TravellerAttemptBudgetModel.company_id == claim.company_id,
        TravellerAttemptBudgetModel.agency_id == claim.agency_id,
    ).with_for_update())
    if row is None:
        row = TravellerAttemptBudgetModel(
            traveller_id=claim.traveller_id, company_id=claim.company_id,
            agency_id=claim.agency_id, failure_count=0, window_started_at=now, revision=1,
        )
        session.add(row)
    budget = FailureBudget(row.failure_count, row.window_started_at, row.cooldown_until)
    if budget.blocked(now) or claim.failed_answer_sets >= MAX_FAILURES:
        raise ReuseError(ReuseReason.RATE_LIMITED)
    return row


async def verify_document_answers(
    session: AsyncSession, claim: TravellerClaimModel,
    revision: TravellerDocumentRevisionModel, answers: dict[str, str], now: datetime,
) -> None:
    if claim.status not in {"passport_matched", "challenge_passed", "recovery_confirmation"}:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    budget = await require_attempt_budget(session, claim, now)
    selected = await questions_for_claim(session, claim, revision, now)
    if not answers_match(selected, reliable_answers(revision), answers):
        await record_failed_proof(session, claim, now, budget=budget)
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    claim.status = "recovery_confirmation" if claim.required_question_count == 2 else "challenge_passed"


async def record_failed_proof(
    session: AsyncSession, claim: TravellerClaimModel, now: datetime,
    *, budget: TravellerAttemptBudgetModel | None = None,
) -> None:
    """All failed passport/code/date checks share one durable attempt policy.

The eligible person row is already locked by exact matching or selection. A
failure with no known person still consumes the claim's five-attempt budget.
"""
    if claim.traveller_id is not None:
        # A prior candidate selection may have committed its person lock. Take
        # it again before creating the shared budget to serialize first failure.
        await session.scalar(select(TravellerProfileModel.id).where(
            TravellerProfileModel.id == claim.traveller_id,
            TravellerProfileModel.agency_id == claim.agency_id,
            TravellerProfileModel.company_id == claim.company_id,
        ).with_for_update())
        budget = budget or await require_attempt_budget(session, claim, now)
        failed = FailureBudget(budget.failure_count, budget.window_started_at, budget.cooldown_until).fail(now)
        budget.failure_count = failed.failures
        budget.window_started_at = failed.window_started_at or now
        budget.cooldown_until = failed.blocked_until
        budget.revision += 1
    claim.failed_answer_sets = min(MAX_FAILURES, claim.failed_answer_sets + 1)
    if claim.failed_answer_sets >= MAX_FAILURES:
        claim.status = "locked"
    await record_claim_action(session, claim, "proof_failed")
    await session.commit()


async def change_document_question(
    session: AsyncSession, claim: TravellerClaimModel,
    revision: TravellerDocumentRevisionModel, field: DocumentQuestion, now: datetime,
) -> tuple[DocumentQuestion, ...]:
    """User-requested alternate, keeping person/claim limits and expiry intact."""
    if claim.status != "passport_matched" or claim.required_question_count == 0:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    await require_attempt_budget(session, claim, now)
    selected = list(await questions_for_claim(session, claim, revision, now))
    if field not in reliable_answers(revision):
        raise ReuseError(ReuseReason.INSUFFICIENT_EVIDENCE)
    if field not in selected:
        selected[-1] = field
    row = await session.scalar(select(TravellerChallengeSelectionModel).where(
        TravellerChallengeSelectionModel.traveller_id == claim.traveller_id,
        TravellerChallengeSelectionModel.document_revision_id == revision.id,
        TravellerChallengeSelectionModel.agency_id == claim.agency_id,
        TravellerChallengeSelectionModel.company_id == claim.company_id,
        TravellerChallengeSelectionModel.purpose == "history_reuse",
    ).with_for_update())
    assert row is not None
    row.fields = [question.value for question in selected]
    return tuple(selected)
