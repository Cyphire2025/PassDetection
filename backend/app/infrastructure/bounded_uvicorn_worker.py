"""Gunicorn worker with transport-level WebSocket memory bounds."""

from __future__ import annotations

from typing import Any

from uvicorn.workers import UvicornWorker

from app.core.logging.server_diagnostics import install_server_diagnostic_filter


class BoundedUvicornWorker(UvicornWorker):
    """Keep oversized frames out of application memory before validation."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        install_server_diagnostic_filter()
        super().__init__(*args, **kwargs)

    CONFIG_KWARGS: dict[str, Any] = {
        **UvicornWorker.CONFIG_KWARGS,
        "ws_max_size": 1_024,
        "ws_max_queue": 4,
        # Hints are tiny and never contain content worth compressing. Disabling
        # negotiation removes per-connection compression memory and CPU cost.
        "ws_per_message_deflate": False,
    }


__all__ = ["BoundedUvicornWorker"]
