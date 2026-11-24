"""Worker-side execution and receipt handling for attendance QR deliveries."""

from __future__ import annotations

import logging
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime

import httpx
from sqlalchemy import Select, select, update

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
    send_whatsapp_qr_template,
    upload_whatsapp_image,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryGroupSourceSnapshot,
    lock_private_delivery_group_source_snapshot,
    validate_private_delivery_recipient,
    validate_private_delivery_welcome,
)
from app.infrastructure.whatsapp.qr_delivery_dispatch import dispatch_qr_delivery
from app.infrastructure.whatsapp.qr_delivery_media import prepare_qr_delivery_media
from app.infrastructure.whatsapp.qr_delivery_state import (
    ACCEPTED_STATUS_RANK as ACCEPTED_STATUS_RANK,
)
from app.infrastructure.whatsapp.qr_delivery_state import (
    ACCEPTED_STATUSES as ACCEPTED_STATUSES,
)
from app.infrastructure.whatsapp.qr_delivery_state import (
    _mark_delivery as _persist_delivery,
)
from app.infrastructure.whatsapp.qr_delivery_state import (
    apply_qr_provider_status as apply_qr_provider_status,
)
from app.infrastructure.whatsapp.qr_delivery_state import (
    mark_qr_batch_failed as _persist_batch_failure,
)
from app.infrastructure.whatsapp.qr_delivery_types import QrDispatchCallbacks, QrMediaCallbacks
from app.infrastructure.whatsapp.receipt_bindings import commit_private_provider_outcome

MAX_PROVIDER_ATTEMPTS = 3
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
            PassengerQRTokenModel.id == PassengerQrWhatsAppDeliveryModel.qr_token_id,
        )
        .where(
            PassengerQrWhatsAppDeliveryModel.id == delivery_id,
            PassengerQrWhatsAppDeliveryModel.send_batch_id == send_batch_id,
            PassengerQrWhatsAppDeliveryModel.status == "processing",
            PassengerQRTokenModel.agency_id == PassengerQrWhatsAppDeliveryModel.agency_id,
            PassengerQRTokenModel.passenger_id == PassengerQrWhatsAppDeliveryModel.passenger_id,
        )
    )


async def _mark_delivery(
    delivery_id: uuid.UUID,
    *,
    status: str,
    error_message: str | None,
    provider_message_id: str | None = None,
    provider_media_id: str | None = None,
) -> None:
    await _persist_delivery(
        delivery_id,
        session_factory=AsyncSessionFactory,
        status=status,
        error_message=error_message,
        provider_message_id=provider_message_id,
        provider_media_id=provider_media_id,
    )


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
                .where(PassengerQrWhatsAppDeliveryModel.send_batch_id == parsed_batch_id)
                .order_by(PassengerQrWhatsAppDeliveryModel.created_at.asc())
            )
            batch_rows = list(rows_result.all())
            if not batch_rows:
                return
            source_pairs = {(row.agency_id, row.group_id) for row in batch_rows}
            if len(source_pairs) != 1:
                raise RuntimeError("A private delivery batch must belong to exactly one group")
            agency_id, group_id = next(iter(source_pairs))
            source_snapshot = await lock_private_delivery_group_source_snapshot(
                session,
                agency_id=agency_id,
                group_id=group_id,
            )
            if source_snapshot is None:
                raise RuntimeError("The private delivery source is no longer available")
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
        nullcontext(_client) if _client is not None else httpx.AsyncClient(timeout=timeout)
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

            media_id = await prepare_qr_delivery_media(
                delivery_id=delivery_id,
                parsed_batch_id=parsed_batch_id,
                client=client,
                settings=settings,
                max_attempts=MAX_PROVIDER_ATTEMPTS,
                callbacks=QrMediaCallbacks(
                    session_factory=AsyncSessionFactory,
                    source_statement=_qr_media_source_statement,
                    mark_delivery=_mark_delivery,
                    qr_status=qr_status,
                    render=render_attendance_qr_png,
                    upload=upload_whatsapp_image,
                ),
            )
            if not media_id:
                continue
            await dispatch_qr_delivery(
                delivery_id=delivery_id,
                parsed_batch_id=parsed_batch_id,
                client=client,
                settings=settings,
                media_id=media_id,
                source_snapshot=_source_snapshot,
                max_attempts=MAX_PROVIDER_ATTEMPTS,
                callbacks=QrDispatchCallbacks(
                    session_factory=AsyncSessionFactory,
                    validate_recipient=validate_private_delivery_recipient,
                    validate_welcome=validate_private_delivery_welcome,
                    qr_status=qr_status,
                    send_template=send_whatsapp_qr_template,
                    commit_outcome=commit_private_provider_outcome,
                ),
            )


async def mark_qr_batch_failed(*, send_batch_id: str, error_message: str) -> None:
    await _persist_batch_failure(
        send_batch_id=send_batch_id,
        error_message=error_message,
        session_factory=AsyncSessionFactory,
    )
