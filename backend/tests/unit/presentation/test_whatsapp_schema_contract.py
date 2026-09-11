from __future__ import annotations

import hashlib
import json

import pydantic

from app.presentation.api.v1.routes import whatsapp

_MODEL_NAMES = [
    "WhatsAppRecipientInput",
    "WhatsAppContactPreviewRecipient",
    "WhatsAppContactPreviewRejectedRow",
    "WhatsAppContactPreviewResponse",
    "WhatsAppRejectedContactInput",
    "WhatsAppRejectedContactResponse",
    "WhatsAppRejectedContactListResponse",
    "WhatsAppRejectedContactResolveRequest",
    "WhatsAppSupportContactInput",
    "WhatsAppRecipientResponse",
    "WhatsAppRecipientMessageStatusResponse",
    "WhatsAppReplacedRecipientResponse",
    "WhatsAppUnidentifiedUploadResponse",
    "WhatsAppRecipientRosterItemResponse",
    "WhatsAppRecipientRosterCountsResponse",
    "WhatsAppRecipientRosterResponse",
    "WhatsAppSupportContactResponse",
    "WhatsAppBroadcastGroupResponse",
    "WhatsAppBroadcastGroupDetailResponse",
    "WhatsAppSendRequest",
    "WhatsAppResendRequest",
    "WhatsAppRecipientPhoneUpdateRequest",
    "WhatsAppPreviewRequest",
    "WhatsAppPreviewResponse",
    "WhatsAppWelcomeMediaResponse",
    "WhatsAppSendResult",
    "WhatsAppSendResponse",
    "WhatsAppBatchSummaryResponse",
    "WhatsAppWebhookAck",
]
_SCHEMA_SHA256_BY_PYDANTIC = {
    # Repository-pinned production and CI runtime.
    "2.7.4": "7f1bdd988f80973e0506b5e938f4d302086c34ce6069173da20a431329a07299",
    # Python 3.13-compatible Windows development runtime.
    "2.13.4": "75c75c634bbde6846c3e95bc38cf96b7bdbe1d45a44c42c8c7250112adce13e3",
}


def test_whatsapp_route_reexports_reviewed_schema_contracts() -> None:
    schemas = [(name, getattr(whatsapp, name).model_json_schema()) for name in _MODEL_NAMES]
    payload = json.dumps(
        schemas,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()

    assert len(schemas) == 29
    expected_hash = _SCHEMA_SHA256_BY_PYDANTIC[pydantic.__version__]
    assert hashlib.sha256(payload).hexdigest() == expected_hash


def test_phone_welcome_fields_are_additive_response_contracts() -> None:
    recipient = whatsapp.WhatsAppRecipientResponse.model_fields
    assert recipient["welcome_status"].default is None
    assert recipient["welcome_delivered"].default is False
    assert recipient["welcome_required_reason"].default is None
    preview = whatsapp.WhatsAppPreviewResponse.model_fields
    assert preview["welcome_required_count"].default == 0
    assert preview["welcome_required_reason"].default is None
