"""Project automatic Celery records before any output handler sees private values."""

from __future__ import annotations

import logging
import math
import uuid
from collections.abc import Mapping
from typing import Any

from app.core.logging.task_diagnostics import (
    PRIVATE_ARGUMENTS,
    diagnostic_name,
    task_failure_diagnostic,
)

CELERY_TASK_LOGGERS = (
    "celery.app.trace",
    "celery.worker.request",
    "celery.worker.strategy",
    "celery.worker.consumer.consumer",
)


def _event(record: logging.LogRecord, template: str, raw_message_report: bool) -> str:
    if raw_message_report:
        return "task_message_rejected"
    if record.levelno >= logging.ERROR:
        return "task_failed"
    for keyword in ("received", "succeeded", "retry", "rejected", "ignored"):
        if keyword in template.lower():
            return f"task_{keyword}"
    return "task_diagnostic"


def _task_id(value: object) -> str:
    try:
        return str(uuid.UUID(value)) if isinstance(value, str) else "unknown"
    except ValueError:
        return "unknown"


def _project_context(
    record: logging.LogRecord,
    context: Mapping[str, Any],
    event: str,
) -> dict[str, object]:
    error = record.exc_info[1] if record.exc_info else None
    diagnostic = task_failure_diagnostic(error)
    message = (
        diagnostic.message
        if error is not None
        else {
            "task_received": "Task received; private arguments omitted",
            "task_succeeded": "Task completed; private result omitted",
            "task_retry": "Task retry requested; private details omitted",
            "task_message_rejected": "Task message rejected; private body omitted",
        }.get(event, "Private task diagnostic details withheld")
    )
    safe: dict[str, object] = {
        "id": _task_id(context.get("id")),
        "name": diagnostic_name(context.get("name")),
        "event": event,
        "diagnostic": message,
        "error_type": diagnostic.exception_type if error is not None else None,
        "diagnostic_code": diagnostic.code,
        "traceback": diagnostic.traceback,
        "args": PRIVATE_ARGUMENTS,
        "kwargs": PRIVATE_ARGUMENTS,
    }
    duration = context.get("runtime")
    if (
        isinstance(duration, (float, int))
        and not isinstance(duration, bool)
        and math.isfinite(duration)
        and 0 <= duration <= 86400
    ):
        safe["duration_seconds"] = duration
    return safe


class CeleryTaskDiagnosticFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "private_diagnostic_projected", False):
            return True
        if not record.name.startswith(CELERY_TASK_LOGGERS):
            return True
        context = record.args if isinstance(record.args, Mapping) else {}
        extra = getattr(record, "data", None)
        if not context and isinstance(extra, Mapping):
            context = extra
        template = record.msg if isinstance(record.msg, str) else ""
        # Celery's unknown-message path runs before Request construction and
        # includes the raw body without exc_info or structured task context.
        raw_message_report = (
            record.name == "celery.worker.consumer.consumer" and "message body" in template.lower()
        )
        sensitive_context = {"args", "kwargs", "exc", "exception", "traceback", "return_value"}
        if (
            not record.exc_info
            and not sensitive_context.intersection(context)
            and not raw_message_report
        ):
            return True
        safe = _project_context(record, context, _event(record, template, raw_message_report))
        record.msg = "Celery task %(name)s[%(id)s] %(event)s: %(diagnostic)s"
        record.args = safe
        record.data = safe
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record.private_diagnostic_projected = True
        return True


def install_celery_diagnostic_filters() -> None:
    for name in CELERY_TASK_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(item, CeleryTaskDiagnosticFilter) for item in logger.filters):
            logger.addFilter(CeleryTaskDiagnosticFilter())
