"""Decode, query and merge immutable saved composer snapshots."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import (
    WhatsAppMessageType,
    validate_template_parameters,
)
from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.presentation.api.v1.routes.whatsapp_composer_content import _as_message_type
from app.presentation.api.v1.routes.whatsapp_composer_legacy import _decode_legacy_template_snapshot
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_IN_PROGRESS_STATUSES,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendRequest

logger = logging.getLogger("app.presentation.api.v1.routes.whatsapp")


@dataclass(frozen=True, slots=True)
class _WhatsAppComposerSnapshot:
    log: WhatsAppMessageLogModel
    passport_intro: str | None
    passport_link: str | None
    message_content: str
    header_image_id: str | None
    group_invite_link: str | None = None


def _template_snapshot_from_log(
    log: WhatsAppMessageLogModel,
) -> tuple[list[str], list[str]]:
    if log.message_type not in {"welcome", "passport_link", "reminder", "group_invite", "update"}:
        raise ValueError("The saved WhatsApp message type cannot be resent")
    message_type = _as_message_type(log.message_type)
    saved_header = log.header_parameter_values
    saved_body = log.template_parameter_values
    if saved_header is None and saved_body is None:
        return _decode_legacy_template_snapshot(
            message_type=message_type,
            rendered_message=log.rendered_message,
        )
    if not isinstance(saved_header, list) or not isinstance(saved_body, list):
        raise ValueError("The saved WhatsApp message parameters are incomplete")
    if any(not isinstance(value, str) for value in [*saved_header, *saved_body]):
        raise ValueError("The saved WhatsApp message parameters are invalid")
    header_parameters = list(saved_header)
    parameters = list(saved_body)
    validate_template_parameters(
        message_type=message_type,
        header_parameters=header_parameters,
        body_parameters=parameters,
        allow_legacy_group_invite_header=True,
    )
    return header_parameters, parameters


def _composer_snapshot_from_log(
    log: WhatsAppMessageLogModel,
) -> _WhatsAppComposerSnapshot:
    header_parameters, parameters = _template_snapshot_from_log(log)
    header_image_id = header_parameters[0] if header_parameters else None
    if log.message_type in {"welcome", "reminder", "group_invite", "update"}:
        return _WhatsAppComposerSnapshot(
            log=log,
            passport_intro=None,
            passport_link=None,
            message_content=parameters[0],
            header_image_id=header_image_id,
            group_invite_link=parameters[1] if log.message_type == "group_invite" else None,
        )
    return _WhatsAppComposerSnapshot(
        log=log,
        passport_intro=parameters[0],
        passport_link=parameters[1],
        message_content=parameters[2],
        header_image_id=header_image_id,
    )


async def _latest_composer_snapshot(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    message_type: WhatsAppMessageType,
    recipient_id: uuid.UUID | None = None,
    accepted_only: bool = True,
    include_failed: bool = False,
    include_explicit_resends: bool = False,
) -> _WhatsAppComposerSnapshot | None:
    reusable_statuses = (
        WHATSAPP_ACCEPTED_STATUSES
        if accepted_only
        else WHATSAPP_ACCEPTED_STATUSES | WHATSAPP_IN_PROGRESS_STATUSES
    )
    if include_failed:
        reusable_statuses = reusable_statuses | {"failed"}
    predicates: list[Any] = [
        WhatsAppMessageLogModel.broadcast_group_id == group_id,
        WhatsAppMessageLogModel.message_type == message_type,
        WhatsAppMessageLogModel.status.in_(reusable_statuses),
    ]
    if recipient_id is not None:
        predicates.append(WhatsAppMessageLogModel.recipient_id == recipient_id)
    if not include_explicit_resends:
        predicates.append(WhatsAppMessageLogModel.is_explicit_resend.is_(False))
    result = await session.execute(
        select(WhatsAppMessageLogModel)
        .where(*predicates)
        .order_by(
            WhatsAppMessageLogModel.created_at.desc(),
            WhatsAppMessageLogModel.status_updated_at.desc(),
        )
        .limit(20)
    )
    for log in result.scalars().all():
        try:
            return _composer_snapshot_from_log(log)
        except ValueError:
            logger.warning(
                "whatsapp_composer_snapshot_ignored",
                extra={
                    "message_log_id": str(log.id),
                    "message_type": message_type,
                },
            )
    return None


def _merge_composer_snapshot(
    body: WhatsAppSendRequest,
    snapshot: _WhatsAppComposerSnapshot | None,
) -> WhatsAppSendRequest:
    message_type = _as_message_type(body.message_type)
    return WhatsAppSendRequest(
        message_type=message_type,
        passport_intro=(
            body.passport_intro
            if body.passport_intro is not None
            else snapshot.passport_intro
            if snapshot
            else None
        ),
        passport_link=(
            body.passport_link
            if body.passport_link is not None
            else snapshot.passport_link
            if snapshot
            else None
        ),
        message_content=(
            body.message_content
            if body.message_content is not None
            else snapshot.message_content
            if snapshot
            else None
        ),
        group_invite_link=(
            body.group_invite_link
            if body.group_invite_link is not None
            else snapshot.group_invite_link
            if snapshot
            else None
        ),
        header_image_id=(
            body.header_image_id
            if body.header_image_id is not None
            else snapshot.header_image_id
            if snapshot
            else None
        ),
        recipient_ids=body.recipient_ids,
        support_contact_ids=body.support_contact_ids,
        audience=body.audience,
        audience_client_group_id=body.audience_client_group_id,
        update_submission=body.update_submission,
        update_distribution=body.update_distribution,
        update_document_type=body.update_document_type,
        include_previous_recipients=body.include_previous_recipients,
    )


# Keep existing public imports and pickle identities.
_WhatsAppComposerSnapshot.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_template_snapshot_from_log.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_composer_snapshot_from_log.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_latest_composer_snapshot.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
_merge_composer_snapshot.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"

for _method_name in ("__init__", "__repr__", "__eq__", "__setattr__", "__delattr__", "__hash__"):
    getattr(
        _WhatsAppComposerSnapshot, _method_name
    ).__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
del _method_name
