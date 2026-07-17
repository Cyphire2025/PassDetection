"""Worker-side WhatsApp broadcast execution."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, update

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
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_template,
)

MAX_PROVIDER_ATTEMPTS = 3


async def run_whatsapp_broadcast(
    *,
    batch_id: str,
    message_type: WhatsAppMessageType,
    message_content: str,
    passport_link: str | None,
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
                if log.status not in {"queued", "processing"}:
                    continue
                log.status = "failed"
                log.status_updated_at = datetime.now(tz=UTC)
                log.error_message = "WhatsApp broadcast group no longer exists"
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

        recipient_ids = [log.recipient_id for log in logs]
        recipients_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.id.in_(recipient_ids)
            )
        )
        recipients = {recipient.id: recipient for recipient in recipients_result.scalars().all()}

        async with httpx.AsyncClient(timeout=timeout) as client:
            for log in logs:
                claim_result = await session.execute(
                    update(WhatsAppMessageLogModel)
                    .where(
                        WhatsAppMessageLogModel.id == log.id,
                        WhatsAppMessageLogModel.status == "queued",
                    )
                    .values(
                        status="processing",
                        status_updated_at=datetime.now(tz=UTC),
                    )
                    .returning(WhatsAppMessageLogModel.id)
                    .execution_options(synchronize_session=False)
                )
                claimed_id = claim_result.scalar_one_or_none()
                await session.commit()
                if not claimed_id:
                    continue
                recipient = recipients.get(log.recipient_id)
                if not recipient:
                    log.status = "failed"
                    log.status_updated_at = datetime.now(tz=UTC)
                    log.error_message = "WhatsApp recipient no longer exists"
                    await session.commit()
                    continue

                parameters = template_parameters(
                    message_type=message_type,
                    recipient_name=recipient.name or "Guest",
                    group_name=group.name,
                    organizing_company_name=group.organizing_company_name or "your organisation",
                    support_contacts=support_block,
                    message_content=message_content,
                    passport_link=passport_link,
                )
                header_parameters = template_header_parameters(
                    message_type=message_type,
                    recipient_name=recipient.name or "Guest",
                )
                for attempt in range(MAX_PROVIDER_ATTEMPTS):
                    try:
                        provider_id = await send_whatsapp_template(
                            client=client,
                            settings=settings,
                            to_number=recipient.normalized_phone_number,
                            template_name=log.template_name or "",
                            parameters=parameters,
                            header_parameters=header_parameters,
                        )
                        log.status = "submitted"
                        log.status_updated_at = datetime.now(tz=UTC)
                        log.provider_message_id = provider_id
                        log.error_message = None
                        await session.commit()
                        break
                    except WhatsAppCloudApiError as exc:
                        if exc.transient and attempt + 1 < MAX_PROVIDER_ATTEMPTS:
                            log.status = "processing"
                            log.status_updated_at = datetime.now(tz=UTC)
                            log.error_message = f"Temporary provider error; retrying: {exc}"[:2000]
                            await session.commit()
                            await asyncio.sleep(2**attempt)
                            continue
                        log.status = "failed"
                        log.status_updated_at = datetime.now(tz=UTC)
                        log.error_message = str(exc)[:2000]
                        await session.commit()
                        break
                    except Exception as exc:  # noqa: BLE001 - isolate permanent unknown failures.
                        log.status = "failed"
                        log.status_updated_at = datetime.now(tz=UTC)
                        log.error_message = str(exc)[:2000]
                        await session.commit()
                        break


async def mark_whatsapp_batch_failed(*, batch_id: str, error_message: str) -> None:
    """Move any stranded queued rows to a terminal state after retries are exhausted."""

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(WhatsAppMessageLogModel).where(
                WhatsAppMessageLogModel.batch_id == uuid.UUID(batch_id),
                WhatsAppMessageLogModel.status.in_(["queued", "processing"]),
            )
        )
        for log in result.scalars().all():
            log.status = "failed"
            log.status_updated_at = datetime.now(tz=UTC)
            log.error_message = error_message[:2000]
        await session.commit()
