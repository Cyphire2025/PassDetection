"""Shared browser attendance-runtime cookie resolution boundary."""

from __future__ import annotations

import re
import uuid
from typing import Literal

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AttendanceRuntimeRegistrationModel
from app.infrastructure.repositories.attendance_runtime_repository import (
    AttendanceRuntimeError,
    AttendanceRuntimeRepository,
)
from app.presentation.security.auth_cookies import ATTENDANCE_RUNTIME_COOKIE_NAME

_COOKIE_VERSION = "v1"
_COOKIE_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def attendance_runtime_cookie_value(*, runtime_kind: str, secret: str) -> str:
    return f"{_COOKIE_VERSION}.{runtime_kind}.{secret}"


def parse_attendance_runtime_cookie(
    value: str | None,
) -> tuple[Literal["pwa", "webview"], str] | None:
    if not isinstance(value, str) or not value:
        return None
    version, separator, remainder = value.partition(".")
    runtime_kind, second_separator, secret = remainder.partition(".")
    if (
        version != _COOKIE_VERSION
        or not separator
        or not second_separator
        or runtime_kind not in {"pwa", "webview"}
        or _COOKIE_SECRET_PATTERN.fullmatch(secret) is None
    ):
        return None
    typed_kind: Literal["pwa", "webview"] = "pwa" if runtime_kind == "pwa" else "webview"
    return typed_kind, secret


async def resolve_browser_attendance_runtime(
    request: Request,
    *,
    session: AsyncSession,
    agency_id: uuid.UUID,
    coordinator_user_id: uuid.UUID,
    required: bool,
) -> AttendanceRuntimeRegistrationModel | None:
    request_cookies = getattr(request, "cookies", None)
    cookie_value = (
        request_cookies.get(ATTENDANCE_RUNTIME_COOKIE_NAME) if request_cookies is not None else None
    )
    parsed = parse_attendance_runtime_cookie(cookie_value)
    if parsed is None:
        if required:
            raise _registration_required()
        return None
    runtime_kind, secret = parsed
    try:
        return await AttendanceRuntimeRepository(session).resolve_browser_runtime(
            agency_id=agency_id,
            coordinator_user_id=coordinator_user_id,
            cookie_secret=secret,
            runtime_kind=runtime_kind,
            lock=required,
        )
    except AttendanceRuntimeError:
        if required:
            raise _registration_required() from None
        return None


def _registration_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_428_PRECONDITION_REQUIRED,
        detail={
            "code": "ATTENDANCE_RUNTIME_REGISTRATION_REQUIRED",
            "message": "Refresh offline readiness before synchronizing field evidence.",
        },
    )


__all__ = [
    "attendance_runtime_cookie_value",
    "parse_attendance_runtime_cookie",
    "resolve_browser_attendance_runtime",
]
