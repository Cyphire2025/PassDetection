"""Redis-backed API rate limits with separate public-upload safety guards."""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Protocol, cast

from fastapi import status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config.settings import Settings, get_settings
from app.core.logging.logger import get_logger
from app.core.security.jwt import decode_access_token
from app.core.security.upload_session import is_valid_upload_session_id
from app.domain.exceptions.exceptions import AuthenticationError
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)
from app.presentation.security.client_ip import trusted_client_ip

logger = get_logger(__name__)

_PUBLIC_UPLOAD_PATH_RE = re.compile(
    r"^/api/v1/passports/upload/[^/]+(?:/([^/]+)(?:/.*)?)?/?$"
)
_PUBLIC_CLIENT_SUBMIT_PATH_RE = re.compile(
    r"^/api/v1/passports/([^/]+)/client-submit/?$"
)
_PUBLIC_UPLOAD_BOOTSTRAP_PATH_RE = re.compile(
    r"^/api/v1/upload-links/token/[^/]+"
    r"(?:/(?:qualifier-selection|telemetry))?/?$"
)
_DASHBOARD_MEDIA_PATH_RE = re.compile(
    r"^/api/v1/passports/[^/]+/images/"
    r"(?:visa_photo|passport_front|passport_back)(?:/(?:original|thumbnail))?/?$"
)
_RATE_LIMIT_METRIC_REASONS = {
    "APP_RATE_LIMITED": "app_api",
    "DASHBOARD_RATE_LIMITED": "dashboard_user",
    "DASHBOARD_MEDIA_RATE_LIMITED": "dashboard_media",
    "UPLOAD_BOOTSTRAP_SESSION_RATE_LIMITED": "upload_bootstrap_session",
    "UPLOAD_BOOTSTRAP_AGGREGATE_RATE_LIMITED": "upload_bootstrap_aggregate",
    "UPLOAD_SESSION_RATE_LIMITED": "upload_session",
    "UPLOAD_AGGREGATE_RATE_LIMITED": "upload_aggregate",
    "RATE_LIMIT_SERVICE_UNAVAILABLE": "rate_limit_backend_unavailable",
}

_TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local refill_per_second = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local ttl_ms = tonumber(ARGV[3])

local redis_time = redis.call('TIME')
local now_ms = (tonumber(redis_time[1]) * 1000) + math.floor(tonumber(redis_time[2]) / 1000)
local state = redis.call('HMGET', key, 'tokens', 'updated_ms')
local tokens = tonumber(state[1])
local updated_ms = tonumber(state[2])

if tokens == nil or updated_ms == nil then
    tokens = capacity
    updated_ms = now_ms
else
    local elapsed_ms = math.max(0, now_ms - updated_ms)
    tokens = math.min(capacity, tokens + ((elapsed_ms / 1000) * refill_per_second))
end

local allowed = 0
local retry_ms = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
else
    retry_ms = math.ceil(((1 - tokens) / refill_per_second) * 1000)
end

redis.call('HSET', key, 'tokens', tostring(tokens), 'updated_ms', tostring(now_ms))
redis.call('PEXPIRE', key, ttl_ms)
return {allowed, math.floor(tokens), retry_ms}
"""


@dataclass(frozen=True, slots=True)
class _RateLimitGuard:
    scope: str
    identifier: str
    limit: int
    error_code: str
    error_message: str
    burst_rate_per_second: int = 0
    burst_capacity: int = 0


class _RateLimitBackendUnavailable(RuntimeError):
    """Raised when a distributed public-upload counter cannot be enforced."""


class _AsyncRateLimitRedis(Protocol):
    def incr(self, key: str) -> Awaitable[int]: ...

    def expire(self, key: str, seconds: int) -> Awaitable[object]: ...

    def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: str,
    ) -> Awaitable[object]: ...


class RateLimitMiddleware(BaseHTTPMiddleware):
    _local_counts: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    _local_token_buckets: dict[str, tuple[float, float]] = {}

    def __init__(
        self,
        app: ASGIApp,
        *,
        window_seconds: int = 60,
        settings: Settings | None = None,
        redis_client: _AsyncRateLimitRedis | None = None,
        initialize_redis: bool = True,
    ) -> None:
        super().__init__(app)
        self._settings = settings or get_settings()
        self._window_seconds = window_seconds
        self._key_secret = self._settings.app_secret_key.encode("utf-8")
        self._redis: _AsyncRateLimitRedis | None = redis_client
        if initialize_redis and self._redis is None and self._has_enabled_policy():
            try:
                self._redis = cast(
                    _AsyncRateLimitRedis,
                    Redis.from_url(
                        self._settings.redis.security_url,
                        encoding="utf-8",
                        decode_responses=True,
                    ),
                )
            except Exception as exc:
                logger.warning(
                    "rate_limit_redis_init_failed",
                    error_type=type(exc).__name__,
                )

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if (
            request.method.upper() == "OPTIONS"
            or request.url.path.startswith("/api/v1/health")
        ):
            return await call_next(request)

        guards, requires_distributed, policy_error = self._guards_for(request)
        if policy_error is not None:
            policy_error_messages = {
                "UPLOAD_SESSION_ID_REQUIRED": (
                    "This upload request is missing its upload session identifier. "
                    "Refresh the upload page and try again."
                ),
                "UPLOAD_SESSION_ID_INVALID": (
                    "This upload request has an invalid upload session identifier. "
                    "Refresh the upload page and try again."
                ),
                "UPLOAD_SESSION_ID_MISMATCH": (
                    "The upload session identifier does not match this submission."
                ),
            }
            return self._error_response(
                request,
                status_code=status.HTTP_400_BAD_REQUEST,
                code=policy_error,
                message=policy_error_messages[policy_error],
            )
        if not guards:
            return await call_next(request)

        now = time.time()
        bucket = int(now // self._window_seconds)
        retry_after = max(1, self._window_seconds - int(now % self._window_seconds))
        results: list[tuple[_RateLimitGuard, int]] = []
        burst_results: list[tuple[_RateLimitGuard, int]] = []
        try:
            for guard in guards:
                if guard.limit > 0:
                    key = self._counter_key(
                        scope=guard.scope,
                        identifier=guard.identifier,
                        bucket=bucket,
                    )
                    count = await self._increment(
                        key,
                        require_distributed=requires_distributed,
                    )
                    results.append((guard, count))
                    if count > guard.limit:
                        return self._error_response(
                            request,
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            code=guard.error_code,
                            message=guard.error_message,
                            retry_after=retry_after,
                            limit=guard.limit,
                        )

                if guard.burst_rate_per_second > 0 and guard.burst_capacity > 0:
                    burst_key = self._token_bucket_key(
                        scope=f"{guard.scope}-burst",
                        identifier=guard.identifier,
                    )
                    allowed, remaining, burst_retry_ms = await self._consume_token_bucket(
                        burst_key,
                        refill_per_second=guard.burst_rate_per_second,
                        capacity=guard.burst_capacity,
                        require_distributed=requires_distributed,
                    )
                    burst_results.append((guard, remaining))
                    if not allowed:
                        return self._error_response(
                            request,
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            code=guard.error_code,
                            message=guard.error_message,
                            retry_after=max(1, math.ceil(burst_retry_ms / 1000)),
                            limit=guard.burst_capacity,
                        )
        except _RateLimitBackendUnavailable:
            return self._error_response(
                request,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="RATE_LIMIT_SERVICE_UNAVAILABLE",
                message="Request protection is temporarily unavailable. Please try again shortly.",
                retry_after=5,
            )

        response = await call_next(request)
        if results:
            tightest_guard, tightest_count = min(
                results,
                key=lambda item: item[0].limit - item[1],
            )
            response.headers["X-RateLimit-Limit"] = str(tightest_guard.limit)
            response.headers["X-RateLimit-Remaining"] = str(
                max(0, tightest_guard.limit - tightest_count)
            )
            response.headers["X-RateLimit-Policy"] = tightest_guard.scope
        elif burst_results:
            tightest_guard, remaining = min(burst_results, key=lambda item: item[1])
            response.headers["X-RateLimit-Limit"] = str(tightest_guard.burst_capacity)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Policy"] = tightest_guard.scope
        if burst_results:
            burst_guard, burst_remaining = min(burst_results, key=lambda item: item[1])
            response.headers["X-RateLimit-Burst-Capacity"] = str(
                burst_guard.burst_capacity
            )
            response.headers["X-RateLimit-Burst-Remaining"] = str(burst_remaining)
        return response

    def _has_enabled_policy(self) -> bool:
        return any(
            limit > 0
            for limit in (
                self._settings.rate_limit_per_minute,
                self._settings.dashboard_rate_limit_per_minute,
                self._settings.dashboard_rate_limit_per_second,
                self._settings.dashboard_media_rate_limit_per_minute,
                self._settings.dashboard_media_rate_limit_per_second,
                self._settings.public_upload_bootstrap_session_rate_limit_per_minute,
                self._settings.public_upload_bootstrap_aggregate_rate_limit_per_minute,
                self._settings.public_upload_session_rate_limit_per_minute,
                self._settings.public_upload_aggregate_rate_limit_per_minute,
                self._settings.public_upload_followup_session_rate_limit_per_minute,
                self._settings.public_upload_followup_aggregate_rate_limit_per_minute,
            )
        )

    def _guards_for(
        self,
        request: Request,
    ) -> tuple[tuple[_RateLimitGuard, ...], bool, str | None]:
        client_ip = self._trusted_client_ip(request)
        is_upload_bootstrap = bool(
            _PUBLIC_UPLOAD_BOOTSTRAP_PATH_RE.match(request.url.path)
            and request.method.upper() in {"GET", "POST"}
        )
        upload_match = _PUBLIC_UPLOAD_PATH_RE.match(request.url.path)
        client_submit_match = _PUBLIC_CLIENT_SUBMIT_PATH_RE.match(request.url.path)
        submission_id = (
            upload_match.group(1)
            if upload_match
            else client_submit_match.group(1)
            if client_submit_match
            else None
        )
        is_initial_upload = bool(
            upload_match
            and submission_id is None
            and request.method.upper() in {"POST", "PUT"}
        )
        is_upload_followup = bool(upload_match and submission_id is not None)
        is_client_submit = bool(
            client_submit_match and request.method.upper() == "POST"
        )

        if is_upload_bootstrap:
            session_id, session_error = self._upload_session_id(
                request,
                submission_id=None,
                require_header=True,
            )
            if session_error is not None:
                return (), True, session_error
            if session_id is None:
                return (), True, "UPLOAD_SESSION_ID_REQUIRED"
            guards = (
                _RateLimitGuard(
                    scope="public-upload-bootstrap-session",
                    identifier=session_id,
                    limit=(
                        self._settings
                        .public_upload_bootstrap_session_rate_limit_per_minute
                    ),
                    error_code="UPLOAD_BOOTSTRAP_SESSION_RATE_LIMITED",
                    error_message=(
                        "This upload page is sending setup requests too quickly. "
                        "Please wait briefly and try again."
                    ),
                ),
                _RateLimitGuard(
                    scope="public-upload-bootstrap-aggregate",
                    identifier=client_ip,
                    limit=(
                        self._settings
                        .public_upload_bootstrap_aggregate_rate_limit_per_minute
                    ),
                    error_code="UPLOAD_BOOTSTRAP_AGGREGATE_RATE_LIMITED",
                    error_message=(
                        "Too many upload pages are being opened from this network. "
                        "Please wait briefly and try again."
                    ),
                ),
            )
            return (
                tuple(guard for guard in guards if guard.limit > 0),
                self._settings.public_upload_rate_limit_require_redis,
                None,
            )

        if is_initial_upload or is_upload_followup or is_client_submit:
            session_id, session_error = self._upload_session_id(
                request,
                submission_id=submission_id,
                require_header=is_upload_followup or is_client_submit,
            )
            if session_error is not None:
                return (), True, session_error
            if session_id is None:
                return (), True, "UPLOAD_SESSION_ID_REQUIRED"

            if is_initial_upload:
                session_limit = self._settings.public_upload_session_rate_limit_per_minute
                aggregate_limit = (
                    self._settings.public_upload_aggregate_rate_limit_per_minute
                )
                session_scope = "public-upload-session"
                aggregate_scope = "public-upload-aggregate"
            else:
                session_limit = (
                    self._settings.public_upload_followup_session_rate_limit_per_minute
                )
                aggregate_limit = (
                    self._settings.public_upload_followup_aggregate_rate_limit_per_minute
                )
                session_scope = "public-upload-followup-session"
                aggregate_scope = "public-upload-followup-aggregate"

            guards = (
                _RateLimitGuard(
                    scope=session_scope,
                    identifier=session_id,
                    limit=session_limit,
                    error_code="UPLOAD_SESSION_RATE_LIMITED",
                    error_message=(
                        "This upload session is sending requests too quickly. "
                        "Please wait briefly and try again."
                    ),
                ),
                _RateLimitGuard(
                    scope=aggregate_scope,
                    identifier=client_ip,
                    limit=aggregate_limit,
                    error_code="UPLOAD_AGGREGATE_RATE_LIMITED",
                    error_message=(
                        "Too many upload requests are arriving from this network. "
                        "Please wait briefly and try again."
                    ),
                ),
            )
            return (
                tuple(guard for guard in guards if guard.limit > 0),
                self._settings.public_upload_rate_limit_require_redis,
                None,
            )

        authenticated_user_id = self._authenticated_user_id(request)
        if authenticated_user_id is not None:
            is_dashboard_media = bool(
                request.method.upper() == "GET"
                and _DASHBOARD_MEDIA_PATH_RE.match(request.url.path)
            )
            if is_dashboard_media:
                media_limit = self._settings.dashboard_media_rate_limit_per_minute
                media_burst_rate = self._settings.dashboard_media_rate_limit_per_second
                media_burst = self._settings.dashboard_media_rate_limit_burst
                if media_limit <= 0 and (media_burst_rate <= 0 or media_burst <= 0):
                    return (), False, None
                return (
                    (
                        _RateLimitGuard(
                            scope="dashboard-media",
                            identifier=authenticated_user_id,
                            limit=media_limit,
                            error_code="DASHBOARD_MEDIA_RATE_LIMITED",
                            error_message=(
                                "Too many document previews were requested. "
                                "Please wait briefly and try again."
                            ),
                            burst_rate_per_second=media_burst_rate,
                            burst_capacity=media_burst,
                        ),
                    ),
                    self._settings.dashboard_rate_limit_require_redis,
                    None,
                )

            dashboard_limit = self._settings.dashboard_rate_limit_per_minute
            dashboard_burst_rate = self._settings.dashboard_rate_limit_per_second
            dashboard_burst = self._settings.dashboard_rate_limit_burst
            if dashboard_limit <= 0 and (
                dashboard_burst_rate <= 0 or dashboard_burst <= 0
            ):
                return (), False, None
            return (
                (
                    _RateLimitGuard(
                        scope="dashboard-user",
                        identifier=authenticated_user_id,
                        limit=dashboard_limit,
                        error_code="DASHBOARD_RATE_LIMITED",
                        error_message=(
                            "This dashboard account is sending requests too quickly. "
                            "Please wait briefly and try again."
                        ),
                        burst_rate_per_second=dashboard_burst_rate,
                        burst_capacity=dashboard_burst,
                    ),
                ),
                self._settings.dashboard_rate_limit_require_redis,
                None,
            )

        base_limit = self._settings.rate_limit_per_minute
        if base_limit <= 0:
            return (), False, None
        return (
            (
                _RateLimitGuard(
                    scope="api",
                    identifier=client_ip,
                    limit=base_limit,
                    error_code="APP_RATE_LIMITED",
                    error_message="Rate limit exceeded. Please try again later.",
                ),
            ),
            False,
            None,
        )

    def _authenticated_user_id(self, request: Request) -> str | None:
        authorization = request.headers.get("authorization", "").strip()
        token = ""
        if authorization:
            scheme, separator, credentials = authorization.partition(" ")
            if separator and scheme.lower() == "bearer":
                token = credentials.strip()
        if not token:
            token = request.cookies.get(
                self._settings.jwt.access_cookie_name,
                "",
            ).strip()
        if not token:
            return None
        try:
            payload = decode_access_token(token)
            return str(uuid.UUID(str(payload["sub"])))
        except (AuthenticationError, KeyError, TypeError, ValueError):
            # The route's normal authentication dependency owns the response.
            # An invalid or expired token never receives a trusted user bucket.
            return None

    @staticmethod
    def _trusted_client_ip(request: Request) -> str:
        return trusted_client_ip(request) or "unknown"

    @staticmethod
    def _upload_session_id(
        request: Request,
        *,
        submission_id: str | None,
        require_header: bool = False,
    ) -> tuple[str | None, str | None]:
        header_value = request.headers.get("x-upload-session-id", "").strip()
        if header_value and not is_valid_upload_session_id(header_value):
            return None, "UPLOAD_SESSION_ID_INVALID"
        if submission_id is not None:
            if not is_valid_upload_session_id(submission_id):
                return None, "UPLOAD_SESSION_ID_INVALID"
            if require_header and not header_value:
                return None, "UPLOAD_SESSION_ID_REQUIRED"
            # The path UUID is public routing data, not an ownership proof.
            # A separate high-entropy upload credential is used as the limiter
            # identity here and is validated against the submission in the
            # route before any data is returned or mutated.
            return (header_value or None), None
        return (header_value or None), None

    def _counter_key(self, *, scope: str, identifier: str, bucket: int) -> str:
        digest = hmac.new(
            self._key_secret,
            f"{scope}\0{identifier}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"rate-limit:v2:{scope}:{digest}:{bucket}"

    def _token_bucket_key(self, *, scope: str, identifier: str) -> str:
        digest = hmac.new(
            self._key_secret,
            f"{scope}\0{identifier}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"rate-limit:v3:{scope}:{digest}"

    async def _increment(self, key: str, *, require_distributed: bool) -> int:
        if self._redis is not None:
            try:
                count = await self._redis.incr(key)
                # Refreshing this fixed-bucket key's short TTL also heals the
                # narrow case where a prior INCR succeeded but EXPIRE failed.
                await self._redis.expire(key, self._window_seconds + 1)
                return int(count)
            except Exception as exc:
                logger.warning(
                    "rate_limit_redis_counter_failed",
                    error_type=type(exc).__name__,
                )

        if require_distributed:
            raise _RateLimitBackendUnavailable
        count, expires_at = self._local_counts[key]
        now = time.time()
        if now > expires_at:
            count = 0
            expires_at = now + self._window_seconds
        count += 1
        self._local_counts[key] = (count, expires_at)
        return count

    async def _consume_token_bucket(
        self,
        key: str,
        *,
        refill_per_second: int,
        capacity: int,
        require_distributed: bool,
    ) -> tuple[bool, int, int]:
        ttl_ms = max(60_000, math.ceil((capacity / refill_per_second) * 2_000))
        if self._redis is not None:
            try:
                result = await self._redis.eval(
                    _TOKEN_BUCKET_SCRIPT,
                    1,
                    key,
                    str(refill_per_second),
                    str(capacity),
                    str(ttl_ms),
                )
                if not isinstance(result, (list, tuple)) or len(result) != 3:
                    raise ValueError("unexpected token bucket response")
                return (
                    bool(int(result[0])),
                    max(0, int(result[1])),
                    max(0, int(result[2])),
                )
            except Exception as exc:
                logger.warning(
                    "rate_limit_redis_token_bucket_failed",
                    error_type=type(exc).__name__,
                )

        if require_distributed:
            raise _RateLimitBackendUnavailable

        now = time.monotonic()
        tokens, updated_at = self._local_token_buckets.get(
            key,
            (float(capacity), now),
        )
        tokens = min(
            float(capacity),
            tokens + (max(0.0, now - updated_at) * refill_per_second),
        )
        if tokens >= 1:
            tokens -= 1
            allowed = True
            retry_ms = 0
        else:
            allowed = False
            retry_ms = math.ceil(((1 - tokens) / refill_per_second) * 1000)
        self._local_token_buckets[key] = (tokens, now)
        return allowed, max(0, math.floor(tokens)), retry_ms

    def _error_response(
        self,
        request: Request,
        *,
        status_code: int,
        code: str,
        message: str,
        retry_after: int | None = None,
        limit: int | None = None,
    ) -> JSONResponse:
        headers = {
            "Cache-Control": "no-store",
        }
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        if limit is not None:
            headers["X-RateLimit-Limit"] = str(limit)
            headers["X-RateLimit-Remaining"] = "0"
        origin = request.headers.get("origin", "")
        if origin and origin in self._settings.allowed_origins:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "true"
            headers["Vary"] = "Origin"
        metric_reason = _RATE_LIMIT_METRIC_REASONS.get(code)
        if metric_reason is not None:
            record_operational_event(
                OperationalEvent.RATE_LIMIT,
                metric_reason,
            )
        return JSONResponse(
            status_code=status_code,
            content={"error": {"code": code, "message": message}},
            headers=headers,
        )
