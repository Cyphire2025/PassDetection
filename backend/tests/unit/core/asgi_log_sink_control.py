"""Networkless Uvicorn cycle using real middleware/formatters and synthetic errors."""

from __future__ import annotations

import asyncio
import io
import logging
from types import SimpleNamespace
from typing import Any

import h11
from fastapi import FastAPI
from uvicorn import Config
from uvicorn.protocols.http import h11_impl, httptools_impl
from uvicorn.protocols.http.flow_control import FlowControl

from app.core.logging import logger as application_logging
from app.presentation.middleware.error_handler import register_exception_handlers
from app.presentation.middleware.request_id import RequestIDMiddleware


class SyntheticTransport:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.chunks.append(data)

    def close(self) -> None:
        self.closed = True

    def is_closing(self) -> bool:
        return self.closed

    def resume_reading(self) -> None:
        pass

    def pause_reading(self) -> None:
        pass


def configure_sink(monkeypatch: Any, mode: str) -> tuple[io.StringIO, io.StringIO]:
    application, server = io.StringIO(), io.StringIO()
    monkeypatch.setattr(application_logging, "sys", SimpleNamespace(stdout=application))
    monkeypatch.setattr("sys.stderr", server)
    if mode == "uvicorn-default-stderr":
        # Config installs the real default stderr handler without starting a server.
        Config(FastAPI(), log_level="error", use_colors=False)
    else:
        for name in ("uvicorn", "uvicorn.error"):
            logger = logging.getLogger(name)
            logger.handlers = []
            logger.propagate = True
    monkeypatch.setattr(
        application_logging,
        "get_settings",
        lambda: SimpleNamespace(
            is_production=True,
            app_debug=False,
        ),
    )
    application_logging.configure_logging()
    return application, server


async def exercise_cycle(protocol: str, failure: Exception) -> bytes:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/synthetic-failure")
    async def fail() -> None:
        raise failure

    transport = SyntheticTransport()
    event = asyncio.Event()
    event.set()
    scope: Any = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "server": ("127.0.0.1", 0),
        "client": ("127.0.0.1", 1),
        "scheme": "http",
        "method": "GET",
        "root_path": "",
        "path": "/synthetic-failure",
        "raw_path": b"/synthetic-failure",
        "query_string": b"",
        "headers": [(b"host", b"synthetic.invalid")],
        "state": {},
    }
    common: dict[str, Any] = {
        "scope": scope,
        "transport": transport,
        "flow": FlowControl(transport),
        "logger": logging.getLogger("uvicorn.error"),
        "access_logger": logging.getLogger("uvicorn.access"),
        "access_log": False,
        "default_headers": [],
        "message_event": event,
        "on_response": lambda: None,
    }
    if protocol == "h11":
        conn = h11.Connection(h11.SERVER)
        conn.receive_data(b"GET /synthetic-failure HTTP/1.1\r\nHost: synthetic.invalid\r\n\r\n")
        assert isinstance(conn.next_event(), h11.Request)
        assert isinstance(conn.next_event(), h11.EndOfMessage)
        cycle = h11_impl.RequestResponseCycle(**common, conn=conn)
    else:
        cycle = httptools_impl.RequestResponseCycle(
            **common, expect_100_continue=False, keep_alive=True
        )
    cycle.more_body = False
    await cycle.run_asgi(app)
    return b"".join(transport.chunks)
