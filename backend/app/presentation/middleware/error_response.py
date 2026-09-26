"""The common v1 error envelope, including compatible legacy HTTP detail."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel

HTTP_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_ERROR",
    403: "AUTHORIZATION_ERROR",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    408: "REQUEST_TIMEOUT",
    409: "CONFLICT",
    410: "GONE",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "REQUEST_VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
    500: "INTERNAL_SERVER_ERROR",
    502: "BAD_GATEWAY",
    503: "DEPENDENCY_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | list[dict[str, Any]] | None = None


class ApiErrorResponse(BaseModel):
    error: ApiError
    # Legacy HTTPException clients keep this field during the v1 compatibility window.
    detail: Any = None


def error_response(
    code: str,
    message: str,
    status_code: int,
    *,
    headers: Mapping[str, str] | None = None,
    detail: object = None,
    details: object = None,
) -> JSONResponse:
    if status_code == 500:
        message = "An unexpected error occurred. Please try again."
        detail, details = (message if detail is not None else None), None
    error: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    content: dict[str, object] = {"error": error}
    if detail is not None:
        content["detail"] = detail
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers={"Cache-Control": "no-store", **dict(headers or {})},
    )
