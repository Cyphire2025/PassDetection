"""
Structured logging configuration.

Uses structlog for JSON-structured logs in production
and pretty console output in development.

Every log entry automatically includes:
  - timestamp (ISO 8601)
  - log level
  - logger name
  - request_id (injected by middleware)
  - environment
"""

from __future__ import annotations

import logging
import sys
from threading import Lock
from typing import Any

try:
    import structlog
except ModuleNotFoundError:  # pragma: no cover - exercised in lightweight local envs
    structlog = None  # type: ignore[assignment]

from app.core.config.settings import get_settings

_HANDLER_NAME = "passdetection.application.stdout"
_HANDLER_LOCK = Lock()


def _configure_root_handler(formatter: logging.Formatter, level: int) -> None:
    """Replace only our output handler when another app is created in-process."""
    with _HANDLER_LOCK:
        root_logger = logging.getLogger()
        for previous in root_logger.handlers[:]:
            if previous.name == _HANDLER_NAME:
                root_logger.removeHandler(previous)
                previous.close()
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        root_logger.setLevel(level)


def configure_logging() -> None:
    """
    Bootstrap structlog.

    Safe to call for each application created in the same process.
    """
    # HTTPX includes the complete APNs device-token URL at INFO; HTTP/2 debug
    # traces can include authentication headers. Keep transport internals quiet
    # even in debug builds. Application delivery logs use bounded identifiers.
    for noisy in (
        "uvicorn.access", "sqlalchemy.engine", "boto3", "botocore",
        "httpx", "httpcore", "httpx2", "httpcore2", "hpack",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if structlog is None:
        _configure_root_handler(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"),
            logging.INFO,
        )
        return

    settings = get_settings()

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.is_production:
        # Machine-readable JSON for log aggregation (Datadog, CloudWatch, etc.)
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        # Human-readable coloured output for local development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    _configure_root_handler(formatter, logging.DEBUG if settings.app_debug else logging.INFO)

class _StdlibStructuredLogger:
    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, event, kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._log(logging.INFO, event, kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, event, kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, event, kwargs)

    def exception(self, event: str, **kwargs: Any) -> None:
        self._logger.exception("%s %s", event, kwargs if kwargs else "")

    def _log(self, level: int, event: str, kwargs: dict[str, Any]) -> None:
        self._logger.log(level, "%s %s", event, kwargs if kwargs else "")


def get_logger(name: str) -> Any:
    """
    Return a bound structlog logger for a given module.

    Usage:
        from app.core.logging.logger import get_logger
        logger = get_logger(__name__)
        logger.info("passport_uploaded", passport_id=str(passport.id))
    """
    if structlog is None:
        return _StdlibStructuredLogger(name)
    return structlog.get_logger(name)
