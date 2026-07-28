from __future__ import annotations

import gzip

import pytest
from starlette.middleware.gzip import GZipResponder
from starlette.types import Message, Receive, Scope

from app.presentation.middleware import safe_gzip
from app.presentation.middleware.safe_gzip import SafeGZipMiddleware


async def _receive() -> Message:
    return {"type": "http.disconnect"}


def _scope() -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/test",
        "raw_path": b"/test",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"accept-encoding", b"gzip")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }


async def test_small_response_is_forwarded_without_compression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Message] = []
    responders: list[GZipResponder] = []

    class RecordingGZipResponder(GZipResponder):
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            super().__init__(*args, **kwargs)
            responders.append(self)

    monkeypatch.setattr(safe_gzip, "GZipResponder", RecordingGZipResponder)

    async def collect(message: Message) -> None:
        sent.append(message)

    async def app(scope: Scope, receive: Receive, send) -> None:  # type: ignore[no-untyped-def]
        del scope, receive
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-length", b"2")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = SafeGZipMiddleware(app, minimum_size=1_000)
    await middleware(_scope(), _receive, collect)

    assert sent[-1]["body"] == b"ok"
    assert (b"content-encoding", b"gzip") not in sent[0]["headers"]
    assert responders[0].gzip_file.closed is True


async def test_large_response_remains_valid_gzip() -> None:
    sent: list[Message] = []
    body = b"x" * 2_000

    async def collect(message: Message) -> None:
        sent.append(message)

    async def app(scope: Scope, receive: Receive, send) -> None:  # type: ignore[no-untyped-def]
        del scope, receive
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})

    middleware = SafeGZipMiddleware(app, minimum_size=1_000)
    await middleware(_scope(), _receive, collect)

    assert (b"content-encoding", b"gzip") in sent[0]["headers"]
    assert gzip.decompress(sent[-1]["body"]) == body


async def test_preencoded_response_closes_unused_compressor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Message] = []
    responders: list[GZipResponder] = []

    class RecordingGZipResponder(GZipResponder):
        def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
            super().__init__(*args, **kwargs)
            responders.append(self)

    monkeypatch.setattr(safe_gzip, "GZipResponder", RecordingGZipResponder)

    async def collect(message: Message) -> None:
        sent.append(message)

    async def app(scope: Scope, receive: Receive, send) -> None:  # type: ignore[no-untyped-def]
        del scope, receive
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-encoding", b"br"),
                    (b"content-length", b"7"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b"encoded"})

    middleware = SafeGZipMiddleware(app, minimum_size=1)
    await middleware(_scope(), _receive, collect)

    assert sent[-1]["body"] == b"encoded"
    assert (b"content-encoding", b"br") in sent[0]["headers"]
    assert responders[0].gzip_file.closed is True
