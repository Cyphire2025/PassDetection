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
    "2.7.4": "412e9736798e5e1d039797e4bd189db5930d544845a51c861fa821346c205fa0",
    # Python 3.13-compatible Windows development runtime.
    "2.13.4": "0bff4a036b43b8ca87677f4c366df3522ae6cc9087b9c7f734044d72d319a6bf",
}


def test_whatsapp_route_reexports_unchanged_schema_contracts() -> None:
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
