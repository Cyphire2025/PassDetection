"""Individual WhatsApp delivery for passenger attendance QR codes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientForComparison,
    SubmissionForComparison,
    compare_group_submissions,
)
from app.application.use_cases.whatsapp.qr_templates import (
    QR_DEFAULT_MESSAGE_CONTENT,
    render_qr_message,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassengerQRTokenModel,
    PassengerQrWhatsAppDeliveryModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.qr.approved_passenger_qr_issuer import qr_status
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    QrDeliveryPreviewRecipient,
    QrDeliveryPreviewResponse,
    QrDeliveryPreviewSummary,
    SendQrBroadcastRequest,
    SendQrBroadcastResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()

QR_DELIVERY_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]
ACCEPTED_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})
IN_PROGRESS_STATUSES = frozenset({"queued", "processing", "delivery_unknown"})


def _agency_id(current_user: User) -> uuid.UUID:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not assigned to an agency",
        )
    return current_user.agency_id


async def _manageable_group(
    session: AsyncSession,
    *,
    current_user: User,
    group_id: uuid.UUID,
) -> ClientGroupModel:
    agency_id = _agency_id(current_user)
    result = await session.execute(
        select(ClientGroupModel).where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.status != "deleted",
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_assign_coordinator(
            current_user,
            group,
        )
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    return group


def _passport_number(submission: PassportSubmissionModel) -> str | None:
    fields = submission.confirmed_fields or submission.extracted_fields or {}
    value = fields.get("passport_number")
    return str(value).strip() if value else None


async def _linked_recipients(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
) -> tuple[dict[uuid.UUID, str], list[WhatsAppBroadcastRecipientModel]]:
    linked_result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            WhatsAppBroadcastGroupModel.name,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
            WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
            WhatsAppBroadcastGroupModel.recipient_opt_in_confirmed_at.is_not(None),
        )
    )
    linked = {broadcast_id: broadcast_name for broadcast_id, broadcast_name in linked_result.all()}
    if not linked:
        return {}, []
    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(list(linked)),
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
    )
    return linked, list(recipient_result.scalars().all())


def _matched_recipients(
    *,
    submissions: list[PassportSubmissionModel],
    recipients: list[WhatsAppBroadcastRecipientModel],
    linked_broadcasts: dict[uuid.UUID, str],
) -> dict[uuid.UUID, tuple[WhatsAppBroadcastRecipientModel, str]]:
    comparison_recipients = [
        RecipientForComparison(
            id=recipient.id,
            broadcast_id=recipient.broadcast_group_id,
            broadcast_name=linked_broadcasts[recipient.broadcast_group_id],
            name=recipient.name,
            phone=recipient.normalized_phone_number,
            updated_at=recipient.created_at,
            imported_fields=dict(recipient.imported_fields or {}),
        )
        for recipient in recipients
    ]
    comparison_submissions = [
        SubmissionForComparison(
            id=submission.id,
            name=submission.client_name,
            client_phone=submission.client_phone,
            family_head_phone=submission.family_head_phone,
            updated_at=submission.updated_at,
            client_email=submission.client_email,
            family_head_email=submission.family_head_email,
            confirmed_fields=dict(submission.confirmed_fields or {}),
            extracted_fields=dict(submission.extracted_fields or {}),
            staff_metadata=dict(submission.staff_metadata or {}),
        )
        for submission in submissions
    ]
    rows, _ = compare_group_submissions(
        comparison_recipients,
        comparison_submissions,
    )
    recipients_by_id = {recipient.id: recipient for recipient in recipients}
    matched: dict[
        uuid.UUID,
        tuple[WhatsAppBroadcastRecipientModel, str],
    ] = {}
    for row in rows:
        if row.status not in {"submitted", "multiple_submissions"}:
            continue
        candidates = sorted(
            (
                recipients_by_id[recipient_id]
                for recipient_id in row.recipient_ids
                if recipient_id in recipients_by_id
            ),
            key=lambda recipient: (
                linked_broadcasts.get(
                    recipient.broadcast_group_id,
                    "",
                ).casefold(),
                str(recipient.id),
            ),
        )
        if not candidates:
            continue
        selected = candidates[0]
        for submission_id in row.submission_ids:
            matched[submission_id] = (
                selected,
                linked_broadcasts[selected.broadcast_group_id],
            )
    return matched


async def _build_preview(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
) -> QrDeliveryPreviewResponse:
    passengers_result = await session.execute(
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    passengers = list(passengers_result.scalars().all())
    passenger_ids = [passenger.id for passenger in passengers]

    latest_token_by_passenger: dict[uuid.UUID, PassengerQRTokenModel] = {}
    if passenger_ids:
        token_result = await session.execute(
            select(PassengerQRTokenModel)
            .where(PassengerQRTokenModel.passenger_id.in_(passenger_ids))
            .order_by(
                PassengerQRTokenModel.passenger_id,
                PassengerQRTokenModel.token_version.desc(),
                PassengerQRTokenModel.created_at.desc(),
            )
        )
        for token in token_result.scalars().all():
            latest_token_by_passenger.setdefault(token.passenger_id, token)

    token_ids = [token.id for token in latest_token_by_passenger.values()]
    delivery_by_token: dict[uuid.UUID, PassengerQrWhatsAppDeliveryModel] = {}
    if token_ids:
        delivery_result = await session.execute(
            select(PassengerQrWhatsAppDeliveryModel).where(
                PassengerQrWhatsAppDeliveryModel.qr_token_id.in_(token_ids)
            )
        )
        delivery_by_token = {
            delivery.qr_token_id: delivery for delivery in delivery_result.scalars().all()
        }

    linked_broadcasts, recipient_models = await _linked_recipients(
        session,
        group=group,
    )
    recipient_by_submission = _matched_recipients(
        submissions=passengers,
        recipients=recipient_models,
        linked_broadcasts=linked_broadcasts,
    )

    rows: list[QrDeliveryPreviewRecipient] = []
    summary = QrDeliveryPreviewSummary(total_passengers=len(passengers))
    for passenger in passengers:
        token = latest_token_by_passenger.get(passenger.id)
        token_status = qr_status(token)
        matched_recipient = recipient_by_submission.get(passenger.id)
        existing_delivery = delivery_by_token.get(token.id) if token else None
        delivery_status = "blocked"
        eligible = False
        reason = "Generate an active QR code for this passenger first."

        if token and token_status != "active":
            reason = (
                "Only an active QR code can be sent. Activate or regenerate this "
                "passenger's QR first."
            )
        elif token and not token.qr_payload:
            reason = "The active QR image cannot be reconstructed; regenerate it first."
        elif token and not matched_recipient:
            reason = (
                "No confirmed WhatsApp recipient could be matched to this passenger "
                "from the linked broadcasts."
            )
        elif token and matched_recipient:
            if existing_delivery and existing_delivery.status in ACCEPTED_STATUSES:
                delivery_status = "already_sent"
                reason = "This QR version was already accepted by WhatsApp."
                summary.already_sent += 1
            elif existing_delivery and existing_delivery.status in IN_PROGRESS_STATUSES:
                delivery_status = existing_delivery.status
                reason = (
                    "Delivery is already in progress."
                    if existing_delivery.status != "delivery_unknown"
                    else (
                        "The previous delivery outcome is uncertain; automatic "
                        "resend is suppressed."
                    )
                )
                summary.in_progress += 1
            elif existing_delivery and existing_delivery.status == "failed":
                delivery_status = "retryable"
                reason = "The previous attempt failed and can be retried safely."
                eligible = True
                summary.retryable += 1
            else:
                delivery_status = "ready"
                reason = "Ready to send this passenger's individual QR."
                eligible = True
                summary.ready += 1
        if not eligible and delivery_status == "blocked":
            summary.blocked += 1

        recipient = matched_recipient[0] if matched_recipient else None
        rows.append(
            QrDeliveryPreviewRecipient(
                passenger_id=passenger.id,
                passenger_name=passenger.client_name,
                passport_number=_passport_number(passenger),
                qr_token_id=token.id if token else None,
                qr_token_version=token.token_version if token else None,
                qr_status=token_status,
                recipient_id=recipient.id if recipient else None,
                broadcast_group_id=(recipient.broadcast_group_id if recipient else None),
                broadcast_name=matched_recipient[1] if matched_recipient else None,
                phone_number=recipient.normalized_phone_number if recipient else None,
                delivery_id=existing_delivery.id if existing_delivery else None,
                delivery_status=delivery_status,
                eligible=eligible,
                reason=reason,
                error_message=(
                    existing_delivery.error_message
                    if existing_delivery and existing_delivery.status == "failed"
                    else None
                ),
                message_preview=(
                    render_qr_message(
                        message_content=QR_DEFAULT_MESSAGE_CONTENT,
                    )
                    if token and matched_recipient
                    else None
                ),
            )
        )

    settings = get_settings()
    template_name = settings.whatsapp_qr_template_name.strip()
    provider_configured = bool(
        template_name and settings.whatsapp_access_token and settings.whatsapp_phone_number_id
    )
    configuration_error: str | None = None
    if not linked_broadcasts:
        configuration_error = "Link at least one opted-in WhatsApp broadcast to this group first."
    elif not provider_configured:
        configuration_error = (
            "The WhatsApp QR template or Cloud API credentials are not configured."
        )
    elif summary.ready + summary.retryable == 0:
        configuration_error = "There are no new or safely retryable QR codes to send."

    return QrDeliveryPreviewResponse(
        group_id=group.id,
        template_name=template_name or None,
        template_configured=provider_configured,
        linked_broadcast_count=len(linked_broadcasts),
        can_send=configuration_error is None,
        configuration_error=configuration_error,
        message_content=QR_DEFAULT_MESSAGE_CONTENT,
        summary=summary,
        recipients=rows,
    )


@router.get(
    "/groups/{group_id}/qr-codes/whatsapp-preview",
    response_model=QrDeliveryPreviewResponse,
)
async def preview_qr_whatsapp_broadcast(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(QR_DELIVERY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> QrDeliveryPreviewResponse:
    group = await _manageable_group(
        session,
        current_user=current_user,
        group_id=group_id,
    )
    return await _build_preview(session, group=group)


@router.post(
    "/groups/{group_id}/qr-codes/whatsapp-send",
    response_model=SendQrBroadcastResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_qr_whatsapp_broadcast(
    group_id: uuid.UUID,
    payload: SendQrBroadcastRequest,
    current_user: User = Depends(require_role(QR_DELIVERY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> SendQrBroadcastResponse:
    message_content = payload.message_content.strip()
    if not message_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The editable QR message section is required",
        )
    group = await _manageable_group(
        session,
        current_user=current_user,
        group_id=group_id,
    )
    await session.execute(
        select(ClientGroupModel.id).where(ClientGroupModel.id == group.id).with_for_update()
    )
    preview = await _build_preview(session, group=group)
    if not preview.can_send:
        error_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if not preview.template_configured
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=error_status,
            detail=preview.configuration_error or "QR codes are not ready to send",
        )

    requested_ids = (
        set(payload.qr_token_ids)
        if payload.qr_token_ids is not None
        else {row.qr_token_id for row in preview.recipients if row.qr_token_id and row.eligible}
    )
    eligible_rows = [
        row for row in preview.recipients if row.qr_token_id in requested_ids and row.eligible
    ]
    if not eligible_rows:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Select at least one new or safely retryable QR code",
        )

    send_batch_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    template_name = preview.template_name or ""
    queued_count = 0
    for row in eligible_rows:
        if not (
            row.qr_token_id and row.recipient_id and row.broadcast_group_id and row.phone_number
        ):
            continue
        delivery: PassengerQrWhatsAppDeliveryModel | None = None
        if row.delivery_id:
            delivery_result = await session.execute(
                select(PassengerQrWhatsAppDeliveryModel)
                .where(PassengerQrWhatsAppDeliveryModel.id == row.delivery_id)
                .with_for_update()
            )
            delivery = delivery_result.scalar_one_or_none()
        if delivery:
            if delivery.status != "failed":
                continue
            delivery.send_batch_id = send_batch_id
            delivery.broadcast_group_id = row.broadcast_group_id
            delivery.recipient_id = row.recipient_id
            delivery.phone_number = row.phone_number
            delivery.normalized_phone_number = row.phone_number
            delivery.template_name = template_name
            delivery.template_parameter_values = [message_content]
            delivery.status = "queued"
            delivery.status_updated_at = now
            delivery.provider_status_at = None
            delivery.provider_message_id = None
            delivery.provider_media_id = None
            delivery.error_message = None
            delivery.updated_at = now
        else:
            delivery = PassengerQrWhatsAppDeliveryModel(
                id=uuid.uuid4(),
                agency_id=group.agency_id,
                group_id=group.id,
                passenger_id=row.passenger_id,
                qr_token_id=row.qr_token_id,
                broadcast_group_id=row.broadcast_group_id,
                recipient_id=row.recipient_id,
                send_batch_id=send_batch_id,
                passenger_name=row.passenger_name,
                passport_number=row.passport_number,
                phone_number=row.phone_number,
                normalized_phone_number=row.phone_number,
                template_name=template_name,
                template_parameter_values=[message_content],
                status="queued",
                attempt_count=0,
                status_updated_at=now,
                created_by_user_id=current_user.id,
                created_at=now,
                updated_at=now,
            )
            session.add(delivery)
        queued_count += 1

    if not queued_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected QR codes were already claimed by another send",
        )
    await AuditLogRepository(session).record(
        action="qr_whatsapp_broadcast_queued",
        entity_type="client_group",
        entity_id=str(group.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "send_batch_id": str(send_batch_id),
            "queued_count": queued_count,
            "message_content_length": len(message_content),
        },
    )
    await session.commit()

    from app.infrastructure.whatsapp.tasks import process_qr_whatsapp_broadcast

    try:
        process_qr_whatsapp_broadcast.apply_async(
            kwargs={"send_batch_id": str(send_batch_id)},
            queue="whatsapp",
        )
    except Exception as exc:
        failed_result = await session.execute(
            select(PassengerQrWhatsAppDeliveryModel).where(
                PassengerQrWhatsAppDeliveryModel.send_batch_id == send_batch_id,
                PassengerQrWhatsAppDeliveryModel.status == "queued",
            )
        )
        failure_time = datetime.now(tz=UTC)
        for delivery in failed_result.scalars().all():
            delivery.status = "failed"
            delivery.status_updated_at = failure_time
            delivery.updated_at = failure_time
            delivery.error_message = "The WhatsApp worker queue is temporarily unavailable"
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The WhatsApp worker queue is temporarily unavailable",
        ) from exc

    attempted_count = (
        len(requested_ids) if payload.qr_token_ids is not None else len(preview.recipients)
    )
    return SendQrBroadcastResponse(
        send_batch_id=send_batch_id,
        queued_count=queued_count,
        skipped_count=max(0, attempted_count - queued_count),
        message=(
            f"Queued {queued_count} QR code{'' if queued_count == 1 else 's'} "
            "for individual WhatsApp delivery."
        ),
    )
