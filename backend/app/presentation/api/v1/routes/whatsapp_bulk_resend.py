"""Queue one tracked, idempotent resend batch for an explicit roster selection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    AuditLogModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_phone_numbers_for_broadcast,
)
from app.infrastructure.whatsapp.publication import (
    fail_unclaimed_broadcast_rows,
    publish_whatsapp_task,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    SKIP_MESSAGES,
    build_response,
    expire_stale_explicit_claims,
    frozen_resend_log,
    recipient_skip_reason,
    refresh_batch_response,
    selection_delivery_maps,
    selection_fingerprint,
)
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES, _agency_filter, logger
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendRequest,
    WhatsAppBulkResendResponse,
    WhatsAppSendResult,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()
AUDIT_ACTION = "whatsapp_selected_messages_resend_requested"


@router.post(
    "/groups/{group_id}/recipients/resend",
    response_model=WhatsAppBulkResendResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def resend_selected_recipient_messages(
    group_id: uuid.UUID,
    body: WhatsAppBulkResendRequest,
    request: Request,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBulkResendResponse:
    group = (
        await session.execute(
            select(WhatsAppBroadcastGroupModel)
            .where(WhatsAppBroadcastGroupModel.id == group_id, *_agency_filter(current_user))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="WhatsApp broadcast group not found")
    if group.recipient_opt_in_confirmed_at is None:
        raise HTTPException(
            status_code=400, detail="Recipient WhatsApp opt-in has not been confirmed for this list"
        )

    # The existing group lock serializes single sends, bulk sends and roster mutations.
    # Persist the request receipt in the same transaction as all delivery claims, so
    # retrying after a lost HTTP response cannot produce another provider submission.
    request_scope = uuid.uuid5(group.id, f"selected-resend:{body.request_id}")
    fingerprint = selection_fingerprint(body)
    previous = (
        await session.execute(
            select(AuditLogModel).where(
                AuditLogModel.agency_id == group.agency_id,
                AuditLogModel.action == AUDIT_ACTION,
                AuditLogModel.entity_type == "whatsapp_bulk_resend_request",
                AuditLogModel.entity_id == str(request_scope),
            )
        )
    ).scalar_one_or_none()
    if previous is not None:
        receipt = previous.metadata_json or {}
        if receipt.get("selection_fingerprint") != fingerprint:
            raise HTTPException(
                status_code=409,
                detail="This resend request ID was already used for a different selection or message",
            )
        response = WhatsAppBulkResendResponse.model_validate(receipt["response"])
        # Receipt metadata deliberately stores no phone numbers or private message content.
        recipients = list(
            (
                await session.execute(
                    select(WhatsAppBroadcastRecipientModel).where(
                        WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
                        WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                        WhatsAppBroadcastRecipientModel.id.in_(body.recipient_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        phones = {recipient.id: recipient.normalized_phone_number for recipient in recipients}
        response.results = [
            item.model_copy(update={"phone_number": phones.get(item.recipient_id, "")})
            for item in response.results
        ]
        response = await refresh_batch_response(session, response, replayed=True)
        await session.commit()
        return response

    recipients = list(
        (
            await session.execute(
                select(WhatsAppBroadcastRecipientModel)
                .where(
                    WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
                    WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                    WhatsAppBroadcastRecipientModel.id.in_(body.recipient_ids),
                    WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                )
                .order_by(WhatsAppBroadcastRecipientModel.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if {recipient.id for recipient in recipients} != set(body.recipient_ids):
        # Validate the entire selection before creating any claim or revealing other lists.
        raise HTTPException(
            status_code=404,
            detail="One or more selected recipients are unavailable in this WhatsApp broadcast",
        )

    await expire_stale_explicit_claims(session, group_id=group.id, body=body)
    states, active_statuses, sources = await selection_delivery_maps(
        session, group_id=group.id, body=body
    )
    replaced_phones = await active_replacement_phone_numbers_for_broadcast(
        session, broadcast_group_id=group.id, agency_id=group.agency_id
    )
    batch_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    logs: list[WhatsAppMessageLogModel] = []
    results: list[WhatsAppSendResult] = []
    by_id = {recipient.id: recipient for recipient in recipients}
    for recipient_id in body.recipient_ids:
        recipient = by_id[recipient_id]
        state = states.get(recipient.id)
        reason = recipient_skip_reason(
            recipient=recipient,
            state=state,
            active_statuses=active_statuses.get(recipient.id, set()),
            replaced_phones=replaced_phones,
        )
        source = sources.get(recipient.id)
        if reason is None:
            if source is None or state is None:
                reason = "skipped_no_saved_message"
            else:
                try:
                    log = frozen_resend_log(
                        recipient=recipient, source=source, state=state, batch_id=batch_id, now=now
                    )
                except (ValueError, IndexError):
                    reason = "skipped_no_saved_message"
                else:
                    logs.append(log)
                    session.add(log)
                    if state.status == "failed":
                        state.status = "queued"
                        state.batch_id = batch_id
                        state.submitted_at = None
                        state.provider_status_at = None
                        state.status_updated_at = now
                        state.updated_at = now
        results.append(
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status=reason or "queued",
                error_message=SKIP_MESSAGES.get(reason) if reason else None,
            )
        )

    if logs:
        settings = get_settings()
        if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
            await session.rollback()
            raise HTTPException(
                status_code=503, detail="WhatsApp Cloud API credentials are incomplete"
            )
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A resend is already active for part of this selection; refresh the list",
        ) from exc

    response = build_response(batch_id=batch_id if logs else None, results=results)
    receipt_response = response.model_dump(mode="json")
    for item in receipt_response["results"]:
        item["phone_number"] = ""
    await AuditLogRepository(session).record(
        action=AUDIT_ACTION,
        entity_type="whatsapp_bulk_resend_request",
        entity_id=str(request_scope),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=trusted_client_ip(request),
        metadata={
            "broadcast_group_id": str(group.id),
            "message_type": body.message_type,
            "selection_fingerprint": fingerprint,
            "response": receipt_response,
        },
    )
    await session.commit()
    if not logs:
        return response

    from app.infrastructure.whatsapp.tasks import process_whatsapp_broadcast

    # The existing worker uses each row's frozen parameters. These required task
    # arguments only support older rows; none can replace a selected row's snapshot.
    first = logs[0]
    parameters = first.template_parameter_values or []
    header = first.header_parameter_values or []
    try:
        await publish_whatsapp_task(
            process_whatsapp_broadcast,
            payload={
                "batch_id": str(batch_id),
                "message_type": body.message_type,
                "message_content": parameters[0]
                if body.message_type == "welcome"
                else parameters[2],
                "passport_intro": parameters[0] if body.message_type == "passport_link" else None,
                "passport_link": parameters[1] if body.message_type == "passport_link" else None,
                "header_image_id": header[0] if header else None,
            },
        )
    except Exception as exc:  # noqa: BLE001 - Persist conservative publication compensation.
        logger.error(
            "whatsapp_selected_resend_queue_unavailable",
            extra={"batch_id": str(batch_id), "error_type": type(exc).__name__},
        )
        await fail_unclaimed_broadcast_rows(
            session,
            batch_id=batch_id,
            error_message="WHATSAPP_QUEUE_UNAVAILABLE: WhatsApp delivery queue is temporarily unavailable",
        )
        await session.commit()
        return await refresh_batch_response(session, response, replayed=False)
    return response
