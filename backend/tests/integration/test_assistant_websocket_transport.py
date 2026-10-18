"""Real loopback transport using the production worker's exact WebSocket options.

TestClient and browser socket mocks bypass Uvicorn's pre-ASGI frame limit.
These synthetic echo routes exercise that limit without data, keys or providers.
"""

import asyncio
import base64
import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedError, InvalidStatus

from app.infrastructure.bounded_websocket_protocol import BOUNDED_WEBSOCKET_OPTIONS

VOICE = "/api/v1/ai-assistant/voice"
SMALL_ROUTES = [
    "/api/v1/mobile/realtime",
    "/api/v1/dashboard/realtime",
    VOICE + "/",
    VOICE + "-other",
]


def native_gateway_app(monkeypatch, complete=True) -> FastAPI:
    from app.core.assistant_config import AssistantSettings
    from app.domain.entities.entities import User, UserRole
    from app.presentation.api.v1.routes import ai_assistant_voice as voice
    from app.presentation.assistant import native_session

    actor = User.create("transport@example.test", "synthetic", "Transport check", UserRole.SUPER_ADMIN)
    settings = AssistantSettings(provider="gemini", revision=1, _env_file=None)
    store = SimpleNamespace(create_conversation=AsyncMock(), claim_request=AsyncMock(),
                            turns=AsyncMock(return_value={"items": []}), save_turn=AsyncMock())

    class Provider:
        def __init__(self):
            self.events = asyncio.Queue()
            self.packets = 0

        async def send(self, raw):
            value = json.loads(raw)
            if "setup" in value:
                await self.events.put({"setupComplete": {}})
            elif "audio" in value.get("realtimeInput", {}):
                self.packets += 1
                if self.packets == 1:
                    await self.events.put({"serverContent": {
                        "inputTranscription": {"text": "Synthetic connection check"},
                        "outputTranscription": {"text": "Ready."},
                        "modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000",
                            "data": base64.b64encode(b"\x01\x00" * 1600).decode()}}]},
                        "turnComplete": complete,
                    }})

        async def recv(self):
            return json.dumps(await self.events.get())

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self.recv()

    @asynccontextmanager
    async def provider(_settings):
        yield Provider()

    @asynccontextmanager
    async def admission(*args, **kwargs):
        yield SimpleNamespace(commit=lambda: None)

    monkeypatch.setattr(voice, "authorize_voice", AsyncMock(return_value=(actor, settings)))
    monkeypatch.setattr(voice, "assistant_store", lambda _actor: store)
    monkeypatch.setattr(voice, "assistant_admission", admission)
    monkeypatch.setattr(voice, "live_connection", provider)
    monkeypatch.setattr(native_session, "fresh_actor", AsyncMock(return_value=actor))
    app = FastAPI()
    app.include_router(voice.router, prefix="/api/v1/ai-assistant")
    return app


@pytest.fixture
def transport_origin(request, monkeypatch) -> Iterator[str]:
    app = FastAPI()

    async def echo(websocket: WebSocket) -> None:
        if websocket.url.query:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_json({"type": "ready"})
        try:
            while True:
                message = await websocket.receive_text()
                await websocket.send_json({"received_bytes": len(message.encode("utf-8"))})
        except WebSocketDisconnect:
            pass

    for path in [VOICE, *SMALL_ROUTES]:
        app.add_api_websocket_route(path, echo)
    if getattr(request, "param", None) in {"native", "native_partial"}:
        app = native_gateway_app(monkeypatch, complete=request.param != "native_partial")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    port = listener.getsockname()[1]
    options = dict(BOUNDED_WEBSOCKET_OPTIONS)
    if getattr(request, "param", None) == "legacy":
        options.pop("ws")  # Original auto protocol with the same 1 KiB limit.
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, lifespan="off", access_log=False,
        log_level="critical", **options,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started, "Synthetic loopback server did not start"
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive(), "Synthetic loopback server did not stop"


async def test_real_worker_accepts_microphone_packets_then_long_native_text(transport_origin):
    pcm = base64.b64encode(b"\x00\x00" * 1600).decode()
    packets = [
        json.dumps({"type": "audio", "data": pcm}),
        json.dumps({"type": "audio", "data": pcm}),
        json.dumps({"type": "heartbeat_ack"}),
        json.dumps({"type": "text", "text": "क" * 8000}, ensure_ascii=False),
    ]
    assert len(packets[0].encode()) > 4096
    async with asyncio.timeout(5), connect(transport_origin + VOICE) as websocket:
        assert json.loads(await websocket.recv())["type"] == "ready"
        for packet in packets:
            await websocket.send(packet)
            assert json.loads(await websocket.recv()) == {"received_bytes": len(packet.encode())}


@pytest.mark.parametrize("transport_origin", ["legacy"], indirect=True)
async def test_previous_policy_reproduces_microphone_close_1009(transport_origin):
    packet = json.dumps({"type": "audio", "data": base64.b64encode(b"\x00\x00" * 1600).decode()})
    async with asyncio.timeout(5), connect(transport_origin + VOICE) as websocket:
        await websocket.recv()
        await websocket.send(packet)
        with pytest.raises(ConnectionClosedError) as closed:
            await websocket.recv()
        assert closed.value.rcvd.code == 1009


@pytest.mark.parametrize("transport_origin", ["native"], indirect=True)
async def test_real_native_gateway_survives_audio_output_and_authorization_heartbeat(transport_origin):
    from uuid import uuid4

    pcm = base64.b64encode(b"\x00\x00" * 1600).decode()
    async with asyncio.timeout(10), connect(transport_origin + VOICE) as websocket:
        await websocket.send(json.dumps({"type": "start", "conversation_id": str(uuid4()),
                                         "session_id": str(uuid4()), "attachment_ids": []}))
        assert json.loads(await websocket.recv())["type"] == "ready"
        for _ in range(3):
            await websocket.send(json.dumps({"type": "audio", "data": pcm}))
        events = []
        while not events or events[-1]["type"] != "heartbeat":
            events.append(json.loads(await websocket.recv()))
        assert {event["type"] for event in events} >= {"input_transcript", "text_delta", "audio", "turn_complete", "heartbeat"}
        assert next(event for event in events if event["type"] == "audio")["sample_rate"] == 24000
        await websocket.send(json.dumps({"type": "heartbeat_ack"}))


@pytest.mark.parametrize("path", SMALL_ROUTES)
async def test_other_routes_keep_their_transport_limit(transport_origin, path):
    async with asyncio.timeout(5), connect(transport_origin + path) as websocket:
        await websocket.recv()
        await websocket.send("x" * 1024)
        assert json.loads(await websocket.recv()) == {"received_bytes": 1024}
        await websocket.send("x" * 1025)
        with pytest.raises(ConnectionClosedError) as closed:
            await websocket.recv()
        assert closed.value.rcvd.code == 1009


@pytest.mark.parametrize("fragmented", [False, True])
async def test_voice_rejects_oversize_messages_before_asgi(transport_origin, fragmented):
    async with asyncio.timeout(5), connect(transport_origin + VOICE) as websocket:
        await websocket.recv()
        payload = ["x" * 16384, "x" * 16385] if fragmented else "x" * 32769
        await websocket.send(payload)
        with pytest.raises(ConnectionClosedError) as closed:
            await websocket.recv()
        assert closed.value.rcvd.code == 1009


async def test_route_policy_does_not_override_an_asgi_handshake_denial(transport_origin):
    with pytest.raises(InvalidStatus) as denied:
        async with connect(transport_origin + VOICE + "?credential=synthetic"):
            pass
    assert denied.value.response.status_code == 403


@pytest.mark.parametrize("transport_origin", ["native_partial"], indirect=True)
async def test_explicit_end_saves_partial_captions_before_normal_socket_close(transport_origin):
    async with asyncio.timeout(8), connect(transport_origin + VOICE) as websocket:
        await websocket.send(json.dumps({"type":"start","conversation_id":str(uuid4()),"session_id":str(uuid4())}))
        assert json.loads(await websocket.recv())["type"] == "ready"
        await websocket.send(json.dumps({"type":"audio","data":base64.b64encode(b"\x00\x00" * 1600).decode()}))
        while json.loads(await websocket.recv())["type"] != "audio":
            pass
        await websocket.send('{"type":"end"}')
        saved = json.loads(await websocket.recv())
        assert saved["type"] == "turn_complete"
        assert saved["turn"]["user"] == "Synthetic connection check"
        assert "Ready." in saved["turn"]["assistant"] and saved["turn"]["interrupted"] is True
        assert json.loads(await websocket.recv())["type"] == "voice_saved"
        await websocket.wait_closed()
        assert websocket.close_code == 1000
