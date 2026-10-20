"""First speech survives provider setup without weakening the stream limits."""

import asyncio
import base64
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.websockets import WebSocketState

from app.application.assistant.contracts import AssistantError
from app.core.assistant_config import AssistantSettings
from app.presentation.api.v1.routes import ai_assistant_voice as voice


@pytest.mark.parametrize("setup_seconds, accepted", [(5, True), (0, False)])
async def test_buffered_capture_uses_server_session_time(setup_seconds, accepted):
    frame = json.dumps({"type": "audio", "data": base64.b64encode(b"\0" * 3200).decode()})
    messages = iter([frame] * 50 + ['{"type":"end"}'])
    socket = SimpleNamespace(receive_text=AsyncMock(side_effect=lambda: next(messages)))
    upstream = SimpleNamespace(send=AsyncMock())
    conversation = SimpleNamespace(recovering=False)
    started = time.monotonic() - setup_seconds
    if accepted:
        await voice._client_audio(socket, upstream, conversation, session_started=started)
        assert upstream.send.await_count == 50
        assert conversation.ending
    else:
        with pytest.raises(AssistantError) as error:
            await voice._client_audio(socket, upstream, conversation, session_started=started)
        assert error.value.code == "voice_limit"
        assert upstream.send.await_count == 20


async def test_route_keeps_first_utterance_buffered_during_authorization(monkeypatch):
    clock = [100.0]
    settings = AssistantSettings(_env_file=None)
    actor = SimpleNamespace(id=uuid4())
    conversation_id = uuid4()
    start = json.dumps(
        {"type": "start", "conversation_id": str(conversation_id), "session_id": str(uuid4())}
    )
    frame = json.dumps({"type": "audio", "data": base64.b64encode(b"\0" * 3200).decode()})
    socket = SimpleNamespace(
        application_state=WebSocketState.CONNECTED,
        accept=AsyncMock(),
        receive_text=AsyncMock(side_effect=[start, *([frame] * 50), '{"type":"end"}']),
        send_json=AsyncMock(),
        close=AsyncMock(),
    )
    upstream = SimpleNamespace(send=AsyncMock())
    store = SimpleNamespace(claim_request=AsyncMock())
    conversation = SimpleNamespace(
        context=AsyncMock(return_value=("Synthetic fixture", [])),
        recovering=False, ending=False, input="", output="", conversation_id=conversation_id,
    )

    async def authorize(_socket):
        clock[0] += 5
        return actor, settings

    @asynccontextmanager
    async def admission(*args, **kwargs):
        yield SimpleNamespace(commit=lambda: None)

    @asynccontextmanager
    async def connect(*args):
        yield upstream

    async def idle(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(voice, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(voice, "authorize_voice", authorize)
    monkeypatch.setattr(voice, "assistant_admission", admission)
    monkeypatch.setattr(voice, "assistant_store", lambda _actor: store)
    monkeypatch.setattr(voice, "_request", lambda _socket: None)
    monkeypatch.setattr(voice, "NativeSession", lambda *args: conversation)
    monkeypatch.setattr(voice, "configured_voice_connection", connect)
    monkeypatch.setattr(voice, "_server_audio", idle)
    monkeypatch.setattr(voice, "_authorization_heartbeat", idle)

    await voice.assistant_voice(socket)

    assert upstream.send.await_count == 50
    assert [call.args[0]["type"] for call in socket.send_json.await_args_list] == [
        "ready", "voice_saved",
    ]
    socket.close.assert_awaited_once_with(code=1000)


@pytest.mark.parametrize(
    "provider, model",
    [
        ("openai", "gpt-realtime-translate"),
        ("gemini", "gemini-3.5-transcribe-live"),
        ("gemini", "gemini-robotics-er-2-streaming-preview"),
    ],
)
async def test_nonconversational_models_fail_with_actionable_error_before_upstream(provider, model):
    settings = AssistantSettings(_env_file=None).model_copy(
        update={"provider": provider, "live_model": model}
    )
    with pytest.raises(AssistantError) as error:
        async with voice.configured_voice_connection(settings, [], "Synthetic fixture"):
            pytest.fail("Incompatible model reached the provider.")
    assert error.value.code == "provider_configuration"
    assert "AI settings" in error.value.message
