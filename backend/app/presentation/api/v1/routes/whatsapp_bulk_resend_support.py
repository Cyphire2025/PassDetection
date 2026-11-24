"""Selected-resend eligibility/snapshot policy and compatibility exports."""

from __future__ import annotations

import hashlib as hashlib
import json as json
import uuid as uuid
from datetime import UTC as UTC
from datetime import datetime as datetime

from sqlalchemy import select as select
from sqlalchemy import update as update
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.core.config.settings import get_settings as get_settings
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel as WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.models import WhatsAppMessageLogModel as WhatsAppMessageLogModel
from app.infrastructure.database.models import (
    WhatsAppRecipientMessageStateModel as WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_blocking_statuses as group_invite_blocking_statuses,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_skip_reason as group_invite_skip_reason,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    message_phone_blocking_statuses as message_phone_blocking_statuses,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_composer import (
    BulkResendEdits as BulkResendEdits,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_composer import (
    resolve_saved_resend_snapshot as resolve_saved_resend_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_history import (
    expire_stale_explicit_claims as expire_stale_explicit_claims,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_history import (
    selection_delivery_maps as selection_delivery_maps,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_results import (
    build_response as build_response,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_results import (
    refresh_batch_response as refresh_batch_response,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES as WHATSAPP_ACCEPTED_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES as WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_IN_PROGRESS_STATUSES as WHATSAPP_IN_PROGRESS_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_STALE_CLAIM_AGE as WHATSAPP_STALE_CLAIM_AGE,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _snapshot_template_language as _snapshot_template_language,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendDraft as WhatsAppBulkResendDraft,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendRequest as WhatsAppBulkResendRequest,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendResponse as WhatsAppBulkResendResponse,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppSendResult as WhatsAppSendResult,
)

SKIP_MESSAGES = {
    "skipped_already_sent": "This WhatsApp number already has this message submitted or delivered; another send is blocked.",
    "skipped_replaced": "This person is replaced in a linked passport group.",
    "skipped_in_progress": "A message of this type is already in progress.",
    "skipped_delivery_unknown": "Previous delivery is unknown; verify it before resending.",
    "skipped_no_saved_message": "No safely saved sent or failed message is available.",
    "skipped_ineligible": "Only previously submitted or failed messages can be resent.",
}


def selection_fingerprint(body: WhatsAppBulkResendRequest) -> str:
    selected = ",".join(sorted(str(value) for value in body.recipient_ids))
    selection = f"{body.message_type}:{selected}"
    overrides = body.model_dump(
        mode="json",
        include={
            "message_content",
            "passport_intro",
            "header_image_id",
            "support_contact_ids",
            "group_invite_link",
        },
        exclude_none=True,
    )
    if overrides:
        # Keep the deployed no-edit fingerprint stable for old durable receipts.
        selection += ":" + json.dumps(overrides, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(selection.encode()).hexdigest()


def recipient_skip_reason(
    *,
    recipient: WhatsAppBroadcastRecipientModel,
    state: WhatsAppRecipientMessageStateModel | None,
    active_statuses: set[str],
    replaced_phones: set[str],
    message_type: str | None = None,
) -> str | None:
    if recipient.normalized_phone_number in replaced_phones:
        return "skipped_replaced"
    state_status = state.status if state else None
    if message_type == "group_invite":
        for candidate in (
            "read",
            "delivered",
            "sent",
            "submitted",
            "delivery_unknown",
            "processing",
            "queued",
        ):
            if candidate == state_status or candidate in active_statuses:
                return group_invite_skip_reason(candidate)
    if state_status == "delivery_unknown" or "delivery_unknown" in active_statuses:
        return "skipped_delivery_unknown"
    if message_type == "passport_link" and state_status == "failed":
        if active_statuses & WHATSAPP_ACCEPTED_STATUSES:
            return "skipped_already_sent"
    if state_status in WHATSAPP_IN_PROGRESS_STATUSES or active_statuses:
        return "skipped_in_progress"
    if state_status is None:
        return "skipped_no_saved_message"
    if state_status not in WHATSAPP_ACCEPTED_STATUSES | {"failed"}:
        return "skipped_ineligible"
    return None


def frozen_resend_log(
    *,
    recipient: WhatsAppBroadcastRecipientModel,
    source: WhatsAppMessageLogModel,
    state: WhatsAppRecipientMessageStateModel,
    batch_id: uuid.UUID,
    now: datetime,
    edits: BulkResendEdits | None = None,
) -> WhatsAppMessageLogModel:
    """Keep every recipient's own template, message, support block and private link.

    No common composer defaults are substituted into an existing saved message.
    Legacy snapshots are accepted only if the existing decoder verifies them.
    """
    snapshot = resolve_saved_resend_snapshot(source, edits)
    return WhatsAppMessageLogModel(
        id=uuid.uuid4(),
        normalized_phone_number=recipient.normalized_phone_number,
        batch_id=batch_id,
        broadcast_group_id=recipient.broadcast_group_id,
        recipient_id=recipient.id,
        agency_id=recipient.agency_id,
        message_type=source.message_type,
        status="queued",
        status_updated_at=now,
        provider_message_id=None,
        error_message=None,
        template_name=snapshot.template_name,
        template_language=_snapshot_template_language(get_settings(), source.message_type, source),
        rendered_message=snapshot.rendered_message,
        header_parameter_values=snapshot.header_parameters,
        template_parameter_values=snapshot.parameters,
        is_explicit_resend=state.status != "failed",
        created_at=now,
    )
