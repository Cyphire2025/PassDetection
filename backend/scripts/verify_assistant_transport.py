"""Qualify production WebSocket packet bounds using a synthetic loopback server.

Run inside the Linux backend image. No accounts, credentials, provider calls or
persistent storage are used. The temporary server cannot receive external traffic.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402
from websockets.exceptions import ConnectionClosedError  # noqa: E402

from app.infrastructure.bounded_uvicorn_worker import BoundedUvicornWorker  # noqa: E402


async def echo(scope: Any, receive: Any, send: Any) -> None:
    await receive()
    await send({"type": "websocket.accept"})
    await send({"type": "websocket.send", "text": "ready"})
    while True:
        event = await receive()
        if event["type"] == "websocket.disconnect":
            return
        text = event.get("text", "")
        await send({"type": "websocket.send", "text": json.dumps({"bytes": len(text.encode())})})


async def qualify() -> dict[str, Any]:
    options = BoundedUvicornWorker.CONFIG_KWARGS
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        echo, lifespan="off", log_level="critical", access_log=False, **options,
    ))
    task = asyncio.create_task(server.serve(sockets=[listener]))

    async def exchange(path: str, payload: str | list[str]) -> dict[str, int | None]:
        async with connect(f"ws://127.0.0.1:{port}{path}", compression=None, close_timeout=2) as ws:
            await ws.recv()
            await ws.send(payload)
            try:
                return {"received_bytes": json.loads(await ws.recv())["bytes"]}
            except ConnectionClosedError as error:
                return {"close_code": error.rcvd.code if error.rcvd else None}

    result: dict[str, Any] = {
        "default_message_bytes": options["ws_max_size"],
        "max_queue": options["ws_max_queue"],
        "compression": options["ws_per_message_deflate"],
    }
    try:
        async with asyncio.timeout(12):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(.01)
            packet = json.dumps({"type": "audio", "data": base64.b64encode(b"\x00\x00" * 1600).decode()})
            result["microphone_packet_bytes"] = len(packet.encode())
            result["voice_audio"] = await exchange("/api/v1/ai-assistant/voice", packet)
            text = json.dumps({"type": "text", "text": "क" * 8000}, ensure_ascii=False)
            result["voice_text"] = await exchange("/api/v1/ai-assistant/voice", text)
            result["voice_oversize"] = await exchange("/api/v1/ai-assistant/voice", ["x" * 16384, "x" * 16385])
            result["mobile_small"] = await exchange("/api/v1/mobile/realtime", "x" * 1024)
            result["mobile_oversize"] = await exchange("/api/v1/mobile/realtime", "x" * 1025)
            result["dashboard_oversize"] = await exchange("/api/v1/dashboard/realtime", "x" * 1025)
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
        listener.close()
    passed = (
        result["voice_audio"] == {"received_bytes": result["microphone_packet_bytes"]}
        and result["voice_text"] == {"received_bytes": len(text.encode())}
        and result["voice_oversize"] == result["mobile_oversize"] == result["dashboard_oversize"] == {"close_code": 1009}
        and result["mobile_small"] == {"received_bytes": 1024}
        and result["default_message_bytes"] == 1024 and result["max_queue"] == 4
        and result["compression"] is False
    )
    if not passed:
        raise ValueError("assistant_transport_bounds_not_qualified")
    return {"status": "passed", **result}


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    try:
        print(json.dumps(asyncio.run(qualify())))
    except Exception:
        print(json.dumps({"status": "failed", "reason": "assistant_transport_bounds_not_qualified"}))
        raise SystemExit(1) from None
