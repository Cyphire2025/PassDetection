"""Fail-closed Sentry event projection for the travel-document platform.

Sentry is useful for crash grouping, but the default SDK event contains more
context than this application is permitted to export. This module constructs a
small allowlisted event instead of trying to enumerate every possible passport,
phone, token, filename, form-field, or future custom-field key.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_UUID_SEGMENT = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_OPAQUE_SEGMENT = re.compile(r"^[A-Za-z0-9._~-]{24,}$")
_SAFE_TOP_LEVEL = (
    "event_id",
    "timestamp",
    "platform",
    "level",
    "logger",
    "release",
    "environment",
)
_SAFE_FRAME_FIELDS = (
    "filename",
    "function",
    "module",
    "lineno",
    "colno",
    "in_app",
    "package",
)


def _sanitized_path(value: str) -> str:
    """Retain route shape while removing UUIDs and opaque locator/token segments."""

    parsed = urlsplit(value)
    path = parsed.path if parsed.scheme or parsed.netloc else value.split("?", 1)[0]
    parts = [
        "{id}" if _UUID_SEGMENT.fullmatch(part) or _OPAQUE_SEGMENT.fullmatch(part) else part
        for part in path.split("/")
    ]
    safe_path = "/".join(parts)
    if not parsed.scheme and not parsed.netloc:
        return safe_path
    return urlunsplit((parsed.scheme, parsed.netloc, safe_path, "", ""))


def _safe_stacktrace(stacktrace: object) -> dict[str, object] | None:
    if not isinstance(stacktrace, dict):
        return None
    frames = stacktrace.get("frames")
    if not isinstance(frames, list):
        return None
    safe_frames: list[dict[str, object]] = []
    for frame in frames[-100:]:
        if not isinstance(frame, dict):
            continue
        safe_frames.append(
            {key: frame[key] for key in _SAFE_FRAME_FIELDS if key in frame}
        )
    return {"frames": safe_frames}


def scrub_sentry_event(
    event: dict[str, Any],
    hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an allowlisted event containing no request/user/business payloads."""

    del hint
    safe: dict[str, Any] = {
        key: event[key] for key in _SAFE_TOP_LEVEL if key in event
    }

    request = event.get("request")
    if isinstance(request, dict):
        safe_request: dict[str, object] = {}
        method = request.get("method")
        if isinstance(method, str) and method.isascii() and len(method) <= 16:
            safe_request["method"] = method.upper()
        url = request.get("url")
        if isinstance(url, str) and len(url) <= 4_096:
            safe_request["url"] = _sanitized_path(url)
        if safe_request:
            safe["request"] = safe_request

    transaction = event.get("transaction")
    if isinstance(transaction, str) and len(transaction) <= 4_096:
        safe["transaction"] = _sanitized_path(transaction)

    exception = event.get("exception")
    if isinstance(exception, dict) and isinstance(exception.get("values"), list):
        values: list[dict[str, object]] = []
        for value in exception["values"][-10:]:
            if not isinstance(value, dict):
                continue
            safe_value: dict[str, object] = {}
            exception_type = value.get("type")
            if isinstance(exception_type, str) and len(exception_type) <= 255:
                safe_value["type"] = exception_type
            mechanism = value.get("mechanism")
            if isinstance(mechanism, dict):
                safe_value["mechanism"] = {
                    key: mechanism[key]
                    for key in ("type", "handled")
                    if key in mechanism
                }
            stacktrace = _safe_stacktrace(value.get("stacktrace"))
            if stacktrace is not None:
                safe_value["stacktrace"] = stacktrace
            if safe_value:
                values.append(safe_value)
        if values:
            safe["exception"] = {"values": values}

    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict) and isinstance(breadcrumbs.get("values"), list):
        safe_breadcrumbs: list[dict[str, object]] = []
        for crumb in breadcrumbs["values"][-50:]:
            if not isinstance(crumb, dict):
                continue
            # Breadcrumb messages and data can contain names, phones, object
            # keys, SQL values, document titles, and request URLs. Category and
            # severity are enough to reconstruct the event sequence safely.
            safe_breadcrumbs.append(
                {
                    key: crumb[key]
                    for key in ("timestamp", "type", "category", "level")
                    if key in crumb
                }
            )
        safe["breadcrumbs"] = {"values": safe_breadcrumbs}

    # Package versions help reproduce crashes and do not contain request data.
    modules = event.get("modules")
    if isinstance(modules, dict):
        safe["modules"] = {
            str(key)[:200]: str(value)[:100]
            for key, value in list(modules.items())[:500]
        }

    return safe


def sentry_init_options() -> dict[str, object]:
    """Settings that keep SDK integrations from collecting sensitive context."""

    return {
        "send_default_pii": False,
        "include_local_variables": False,
        "max_request_body_size": "never",
        "before_send": scrub_sentry_event,
        "before_send_transaction": scrub_sentry_event,
    }
