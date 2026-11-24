"""Message composition and reusable snapshot helpers for WhatsApp routes."""

from __future__ import annotations

import logging as logging
import uuid as uuid
from dataclasses import dataclass as dataclass
from typing import Any as Any
from urllib.parse import urlparse as urlparse

from fastapi import HTTPException as HTTPException
from fastapi import status as status
from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.application.use_cases.whatsapp.message_templates import (
    AUTOMATED_NOTICE as AUTOMATED_NOTICE,
)
from app.application.use_cases.whatsapp.message_templates import GREETING as GREETING
from app.application.use_cases.whatsapp.message_templates import (
    PASSPORT_INFORMATION_NOTICE as PASSPORT_INFORMATION_NOTICE,
)
from app.application.use_cases.whatsapp.message_templates import (
    STATIC_TEMPLATE_HEADER as STATIC_TEMPLATE_HEADER,
)
from app.application.use_cases.whatsapp.message_templates import (
    WhatsAppMessageType as WhatsAppMessageType,
)
from app.application.use_cases.whatsapp.message_templates import (
    default_message_content as default_message_content,
)
from app.application.use_cases.whatsapp.message_templates import (
    format_support_contacts as format_support_contacts,
)
from app.application.use_cases.whatsapp.message_templates import (
    passport_link_intro as passport_link_intro,
)
from app.application.use_cases.whatsapp.message_templates import render_message as render_message
from app.application.use_cases.whatsapp.message_templates import (
    template_header_parameters as template_header_parameters,
)
from app.application.use_cases.whatsapp.message_templates import (
    template_parameters as template_parameters,
)
from app.application.use_cases.whatsapp.message_templates import (
    validate_group_invite_link as validate_group_invite_link,
)
from app.application.use_cases.whatsapp.message_templates import (
    validate_template_parameters as validate_template_parameters,
)
from app.application.use_cases.whatsapp.template_text import (
    normalize_template_text as normalize_template_text,
)
from app.core.config.settings import Settings as Settings
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel as WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel as WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastSupportContactModel as WhatsAppBroadcastSupportContactModel,
)
from app.infrastructure.database.models import WhatsAppMessageLogModel as WhatsAppMessageLogModel
from app.presentation.api.v1.routes.whatsapp_composer_content import (
    _as_message_type as _as_message_type,
)
from app.presentation.api.v1.routes.whatsapp_composer_content import (
    _preview_message_metadata as _preview_message_metadata,
)
from app.presentation.api.v1.routes.whatsapp_composer_content import (
    _resolve_message_content as _resolve_message_content,
)
from app.presentation.api.v1.routes.whatsapp_composer_content import (
    _resolve_message_links as _resolve_message_links,
)
from app.presentation.api.v1.routes.whatsapp_composer_content import (
    _resolve_passport_intro as _resolve_passport_intro,
)
from app.presentation.api.v1.routes.whatsapp_composer_content import (
    _resolve_send_header_image as _resolve_send_header_image,
)
from app.presentation.api.v1.routes.whatsapp_composer_content import (
    _resolve_send_message_content as _resolve_send_message_content,
)
from app.presentation.api.v1.routes.whatsapp_composer_content import (
    _resolve_send_passport_intro as _resolve_send_passport_intro,
)
from app.presentation.api.v1.routes.whatsapp_composer_content import (
    _snapshot_template_language as _snapshot_template_language,
)
from app.presentation.api.v1.routes.whatsapp_composer_content import (
    _validate_group_invite_link as _validate_group_invite_link,
)
from app.presentation.api.v1.routes.whatsapp_composer_content import (
    _validate_passport_link as _validate_passport_link,
)
from app.presentation.api.v1.routes.whatsapp_composer_legacy import (
    _decode_legacy_template_snapshot as _decode_legacy_template_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_composer_legacy import (
    _split_rendered_support_block as _split_rendered_support_block,
)
from app.presentation.api.v1.routes.whatsapp_composer_rendering import (
    _message_values as _message_values,
)
from app.presentation.api.v1.routes.whatsapp_composer_snapshots import (
    _composer_snapshot_from_log as _composer_snapshot_from_log,
)
from app.presentation.api.v1.routes.whatsapp_composer_snapshots import (
    _latest_composer_snapshot as _latest_composer_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_composer_snapshots import (
    _merge_composer_snapshot as _merge_composer_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_composer_snapshots import (
    _template_snapshot_from_log as _template_snapshot_from_log,
)
from app.presentation.api.v1.routes.whatsapp_composer_snapshots import (
    _WhatsAppComposerSnapshot as _WhatsAppComposerSnapshot,
)
from app.presentation.api.v1.routes.whatsapp_composer_snapshots import (
    logger as logger,
)
from app.presentation.api.v1.routes.whatsapp_contact_support import _clean_name as _clean_name
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    WHATSAPP_ACCEPTED_STATUSES as WHATSAPP_ACCEPTED_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    WHATSAPP_IN_PROGRESS_STATUSES as WHATSAPP_IN_PROGRESS_STATUSES,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppSendRequest as WhatsAppSendRequest,
)
