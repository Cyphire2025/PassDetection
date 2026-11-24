"""Protect diagnostic representations before received/early-failure worker events."""

from __future__ import annotations

from typing import Any

from billiard.einfo import ExceptionWithTraceback
from celery.exceptions import Retry
from celery.worker.request import Request

from app.core.logging.task_diagnostics import PRIVATE_ARGUMENTS, task_failure_diagnostic


class PrivateTaskRequest(Request):  # type: ignore[misc]  # Celery's extension base is untyped.
    def __init__(self, message: Any, *args: Any, **kwargs: Any) -> None:
        # Request consumes the body separately: never replace actual task args.
        supplied_headers = kwargs.get("headers")
        headers = dict(message.headers if supplied_headers is None else supplied_headers)
        headers.update(argsrepr=PRIVATE_ARGUMENTS, kwargsrepr=PRIVATE_ARGUMENTS)
        kwargs["headers"] = headers
        super().__init__(message, *args, **kwargs)
        self._private_failure = task_failure_diagnostic(None)

    def _capture_failure(self, exc_info: Any) -> None:
        error = exc_info.exception
        # Billiard wraps child-process failures; use only the actual exception
        # for frame projection, never its textual traceback representation.
        if isinstance(error, ExceptionWithTraceback):
            error = error.exc
        if isinstance(error, Retry):
            error = error.exc
        self._private_failure = task_failure_diagnostic(
            error if isinstance(error, BaseException) else None,
        )

    def on_failure(self, exc_info: Any, *args: Any, **kwargs: Any) -> Any:
        self._capture_failure(exc_info)
        return super().on_failure(exc_info, *args, **kwargs)

    def on_retry(self, exc_info: Any) -> Any:
        self._capture_failure(exc_info)
        return super().on_retry(exc_info)

    def send_event(self, type: str, **fields: Any) -> Any:
        if "exception" in fields:
            fields["exception"] = self._private_failure.message
        if "traceback" in fields:
            fields["traceback"] = self._private_failure.traceback
        if "result" in fields:
            fields["result"] = "<private task result>"
        return super().send_event(type, **fields)
