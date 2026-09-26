"""Bounded, untrusted browser failure signals without free-text or user content."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Literal, NamedTuple
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()
logger = get_logger(__name__)
MAX_REPORT_BYTES = 2048
MAX_REPORTS_PER_IP = 30
MAX_REPORTS_GLOBAL = 1000
REPORT_WINDOW_SECONDS = 60
REPORT_DEDUP_SECONDS = 300
ROUTES = frozenset(
    json.loads(
        (
            Path(__file__).resolve().parents[4] / "core/config/frontend_route_templates.json"
        ).read_text("utf-8")
    )
)

_ADMIT = """
local total = tonumber(redis.call('GET', KEYS[1]) or '0')
if total > 0 and redis.call('TTL', KEYS[1]) < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[3])
end
if total >= tonumber(ARGV[2]) then return {-1, ''} end
local count = redis.call('INCR', KEYS[2])
if count == 1 or redis.call('TTL', KEYS[2]) < 0 then
    redis.call('EXPIRE', KEYS[2], ARGV[3])
end
if count > tonumber(ARGV[1]) then return {-1, ''} end
local recorded_event = redis.call('GET', KEYS[3])
if recorded_event then return {0, recorded_event} end
total = redis.call('INCR', KEYS[1])
if total == 1 then redis.call('EXPIRE', KEYS[1], ARGV[3]) end
redis.call('SET', KEYS[3], ARGV[5], 'EX', ARGV[4])
return {1, ARGV[5]}
"""


class FrontendErrorReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    fingerprint: str = Field(pattern=r"^[a-f0-9]{32}$")
    release: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    route: str = Field(max_length=160)
    boundary: Literal["shared", "route", "global"]
    error_kind: Literal["Error", "TypeError", "RangeError", "Unknown"]
    request_id: UUID | None = None

    @field_validator("route")
    @classmethod
    def static_route_only(cls, value: str) -> str:
        if value not in ROUTES:
            raise ValueError("Use a declared static route template")
        return value


class FrontendErrorReceipt(BaseModel):
    event_id: UUID


class ReportAdmission(NamedTuple):
    status: int
    event_id: UUID | None


def _origin(value: str) -> tuple[str, str, int | None] | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            return None
        port = parsed.port
        if port == (443 if parsed.scheme == "https" else 80):
            port = None
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        return None


async def _admit(request: Request, report: FrontendErrorReport) -> ReportAdmission:
    settings = get_settings()
    peer = trusted_client_ip(request, settings=settings) or "unknown"
    peer_hash = hmac.new(
        settings.app_secret_key.encode(), peer.encode(), hashlib.sha256
    ).hexdigest()
    identity = f"{peer_hash}:{report.release}:{report.route}:{report.boundary}:{report.error_kind}:{report.fingerprint}"
    dedup = hashlib.sha256(identity.encode()).hexdigest()
    try:
        async with Redis.from_url(
            settings.redis.security_url,
            decode_responses=True,
            socket_timeout=1,
            socket_connect_timeout=1,
        ) as redis:
            result = await redis.eval(
                _ADMIT,
                3,
                "{frontend-errors}:global",
                f"{{frontend-errors}}:ip:{peer_hash}",
                f"{{frontend-errors}}:event:{dedup}",
                MAX_REPORTS_PER_IP,
                MAX_REPORTS_GLOBAL,
                REPORT_WINDOW_SECONDS,
                REPORT_DEDUP_SECONDS,
                str(report.event_id),
            )
            if not isinstance(result, list) or len(result) != 2:
                raise ValueError("Invalid admission result")
            admission = int(result[0])
            if admission not in {-1, 0, 1}:
                raise ValueError("Invalid admission status")
            return ReportAdmission(admission, UUID(result[1]) if admission >= 0 else None)
    except (RedisError, ValueError, TypeError):
        # No unbounded in-process fallback and no raw exception/connection URL.
        raise HTTPException(
            503, "Browser diagnostics are temporarily unavailable", headers={"Retry-After": "60"}
        ) from None


@router.post(
    "/frontend-errors",
    status_code=202,
    response_model=FrontendErrorReceipt,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": FrontendErrorReport.model_json_schema()}},
        }
    },
)
async def report_frontend_error(request: Request) -> FrontendErrorReceipt:
    settings = get_settings()
    supplied = _origin(request.headers.get("origin", ""))
    allowed = {_origin(value) for value in settings.allowed_origins} - {None}
    if supplied is None or supplied not in allowed:
        raise HTTPException(403, "Trusted Origin required for browser diagnostics")
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(415, "Browser diagnostics require application/json")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_REPORT_BYTES:
            raise HTTPException(413, "Browser diagnostic exceeds the size limit")
        body.extend(chunk)
    try:
        report = FrontendErrorReport.model_validate_json(body)
    except ValidationError:
        # Do not reflect invalid free-text payloads, even inside validation errors.
        raise HTTPException(422, "Invalid browser diagnostic metadata") from None
    admission = await _admit(request, report)
    if admission.status < 0:
        raise HTTPException(
            429, "Browser diagnostic rate limit exceeded", headers={"Retry-After": "60"}
        )
    if admission.status > 0:
        logger.warning(
            "frontend_render_failure",
            source="untrusted_browser",
            **report.model_dump(mode="json", exclude_none=True),
        )
    if admission.event_id is None:
        raise HTTPException(503, "Browser diagnostics are temporarily unavailable")
    return FrontendErrorReceipt(event_id=admission.event_id)
