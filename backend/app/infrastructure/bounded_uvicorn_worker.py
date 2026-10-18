"""Gunicorn worker with transport-level WebSocket memory bounds."""

from __future__ import annotations

from typing import Any

from uvicorn.workers import UvicornWorker

from app.infrastructure.bounded_websocket_protocol import BOUNDED_WEBSOCKET_OPTIONS


class BoundedUvicornWorker(UvicornWorker):
    """Keep oversized frames out of application memory before validation."""

    CONFIG_KWARGS: dict[str, Any] = {
        **UvicornWorker.CONFIG_KWARGS,
        **BOUNDED_WEBSOCKET_OPTIONS,
    }


__all__ = ["BoundedUvicornWorker"]
