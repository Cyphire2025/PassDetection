"""Worker-side execution and receipt handling for attendance QR deliveries."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime

import httpx
from sqlalchemy import Select, select, update

from app.application.use_cases.whatsapp.qr_templates import (
    QR_DEFAULT_MESSAGE_CONTENT,
    qr_template_parameters,
)
from app.core.config.settings import get_settings
from app.infrastructure.database.models import (
    PassengerQRTokenModel,
    PassengerQrWhatsAppDeliveryModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.qr.approved_passenger_qr_issuer import qr_status
from app.infrastructure.qr.qr_image_renderer import render_attendance_qr_png
from app.infrastructure.whatsapp.bounded_delivery import (
    bounded_delivery_concurrency,
    run_bounded_delivery_items,
)
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_qr_template,
    upload_whatsapp_image,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    PRIVATE_DELIVERY_RECIPIENT_CHANGED,
    PrivateDeliveryGroupSourceSnapshot,
    lock_private_delivery_group_source_snapshot,
    validate_private_delivery_recipient,
)

MAX_PROVIDER_ATTEMPTS = 3
ACCEPTED_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})
ACCEPTED_STATUS_RANK = {"submitted": 0, "sent": 1, "delivered": 2, "read": 3}
logger = logging.getLogger(__name__)


def _qr_media_source_statement(
    *,
    delivery_id: uuid.UUID,
    send_batch_id: uuid.UUID,
) -> Select[tuple[PassengerQrWhatsAppDeliveryModel, PassengerQRTokenModel]]:
    return (
        select(
            PassengerQrWhatsAppDeliveryModel,
            PassengerQRTokenModel,
        )
        .join(
            PassengerQRTokenModel,
            PassengerQRTokenModel.id
            == PassengerQrWhatsAppDeliveryModel.qr_token_id,
        )
        .where(
            PassengerQrWhatsAppDeliveryModel.id == delivery_id,
            PassengerQrWhatsAppDeliveryModel.send_batch_id == send_batch_id,
            PassengerQrWhatsAppDeliveryModel.status == "processing",
            PassengerQRTokenModel.agency_id
            == PassengerQrWhatsAppDeliveryModel.agency_id,
            PassengerQRTokenModel.passenger_id
            == PassengerQrWhatsAppDeliveryModel.passenger_id,
        )
    )


def apply_qr_provider_status(
    delivery: PassengerQrWhatsAppDeliveryModel,
    *,
    provider_status: str,
    error_message: str | None,
    provider_status_at: datetime | None,
    now: datetime,
) -> None:
    """Apply Meta receipts monotonically so late webhooks cannot regress state."""

    if (
        delivery.provider_status_at
        and provider_status_at
        and provider_status_at < delivery.provider_status_at
    ):
        return
    if provider_status in ACCEPTED_STATUSES:
        current_rank = ACCEPTED_STATUS_RANK.get(delivery.status, -1)
        incoming_rank = ACCEPTED_STATUS_RANK[provider_status]
        if incoming_rank >= current_rank:
            delivery.status = provider_status
            delivery.status_updated_at = now
            delivery.provider_status_at = provider_status_at or delivery.provider_status_at
            delivery.updated_at = now
    elif provider_status == "failed" and delivery.status not in {"delivered", "read"}:
        delivery.status = "failed"
        delivery.status_updated_at = now
        delivery.provider_status_at = provider_status_at or delivery.provider_status_at
        delivery.updated_at = now
    if error_message:
        delivery.error_message = error_message[:2000]


async def _mark_delivery(
    delivery_id: uuid.UUID,
    *,
    status: str,
    error_message: str | None,
    provider_message_id: str | None = None,
    provider_media_id: str | None = None,
) -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(PassengerQrWhatsAppDeliveryModel)
            .where(PassengerQrWhatsAppDeliveryModel.id == delivery_id)
            .with_for_update()
        )
        delivery = result.scalar_one_or_none()
        if not delivery:
            return
        now = datetime.now(tz=UTC)
        delivery.status = status
        delivery.status_updated_at = now
        delivery.updated_at = now
        delivery.error_message = error_message[:2000] if error_message else None
        if provider_message_id:
            delivery.provider_message_id = provider_message_id
        if provider_media_id:
            delivery.provider_media_id = provider_media_id
        await session.commit()


async def run_qr_whatsapp_broadcast(
    *,
    send_batch_id: str,
    _delivery_id: uuid.UUID | None = None,
    _source_snapshot: PrivateDeliveryGroupSourceSnapshot | None = None,
    _client: httpx.AsyncClient | None = None,
) -> None:
    """Upload and send each currently active passenger QR exactly once."""

    parsed_batch_id = uuid.UUID(send_batch_id)
    settings = get_settings()
    timeout = httpx.Timeout(30.0, connect=5.0)

    if _delivery_id is None:
        async with AsyncSessionFactory() as session:
            rows_result = await session.execute(
                select(
                    PassengerQrWhatsAppDeliveryModel.id,
                    PassengerQrWhatsAppDeliveryModel.agency_id,
                    PassengerQrWhatsAppDeliveryModel.group_id,
                )
                .where(
                    PassengerQrWhatsAppDeliveryModel.send_batch_id
                    == parsed_batch_id
                )
                .order_by(PassengerQrWhatsAppDeliveryModel.created_at.asc())
            )
            batch_rows = list(rows_result.all())
            if not batch_rows:
                return
            source_pairs = {(row.agency_id, row.group_id) for row in batch_rows}
            if len(source_pairs) != 1:
                raise RuntimeError(
                    "A private delivery batch must belong to exactly one group"
                )
            agency_id, group_id = next(iter(source_pairs))
            source_snapshot = await lock_private_delivery_group_source_snapshot(
                session,
                agency_id=agency_id,
                group_id=group_id,
            )
            if source_snapshot is None:
                raise RuntimeError(
                    "The private delivery source is no longer available"
                )
            concurrency = bounded_delivery_concurrency(
                getattr(settings, "whatsapp_delivery_concurrency", 4)
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                await run_bounded_delivery_items(
                    [row.id for row in batch_rows],
                    lambda delivery_id: run_qr_whatsapp_broadcast(
                        send_batch_id=send_batch_id,
                        _delivery_id=delivery_id,
                        _source_snapshot=source_snapshot,
                        _client=client,
                    ),
                    concurrency=concurrency,
                )
        return

    delivery_ids = [_delivery_id]

    client_context = (
        nullcontext(_client)
        if _client is not None
        else httpx.AsyncClient(timeout=timeout)
    )
    async with client_context as client:
        for delivery_id in delivery_ids:
            async with AsyncSessionFactory() as session:
                claim_time = datetime.now(tz=UTC)
                claim_result = await session.execute(
                    update(PassengerQrWhatsAppDeliveryModel)
                    .where(
                        PassengerQrWhatsAppDeliveryModel.id == delivery_id,
                        PassengerQrWhatsAppDeliveryModel.send_batch_id == parsed_batch_id,
                        PassengerQrWhatsAppDeliveryModel.status == "queued",
                    )
                    .values(
                        status="processing",
                        status_updated_at=claim_time,
                        updated_at=claim_time,
                        attempt_count=(PassengerQrWhatsAppDeliveryModel.attempt_count + 1),
                    )
                    .returning(PassengerQrWhatsAppDeliveryModel.id)
                    .execution_options(synchronize_session=False)
                )
                claimed_id = claim_result.scalar_one_or_none()
                if not claimed_id:
                    await session.rollback()
                    stale_result = await session.execute(
                        select(PassengerQrWhatsAppDeliveryModel)
                        .where(
                            PassengerQrWhatsAppDeliveryModel.id == delivery_id,
                            PassengerQrWhatsAppDeliveryModel.send_batch_id == parsed_batch_id,
                            PassengerQrWhatsAppDeliveryModel.status == "processing",
                        )
                        .with_for_update()
                    )
                    stale = stale_result.scalar_one_or_none()
                    if stale:
                        stale.status = "delivery_unknown"
                        stale.status_updated_at = claim_time
                        stale.updated_at = claim_time
                        stale.error_message = (
                            "A retried worker found an interrupted provider request; "
                            "automatic resend is suppressed"
                        )
                        await session.commit()
                    continue
                await session.commit()

            async with AsyncSessionFactory() as session:
                data_result = await session.execute(
                    _qr_media_source_statement(
                        delivery_id=delivery_id,
                        send_batch_id=parsed_batch_id,
                    )
                )
                row = data_result.one_or_none()
                if not row:
                    await _mark_delivery(
                        delivery_id,
                        status="failed",
                        error_message="The saved QR code is no longer available",
                    )
                    continue
                delivery, token = row
                latest_result = await session.execute(
                    select(PassengerQRTokenModel.id)
                    .where(
                        PassengerQRTokenModel.agency_id == delivery.agency_id,
                        PassengerQRTokenModel.passenger_id == delivery.passenger_id,
                    )
                    .order_by(
                        PassengerQRTokenModel.token_version.desc(),
                        PassengerQRTokenModel.created_at.desc(),
                    )
                    .limit(1)
                )
                latest_token_id = latest_result.scalar_one_or_none()

            if latest_token_id != token.id or qr_status(token) != "active" or not token.qr_payload:
                await _mark_delivery(
                    delivery_id,
                    status="failed",
                    error_message=(
                        "This QR code is no longer active; preview the current QR before sending"
                    ),
                )
                continue

            try:
                image_content = await asyncio.to_thread(
                    render_attendance_qr_png,
                    token.qr_payload,
                )
            except ValueError:
                await _mark_delivery(
                    delivery_id,
                    status="failed",
                    error_message=(
                        "The saved QR image cannot be reconstructed; regenerate it before sending"
                    ),
                )
                continue

            media_id: str | None = None
            upload_failed = False
            for attempt in range(MAX_PROVIDER_ATTEMPTS):
                try:
                    media_id = await upload_whatsapp_image(
                        client=client,
                        settings=settings,
                        file_name="passenger-attendance-qr.png",
                        file_content=image_content,
                        content_type="image/png",
                    )
                    break
                except WhatsAppCloudApiError as exc:
                    if exc.transient and attempt + 1 < MAX_PROVIDER_ATTEMPTS:
                        await asyncio.sleep(2**attempt)
                        continue
                    await _mark_delivery(
                        delivery_id,
                        status="failed",
                        error_message=exc.persistence_message,
                    )
                    upload_failed = True
                    break
            if upload_failed or not media_id:
                continue

            # The batch coordinator retains one authoritative identity-source
            # fence. Lock only this item's QR token and delivery row here so
            # distinct provider requests can overlap safely.
            async with AsyncSessionFactory() as session:
                snapshot_result = await session.execute(
                    select(PassengerQrWhatsAppDeliveryModel)
                    .where(
                        PassengerQrWhatsAppDeliveryModel.id == delivery_id,
                        PassengerQrWhatsAppDeliveryModel.send_batch_id
                        == parsed_batch_id,
                        PassengerQrWhatsAppDeliveryModel.status == "processing",
                    )
                )
                delivery_snapshot = snapshot_result.scalar_one_or_none()
                if not delivery_snapshot:
                    continue
                queued_identity = (
                    delivery_snapshot.agency_id,
                    delivery_snapshot.group_id,
                    delivery_snapshot.passenger_id,
                    delivery_snapshot.qr_token_id,
                    delivery_snapshot.broadcast_group_id,
                    delivery_snapshot.recipient_id,
                    delivery_snapshot.normalized_phone_number,
                )

                validation = (
                    None
                    if _source_snapshot is not None
                    else await validate_private_delivery_recipient(
                        session,
                        agency_id=delivery_snapshot.agency_id,
                        group_id=delivery_snapshot.group_id,
                        passenger_id=delivery_snapshot.passenger_id,
                        broadcast_group_id=delivery_snapshot.broadcast_group_id,
                        recipient_id=delivery_snapshot.recipient_id,
                        normalized_phone_number=(
                            delivery_snapshot.normalized_phone_number
                        ),
                    )
                )
                recipient_allowed = (
                    _source_snapshot.allows(
                        agency_id=delivery_snapshot.agency_id,
                        group_id=delivery_snapshot.group_id,
                        passenger_id=delivery_snapshot.passenger_id,
                        broadcast_group_id=delivery_snapshot.broadcast_group_id,
                        recipient_id=delivery_snapshot.recipient_id,
                        normalized_phone_number=(
                            delivery_snapshot.normalized_phone_number
                        ),
                    )
                    if _source_snapshot is not None
                    else bool(validation and validation.allowed)
                )

                token_result = await session.execute(
                    select(PassengerQRTokenModel)
                    .where(
                        PassengerQRTokenModel.id == delivery_snapshot.qr_token_id,
                        PassengerQRTokenModel.agency_id
                        == delivery_snapshot.agency_id,
                        PassengerQRTokenModel.passenger_id
                        == delivery_snapshot.passenger_id,
                    )
                    .with_for_update()
                )
                current_token = token_result.scalar_one_or_none()
                latest_result = await session.execute(
                    select(PassengerQRTokenModel.id)
                    .where(
                        PassengerQRTokenModel.agency_id
                        == delivery_snapshot.agency_id,
                        PassengerQRTokenModel.passenger_id
                        == delivery_snapshot.passenger_id,
                    )
                    .order_by(
                        PassengerQRTokenModel.token_version.desc(),
                        PassengerQRTokenModel.created_at.desc(),
                    )
                    .limit(1)
                )
                latest_token_id = latest_result.scalar_one_or_none()
                locked_result = await session.execute(
                    select(PassengerQrWhatsAppDeliveryModel)
                    .where(
                        PassengerQrWhatsAppDeliveryModel.id == delivery_id,
                        PassengerQrWhatsAppDeliveryModel.send_batch_id
                        == parsed_batch_id,
                        PassengerQrWhatsAppDeliveryModel.status == "processing",
                    )
                    .with_for_update()
                )
                locked_delivery = locked_result.scalar_one_or_none()
                current_identity = (
                    (
                        locked_delivery.agency_id,
                        locked_delivery.group_id,
                        locked_delivery.passenger_id,
                        locked_delivery.qr_token_id,
                        locked_delivery.broadcast_group_id,
                        locked_delivery.recipient_id,
                        locked_delivery.normalized_phone_number,
                    )
                    if locked_delivery
                    else None
                )
                if not locked_delivery:
                    continue
                token_is_current = bool(
                    current_token
                    and latest_token_id == current_token.id
                    and qr_status(current_token) == "active"
                    and current_token.qr_payload
                )
                if (
                    not token_is_current
                    or not recipient_allowed
                    or current_identity != queued_identity
                ):
                    now = datetime.now(tz=UTC)
                    locked_delivery.status = "failed"
                    locked_delivery.status_updated_at = now
                    locked_delivery.updated_at = now
                    locked_delivery.provider_media_id = media_id
                    locked_delivery.error_message = (
                        (validation.reason or PRIVATE_DELIVERY_RECIPIENT_CHANGED)
                        if validation is not None and not validation.allowed
                        else PRIVATE_DELIVERY_RECIPIENT_CHANGED
                        if not recipient_allowed
                        else (
                            "This QR code changed after queueing; preview the "
                            "current QR before sending"
                        )
                    )
                    await session.commit()
                    continue

                saved_parameters = locked_delivery.template_parameter_values
                parameters = (
                    qr_template_parameters(message_content=saved_parameters[0])
                    if (
                        isinstance(saved_parameters, list)
                        and len(saved_parameters) == 1
                        and isinstance(saved_parameters[0], str)
                    )
                    else qr_template_parameters(
                        message_content=QR_DEFAULT_MESSAGE_CONTENT
                    )
                )
                for attempt in range(MAX_PROVIDER_ATTEMPTS):
                    try:
                        provider_id = await send_whatsapp_qr_template(
                            client=client,
                            settings=settings,
                            to_number=locked_delivery.normalized_phone_number,
                            template_name=locked_delivery.template_name,
                            media_id=media_id,
                            parameters=parameters,
                        )
                    except WhatsAppCloudApiError as exc:
                        if exc.delivery_unknown:
                            locked_delivery.status = "delivery_unknown"
                            locked_delivery.error_message = exc.persistence_message
                            break
                        if exc.transient and attempt + 1 < MAX_PROVIDER_ATTEMPTS:
                            await asyncio.sleep(2**attempt)
                            continue
                        locked_delivery.status = "failed"
                        locked_delivery.error_message = exc.persistence_message
                        break
                    except Exception:  # noqa: BLE001 - provider outcome is ambiguous.
                        logger.warning(
                            "qr_whatsapp_provider_outcome_unknown delivery_id=%s",
                            delivery_id,
                        )
                        locked_delivery.status = "delivery_unknown"
                        locked_delivery.error_message = (
                            "WhatsApp delivery outcome is unknown; automatic resend "
                            "is suppressed"
                        )
                        break
                    else:
                        locked_delivery.status = "submitted"
                        locked_delivery.error_message = None
                        locked_delivery.provider_message_id = provider_id
                        break
                now = datetime.now(tz=UTC)
                locked_delivery.provider_media_id = media_id
                locked_delivery.status_updated_at = now
                locked_delivery.updated_at = now
                await session.commit()


async def mark_qr_batch_failed(*, send_batch_id: str, error_message: str) -> None:
    parsed_batch_id = uuid.UUID(send_batch_id)
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(PassengerQrWhatsAppDeliveryModel).where(
                PassengerQrWhatsAppDeliveryModel.send_batch_id == parsed_batch_id,
                PassengerQrWhatsAppDeliveryModel.status.in_(["queued", "processing"]),
            )
        )
        now = datetime.now(tz=UTC)
        for delivery in result.scalars().all():
            delivery.status = "delivery_unknown" if delivery.status == "processing" else "failed"
            delivery.status_updated_at = now
            delivery.updated_at = now
            delivery.error_message = error_message[:2000]
        await session.commit()
