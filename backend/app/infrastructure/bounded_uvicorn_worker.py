"""Gunicorn worker with transport-level WebSocket memory bounds."""

from __future__ import annotations

from typing import Any

from uvicorn.workers import UvicornWorker

from app.core.logging.server_diagnostics import install_server_diagnostic_filter
from app.infrastructure.bounded_websocket_protocol import BOUNDED_WEBSOCKET_OPTIONS


class BoundedUvicornWorker(UvicornWorker):
    """Keep oversized frames out of application memory before validation."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        install_server_diagnostic_filter()
        super().__init__(*args, **kwargs)

    CONFIG_KWARGS: dict[str, Any] = {
        **UvicornWorker.CONFIG_KWARGS,
        **BOUNDED_WEBSOCKET_OPTIONS,
    }


__all__ = ["BoundedUvicornWorker"]
