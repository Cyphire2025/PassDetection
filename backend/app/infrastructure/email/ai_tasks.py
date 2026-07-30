"""Celery entry points for asynchronous travel email analysis."""

from __future__ import annotations

import re
import uuid

from celery.utils.log import get_task_logger

from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.email.ai_runtime import (
    EmailAiClaim,
    release_email_ai_claim_after_error,
    release_email_ai_claim_after_publish_failure,
    run_email_ai_claim,
    seed_and_claim_email_ai_work,
)
from app.infrastructure.email.deadline_notifications import (
    scan_email_ai_deadline_notifications,
)
from app.infrastructure.processing.celery_app import celery_app

logger = get_task_logger(__name__)

EMAIL_AI_QUEUE = "email_ai"
EMAIL_AI_DISPATCH_QUEUE = "email_integrations"
EMAIL_AI_ANALYZE_TASK = "email.analyze_travel_message"
EMAIL_AI_DISPATCH_TASK = "email.dispatch_ai_analyses"
EMAIL_AI_DEADLINE_SCAN_TASK = "email.notify_ai_deadline_window"
_LEASE_TOKEN = re.compile(r"^[0-9a-f]{32}$")


@celery_app.task(
    bind=True,
    name=EMAIL_AI_DISPATCH_TASK,
    queue=EMAIL_AI_DISPATCH_QUEUE,
    max_retries=0,
)  # type: ignore[untyped-decorator]
def dispatch_email_ai_analyses(self: object) -> int:
    del self
    claims = celery_async_runtime.run(seed_and_claim_email_ai_work())
    published = 0
    for claim in claims:
        try:
            analyze_travel_email.apply_async(
                kwargs=claim.task_kwargs(),
                queue=EMAIL_AI_QUEUE,
            )
            published += 1
        except Exception as exc:
            logger.error(
                "email_ai_dispatch_publish_failed",
                extra={
                    "analysis_id": str(claim.analysis_id),
                    "error_type": type(exc).__name__,
                },
            )
            try:
                celery_async_runtime.run(
                    release_email_ai_claim_after_publish_failure(claim)
                )
            except Exception as release_exc:
                logger.error(
                    "email_ai_dispatch_release_failed",
                    extra={
                        "analysis_id": str(claim.analysis_id),
                        "error_type": type(release_exc).__name__,
                    },
                )
    return published


@celery_app.task(
    bind=True,
    name=EMAIL_AI_DEADLINE_SCAN_TASK,
    queue=EMAIL_AI_DISPATCH_QUEUE,
    max_retries=0,
)  # type: ignore[untyped-decorator]
def notify_email_ai_deadline_window(self: object) -> int:
    del self
    try:
        return celery_async_runtime.run(
            scan_email_ai_deadline_notifications()
        )
    except Exception as exc:
        logger.error(
            "email_ai_deadline_scan_failed",
            extra={"error_type": type(exc).__name__},
        )
        return 0


@celery_app.task(
    bind=True,
    name=EMAIL_AI_ANALYZE_TASK,
    queue=EMAIL_AI_QUEUE,
    max_retries=0,
)  # type: ignore[untyped-decorator]
def analyze_travel_email(
    self: object,
    *,
    analysis_id: str,
    agency_id: str,
    owner_user_id: str,
    connection_id: str,
    message_id: str,
    provider_account_id: str,
    sync_generation: int,
    lease_token: str,
) -> None:
    del self
    claim = _parse_claim(
        analysis_id=analysis_id,
        agency_id=agency_id,
        owner_user_id=owner_user_id,
        connection_id=connection_id,
        message_id=message_id,
        provider_account_id=provider_account_id,
        sync_generation=sync_generation,
        lease_token=lease_token,
    )
    if claim is None:
        logger.warning("email_ai_task_invalid_envelope")
        return
    try:
        celery_async_runtime.run(run_email_ai_claim(claim))
    except Exception as exc:
        logger.error(
            "email_ai_task_failed",
            extra={
                "analysis_id": str(claim.analysis_id),
                "error_type": type(exc).__name__,
            },
        )
        try:
            celery_async_runtime.run(release_email_ai_claim_after_error(claim))
        except Exception as release_exc:
            logger.error(
                "email_ai_task_release_failed",
                extra={
                    "analysis_id": str(claim.analysis_id),
                    "error_type": type(release_exc).__name__,
                },
            )


def _parse_claim(
    *,
    analysis_id: str,
    agency_id: str,
    owner_user_id: str,
    connection_id: str,
    message_id: str,
    provider_account_id: str,
    sync_generation: int,
    lease_token: str,
) -> EmailAiClaim | None:
    try:
        identifiers = [
            uuid.UUID(value)
            for value in (
                analysis_id,
                agency_id,
                owner_user_id,
                connection_id,
                message_id,
            )
        ]
    except (TypeError, ValueError):
        return None
    if (
        not isinstance(provider_account_id, str)
        or not 1 <= len(provider_account_id) <= 512
        or not isinstance(sync_generation, int)
        or isinstance(sync_generation, bool)
        or sync_generation < 0
        or not isinstance(lease_token, str)
        or _LEASE_TOKEN.fullmatch(lease_token) is None
    ):
        return None
    return EmailAiClaim(
        analysis_id=identifiers[0],
        agency_id=identifiers[1],
        owner_user_id=identifiers[2],
        connection_id=identifiers[3],
        message_id=identifiers[4],
        provider_account_id=provider_account_id,
        sync_generation=sync_generation,
        lease_token=lease_token,
    )
