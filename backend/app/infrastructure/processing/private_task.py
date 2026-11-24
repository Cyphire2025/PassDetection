"""Keep task payloads intact while excluding them from diagnostic representations."""

from __future__ import annotations

from typing import Any

from celery import Task

from app.core.logging.task_diagnostics import PRIVATE_ARGUMENTS


class PrivateTask(Task):  # type: ignore[misc]  # Celery's extension base is untyped.
    Request = "app.infrastructure.processing.private_task_request:PrivateTaskRequest"

    def apply_async(
        self,
        args: Any = None,
        kwargs: Any = None,
        task_id: Any = None,
        producer: Any = None,
        link: Any = None,
        link_error: Any = None,
        shadow: Any = None,
        **options: Any,
    ) -> Any:
        options.update(argsrepr=PRIVATE_ARGUMENTS, kwargsrepr=PRIVATE_ARGUMENTS)
        return super().apply_async(
            args=args,
            kwargs=kwargs,
            task_id=task_id,
            producer=producer,
            link=link,
            link_error=link_error,
            shadow=shadow,
            **options,
        )

    def signature_from_request(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.update(argsrepr=PRIVATE_ARGUMENTS, kwargsrepr=PRIVATE_ARGUMENTS)
        return super().signature_from_request(*args, **kwargs)

    def before_start(self, task_id: str, args: Any, kwargs: Any) -> None:
        # Also covers eager execution and old queued messages lacking headers.
        self.request.argsrepr = PRIVATE_ARGUMENTS
        self.request.kwargsrepr = PRIVATE_ARGUMENTS
        super().before_start(task_id, args, kwargs)
