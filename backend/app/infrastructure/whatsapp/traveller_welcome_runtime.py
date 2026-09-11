"""Durable, bounded welcomes to submitted traveller phones without roster edits."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import validate_template_parameters
from app.core.config.settings import get_settings
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppPhoneWelcomeAttemptModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_template,
)
from app.infrastructure.whatsapp.phone_welcome import assert_phone_welcome_claim, sync_phone_welcome
from app.infrastructure.whatsapp.traveller_destinations import load_traveller_destinations


async def _sync_attempt(session: AsyncSession, attempt: WhatsAppPhoneWelcomeAttemptModel) -> None:
    await sync_phone_welcome(
        session,
        agency_id=attempt.agency_id,
        phone=attempt.normalized_phone_number,
        attempt_id=attempt.id,
        status=attempt.status,
        provider_status_at=attempt.provider_status_at,
    )


async def _commit_provider_outcome(
    session: AsyncSession,
    attempt: WhatsAppPhoneWelcomeAttemptModel,
) -> None:
    attempt_id, provider_id = attempt.id, attempt.provider_message_id
    try:
        await _sync_attempt(session, attempt)
        await session.commit()
    except Exception:
        await session.rollback()
        if not provider_id:
            raise
        saved = (
            await session.execute(
                select(WhatsAppPhoneWelcomeAttemptModel)
                .where(
                    WhatsAppPhoneWelcomeAttemptModel.id == attempt_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if saved is None:
            raise
        if saved.status not in {"sent", "delivered", "read"}:
            saved.status = "submitted"
        saved.provider_message_id = provider_id
        saved.error_message = None
        saved.status_updated_at = saved.updated_at = datetime.now(tz=UTC)
        await _sync_attempt(session, saved)
        await session.commit()


async def _lock_current_source(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    broadcast_group_id: uuid.UUID,
    passenger_ids: list[str],
    phone: str,
) -> bool:
    group = (
        await session.execute(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == group_id,
                ClientGroupModel.agency_id == agency_id,
                ClientGroupModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if group is None:
        return False
    source = (
        await session.execute(
            select(WhatsAppBroadcastGroupModel)
            .join(
                ClientGroupWhatsAppBroadcastLinkModel,
                ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id
                == WhatsAppBroadcastGroupModel.id,
            )
            .where(
                ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
                ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
                WhatsAppBroadcastGroupModel.id == broadcast_group_id,
                WhatsAppBroadcastGroupModel.agency_id == agency_id,
                WhatsAppBroadcastGroupModel.recipient_opt_in_confirmed_at.is_not(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if source is None:
        return False
    destinations = await load_traveller_destinations(
        session,
        agency_id=agency_id,
        group_id=group_id,
        lock=True,
    )
    current_ids = {
        str(item.passenger_id)
        for item in destinations
        if item.phone_number == phone and item.reason is None
    }
    return bool(passenger_ids) and set(passenger_ids) <= current_ids


def apply_traveller_welcome_provider_status(
    attempt: WhatsAppPhoneWelcomeAttemptModel,
    *,
    provider_status: str,
    error_message: str | None,
    provider_status_at: datetime | None,
    now: datetime,
) -> None:
    rank = {"submitted": 0, "sent": 1, "delivered": 2, "read": 3}
    if attempt.provider_status_at and provider_status_at:
        current_at = attempt.provider_status_at
        if current_at.tzinfo is None:
            current_at = current_at.replace(tzinfo=UTC)
        if provider_status_at < current_at:
            return
    if provider_status in rank:
        if rank[provider_status] < rank.get(attempt.status, -1):
            return
        attempt.status = provider_status
        attempt.error_message = None
    elif provider_status == "failed" and attempt.status not in {"delivered", "read"}:
        attempt.status = "failed"
        attempt.error_message = error_message
    else:
        return
    attempt.provider_status_at = provider_status_at or attempt.provider_status_at
    attempt.status_updated_at = attempt.updated_at = now


async def _run_attempt(attempt_id: uuid.UUID, client: httpx.AsyncClient) -> None:
    async with AsyncSessionFactory() as session:
        claimed = (
            await session.execute(
                update(WhatsAppPhoneWelcomeAttemptModel)
                .where(
                    WhatsAppPhoneWelcomeAttemptModel.id == attempt_id,
                    WhatsAppPhoneWelcomeAttemptModel.status == "queued",
                )
                .values(status="processing", status_updated_at=datetime.now(tz=UTC))
                .returning(WhatsAppPhoneWelcomeAttemptModel.id)
                .execution_options(synchronize_session=False)
            )
        ).scalar_one_or_none()
        attempt = (
            await session.execute(
                select(WhatsAppPhoneWelcomeAttemptModel)
                .where(
                    WhatsAppPhoneWelcomeAttemptModel.id == attempt_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if attempt is None:
            return
        if claimed is None:
            updated_at = attempt.status_updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
            if attempt.status == "processing" and updated_at < datetime.now(UTC) - timedelta(
                minutes=30
            ):
                attempt.status = "delivery_unknown"
                attempt.error_message = (
                    "Interrupted welcome delivery; automatic resend is suppressed."
                )
                await _sync_attempt(session, attempt)
                await session.commit()
            return
        await _sync_attempt(session, attempt)
        source = (
            attempt.agency_id,
            attempt.group_id,
            attempt.broadcast_group_id,
            list(attempt.passenger_ids),
            attempt.normalized_phone_number,
        )
        await session.commit()

        for provider_attempt in range(3):
            allowed = await _lock_current_source(
                session,
                agency_id=source[0],
                group_id=source[1],
                broadcast_group_id=source[2],
                passenger_ids=source[3],
                phone=source[4],
            )
            current = (
                await session.execute(
                    select(WhatsAppPhoneWelcomeAttemptModel)
                    .where(
                        WhatsAppPhoneWelcomeAttemptModel.id == attempt_id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            if current is None or current.status != "processing":
                return
            claimed_phone = await assert_phone_welcome_claim(
                session,
                agency_id=current.agency_id,
                phone=current.normalized_phone_number,
                attempt_id=current.id,
            )
            current_source = (
                current.agency_id,
                current.group_id,
                current.broadcast_group_id,
                list(current.passenger_ids),
                current.normalized_phone_number,
            )
            if not allowed or not claimed_phone or current_source != source:
                current.status = "failed"
                current.error_message = "Traveller details, welcome prerequisite, or source list changed. Refresh the preview."
                await _sync_attempt(session, current)
                await session.commit()
                return
            try:
                validate_template_parameters(
                    message_type="welcome",
                    header_parameters=current.header_parameter_values,
                    body_parameters=current.template_parameter_values,
                )
            except (ValueError, TypeError):
                current.status = "failed"
                current.error_message = (
                    "The saved welcome template is incomplete. Review it before retrying."
                )
                await _sync_attempt(session, current)
                await session.commit()
                return
            retry = False
            try:
                provider_id = await send_whatsapp_template(
                    client=client,
                    settings=get_settings(),
                    to_number=current.normalized_phone_number,
                    template_name=current.template_name,
                    message_type="welcome",
                    parameters=current.template_parameter_values,
                    header_parameters=current.header_parameter_values,
                )
            except WhatsAppCloudApiError as exc:
                current.status = "delivery_unknown" if exc.delivery_unknown else "failed"
                current.error_message = exc.persistence_message[:2000]
                if exc.transient and not exc.delivery_unknown and provider_attempt < 2:
                    current.status = "processing"
                    retry = True
            except Exception:
                current.status = "delivery_unknown"
                current.error_message = (
                    "Welcome delivery outcome is unknown; automatic resend is suppressed."
                )
            else:
                current.status = "submitted"
                current.provider_message_id = provider_id
                current.error_message = None
            current.status_updated_at = current.updated_at = datetime.now(tz=UTC)
            # Preserve a known provider ID after a transient commit failure.
            # A persistent DB outage leaves processing durable; scheduled
            # recovery eventually marks it unknown without submitting again.
            await _commit_provider_outcome(session, current)
            if not retry:
                return
            await asyncio.sleep(2**provider_attempt)


async def run_traveller_welcome_broadcast(*, batch_id: str) -> None:
    async with AsyncSessionFactory() as session:
        ids = list(
            (
                await session.execute(
                    select(WhatsAppPhoneWelcomeAttemptModel.id)
                    .where(
                        WhatsAppPhoneWelcomeAttemptModel.batch_id == uuid.UUID(batch_id),
                    )
                    .order_by(WhatsAppPhoneWelcomeAttemptModel.id)
                )
            )
            .scalars()
            .all()
        )
    async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5)) as client:
        last_heartbeat = datetime.now(tz=UTC)
        for attempt_id in ids:
            now = datetime.now(tz=UTC)
            if now - last_heartbeat >= timedelta(minutes=5):
                await _heartbeat_queued_welcomes(uuid.UUID(batch_id), now)
                last_heartbeat = now
            await _run_attempt(attempt_id, client)


async def _heartbeat_queued_welcomes(batch_id: uuid.UUID, now: datetime) -> None:
    async with AsyncSessionFactory() as session:
        await session.execute(
            update(WhatsAppPhoneWelcomeAttemptModel)
            .where(
                WhatsAppPhoneWelcomeAttemptModel.batch_id == batch_id,
                WhatsAppPhoneWelcomeAttemptModel.status == "queued",
            )
            .values(status_updated_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        await session.commit()


async def mark_traveller_welcome_batch_failed(*, batch_id: str, error_message: str) -> None:
    async with AsyncSessionFactory() as session:
        attempts = (
            (
                await session.execute(
                    select(WhatsAppPhoneWelcomeAttemptModel)
                    .where(
                        WhatsAppPhoneWelcomeAttemptModel.batch_id == uuid.UUID(batch_id),
                        WhatsAppPhoneWelcomeAttemptModel.status.in_({"queued", "processing"}),
                    )
                    .order_by(
                        WhatsAppPhoneWelcomeAttemptModel.agency_id,
                        WhatsAppPhoneWelcomeAttemptModel.normalized_phone_number,
                        WhatsAppPhoneWelcomeAttemptModel.id,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for attempt in attempts:
            attempt.status = "delivery_unknown" if attempt.status == "processing" else "failed"
            attempt.error_message = error_message[:2000]
            attempt.status_updated_at = attempt.updated_at = datetime.now(tz=UTC)
            await _sync_attempt(session, attempt)
        await session.commit()


async def process_traveller_welcome_receipt(
    session: AsyncSession,
    *,
    provider_id: str,
    provider_status: str,
    error_message: str | None,
    provider_status_at: datetime | None,
) -> int:
    attempts = (
        (
            await session.execute(
                select(WhatsAppPhoneWelcomeAttemptModel)
                .where(
                    WhatsAppPhoneWelcomeAttemptModel.provider_message_id == provider_id,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for attempt in attempts:
        apply_traveller_welcome_provider_status(
            attempt,
            provider_status=provider_status,
            error_message=error_message,
            provider_status_at=provider_status_at,
            now=datetime.now(tz=UTC),
        )
        await _sync_attempt(session, attempt)
    return len(attempts)
