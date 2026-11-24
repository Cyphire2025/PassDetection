"""Project ASGI exception records before server handlers can render private text."""

from __future__ import annotations

import logging
import uuid

from app.core.logging.exception_diagnostics import diagnostic_frames, diagnostic_name


def _request_id(value: object) -> str | None:
    try:
        return str(uuid.UUID(value)) if isinstance(value, str) else None
    except ValueError:
        return None


def _context_request_id() -> str | None:
    try:
        from structlog.contextvars import get_contextvars
    except ModuleNotFoundError:
        return None
    return _request_id(get_contextvars().get("request_id"))


class ServerExceptionDiagnosticFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "private_server_exception_projected", False):
            return True
        if not record.exc_info and not record.exc_text:
            return True
        error = record.exc_info[1] if record.exc_info else None
        trace = record.exc_info[2] if record.exc_info else None
        request_id = _request_id(getattr(record, "request_id", None)) or _context_request_id()
        safe = {
            "error_type": diagnostic_name(type(error).__qualname__, "Exception")
            if error is not None
            else "Exception",
            "error_module": diagnostic_name(type(error).__module__, "builtins")
            if error is not None
            else "builtins",
            "request_id": request_id or "unknown",
            "traceback": diagnostic_frames(trace),
        }
        record.msg = (
            "ASGI application failure: %(error_module)s.%(error_type)s; "
            "request_id=%(request_id)s; frames=%(traceback)s"
        )
        record.args = safe
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        # Some handlers/factories cache message before their own formatting.
        record.message = record.getMessage()
        record.private_server_exception_projected = True
        return True


def install_server_diagnostic_filter() -> None:
    # A logger-level filter runs once before every attached/inherited handler.
    # UvicornWorker replaces handlers with Gunicorn's but retains this logger.
    logger = logging.getLogger("uvicorn.error")
    if not any(isinstance(item, ServerExceptionDiagnosticFilter) for item in logger.filters):
        logger.addFilter(ServerExceptionDiagnosticFilter())
