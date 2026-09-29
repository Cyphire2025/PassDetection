"""One explicit selected header image and stable key to the fixed application route."""

import hashlib
import hmac
import re
import uuid
from datetime import datetime

from .config import ConnectorError
from .files import provided_file_chunks

MAX_BYTES = 5 * 1024 * 1024
KEY_PATTERN = r"[A-Za-z0-9._:-]{16,256}"
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_HANDLE = re.compile(r"gcmcp_wa_media_[A-Za-z0-9_-]{64}\Z")
_FAILURES = {
    None,
    "source_integrity_unavailable",
    "provider_upload_unreachable",
    "provider_upload_unconfirmed",
    "provider_upload_receipt_unavailable",
}


def _aware_timestamp(value):
    if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
        raise ValueError()
    return value


def _receipt(raw, *, agency_id, broadcast_id, size=None, checksum=None, media_type=None):
    try:
        identifier = str(uuid.UUID(raw["media_artifact_id"]))
        if (
            identifier != raw["media_artifact_id"]
            or not _HANDLE.fullmatch(raw["media_handle"])
            or raw["agency_id"] != str(agency_id)
            or raw["broadcast_id"] != str(broadcast_id)
            or type(raw["byte_size"]) is not int
            or not 1 <= raw["byte_size"] <= MAX_BYTES
            or size is not None
            and raw["byte_size"] != size
            or not _DIGEST.fullmatch(raw["sha256"])
            or checksum is not None
            and not hmac.compare_digest(raw["sha256"], checksum)
            or raw["media_type"] not in {"image/jpeg", "image/png"}
            or media_type is not None
            and raw["media_type"] != media_type
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", raw["filename"])
            or not raw["filename"]
            .lower()
            .endswith(".png" if raw["media_type"] == "image/png" else ".jpg")
            or not _DIGEST.fullmatch(raw["provider_content_sha256"])
            or raw["status"] not in {"staged", "uploading", "ready", "failed", "unknown"}
            or type(raw["revision"]) is not int
            or raw["revision"] < 1
            or type(raw["messages_queued"]) is not int
            or raw["messages_queued"] != 0
            or raw["failure_code"] not in _FAILURES
        ):
            raise ValueError()
        _aware_timestamp(raw["expires_at"])
        if raw["attempt_deadline"] is not None:
            _aware_timestamp(raw["attempt_deadline"])
        # Extra provider identifiers, object keys, paths, URLs and instructions
        # never become local tool output or transfer authority.
        return {
            key: raw[key]
            for key in (
                "media_artifact_id",
                "media_handle",
                "agency_id",
                "broadcast_id",
                "filename",
                "media_type",
                "byte_size",
                "sha256",
                "status",
                "expires_at",
                "attempt_deadline",
                "failure_code",
                "revision",
                "messages_queued",
            )
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ConnectorError(
            "Header upload receipt does not match the selected image and broadcast."
        ) from None


async def _authority(client, agency_id, broadcast_id):
    scope = {"agency_id": str(agency_id), "broadcast_id": str(broadcast_id)}
    authority = await client._json(
        "GET", f"{client.config.origin}/mcp/whatsapp-media/authority", params=scope
    )
    if (
        authority.get("authorized") is not True
        or authority.get("agency_id") != str(agency_id)
        or authority.get("broadcast_id") != str(broadcast_id)
        or not isinstance(authority.get("capabilities"), list)
        or not all(isinstance(item, str) for item in authority["capabilities"])
        or sorted(authority["capabilities"]) != ["mcp:communicate", "mcp:upload"]
    ):
        raise ConnectorError(
            "The current connection does not authorize this header upload and broadcast."
        )
    return scope


async def upload_whatsapp_header_image(
    client,
    path,
    *,
    allowed_paths,
    agency_id: uuid.UUID,
    broadcast_id: uuid.UUID,
    idempotency_key: str,
) -> dict:
    if not re.fullmatch(KEY_PATTERN, idempotency_key):
        raise ConnectorError(
            "Use one stable 16-256 character header-upload key containing letters, digits, period, underscore, colon or hyphen."
        )
    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(
        path.suffix.lower()
    )
    if media_type is None:
        raise ConnectorError("Select a JPEG or PNG header image no larger than 5 MiB.")
    scope = await _authority(client, agency_id, broadcast_id)
    size, digest, signature = 0, hashlib.sha256(), b""
    async for part in provided_file_chunks(path, allowed_paths=allowed_paths, max_bytes=MAX_BYTES):
        if not signature:
            signature = part[:8]
        size += len(part)
        digest.update(part)
    if (
        not size
        or (media_type == "image/png" and signature != b"\x89PNG\r\n\x1a\n")
        or (media_type == "image/jpeg" and not signature.startswith(b"\xff\xd8\xff"))
    ):
        raise ConnectorError("The selected file does not contain the declared JPEG or PNG image.")
    checksum = digest.hexdigest()
    try:
        raw = await client._json(
            "POST",
            f"{client.config.origin}/mcp/whatsapp-media/uploads",
            expected_status=201,
            params={**scope, "filename": path.name},
            headers={
                "Content-Type": media_type,
                "X-Artifact-Size": str(size),
                "X-Artifact-SHA256": checksum,
                "Idempotency-Key": idempotency_key,
            },
            content=provided_file_chunks(path, allowed_paths=allowed_paths, max_bytes=MAX_BYTES),
        )
        result = _receipt(
            raw,
            agency_id=agency_id,
            broadcast_id=broadcast_id,
            size=size,
            checksum=checksum,
            media_type=media_type,
        )
    except ConnectorError:
        raise ConnectorError(
            "Header upload outcome was not safely received. Keep the same selected file and "
            f"idempotency key {idempotency_key}. Inspect the existing media receipt before an "
            "explicit retry; do not create a new key or assume the image is ready."
        ) from None
    result["idempotency_key"] = idempotency_key
    return _guidance(result)


def _guidance(result):
    result.update(
        ready_for_message_plan=result["status"] == "ready", automatic_retry_performed=False
    )
    if result["status"] in {"uploading", "unknown"}:
        result["guidance"] = (
            "Inspect this media handle and reconcile the upload outcome. Do not create a new key, reupload automatically, or send a message."
        )
    elif result["status"] in {"failed", "staged"}:
        result["guidance"] = (
            "This image is not ready. Inspect this media handle; no upload retry or message send was performed."
        )
    else:
        result["guidance"] = (
            "Use this media handle only in a separately reviewed message plan. No message was queued."
        )
    return result


async def inspect_whatsapp_header_image(
    client, *, media_handle: str, agency_id: uuid.UUID, broadcast_id: uuid.UUID
) -> dict:
    if not _HANDLE.fullmatch(media_handle):
        raise ConnectorError("Use the exact header-image media handle from the upload receipt.")
    await _authority(client, agency_id, broadcast_id)
    raw = await client._json("GET", f"{client.config.origin}/mcp/whatsapp-media/{media_handle}")
    result = _receipt(raw, agency_id=agency_id, broadcast_id=broadcast_id)
    if result["media_handle"] != media_handle:
        raise ConnectorError("The inspected image receipt does not match the requested handle.")
    return _guidance(result)


async def recover_whatsapp_header_image(
    client, *, media_artifact_id: uuid.UUID, agency_id: uuid.UUID, broadcast_id: uuid.UUID
) -> dict:
    await _authority(client, agency_id, broadcast_id)
    raw = await client._json(
        "POST", f"{client.config.origin}/mcp/whatsapp-media/{media_artifact_id}/recover"
    )
    result = _receipt(raw, agency_id=agency_id, broadcast_id=broadcast_id)
    if result["media_artifact_id"] != str(media_artifact_id) or result["status"] != "ready":
        raise ConnectorError(
            "Only the exact retained ready image can be recovered; no upload was retried."
        )
    return _guidance(result)
