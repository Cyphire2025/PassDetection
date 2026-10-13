"""Allowlisted, reference-only security audit for authorized historical actions."""

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel,
    TravellerHistoryGrantModel,
)
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


async def record_claim_action(
    session: AsyncSession, claim: TravellerClaimModel,
    action: Literal["claim_started", "proof_failed", "otp_failed", "otp_verified", "otp_delivery_failed",
                    "candidates_viewed", "claim_authorized", "contact_recovered"],
) -> None:
    """Bounded enum metrics and reference-only audit share the claim transaction."""
    await AuditLogRepository(session).record(
        action=f"traveller.{action}", entity_type="traveller_claim", entity_id=str(claim.id),
        agency_id=claim.agency_id,
        metadata={"company_id": str(claim.company_id), "group_id": str(claim.group_id),
                  "traveller_id": str(claim.traveller_id) if claim.traveller_id else None,
                  "method": claim.method, "state": claim.status},
    )
    metrics.increment(f"traveller.{action}")


async def record_history_action(
    session: AsyncSession, grant: TravellerHistoryGrantModel,
    action: Literal["history_viewed", "document_viewed", "trip_submitted"],
    *, reference: str | None = None,
) -> None:
    """Caller owns transaction; never record proof secrets, answers or documents."""
    await AuditLogRepository(session).record(
        action=f"traveller.{action}", entity_type="traveller_profile",
        entity_id=str(grant.traveller_id), agency_id=grant.agency_id,
        metadata={"company_id": str(grant.company_id), "group_id": str(grant.group_id),
                  "grant_id": str(grant.id), "actor_kind": grant.actor_kind, "reference": reference},
    )
