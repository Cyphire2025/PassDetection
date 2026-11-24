"""Stage seeds and claim leases atomically after bounded fair SQL selection."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.application.use_cases.email_integrations.analysis_contract import EMAIL_AI_SCHEMA_VERSION
from app.core.config.settings import Settings
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.email_models import EmailMessageModel
from app.infrastructure.email.ai_claim import EmailAiClaim
from app.infrastructure.email.ai_claim_query import build_claim_query
from app.infrastructure.email.ai_runtime_dependencies import SessionFactory
from app.infrastructure.email.ai_seed_query import build_seed_query


async def seed_and_claim_work(
    settings: Settings,
    *,
    session_factory: SessionFactory,
    seed_input_hash: Callable[[EmailMessageModel], str],
    dispatch_batch_size: int,
    per_owner_seed_limit: int,
    per_owner_claim_limit: int,
    claim_starvation_age: timedelta,
    office_roles: set[str],
    settled_statuses: set[str],
) -> list[EmailAiClaim]:
    if not settings.email_ai_runtime_ready:
        return []
    now = datetime.now(tz=UTC)
    async with session_factory() as session:
        seed_result = await session.execute(
            build_seed_query(
                now=now,
                starvation_age=claim_starvation_age,
                per_owner_limit=per_owner_seed_limit,
                batch_size=dispatch_batch_size,
                office_roles=office_roles,
                settled_statuses=settled_statuses,
            )
        )
        for message, connection in seed_result.all():
            session.add(
                EmailAiAnalysisModel(
                    agency_id=message.agency_id,
                    owner_user_id=message.owner_user_id,
                    connection_id=message.connection_id,
                    message_id=message.id,
                    status="pending",
                    input_hash=seed_input_hash(message),
                    prompt_schema_version=EMAIL_AI_SCHEMA_VERSION,
                    config_version=settings.gemini_config_version,
                    ai_model=settings.gemini_model,
                )
            )
        await session.flush()

        active_claim_count = int(
            await session.scalar(
                select(func.count(EmailAiAnalysisModel.id)).where(
                    EmailAiAnalysisModel.status == "processing",
                    EmailAiAnalysisModel.lease_expires_at > now,
                )
            )
            or 0
        )
        claim_limit = max(
            0,
            settings.email_ai_max_inflight - active_claim_count,
        )
        if claim_limit == 0:
            await session.commit()
            return []

        claim_result = await session.execute(
            build_claim_query(
                now=now,
                starvation_age=claim_starvation_age,
                per_owner_limit=per_owner_claim_limit,
                claim_limit=claim_limit,
                max_attempts=settings.email_ai_max_attempts,
                office_roles=office_roles,
                settled_statuses=settled_statuses,
            )
        )
        claims: list[EmailAiClaim] = []
        for analysis, connection in claim_result.all():
            lease_token = uuid.uuid4().hex
            analysis.status = "processing"
            analysis.lease_token = lease_token
            analysis.lease_expires_at = now + timedelta(seconds=settings.email_ai_lease_seconds)
            analysis.next_attempt_at = None
            analysis.attempt_count += 1
            analysis.started_at = now
            claims.append(
                EmailAiClaim(
                    analysis_id=analysis.id,
                    agency_id=analysis.agency_id,
                    owner_user_id=analysis.owner_user_id,
                    connection_id=analysis.connection_id,
                    message_id=analysis.message_id,
                    provider_account_id=connection.provider_account_id,
                    sync_generation=connection.sync_generation,
                    lease_token=lease_token,
                )
            )
        await session.commit()
        return claims
