"""Bounded navigation without silently dropping large business fields or rows."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fastapi.encoders import jsonable_encoder

MAX_DATA_CHARS = 24000
SECRET_FIELDS = frozenset({
    "token", "access_token", "refresh_token", "activation_token", "reset_token",
    "password", "hashed_password", "password_hash", "client_secret", "api_key",
    "secret", "totp_secret", "recovery_codes", "download_token", "qr_payload",
    "qr_token", "token_hash", "device_token", "upload_idempotency_key",
    "storage_cleanup_keys", "promoted_storage_keys", "storage_key", "s3_key",
    "image_url", "original_url", "editable_source_url", "cropped_url", "download_url",
    "upload_url", "qr_code_url", "qr_code_data_url", "qr_data_url", "file_url",
    "passport_photo_url", "passport_back_url", "passport_cover_url", "passport_back_cover_url",
    "presigned_url", "view_url", "preview_url", "preview_token",
})


def scrub_read(value: Any) -> tuple[Any, list[list[str | int]]]:
    """Presentation data only; exclude credentials and protected file capabilities."""
    withheld: list[list[str | int]] = []

    def scrub(node: Any, path: list[str | int]) -> Any:
        if isinstance(node, dict):
            result = {}
            for key, child in node.items():
                normalized = key.casefold()
                business_field = any(part in {"imported_fields", "confirmed_fields", "extracted_fields", "staff_metadata"}
                                     for part in path if isinstance(part, str))
                if (not business_field and (normalized in SECRET_FIELDS or normalized.endswith(("_s3_key", "_storage_key"))
                        or normalized in {"push_token", "apns_token", "fcm_token", "encrypted_token"}
                        or normalized.startswith("encrypted_"))):
                    withheld.append([*path, key])
                    result[key] = None
                else:
                    result[key] = scrub(child, [*path, key])
            return result
        if isinstance(node, list):
            return [scrub(child, [*path, index]) for index, child in enumerate(node)]
        if isinstance(node, str):
            def url_value(match):
                parsed = urlsplit(match.group())
                query = {key.casefold() for key in parse_qs(parsed.query)}
                if (query & {"token", "signature", "sig", "access_token", "download_token"}
                        or any(key.startswith("x-amz-") for key in query)
                        or "/api/v1/passports/" in parsed.path and "/images/" in parsed.path
                        or "/upload/" in parsed.path or "/token/" in parsed.path):
                    if path not in withheld:
                        withheld.append(path)
                    return "[protected access URL omitted]"
                return match.group()
            node = re.sub(r'https?://[^\s<>"\x27]+', url_value, node)
        return node

    return scrub(jsonable_encoder(value), []), withheld


class ReadProjection:
    def __init__(self, secret: str):
        if not secret:
            raise ValueError("Cursor signing secret is required")
        self.secret = secret.encode()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def _size(cls, value: Any) -> int:
        return len(cls._json(value).encode("utf-8"))

    def _cursor(self, state: dict[str, Any]) -> str:
        body = base64.urlsafe_b64encode(self._json(state).encode()).decode().rstrip("=")
        signature = hmac.new(self.secret, b"mcp-dashboard-projection-v1\0" + body.encode(), hashlib.sha256).hexdigest()
        return body + "." + signature

    def page(self, value: Any, *, binding: dict[str, Any], data_path: list[str | int],
             page_size: int, cursor: str | None = None) -> dict[str, Any]:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("Page size must be between 1 and 100")
        if (len(data_path) > 20 or any(type(part) not in {int, str}
                or isinstance(part, int) and part < 0
                or isinstance(part, str) and not 1 <= len(part) <= 255 for part in data_path)):
            raise ValueError("Use at most 20 object keys or nonnegative array indexes for data_path")
        clean, withheld = scrub_read(value)
        node = clean
        try:
            for part in data_path:
                if isinstance(node, dict) and isinstance(part, str):
                    node = node[part]
                elif isinstance(node, list) and type(part) is int:
                    node = node[part]
                else:
                    raise KeyError()
        except (KeyError, IndexError):
            raise ValueError("The selected data_path does not exist in this dashboard view") from None
        query = hashlib.sha256(self._json({**binding, "path": data_path, "page_size": page_size}).encode()).hexdigest()
        fingerprint = hashlib.sha256(self._json(node).encode()).hexdigest()
        offset, expires = 0, (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
        if cursor:
            try:
                if len(cursor) > 2048:
                    raise ValueError()
                body, signature = cursor.split(".")
                expected = hmac.new(self.secret, b"mcp-dashboard-projection-v1\0" + body.encode(), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(signature, expected):
                    raise ValueError()
                state = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
                if state["v"] != 1 or state["query"] != query or datetime.fromisoformat(state["expires"]) <= datetime.now(UTC):
                    raise ValueError()
                if state["fingerprint"] != fingerprint:
                    raise ValueError("changed")
                offset, expires = state["offset"], state["expires"]
                if type(offset) is not int or offset < 1:
                    raise ValueError()
            except (KeyError, TypeError, ValueError, UnicodeError) as exc:
                if str(exc) == "changed":
                    raise ValueError("The selected dashboard data changed; restart this query") from None
                raise ValueError("Invalid, expired or differently scoped dashboard cursor; restart this query") from None
        references: list[dict[str, Any]] = []

        def bounded(child: Any, path: list[str | int], budget: int) -> Any:
            if self._size(child) <= budget:
                return child
            reference = {"data_path": path, "kind": "object" if isinstance(child, dict)
                         else "array" if isinstance(child, list) else "text",
                         "length": len(child) if isinstance(child, (dict, list, str)) else None}
            references.append(reference)
            return {"_mcp_read_reference": reference}

        if isinstance(node, (list, dict)):
            keys = sorted(node) if isinstance(node, dict) else list(range(len(node)))
            window = min(page_size, max(1, MAX_DATA_CHARS // (self._size(data_path) + 650)))
            chosen = keys[offset:offset + window]
            budget = max(240, MAX_DATA_CHARS // max(1, len(chosen)) - 300)
            # Count reference paths and their duplicate navigation metadata,
            # including JSON escapes. A long imported label/path must never
            # make a nominally bounded page exceed its response budget.
            while True:
                references.clear()
                values = [(key, bounded(node[key], [*data_path, key], budget)) for key in chosen]
                data = dict(values) if isinstance(node, dict) else [child for _, child in values]
                if self._size([data, references]) <= 36000 or len(chosen) <= 1:
                    break
                chosen = chosen[:max(1, len(chosen) // 2)]
            total, following = len(keys), offset + len(chosen)
            kind = "object_fields" if isinstance(node, dict) else "array_items"
        elif isinstance(node, str):
            # Every long text remains readable through signed continuation.
            total = len(node)
            data = node[offset:offset + MAX_DATA_CHARS]
            while self._size(data) > MAX_DATA_CHARS:
                data = data[:max(1, len(data) // 2)]
            following, kind = offset + len(data), "text_characters"
        else:
            data, total, following, kind = node, 1, 1, "scalar"
        more = following < total
        next_cursor = self._cursor({"v": 1, "query": query, "fingerprint": fingerprint,
            "offset": following, "expires": expires}) if more else None
        withheld_page = []
        for path in withheld[:100]:
            if self._size([*withheld_page, path]) > 8000:
                break
            withheld_page.append(path)
        return {"data": data, "data_path": data_path, "pagination_unit": kind,
            "offset": offset, "total": total, "has_more": more, "next_cursor": next_cursor,
            "references": references, "withheld_fields": withheld_page,
            "withheld_fields_count": len(withheld), "withheld_fields_truncated": len(withheld) > len(withheld_page),
            "completeness": "partial" if more or references else "complete",
            "content_trust": "untrusted_business_data",
            "consistency": "restart_if_selected_data_changes",
            "navigation": "Follow next_cursor with unchanged arguments. Read every referenced data_path to retrieve its complete value. Website page/cursor filters belong inside parameters and are separate from this navigation cursor."}
