"""Resource-safe wrapper around Starlette's gzip responder."""

from __future__ import annotations

import contextlib

from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipResponder
from starlette.types import ASGIApp, Receive, Scope, Send


class SafeGZipMiddleware:
    """Close Starlette's unused compressor for small or pre-encoded responses."""

    def __init__(
        self,
        app: ASGIApp,
        minimum_size: int = 500,
        compresslevel: int = 9,
    ) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = Headers(scope=scope)
            if "gzip" in headers.get("Accept-Encoding", ""):
                responder = GZipResponder(
                    self.app,
                    self.minimum_size,
                    compresslevel=self.compresslevel,
                )
                try:
                    await responder(scope, receive, send)
                finally:
                    # Starlette 0.37 creates the compressor eagerly but leaves
                    # it open when a response is too small to compress.
                    with contextlib.suppress(Exception):
                        if not responder.gzip_file.closed:
                            responder.gzip_file.close()
                return
        await self.app(scope, receive, send)
