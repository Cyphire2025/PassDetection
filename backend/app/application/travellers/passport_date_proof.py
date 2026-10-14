"""Collect a passport date before resolving an anonymous passport number.

The first response is independent of whether the number exists. The number and
date are checked together; person-wide and claim-wide failure limits remain in
the authoritative verification services.
"""
from datetime import UTC, datetime

from app.application.travellers.claims import ReturningClaims
from app.application.travellers.document_challenge import (
    change_document_question,
    record_failed_proof,
    verify_document_answers,
)
from app.application.travellers.errors import ReuseError, ReuseReason
from app.domain.services.traveller_verification import DocumentQuestion

QUESTION_KEY = "_requested_passport_date"


async def prepare_passport_date(service: ReturningClaims, secret: str,
    proof: dict[str, str | None] | None = None, question: DocumentQuestion | None = None,
) -> DocumentQuestion | None:
    claim, scope = await service.locked(secret)
    if claim.method != "passport":
        return None
    if claim.status not in {"created", "passport_matched"}:
        raise ReuseError(ReuseReason.VERIFICATION_FAILED)
    if proof:
        service._set_identifiers(scope, claim, proof.get("passport_number"),
            proof.get("issuing_country"), proof.get("document_type") or "P", proof.get("individual_code"))
    evidence = dict(claim.actor_evidence or {})
    selected = question or DocumentQuestion(evidence.get(QUESTION_KEY, "date_of_birth"))
    evidence[QUESTION_KEY] = selected.value
    claim.actor_evidence = evidence
    await service.session.commit()
    return selected


async def verify_passport_date(service: ReturningClaims, secret: str, answers: dict[str, str]) -> bool:
    claim, _ = await service.locked(secret)
    if claim.method != "passport":
        return False
    requested = DocumentQuestion((claim.actor_evidence or {}).get(QUESTION_KEY, "date_of_birth"))
    # No proof is resolved by /passport or /challenge/change on this route.
    try:
        await service.bind_passport(secret)
        claim, scope = await service.locked(secret)
        now = datetime.now(UTC)
        _, revision = await service.bound_person(claim, scope, now)
        await change_document_question(service.session, claim, revision, requested, now)
    except ReuseError as exc:
        if exc.reason != ReuseReason.INSUFFICIENT_EVIDENCE:
            raise
        # An unavailable saved date must not create an unlimited alternate-
        # question probe, or reveal more than an incorrect date would.
        await record_failed_proof(service.session, claim, datetime.now(UTC))
        raise ReuseError(ReuseReason.VERIFICATION_FAILED) from exc
    await verify_document_answers(service.session, claim, revision, answers, now)
    await service.session.commit()
    return True
