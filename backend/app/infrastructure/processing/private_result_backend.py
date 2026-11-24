"""Project exception diagnostics before Celery serializes or persists results."""

from __future__ import annotations

from typing import Any

from celery.backends.redis import RedisBackend

from app.core.logging.task_diagnostics import task_failure_diagnostic


class PrivateResultBackendMixin:
    def store_result(
        self,
        task_id: str,
        result: Any,
        state: str,
        traceback: str | None = None,
        request: Any = None,
        **kwargs: Any,
    ) -> Any:
        if state in {"FAILURE", "RETRY", "REVOKED"}:
            error = result if isinstance(result, BaseException) else None
            diagnostic = task_failure_diagnostic(error)
            result = diagnostic.exception_payload()
            traceback = diagnostic.traceback
        return super().store_result(  # type: ignore[misc]
            task_id,
            result,
            state,
            traceback=traceback,
            request=request,
            **kwargs,
        )


class PrivateRedisBackend(PrivateResultBackendMixin, RedisBackend):  # type: ignore[misc]
    """The existing Redis backend, with unchanged connection and state semantics."""
