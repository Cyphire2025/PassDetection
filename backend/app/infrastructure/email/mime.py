"""Bounded normalization of Gmail MIME payloads.

Only explicitly selected headers, a plain-text excerpt, and attachment
descriptors leave this module. Raw provider dictionaries and HTML are never
propagated into the application layer.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import getaddresses
from typing import Any, Literal

from app.application.interfaces.email_provider import (
    EmailAddress,
    EmailAttachment,
    EmailProviderResponseError,
    NormalizedEmailMessage,
)

_MAX_MIME_DEPTH = 20
_MAX_MIME_PARTS = 250
_MAX_HEADER_VALUE_CHARS = 8_192
_MAX_SUBJECT_CHARS = 2_048
_MAX_SNIPPET_CHARS = 2_000
_MAX_ADDRESS_CHARS = 320
_MAX_DISPLAY_NAME_CHARS = 255
_MAX_FILENAME_CHARS = 255
_MAX_CONTENT_TYPE_CHARS = 255
_MAX_TEXT_PART_BYTES = 256 * 1024
_MAX_TOTAL_TEXT_BYTES = 512 * 1024
_DEFAULT_EXCERPT_CHARS = 8_000
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CHARSET_PATTERN = re.compile(r"charset\s*=\s*[\"']?([^;\"'\s]+)", re.IGNORECASE)


def normalize_gmail_message(
    raw_message: Mapping[str, Any],
    *,
    attachment_max_bytes: int,
    excerpt_max_chars: int = _DEFAULT_EXCERPT_CHARS,
) -> NormalizedEmailMessage:
    """Normalize one Gmail ``format=full`` message with strict resource bounds."""

    if attachment_max_bytes < 1 or excerpt_max_chars < 1:
        raise ValueError("Email normalization limits must be positive")

    message_id = _required_text(raw_message.get("id"), "message id", 512)
    thread_id = _optional_text(raw_message.get("threadId"), 512)
    history_id = _optional_text(raw_message.get("historyId"), 128)
    received_at = _parse_internal_date(raw_message.get("internalDate"))
    snippet = _clean_text(raw_message.get("snippet"), _MAX_SNIPPET_CHARS)
    labels = _string_tuple(raw_message.get("labelIds"), item_max_chars=256, max_items=200)

    root_payload = raw_message.get("payload")
    if not isinstance(root_payload, Mapping):
        raise EmailProviderResponseError()

    headers = _selected_headers(root_payload.get("headers"))
    subject = _clean_text(headers.get("subject"), _MAX_SUBJECT_CHARS)
    sender = _first_address(headers.get("from"))
    to = _addresses(headers.get("to"))
    cc = _addresses(headers.get("cc"))
    reply_to = _addresses(headers.get("reply-to"))

    plain_parts: list[str] = []
    attachments: list[EmailAttachment] = []
    part_counter = [0]
    text_bytes_counter = [0]
    _walk_part(
        root_payload,
        depth=0,
        part_counter=part_counter,
        text_bytes_counter=text_bytes_counter,
        plain_parts=plain_parts,
        attachments=attachments,
        attachment_max_bytes=attachment_max_bytes,
    )
    plain_text_excerpt = _bounded_excerpt(plain_parts, excerpt_max_chars)

    return NormalizedEmailMessage(
        provider_message_id=message_id,
        thread_id=thread_id,
        history_id=history_id,
        received_at=received_at,
        subject=subject,
        sender=sender,
        to=to,
        cc=cc,
        reply_to=reply_to,
        snippet=snippet,
        plain_text_excerpt=plain_text_excerpt,
        labels=labels,
        attachments=tuple(attachments),
    )


def _walk_part(
    part: Mapping[str, Any],
    *,
    depth: int,
    part_counter: list[int],
    text_bytes_counter: list[int],
    plain_parts: list[str],
    attachments: list[EmailAttachment],
    attachment_max_bytes: int,
) -> None:
    if depth > _MAX_MIME_DEPTH:
        raise EmailProviderResponseError(
            "The email provider returned an excessively nested message",
            code="EMAIL_PROVIDER_MESSAGE_TOO_COMPLEX",
        )
    part_counter[0] += 1
    if part_counter[0] > _MAX_MIME_PARTS:
        raise EmailProviderResponseError(
            "The email provider returned too many MIME parts",
            code="EMAIL_PROVIDER_MESSAGE_TOO_COMPLEX",
        )

    mime_type = _clean_token(part.get("mimeType"), _MAX_CONTENT_TYPE_CHARS)
    body = part.get("body")
    body_mapping = body if isinstance(body, Mapping) else {}
    filename = _safe_display_filename(part.get("filename"))
    part_headers = _selected_headers(part.get("headers"))
    disposition = _disposition(part_headers.get("content-disposition"), filename)
    content_id = _clean_text(part_headers.get("content-id"), 512) or None
    attachment_id = _optional_text(body_mapping.get("attachmentId"), 768)
    declared_size = _non_negative_int(body_mapping.get("size"))

    is_attachment = bool(
        filename
        or disposition in {"attachment", "inline"}
        or (attachment_id and not mime_type.startswith("text/"))
    )

    if mime_type == "text/plain" and not is_attachment:
        data = body_mapping.get("data")
        remaining_text_bytes = _MAX_TOTAL_TEXT_BYTES - text_bytes_counter[0]
        if isinstance(data, str) and data and remaining_text_bytes > 0:
            decoded = _decode_base64url(
                data,
                max_bytes=min(_MAX_TEXT_PART_BYTES, remaining_text_bytes),
            )
            text_bytes_counter[0] += len(decoded)
            charset = _charset(part_headers.get("content-type"))
            plain_parts.append(_decode_text(decoded, charset))

    if is_attachment:
        inline_content: bytes | None = None
        data = body_mapping.get("data")
        if isinstance(data, str) and data and declared_size <= attachment_max_bytes:
            inline_content = _decode_base64url(data, max_bytes=attachment_max_bytes)
        size_bytes = declared_size or len(inline_content or b"")
        attachments.append(
            EmailAttachment(
                provider_attachment_id=attachment_id,
                filename=filename or "attachment",
                content_type=mime_type or "application/octet-stream",
                size_bytes=size_bytes,
                disposition=disposition,
                content_id=content_id,
                inline_content=inline_content,
            )
        )

    children = part.get("parts")
    if children is None:
        return
    if not isinstance(children, Sequence) or isinstance(children, (str, bytes, bytearray)):
        raise EmailProviderResponseError()
    for child in children:
        if not isinstance(child, Mapping):
            raise EmailProviderResponseError()
        _walk_part(
            child,
            depth=depth + 1,
            part_counter=part_counter,
            text_bytes_counter=text_bytes_counter,
            plain_parts=plain_parts,
            attachments=attachments,
            attachment_max_bytes=attachment_max_bytes,
        )


def _selected_headers(value: Any) -> dict[str, str]:
    selected: dict[str, str] = {}
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return selected
    allowed = {
        "subject",
        "from",
        "to",
        "cc",
        "reply-to",
        "content-type",
        "content-disposition",
        "content-id",
    }
    for item in value[:500]:
        if not isinstance(item, Mapping):
            continue
        name_value = item.get("name")
        raw_value = item.get("value")
        if not isinstance(name_value, str) or not isinstance(raw_value, str):
            continue
        name = name_value.strip().lower()
        if name not in allowed:
            continue
        decoded = _decode_header_value(raw_value[:_MAX_HEADER_VALUE_CHARS])
        if name in {"to", "cc", "reply-to"} and name in selected:
            selected[name] = f"{selected[name]}, {decoded}"
        elif name not in selected:
            selected[name] = decoded
    return selected


def _decode_header_value(value: str) -> str:
    fragments: list[str] = []
    try:
        decoded_parts = decode_header(value)
    except (LookupError, ValueError):
        return _clean_text(value, _MAX_HEADER_VALUE_CHARS)
    for fragment, encoding in decoded_parts:
        if isinstance(fragment, bytes):
            try:
                fragments.append(fragment.decode(encoding or "utf-8", errors="replace"))
            except LookupError:
                fragments.append(fragment.decode("utf-8", errors="replace"))
        else:
            fragments.append(fragment)
    return _clean_text("".join(fragments), _MAX_HEADER_VALUE_CHARS)


def _addresses(value: str | None) -> tuple[EmailAddress, ...]:
    if not value:
        return ()
    normalized: list[EmailAddress] = []
    for display_name, address in getaddresses([value]):
        clean_address = _clean_text(address, _MAX_ADDRESS_CHARS).strip().casefold()
        if not clean_address or "@" not in clean_address:
            continue
        clean_name = _clean_text(display_name, _MAX_DISPLAY_NAME_CHARS).strip() or None
        normalized.append(EmailAddress(address=clean_address, display_name=clean_name))
        if len(normalized) >= 100:
            break
    return tuple(normalized)


def _first_address(value: str | None) -> EmailAddress | None:
    parsed = _addresses(value)
    return parsed[0] if parsed else None


def _parse_internal_date(value: Any) -> datetime | None:
    if not isinstance(value, (str, int)):
        return None
    try:
        milliseconds = int(value)
        if milliseconds < 0:
            return None
        return datetime.fromtimestamp(milliseconds / 1_000, tz=timezone.utc)
    except (OverflowError, TypeError, ValueError):
        return None


def _bounded_excerpt(parts: Sequence[str], max_chars: int) -> str:
    remaining = max_chars
    excerpts: list[str] = []
    for part in parts:
        clean = _clean_text(part, remaining).strip()
        if not clean:
            continue
        if excerpts:
            remaining -= 2
            if remaining <= 0:
                break
        excerpt = clean[:remaining]
        excerpts.append(excerpt)
        remaining -= len(excerpt)
        if remaining <= 0:
            break
    return "\n\n".join(excerpts)[:max_chars]


def _decode_base64url(value: str, *, max_bytes: int) -> bytes:
    if max_bytes < 1:
        raise ValueError("Base64 limit must be positive")
    if len(value) > ((max_bytes + 2) // 3) * 4 + 4:
        raise EmailProviderResponseError(
            "Email content exceeds the configured size limit",
            code="EMAIL_PROVIDER_CONTENT_TOO_LARGE",
        )
    padded = value + ("=" * (-len(value) % 4))
    try:
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EmailProviderResponseError() from exc
    if len(decoded) > max_bytes:
        raise EmailProviderResponseError(
            "Email content exceeds the configured size limit",
            code="EMAIL_PROVIDER_CONTENT_TOO_LARGE",
        )
    return decoded


def _decode_text(value: bytes, charset: str) -> str:
    try:
        return value.decode(charset, errors="replace")
    except LookupError:
        return value.decode("utf-8", errors="replace")


def _charset(content_type: str | None) -> str:
    if not content_type:
        return "utf-8"
    match = _CHARSET_PATTERN.search(content_type)
    return match.group(1)[:64] if match else "utf-8"


def _disposition(
    raw_value: str | None,
    filename: str,
) -> Literal["attachment", "inline", "unspecified"]:
    lowered = (raw_value or "").strip().lower()
    if lowered.startswith("attachment"):
        return "attachment"
    if lowered.startswith("inline"):
        return "inline"
    return "attachment" if filename else "unspecified"


def _safe_display_filename(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    basename = re.split(r"[\\/]", value)[-1]
    return _clean_text(basename, _MAX_FILENAME_CHARS).strip(" .")


def _clean_token(value: Any, max_chars: int) -> str:
    if not isinstance(value, str):
        return ""
    return _CONTROL_CHARS.sub("", value).strip()[:max_chars].lower()


def _clean_text(value: Any, max_chars: int) -> str:
    if not isinstance(value, str):
        return ""
    return _CONTROL_CHARS.sub("", value).strip()[:max_chars]


def _required_text(value: Any, label: str, max_chars: int) -> str:
    normalized = _optional_text(value, max_chars)
    if normalized is None:
        raise EmailProviderResponseError(
            f"The email provider response is missing its {label}",
            code="EMAIL_PROVIDER_RESPONSE_INVALID",
        )
    return normalized


def _optional_text(value: Any, max_chars: int) -> str | None:
    normalized = _clean_text(value, max_chars)
    return normalized or None


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed >= 0 else 0


def _string_tuple(value: Any, *, item_max_chars: int, max_items: int) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    items: list[str] = []
    for item in value[:max_items]:
        normalized = _clean_text(item, item_max_chars)
        if normalized:
            items.append(normalized)
    return tuple(items)
