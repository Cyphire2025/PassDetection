"""Release, defer, retry and pause only the currently validated claimed row."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from app.core.config.settings import Settings, get_settings
from app.domain.value_objects.email_ai_analysis import EmailAnalysisResult
from app.infrastructure.email.ai_claim import EmailAiClaim
from app.infrastructure.email.ai_runtime_dependencies import ClaimDependencies
from app.infrastructure.email.ai_values import _manual_retry_generation, _pause_loaded_analysis


async def _defer_for_ai_priority(
    claim: EmailAiClaim,
    *,
    retry_after_ms: int,
    dependencies: ClaimDependencies,
) -> None:
    """Release a capacity-deferred claim without consuming its attempt budget."""

    delay_seconds = min(300, max(1, math.ceil(retry_after_ms / 1_000)))
    async with dependencies.session_factory() as session:
        row = await dependencies.load_valid_claim(session, claim, for_update=True)
        if row is None:
            return
        analysis, _, _ = row
        analysis.status = "pending"
        analysis.attempt_count = max(0, analysis.attempt_count - 1)
        analysis.last_error_code = "ai_priority_admission_deferred"
        analysis.lease_token = None
        analysis.lease_expires_at = None
        analysis.next_attempt_at = datetime.now(tz=UTC) + timedelta(seconds=delay_seconds)
        analysis.started_at = None
        analysis.completed_at = None
        await session.commit()


async def release_email_ai_claim_after_error(
    claim: EmailAiClaim,
    *,
    settings: Settings | None = None,
    dependencies: ClaimDependencies,
) -> None:
    """Release a claimed row after an unexpected worker failure."""

    settings = settings or get_settings()
    async with dependencies.session_factory() as session:
        row = await dependencies.load_valid_claim(session, claim, for_update=True)
        if row is None:
            return
        analysis, message, connection = row
        analysis.last_error_code = "unexpected_runtime_error"
        analysis.lease_token = None
        analysis.lease_expires_at = None
        if analysis.attempt_count < settings.email_ai_max_attempts:
            analysis.status = "pending"
            analysis.next_attempt_at = datetime.now(tz=UTC) + timedelta(seconds=30)
        else:
            analysis.status = "failed"
            analysis.needs_attention = True
            analysis.completed_at = datetime.now(tz=UTC)
            analysis.next_attempt_at = None
            if settings.email_ai_notifications_ready:
                await dependencies.notification_repository(session).create(
                    agency_id=analysis.agency_id,
                    user_id=analysis.owner_user_id,
                    type="email_ai_failure",
                    title="Travel email analysis needs attention",
                    message=(
                        "Automated analysis could not be completed after retrying. "
                        "The synchronized email remains available for manual review."
                    ),
                    entity_type="email_message",
                    entity_id=str(message.id),
                    priority="high",
                    category="email_operations",
                    dedupe_key=(
                        f"email-ai:{analysis.id}:persistent-failure:"
                        f"{_manual_retry_generation(analysis)}"
                    ),
                    metadata={
                        "provider": connection.provider,
                        "account_email": connection.email_address,
                        "analysis_id": str(analysis.id),
                    },
                )
        await session.commit()


async def release_email_ai_claim_after_publish_failure(
    claim: EmailAiClaim,
    *,
    dependencies: ClaimDependencies,
) -> None:
    """Release broker-undelivered work without spending a provider attempt."""

    async with dependencies.session_factory() as session:
        row = await dependencies.load_valid_claim(session, claim, for_update=True)
        if row is None:
            return
        analysis, _, _ = row
        analysis.status = "pending"
        analysis.attempt_count = max(0, analysis.attempt_count - 1)
        analysis.last_error_code = "broker_publish_failed"
        analysis.lease_token = None
        analysis.lease_expires_at = None
        analysis.next_attempt_at = datetime.now(tz=UTC) + timedelta(seconds=5)
        analysis.started_at = None
        analysis.completed_at = None
        await session.commit()


async def _retry_transient_failure(
    claim: EmailAiClaim,
    *,
    result: EmailAnalysisResult,
    settings: Settings,
    dependencies: ClaimDependencies,
) -> bool:
    async with dependencies.session_factory() as session:
        row = await dependencies.load_valid_claim(session, claim, for_update=True)
        if row is None:
            return True
        analysis, _, _ = row
        if analysis.attempt_count >= settings.email_ai_max_attempts:
            return False
        delay_seconds = min(300, 10 * (2 ** max(0, analysis.attempt_count - 1)))
        analysis.status = "pending"
        analysis.last_error_code = result.reason_code or result.provider_status.value
        analysis.lease_token = None
        analysis.lease_expires_at = None
        analysis.next_attempt_at = datetime.now(tz=UTC) + timedelta(seconds=delay_seconds)
        await session.commit()
        return True


async def _finish_without_analysis(
    claim: EmailAiClaim,
    *,
    status: str,
    error_code: str,
    dependencies: ClaimDependencies,
) -> None:
    async with dependencies.session_factory() as session:
        row = await dependencies.load_valid_claim(session, claim, for_update=True)
        if row is None:
            return
        analysis, _, _ = row
        analysis.status = status
        analysis.last_error_code = error_code
        analysis.needs_attention = status == "failed"
        analysis.completed_at = datetime.now(tz=UTC)
        analysis.lease_token = None
        analysis.lease_expires_at = None
        await session.commit()


async def _pause_claim_for_policy(
    claim: EmailAiClaim,
    *,
    error_code: str,
    dependencies: ClaimDependencies,
) -> None:
    async with dependencies.session_factory() as session:
        row = await dependencies.load_valid_claim(session, claim, for_update=True)
        if row is None:
            return
        analysis, _, _ = row
        _pause_loaded_analysis(analysis, error_code=error_code)
        await session.commit()
