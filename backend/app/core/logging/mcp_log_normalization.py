"""Fixed-source structured Docker/stdout and current Nginx main-format parsing."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from app.core.logging.mcp_log_projection import diagnostic_timestamp, project_diagnostic_record

MAX_INPUT_LINE_BYTES = 16 * 1024
WORKER_SERVICES = frozenset(
    {
        "worker",
        "my-photos-worker",
        "email-worker",
        "email-ai-worker",
        "email-beat",
        "extraction-worker",
        "verification-worker",
        "visa-ai-worker",
        "ecr-worker",
    }
)
COLLECTED_SERVICES = WORKER_SERVICES | {"backend", "nginx"}
INTEGRATION_LOGGER_PREFIXES = (
    "app.infrastructure.ai.",
    "app.infrastructure.email.",
    "app.infrastructure.whatsapp.",
    "app.infrastructure.notifications.",
)
_DOCKER_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2}) "
)
_QUOTED = r'"(?:[^"\\\r\n]|\\.)*"'
_NGINX = re.compile(
    r"^\S+ - \S+ \[(?P<stamp>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\] "
    + _QUOTED
    + r' (?P<status>[1-5]\d{2}) \d+ "-" '
    + _QUOTED
    + " "
    + _QUOTED
    + r" request_id=(?P<request_id>[a-fA-F0-9]{32}) limit_req_status=[A-Z_-]* upstream_status=[0-9,: -]* request_time=(?P<duration>\d+(?:\.\d+)?)$"
)


def _proxy(line: str) -> dict[str, Any] | None:
    match = _NGINX.fullmatch(line)
    if match is None:
        return None
    try:
        stamp = datetime.strptime(match["stamp"], "%d/%b/%Y:%H:%M:%S %z")
        return project_diagnostic_record(
            {
                "event": "proxy_request",
                "request_id": match["request_id"],
                "status": int(match["status"]),
                "request_time": float(match["duration"]),
            },
            stamp,
        )
    except (ValueError, OverflowError):
        return None


def project_log_line(service: str, line: bytes) -> dict[str, dict[str, Any]]:
    """Return sanitized category projections only; unknown/malformed input is omitted."""
    if service not in COLLECTED_SERVICES:
        raise ValueError("Unsupported diagnostic collector service")
    if len(line) > MAX_INPUT_LINE_BYTES:
        return {}
    try:
        value = line.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError:
        return {}
    value = _DOCKER_TIMESTAMP.sub("", value, count=1)
    if service == "nginx":
        projected = _proxy(value)
        return {} if projected is None else {"proxy": projected}
    try:
        record = json.loads(value)
    except (ValueError, RecursionError):
        return {}
    if (
        not isinstance(record, dict)
        or (stamp := diagnostic_timestamp(record.get("timestamp"))) is None
    ):
        return {}
    projected = project_diagnostic_record(record, stamp)
    results = {"api" if service == "backend" else "worker": projected}
    if record.get("event") == "frontend_render_failure":
        results["frontend"] = {**projected, "content_trust": "untrusted_browser_signal"}
    logger = record.get("logger")
    if isinstance(logger, str) and logger.startswith(INTEGRATION_LOGGER_PREFIXES):
        results["integration"] = projected
    return results
