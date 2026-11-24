"""One claimed broadcast provider attempt and known-acceptance persistence."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.core.config.settings import Settings
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError


@dataclass(frozen=True, slots=True)
class BroadcastProviderCallbacks:
    load_recipient: Callable[
        ..., Awaitable[tuple[WhatsAppBroadcastRecipientModel | None, str | None]]
    ]
    set_message_state: Callable[..., Awaitable[None]]
    send_template: Callable[..., Awaitable[str]]
    bind_provider_message: Callable[..., Awaitable[None]]


async def submit_broadcast_log(
    session: AsyncSession,
    *,
    log: WhatsAppMessageLogModel,
    log_id: uuid.UUID,
    parsed_batch_id: uuid.UUID,
    settings: Settings,
    client: httpx.AsyncClient,
    message_type: WhatsAppMessageType,
    parameters: list[str],
    header_parameters: list[str],
    include_previous_recipients: bool,
    max_attempts: int,
    accepted_statuses: Collection[str],
    callbacks: BroadcastProviderCallbacks,
) -> None:
    for attempt in range(max_attempts):
        recipient, claim_error = await callbacks.load_recipient(
            session,
            log=log,
            expected_batch_id=parsed_batch_id,
            include_previous_recipients=include_previous_recipients,
        )
        if not recipient:
            log.status = "failed"
            log.status_updated_at = datetime.now(tz=UTC)
            log.error_message = claim_error
            await callbacks.set_message_state(
                session,
                log=log,
                expected_batch_id=parsed_batch_id,
                state_status="failed",
                release_claim=True,
            )
            await session.commit()
            break
        try:
            provider_id = await callbacks.send_template(
                client=client,
                settings=settings,
                to_number=recipient.normalized_phone_number,
                template_name=log.template_name or "",
                message_type=message_type,
                parameters=parameters,
                header_parameters=header_parameters,
                language_code=(
                    getattr(log, "template_language", None)
                    or (
                        settings.whatsapp_group_invite_template_language
                        if message_type == "group_invite"
                        else settings.whatsapp_template_language
                    )
                ),
            )
        except WhatsAppCloudApiError as exc:
            safe_error = exc.persistence_message[:2000]
            if exc.delivery_unknown:
                log.status = "delivery_unknown"
                log.status_updated_at = datetime.now(tz=UTC)
                log.error_message = safe_error
                await callbacks.set_message_state(
                    session,
                    log=log,
                    expected_batch_id=parsed_batch_id,
                    state_status="delivery_unknown",
                )
                await session.commit()
                break
            if exc.transient and attempt + 1 < max_attempts:
                log.status = "processing"
                log.status_updated_at = datetime.now(tz=UTC)
                log.error_message = (f"{exc.code}: Temporary provider error; retrying")[:2000]
                await session.commit()
                await asyncio.sleep(2**attempt)
                continue
            log.status = "failed"
            log.status_updated_at = datetime.now(tz=UTC)
            log.error_message = safe_error
            await callbacks.set_message_state(
                session,
                log=log,
                expected_batch_id=parsed_batch_id,
                state_status="failed",
                release_claim=True,
            )
            await session.commit()
            break
        except Exception:  # noqa: BLE001 - outcome may be ambiguous.
            log.status = "delivery_unknown"
            log.status_updated_at = datetime.now(tz=UTC)
            log.error_message = (
                "WhatsApp delivery outcome is unknown; automatic resend is suppressed"
            )
            await callbacks.set_message_state(
                session,
                log=log,
                expected_batch_id=parsed_batch_id,
                state_status="delivery_unknown",
            )
            await session.commit()
            break

        try:
            log_id = log.id
            log.status = "submitted"
            log.status_updated_at = datetime.now(tz=UTC)
            log.provider_message_id = provider_id
            log.error_message = None
            await callbacks.bind_provider_message(
                session, log, provider_phone_number_id=settings.whatsapp_phone_number_id
            )
            await callbacks.set_message_state(
                session,
                log=log,
                expected_batch_id=parsed_batch_id,
                state_status="submitted",
                submitted=True,
            )
            await session.commit()
            break
        except Exception:
            # Meta returned a provider ID. A local commit failure
            # must never release the recipient for another send.
            await session.rollback()
            reconciliation_result = await session.execute(
                select(WhatsAppMessageLogModel)
                .where(WhatsAppMessageLogModel.id == log_id)
                .with_for_update()
            )
            reconciliation_log = reconciliation_result.scalar_one_or_none()
            if reconciliation_log:
                if reconciliation_log.status not in accepted_statuses:
                    reconciliation_log.status = "submitted"
                    reconciliation_log.status_updated_at = datetime.now(tz=UTC)
                reconciliation_log.provider_message_id = provider_id
                reconciliation_log.error_message = None
                await callbacks.bind_provider_message(
                    session,
                    reconciliation_log,
                    provider_phone_number_id=settings.whatsapp_phone_number_id,
                )
                await callbacks.set_message_state(
                    session,
                    log=reconciliation_log,
                    expected_batch_id=parsed_batch_id,
                    state_status="submitted",
                    submitted=True,
                )
                await session.commit()
            else:
                raise
            break
