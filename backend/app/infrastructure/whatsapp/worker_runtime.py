"""Worker-side WhatsApp broadcast orchestration with live compatibility seams."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import (
    WhatsAppMessageType,
    format_support_contacts,
    template_header_parameters,
    template_parameters,
)
from app.core.config.settings import get_settings
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.whatsapp import broadcast_worker_policy as _policy
from app.infrastructure.whatsapp import broadcast_worker_provider as _provider
from app.infrastructure.whatsapp import broadcast_worker_state as _state
from app.infrastructure.whatsapp.broadcast_worker_state import (
    ACCEPTED_DELIVERY_STATUSES as ACCEPTED_DELIVERY_STATUSES,
)
from app.infrastructure.whatsapp.cloud_api_provider import send_whatsapp_template
from app.infrastructure.whatsapp.mcp_dispatch import authorize_mcp_batch_dispatch
from app.infrastructure.whatsapp.mcp_progress import refresh_mcp_dispatch_progress
from app.infrastructure.whatsapp.phone_welcome import (
    assert_phone_welcome_claim,
    sync_welcome_from_log,
)
from app.infrastructure.whatsapp.receipt_bindings import bind_source_provider_message
from app.infrastructure.whatsapp.worker_recovery import lock_interrupted_broadcast_log

MAX_PROVIDER_ATTEMPTS = 3
WHATSAPP_BATCH_HEARTBEAT_INTERVAL = timedelta(minutes=5)


_resolve_log_template_snapshot = _policy._resolve_log_template_snapshot
_heartbeat_queued_batch_claims = _state._heartbeat_queued_batch_claims


async def _set_message_state(
    session: AsyncSession,
    *,
    log: WhatsAppMessageLogModel,
    expected_batch_id: uuid.UUID,
    state_status: str,
    release_claim: bool = False,
    submitted: bool = False,
) -> None:
    await _state._set_message_state(
        session,
        log=log,
        expected_batch_id=expected_batch_id,
        state_status=state_status,
        release_claim=release_claim,
        submitted=submitted,
        callbacks=_state.BroadcastStateCallbacks(
            sync_welcome_from_log, refresh_mcp_dispatch_progress
        ),
    )


async def _load_sendable_recipient(
    session: AsyncSession,
    *,
    log: WhatsAppMessageLogModel,
    expected_batch_id: uuid.UUID,
    include_previous_recipients: bool = False,
) -> tuple[WhatsAppBroadcastRecipientModel | None, str | None]:
    return await _policy._load_sendable_recipient(
        session,
        log=log,
        expected_batch_id=expected_batch_id,
        include_previous_recipients=include_previous_recipients,
        callbacks=_policy.BroadcastPolicyCallbacks(
            get_settings,
            authorize_mcp_batch_dispatch,
            assert_phone_welcome_claim,
        ),
    )


async def run_whatsapp_broadcast(
    *,
    batch_id: str,
    message_type: WhatsAppMessageType,
    message_content: str,
    passport_link: str | None,
    header_image_id: str | None = None,
    passport_intro: str | None = None,
    group_invite_link: str | None = None,
    include_previous_recipients: bool = False,
) -> None:
    parsed_batch_id = uuid.UUID(batch_id)
    settings = get_settings()
    timeout = httpx.Timeout(20.0, connect=5.0)

    async with AsyncSessionFactory() as session:
        logs_result = await session.execute(
            select(WhatsAppMessageLogModel)
            .where(WhatsAppMessageLogModel.batch_id == parsed_batch_id)
            .order_by(WhatsAppMessageLogModel.created_at.asc())
        )
        logs = list(logs_result.scalars().all())
        if not logs:
            return

        group_result = await session.execute(
            select(WhatsAppBroadcastGroupModel).where(
                WhatsAppBroadcastGroupModel.id == logs[0].broadcast_group_id
            )
        )
        group = group_result.scalar_one_or_none()
        if not group:
            for log in logs:
                now = datetime.now(tz=UTC)
                if log.status not in {"queued", "processing"}:
                    continue
                log.status = "failed"
                log.status_updated_at = now
                log.error_message = "WhatsApp broadcast group no longer exists"
                await _set_message_state(
                    session,
                    log=log,
                    expected_batch_id=parsed_batch_id,
                    state_status="failed",
                    release_claim=True,
                )
            await session.commit()
            return

        support_result = await session.execute(
            select(WhatsAppBroadcastSupportContactModel)
            .where(WhatsAppBroadcastSupportContactModel.broadcast_group_id == group.id)
            .order_by(
                WhatsAppBroadcastSupportContactModel.sort_order.asc(),
                WhatsAppBroadcastSupportContactModel.created_at.asc(),
            )
        )
        support_contacts = list(support_result.scalars().all())
        support_block = format_support_contacts(
            [(contact.name, contact.phone_number) for contact in support_contacts]
        )
        # Rollback expires every ORM instance in the session, including primary
        # keys and the broadcast loaded above. Keep only immutable values across
        # recipient transactions and explicitly load each successfully claimed row.
        log_ids = tuple(log.id for log in logs)
        group_name = group.name

        last_batch_heartbeat_at = datetime.now(tz=UTC)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for log_id in log_ids:
                heartbeat_at = datetime.now(tz=UTC)
                if heartbeat_at - last_batch_heartbeat_at >= WHATSAPP_BATCH_HEARTBEAT_INTERVAL:
                    await _heartbeat_queued_batch_claims(
                        session,
                        batch_id=parsed_batch_id,
                        heartbeat_at=heartbeat_at,
                    )
                    last_batch_heartbeat_at = heartbeat_at
                claim_time = datetime.now(tz=UTC)
                claim_result = await session.execute(
                    update(WhatsAppMessageLogModel)
                    .where(
                        WhatsAppMessageLogModel.id == log_id,
                        WhatsAppMessageLogModel.status == "queued",
                    )
                    .values(
                        status="processing",
                        status_updated_at=claim_time,
                    )
                    .returning(WhatsAppMessageLogModel.id)
                    .execution_options(synchronize_session=False)
                )
                claimed_id = claim_result.scalar_one_or_none()
                if not claimed_id:
                    await session.rollback()
                    current_log = await lock_interrupted_broadcast_log(session, log_id, settings)
                    if current_log and current_log.status == "processing":
                        now = datetime.now(tz=UTC)
                        current_log.status = "delivery_unknown"
                        current_log.status_updated_at = now
                        current_log.error_message = (
                            "A retried worker found an interrupted provider "
                            "request; automatic resend is suppressed"
                        )
                        await _set_message_state(
                            session,
                            log=current_log,
                            expected_batch_id=parsed_batch_id,
                            state_status="delivery_unknown",
                        )
                        await session.commit()
                    continue
                claimed_log_result = await session.execute(
                    select(WhatsAppMessageLogModel)
                    .where(WhatsAppMessageLogModel.id == log_id)
                    .execution_options(populate_existing=True)
                )
                log = claimed_log_result.scalar_one()
                if not getattr(log, "is_explicit_resend", False):
                    state_claim_result = await session.execute(
                        update(WhatsAppRecipientMessageStateModel)
                        .where(
                            WhatsAppRecipientMessageStateModel.recipient_id == log.recipient_id,
                            WhatsAppRecipientMessageStateModel.message_type == log.message_type,
                            WhatsAppRecipientMessageStateModel.batch_id == parsed_batch_id,
                            WhatsAppRecipientMessageStateModel.status == "queued",
                        )
                        .values(
                            status="processing",
                            status_updated_at=claim_time,
                            updated_at=claim_time,
                        )
                        .returning(WhatsAppRecipientMessageStateModel.id)
                        .execution_options(synchronize_session=False)
                    )
                    state_claimed_id = state_claim_result.scalar_one_or_none()
                    if not state_claimed_id:
                        await session.execute(
                            update(WhatsAppMessageLogModel)
                            .where(WhatsAppMessageLogModel.id == log.id)
                            .values(
                                status="failed",
                                status_updated_at=claim_time,
                                error_message=(
                                    "Delivery claim was superseded before provider submission"
                                ),
                            )
                            .execution_options(synchronize_session=False)
                        )
                        await session.commit()
                        continue
                await sync_welcome_from_log(session, log)
                await session.commit()
                recipient, claim_error = await _load_sendable_recipient(
                    session,
                    log=log,
                    expected_batch_id=parsed_batch_id,
                    include_previous_recipients=include_previous_recipients,
                )
                if not recipient:
                    log.status = "failed"
                    log.status_updated_at = datetime.now(tz=UTC)
                    log.error_message = claim_error
                    await _set_message_state(
                        session,
                        log=log,
                        expected_batch_id=parsed_batch_id,
                        state_status="failed",
                        release_claim=True,
                    )
                    await session.commit()
                    continue

                fallback_parameters = template_parameters(
                    message_type=message_type,
                    group_name=group_name,
                    support_contacts=support_block,
                    message_content=message_content,
                    passport_link=passport_link,
                    passport_intro=passport_intro,
                    group_invite_link=group_invite_link,
                )
                fallback_header_parameters = template_header_parameters(
                    message_type=message_type,
                    header_image_id=header_image_id,
                )
                try:
                    header_parameters, parameters = _resolve_log_template_snapshot(
                        log=log,
                        message_type=message_type,
                        fallback_header_parameters=fallback_header_parameters,
                        fallback_parameters=fallback_parameters,
                    )
                except ValueError as exc:
                    log.status = "failed"
                    log.status_updated_at = datetime.now(tz=UTC)
                    log.error_message = f"Invalid saved WhatsApp template payload: {exc}"[:2000]
                    await _set_message_state(
                        session,
                        log=log,
                        expected_batch_id=parsed_batch_id,
                        state_status="failed",
                        release_claim=True,
                    )
                    await session.commit()
                    continue
                await _provider.submit_broadcast_log(
                    session,
                    log=log,
                    log_id=log_id,
                    parsed_batch_id=parsed_batch_id,
                    settings=settings,
                    client=client,
                    message_type=message_type,
                    parameters=parameters,
                    header_parameters=header_parameters,
                    include_previous_recipients=include_previous_recipients,
                    max_attempts=MAX_PROVIDER_ATTEMPTS,
                    accepted_statuses=ACCEPTED_DELIVERY_STATUSES,
                    callbacks=_provider.BroadcastProviderCallbacks(
                        _load_sendable_recipient,
                        _set_message_state,
                        send_whatsapp_template,
                        bind_source_provider_message,
                    ),
                )


async def mark_whatsapp_batch_failed(*, batch_id: str, error_message: str) -> None:
    """Move any stranded queued rows to a terminal state after retries are exhausted."""

    await _state.mark_whatsapp_batch_failed(
        batch_id=batch_id,
        error_message=error_message,
        session_factory=AsyncSessionFactory,
        set_message_state=_set_message_state,
    )
