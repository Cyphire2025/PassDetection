"""Wire-level native audio regression tests using synthetic sockets."""

import base64
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application.assistant.contracts import AssistantError, SpeechRequest
from app.core.assistant_config import AssistantSettings
from app.infrastructure.assistant.openai_duplex import DuplexGateway, duplex_setup
from app.infrastructure.assistant.openai_live import RealtimeGateway, realtime_setup
from app.presentation.api.v1.routes import ai_assistant


class Socket:
    def __init__(self, events=()):
        self.events = iter(events)
        self.send = AsyncMock()

    async def recv(self):
        try:
            return json.dumps(next(self.events))
        except StopIteration:
            raise EOFError() from None

    async def __aiter__(self):
        for event in self.events:
            yield json.dumps(event)


def settings(**values):
    return AssistantSettings(_env_file=None, provider="openai", live_model="gpt-realtime-2.1", voice="cedar", **values)


def test_realtime_setup_requests_automatic_audio_and_fast_vad():
    setup = realtime_setup(settings(), [], "Speak naturally")["session"]
    assert setup["output_modalities"] == ["audio"]
    assert setup["audio"]["input"]["turn_detection"] == {"type": "server_vad", "threshold": .5, "prefix_padding_ms": 300, "silence_duration_ms": 350, "create_response": True, "interrupt_response": True}
    assert setup["audio"]["output"]["voice"] == "cedar"
    assert setup["reasoning"] == {"effort": "low"}


@pytest.mark.parametrize("model", ["gpt-realtime-2.1", "gpt-4o-realtime-preview"])
async def test_read_aloud_uses_wav_content_type_for_every_realtime_family(monkeypatch, model):
    @asynccontextmanager
    async def admit(*args, **kwargs):
        yield
    async def bound(request, operation):
        return await operation
    monkeypatch.setattr(ai_assistant, "assistant_admission", admit)
    monkeypatch.setattr(ai_assistant, "fresh_actor", AsyncMock())
    monkeypatch.setattr(ai_assistant, "client_bound", bound)
    monkeypatch.setattr(ai_assistant, "assistant_provider", lambda config: SimpleNamespace(speak=AsyncMock(return_value=b"RIFF-synthetic-wave")))
    response = await ai_assistant.speech(SpeechRequest(text="Hello"), SimpleNamespace(), SimpleNamespace(id="synthetic-account"), settings().model_copy(update={"speech_model": model}))
    assert response.media_type == "audio/wav"
    assert response.body == b"RIFF-synthetic-wave"


async def test_pcm_conversion_and_tool_completion_automatically_request_speech():
    socket = Socket()
    gateway = RealtimeGateway(socket, settings())
    await gateway.send(json.dumps({"realtimeInput": {"audio": {"data": base64.b64encode(b"\x10\x00" * 1600).decode()}}}))
    await gateway.send(json.dumps({"realtimeInput": {"audioStreamEnd": True}}))
    await gateway.send(json.dumps({"toolResponse": {"functionResponses": [{"id": "call-1", "response": {"result": {"count": 3}}}]}}))
    sent = [json.loads(call.args[0]) for call in socket.send.await_args_list]
    assert 4790 <= len(base64.b64decode(sent[0]["audio"])) <= 4800
    assert [item["type"] for item in sent] == ["input_audio_buffer.append", "conversation.item.create", "response.create"]
    assert sent[1]["item"]["type"] == "function_call_output"
    assert sent[2]["response"]["output_modalities"] == ["audio"]


async def test_audio_arrives_before_any_caption_and_late_asr_saves_same_turn():
    socket = Socket([
        {"type": "input_audio_buffer.speech_started", "item_id": "in-1"},
        {"type": "response.output_audio.delta", "delta": "AQACAA=="},
        {"type": "response.done", "response": {"status": "completed", "output": []}},
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "in-1", "transcript": "Hello"},
    ])
    stream = RealtimeGateway(socket, settings()).events()
    first = json.loads(await anext(stream))
    assert first["serverContent"]["modelTurn"]["parts"][0]["inlineData"]["data"] == "AQACAA=="
    assert json.loads(await anext(stream))["serverContent"]["inputTranscription"]["text"] == "Hello"
    assert json.loads(await anext(stream))["serverContent"]["turnComplete"]
    await stream.aclose()


async def test_interruption_discards_stale_audio_and_old_transcripts():
    socket = Socket([
        {"type": "input_audio_buffer.speech_started", "item_id": "in-1"},
        {"type": "response.created", "response": {"id": "out-1"}},
        {"type": "response.output_audio.delta", "response_id": "out-1", "delta": "AQACAA=="},
        {"type": "input_audio_buffer.speech_started", "item_id": "in-2"},
        {"type": "response.output_audio.delta", "response_id": "out-1", "delta": "STALE"},
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "in-1", "transcript": "Old"},
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "in-2", "transcript": "New"},
    ])
    stream = RealtimeGateway(socket, settings()).events()
    await anext(stream)
    assert json.loads(await anext(stream))["serverContent"]["interrupted"]
    assert json.loads(await anext(stream))["serverContent"]["inputTranscription"]["text"] == "New"
    await stream.aclose()


async def test_provider_errors_never_echo_secrets():
    stream = RealtimeGateway(Socket([{"type": "error", "error": {"message": "sk-private"}}]), settings()).events()
    with pytest.raises(AssistantError) as exc:
        await anext(stream)
    assert "sk-private" not in str(exc.value)


async def test_interrupting_thinking_discards_the_previous_tool_request():
    socket = Socket([
        {"type": "input_audio_buffer.speech_started", "item_id": "in-1"},
        {"type": "response.created", "response": {"id": "out-1"}},
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "in-1", "transcript": "Old request"},
        {"type": "input_audio_buffer.speech_started", "item_id": "in-2"},
        {"type": "response.done", "response": {"id": "out-1", "status": "completed", "output": [{"type": "function_call", "call_id": "old-call", "name": "call_mcp_tool", "arguments": "{}"}]}},
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "in-2", "transcript": "New request"},
    ])
    stream = RealtimeGateway(socket, settings()).events()
    assert json.loads(await anext(stream))["serverContent"]["inputTranscription"]["text"] == "Old request"
    assert json.loads(await anext(stream))["serverContent"]["interrupted"]
    assert json.loads(await anext(stream))["serverContent"]["inputTranscription"]["text"] == "New request"
    await stream.aclose()


async def test_gpt_live_uses_distinct_protocol_and_deduplicates_delegation():
    config = settings().model_copy(update={"live_model": "gpt-live-1", "voice": "nira"})
    setup = duplex_setup(config, "Saved context")["session"]
    assert setup["delegation"] == {"type": "client"}
    assert setup["audio"]["output"]["voice"] == "nira"
    socket = Socket([
        {"type": "session.input_transcript.delta", "delta": "Read my groups", "start_ms": 0, "end_ms": 1000},
        {"type": "session.delegation.created", "delegation": {"id": "d1", "target": "client"}},
        {"type": "session.delegation.created", "delegation": {"id": "d1", "target": "client"}},
        {"type": "session.output_audio.delta", "delta": "AQACAA=="},
    ])
    gateway = DuplexGateway(socket)
    events = [json.loads(raw) async for raw in gateway]
    assert len(events) == 3
    assert events[1]["backgroundToolCall"] is True
    assert events[1]["toolCall"]["functionCalls"][0]["args"] == {"question": "Read my groups"}
    assert "modelTurn" in events[2]["serverContent"]
    await gateway.send(json.dumps({"toolResponse": {"functionResponses": [{"id": "d1", "response": {"result": {"answer": "नमस्ते " * 100}}}]}}))
    for call in socket.send.await_args_list:
        packet = json.loads(call.args[0])
        assert packet["type"] == "session.commentary.append" and packet["delegation_id"] == "d1"
        assert len(packet["content"].encode()) <= 400
    assert not gateway.pending
