"""Fixed composition of existing website rules; no request-supplied adapters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import HTTPException

from app.application.mcp.contact_broadcasts import ContactBroadcastSupport
from app.application.mcp.contact_mapping import ContactMappingSupport
from app.application.mcp.operations import MCPOperationError
from app.infrastructure.database.models import WhatsAppBroadcastGroupModel
from app.presentation.api.v1.routes.whatsapp_contact_support import (
    _WHATSAPP_CONTACT_REJECTION_REASONS,
    _clean_name,
    _excel_fields_from_row,
    _merge_imported_field_keys,
    _merge_recipient_inputs,
    _normalize_phone,
)
from app.presentation.api.v1.routes.whatsapp_creation import (
    create_new_broadcast,
    validate_new_broadcast,
)

T = TypeVar("T")


def _safe(function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    try:
        return function(*args, **kwargs)
    except HTTPException as exc:
        raise MCPOperationError("invalid_contact_broadcast") from exc


async def _create(*args: Any, **kwargs: Any) -> WhatsAppBroadcastGroupModel:
    try:
        return await create_new_broadcast(*args, **kwargs)
    except HTTPException as exc:
        raise MCPOperationError("invalid_contact_broadcast") from exc


CONTACT_IMPORT_SUPPORT = ContactBroadcastSupport(
    mapping=ContactMappingSupport(
        clean_name=_clean_name,
        normalize_phone=_normalize_phone,
        fields=lambda **kwargs: _safe(_excel_fields_from_row, **kwargs),
        merge_keys=lambda *args, **kwargs: _safe(_merge_imported_field_keys, *args, **kwargs),
        merge_contacts=lambda *args: _safe(_merge_recipient_inputs, *args),
        rejection_reasons=_WHATSAPP_CONTACT_REJECTION_REASONS,
    ),
    validate=lambda **kwargs: _safe(validate_new_broadcast, **kwargs),
    create=_create,
)
