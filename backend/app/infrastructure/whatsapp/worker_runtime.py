"""Worker-side WhatsApp broadcast execution."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import (
    WhatsAppMessageType,
    format_support_contacts,
    template_header_parameters,
    template_parameters,
    validate_template_parameters,
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
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_resolution_id_for_recipient,
)
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_template,
)

MAX_PROVIDER_ATTEMPTS = 3
ACCEPTED_DELIVERY_STATUSES = frozenset(
    {"submitted", "sent", "delivered", "read"}
)


def _resolve_log_template_snapshot(
    *,
    log: WhatsAppMessageLogModel,
    message_type: WhatsAppMessageType,
    fallback_header_parameters: list[str],
    fallback_parameters: list[str],
) -> tuple[list[str], list[str]]:
    saved_header = getattr(log, "header_parameter_values", None)
    saved_body = getattr(log, "template_parameter_values", None)
    if saved_header is None and saved_body is None:
        if getattr(log, "is_explicit_resend", False):
            raise ValueError("Explicit resend is missing its frozen template parameters")
        return fallback_header_parameters, fallback_parameters
    if not isinstance(saved_header, list) or not isinstance(saved_body, list):
        raise ValueError("Saved WhatsApp template parameters are incomplete")
    if any(not isinstance(value, str) for value in [*saved_header, *saved_body]):
        raise ValueError("Saved WhatsApp template parameters are invalid")
    header_parameters = list(saved_header)
    parameters = list(saved_body)
    validate_template_parameters(
        message_type=message_type,
        header_parameters=header_parameters,
        body_parameters=parameters,
    )
    return header_parameters, parameters


async def _set_message_state(
    session: AsyncSession,
    *,
    log: WhatsAppMessageLogModel,
    expected_batch_id: uuid.UUID,
    state_status: str,
    release_claim: bool = False,
    submitted: bool = False,
) -> None:
    if getattr(log, "is_explicit_resend", False):
        return
    now = datetime.now(tz=UTC)
    values: dict[str, object] = {
        "status": state_status,
        "status_updated_at": now,
        "updated_at": now,
    }
    if release_claim:
        values["batch_id"] = None
    if submitted:
        values["submitted_at"] = now
        values["batch_id"] = expected_batch_id
    predicates = [
        WhatsAppRecipientMessageStateModel.recipient_id == log.recipient_id,
        WhatsAppRecipientMessageStateModel.message_type == log.message_type,
    ]
    if submitted:
        # Provider acceptance is authoritative even if removal or stale-claim
        # recovery changed the ledger while the HTTP request was in flight.
        # Never regress a more advanced accepted state.
        predicates.append(
            ~WhatsAppRecipientMessageStateModel.status.in_(
                ACCEPTED_DELIVERY_STATUSES
            )
        )
    else:
        predicates.append(
            WhatsAppRecipientMessageStateModel.batch_id == expected_batch_id
        )
        if release_claim or state_status == "delivery_unknown":
            predicates.append(
                ~WhatsAppRecipientMessageStateModel.status.in_(
                    ACCEPTED_DELIVERY_STATUSES
                )
            )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(*predicates)
        .values(**values)
        .execution_options(synchronize_session=False)
    )


async def _load_sendable_recipient(
    session: AsyncSession,
    *,
    log: WhatsAppMessageLogModel,
    expected_batch_id: uuid.UUID,
) -> tuple[WhatsAppBroadcastRecipientModel | None, str | None]:
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == log.broadcast_group_id
        )
        .with_for_update()
    )
    if not group_result.scalar_one_or_none():
        return None, "WhatsApp broadcast group no longer exists"

    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(WhatsAppBroadcastRecipientModel.id == log.recipient_id)
        .execution_options(populate_existing=True)
    )
    recipient = recipient_result.scalar_one_or_none()
    if not recipient:
        return None, "WhatsApp recipient no longer exists"
    if recipient.removed_at is not None:
        return None, "WhatsApp recipient was removed"
    if await active_replacement_resolution_id_for_recipient(
        session,
        recipient=recipient,
    ):
        return None, "WhatsApp recipient was replaced in a linked passport group"

    if getattr(log, "is_explicit_resend", False):
        resend_claim_result = await session.execute(
            select(WhatsAppMessageLogModel.id).where(
                WhatsAppMessageLogModel.id == log.id,
                WhatsAppMessageLogModel.batch_id == expected_batch_id,
                WhatsAppMessageLogModel.status == "processing",
                WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            )
        )
        if not resend_claim_result.scalar_one_or_none():
            return None, "Explicit resend claim was superseded before provider submission"
        return recipient, None

    state_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel).where(
            WhatsAppRecipientMessageStateModel.recipient_id == log.recipient_id,
            WhatsAppRecipientMessageStateModel.message_type == log.message_type,
        )
    )
    delivery_state = state_result.scalar_one_or_none()
    if (
        not delivery_state
        or delivery_state.batch_id != expected_batch_id
        or delivery_state.status != "processing"
    ):
        return None, "Delivery claim was superseded before provider submission"
    return recipient, None


async def run_whatsapp_broadcast(
    *,
    batch_id: str,
    message_type: WhatsAppMessageType,
    message_content: str,
    passport_link: str | None,
    header_image_id: str | None = None,
    passport_intro: str | None = None,
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

        async with httpx.AsyncClient(timeout=timeout) as client:
            for log in logs:
                claim_time = datetime.now(tz=UTC)
                claim_result = await session.execute(
                    update(WhatsAppMessageLogModel)
                    .where(
                        WhatsAppMessageLogModel.id == log.id,
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
                    current_log_result = await session.execute(
                        select(WhatsAppMessageLogModel).where(
                            WhatsAppMessageLogModel.id == log.id
                        )
                    )
                    current_log = current_log_result.scalar_one_or_none()
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
                if not getattr(log, "is_explicit_resend", False):
                    state_claim_result = await session.execute(
                        update(WhatsAppRecipientMessageStateModel)
                        .where(
                            WhatsAppRecipientMessageStateModel.recipient_id
                            == log.recipient_id,
                            WhatsAppRecipientMessageStateModel.message_type
                            == log.message_type,
                            WhatsAppRecipientMessageStateModel.batch_id
                            == parsed_batch_id,
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
                await session.commit()
                recipient, claim_error = await _load_sendable_recipient(
                    session,
                    log=log,
                    expected_batch_id=parsed_batch_id,
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
                    group_name=group.name,
                    support_contacts=support_block,
                    message_content=message_content,
                    passport_link=passport_link,
                    passport_intro=passport_intro,
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
                for attempt in range(MAX_PROVIDER_ATTEMPTS):
                    recipient, claim_error = await _load_sendable_recipient(
                        session,
                        log=log,
                        expected_batch_id=parsed_batch_id,
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
                        break
                    try:
                        provider_id = await send_whatsapp_template(
                            client=client,
                            settings=settings,
                            to_number=recipient.normalized_phone_number,
                            template_name=log.template_name or "",
                            message_type=message_type,
                            parameters=parameters,
                            header_parameters=header_parameters,
                        )
                    except WhatsAppCloudApiError as exc:
                        safe_error = exc.persistence_message[:2000]
                        if exc.delivery_unknown:
                            log.status = "delivery_unknown"
                            log.status_updated_at = datetime.now(tz=UTC)
                            log.error_message = safe_error
                            await _set_message_state(
                                session,
                                log=log,
                                expected_batch_id=parsed_batch_id,
                                state_status="delivery_unknown",
                            )
                            await session.commit()
                            break
                        if exc.transient and attempt + 1 < MAX_PROVIDER_ATTEMPTS:
                            log.status = "processing"
                            log.status_updated_at = datetime.now(tz=UTC)
                            log.error_message = (
                                f"{exc.code}: Temporary provider error; retrying"
                            )[:2000]
                            await session.commit()
                            await asyncio.sleep(2**attempt)
                            continue
                        log.status = "failed"
                        log.status_updated_at = datetime.now(tz=UTC)
                        log.error_message = safe_error
                        await _set_message_state(
                            session,
                            log=log,
                            expected_batch_id=parsed_batch_id,
                            state_status="failed",
                            release_claim=True,
                        )
                        await session.commit()
                        break
                    except Exception as exc:  # noqa: BLE001 - outcome may be ambiguous.
                        log.status = "delivery_unknown"
                        log.status_updated_at = datetime.now(tz=UTC)
                        log.error_message = (
                            f"WhatsApp delivery outcome is unknown: {exc}"
                        )[:2000]
                        await _set_message_state(
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
                        await _set_message_state(
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
                            reconciliation_log.status = "submitted"
                            reconciliation_log.status_updated_at = datetime.now(tz=UTC)
                            reconciliation_log.provider_message_id = provider_id
                            reconciliation_log.error_message = None
                            await _set_message_state(
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
            was_processing = log.status == "processing"
            log.status = "delivery_unknown" if was_processing else "failed"
            log.status_updated_at = datetime.now(tz=UTC)
            log.error_message = (
                (
                    f"{error_message}; delivery outcome is unknown and "
                    "automatic resend is suppressed"
                )
                if was_processing
                else error_message
            )[:2000]
            await _set_message_state(
                session,
                log=log,
                expected_batch_id=uuid.UUID(batch_id),
                state_status="delivery_unknown" if was_processing else "failed",
                release_claim=not was_processing,
            )
        await session.commit()
