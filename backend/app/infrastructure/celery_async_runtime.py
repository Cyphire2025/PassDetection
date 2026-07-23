"""Process-local async runtime for synchronous Celery task entry points.

Celery's prefork workers execute regular synchronous task functions.  The
application work behind those functions is asynchronous and shares a
SQLAlchemy async engine within each worker child.  Recreating an event loop for
every task (for example with ``asyncio.run``) leaves pooled asyncpg connections
bound to a closed loop.

This runtime owns one ``asyncio.Runner`` per operating-system process, so every
task handled by the same Celery child uses the same event loop.  The singleton
is safe to import before Celery forks because it creates or replaces the runner
only after checking the current PID.
"""

from __future__ import annotations

import asyncio
import atexit
import contextvars
import os
import sys
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from app.core.logging.logger import get_logger

logger = get_logger(__name__)

_Result = TypeVar("_Result")
_AsyncCleanup = Callable[[], Coroutine[Any, Any, None]]


async def _dispose_database_engine_if_loaded() -> None:
    """Dispose loop-bound connections without importing an unused engine."""

    session_module = sys.modules.get("app.infrastructure.database.session")
    if session_module is None:
        return
    engine = getattr(session_module, "engine", None)
    if engine is not None:
        await engine.dispose()


class CeleryAsyncRuntime:
    """Run async task bodies on one event loop per Celery worker child."""

    def __init__(
        self,
        *,
        pid_provider: Callable[[], int] = os.getpid,
        runner_factory: Callable[[], asyncio.Runner] = asyncio.Runner,
        cleanup: _AsyncCleanup = _dispose_database_engine_if_loaded,
    ) -> None:
        self._pid_provider = pid_provider
        self._runner_factory = runner_factory
        self._cleanup = cleanup
        self._owner_pid: int | None = None
        self._runner: asyncio.Runner | None = None
        self._lock = threading.RLock()

    def initialize(self) -> None:
        """Create the loop after Celery forks the worker child."""

        with self._lock:
            self._runner_for_current_process()

    def run(self, coroutine: Coroutine[Any, Any, _Result]) -> _Result:
        """Run one task body while preserving task-local context variables."""

        with self._lock:
            runner = self._runner_for_current_process()
            return runner.run(
                coroutine,
                context=contextvars.copy_context(),
            )

    def shutdown(self) -> None:
        """Dispose async DB connections on their owning loop, then close it."""

        with self._lock:
            current_pid = self._pid_provider()
            runner = self._runner
            if runner is None or self._owner_pid != current_pid:
                self._runner = None
                self._owner_pid = None
                return

            try:
                runner.run(
                    self._cleanup(),
                    context=contextvars.copy_context(),
                )
            except Exception as exc:
                # Worker shutdown must continue even if external resources have
                # already disappeared.  The process exit remains the final
                # resource boundary.
                logger.warning(
                    "celery_async_runtime_cleanup_failed",
                    error_type=type(exc).__name__,
                )
            finally:
                runner.close()
                self._runner = None
                self._owner_pid = None

    def _runner_for_current_process(self) -> asyncio.Runner:
        current_pid = self._pid_provider()
        if self._runner is None or self._owner_pid != current_pid:
            # Never close a runner inherited from another PID.  After a fork,
            # only the parent owns that loop and its resources.
            self._runner = self._runner_factory()
            self._owner_pid = current_pid
        return self._runner


celery_async_runtime = CeleryAsyncRuntime()
atexit.register(celery_async_runtime.shutdown)
