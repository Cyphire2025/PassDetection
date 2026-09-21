from __future__ import annotations

import hashlib
import json

import pydantic

from app.presentation.api.v1.routes import whatsapp
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendPreviewResponse,
    WhatsAppLinkedClientGroupResponse,
)

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
    # The reviewed hashes are from 354d8e4. Git history confirms that archives,
    # group invitations and source-contact metadata extend those contracts.
    # Remove only these explicit additions and keep both runtime hashes intact;
    # every extension removed here is separately checked below.
    for name, schema in schemas:
        if name in {"WhatsAppBroadcastGroupResponse", "WhatsAppBroadcastGroupDetailResponse"}:
            for field in ("archived_at", "is_archived", "has_import_only_source", "source_contact_count"):
                schema["properties"].pop(field)
        linked_group = schema.get("$defs", {}).get("WhatsAppLinkedClientGroupResponse")
        if linked_group is not None:
            linked_group["properties"].pop("import_only")
        if name in {"WhatsAppSendRequest", "WhatsAppResendRequest", "WhatsAppPreviewRequest"}:
            message_type = schema["properties"]["message_type"]
            assert message_type["pattern"] == "^(welcome|passport_link|reminder|group_invite)$"
            message_type["pattern"] = "^(welcome|passport_link|reminder)$"
        if name in {
            "WhatsAppSendRequest", "WhatsAppResendRequest", "WhatsAppPreviewRequest", "WhatsAppPreviewResponse",
        }:
            schema["properties"].pop("group_invite_link")
    payload = json.dumps(
        schemas,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()

    assert len(schemas) == 29
    expected_hash = _SCHEMA_SHA256_BY_PYDANTIC[pydantic.__version__]
    assert hashlib.sha256(payload).hexdigest() == expected_hash


def test_archive_fields_are_additive_response_contracts() -> None:
    for model in (whatsapp.WhatsAppBroadcastGroupResponse, whatsapp.WhatsAppBroadcastGroupDetailResponse):
        assert model.model_fields["archived_at"].default is None
        assert model.model_fields["is_archived"].default is False


def test_phone_welcome_fields_are_additive_response_contracts() -> None:
    recipient = whatsapp.WhatsAppRecipientResponse.model_fields
    assert recipient["welcome_status"].default is None
    assert recipient["welcome_delivered"].default is False
    assert recipient["welcome_required_reason"].default is None
    preview = whatsapp.WhatsAppPreviewResponse.model_fields
    assert preview["welcome_required_count"].default == 0
    assert preview["welcome_required_reason"].default is None


def test_source_contact_markers_are_additive_response_contracts() -> None:
    for model in (whatsapp.WhatsAppBroadcastGroupResponse, whatsapp.WhatsAppBroadcastGroupDetailResponse):
        properties = model.model_json_schema()["properties"]
        assert properties["has_import_only_source"] == {
            "default": False, "title": "Has Import Only Source", "type": "boolean",
        }
        assert properties["source_contact_count"] == {
            "default": 0, "title": "Source Contact Count", "type": "integer",
        }
    assert WhatsAppLinkedClientGroupResponse.model_json_schema()["properties"]["import_only"] == {
        "default": False, "title": "Import Only", "type": "boolean",
    }


def test_group_invite_link_is_optional_and_bounded_in_composer_requests() -> None:
    for model in (whatsapp.WhatsAppSendRequest, whatsapp.WhatsAppResendRequest, whatsapp.WhatsAppPreviewRequest):
        assert model.model_validate({"message_type": "group_invite"}).group_invite_link is None
        assert model.model_json_schema()["properties"]["group_invite_link"] == {
            "anyOf": [{"maxLength": 2048, "type": "string"}, {"type": "null"}],
            "default": None, "title": "Group Invite Link",
        }
    assert whatsapp.WhatsAppPreviewResponse.model_json_schema()["properties"]["group_invite_link"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "default": None, "title": "Group Invite Link",
    }


def test_bulk_preview_missing_image_count_defaults_to_zero_and_cannot_be_negative() -> None:
    field = WhatsAppBulkResendPreviewResponse.model_fields["missing_header_image_count"]
    assert field.default == 0
    assert WhatsAppBulkResendPreviewResponse.model_json_schema()["properties"]["missing_header_image_count"] == {
        "default": 0, "minimum": 0, "title": "Missing Header Image Count", "type": "integer",
    }
