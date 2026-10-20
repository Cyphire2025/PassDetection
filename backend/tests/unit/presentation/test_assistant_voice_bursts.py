"""Fast generated audio stays complete and playback interruption is independent."""

import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Request

from app.domain.entities.entities import User, UserRole
from app.infrastructure.assistant.openai_live import RealtimeGateway
from app.presentation.assistant import native_session
from tests.unit.infrastructure.test_assistant_openai_native import Socket, settings


@pytest.fixture
def session(monkeypatch):
    actor = User.create("voice-burst@example.test", "fixture", "Voice burst", UserRole.SUPER_ADMIN)
    monkeypatch.setattr(native_session, "fresh_actor", AsyncMock(return_value=actor))
    store, send = SimpleNamespace(save_turn=AsyncMock()), AsyncMock()
    conversation = native_session.NativeSession(Request({"type": "http", "headers": []}),
        actor, settings(), store, uuid4(), send)
    return conversation, store, send


async def test_input_started_is_playback_control_without_creating_a_history_turn(session):
    conversation, store, send = session
    identifier = conversation.turn_id
    await conversation.consume({"serverContent": {"inputAudioStarted": True}})
    send.assert_awaited_once_with({"type": "input_started"})
    store.save_turn.assert_not_awaited()
    assert conversation.turn_id == identifier and not conversation.input and not conversation.output


@pytest.mark.parametrize("audio_kind", ["response.audio.delta", "response.output_audio.delta"])
async def test_fast_long_reply_preserves_all_pcm_and_barge_in_after_provider_completion(session, audio_kind):
    conversation, store, send = session
    pcm = base64.b64encode(b"\x10\x00" * 24000).decode()  # One second per provider delta.
    socket = Socket([
        {"type": "input_audio_buffer.speech_started", "item_id": "input-1"},
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "input-1", "transcript": "Explain the journey"},
        {"type": "response.created", "response": {"id": "output-1"}},
        {"type": "response.output_audio_transcript.delta", "delta": "The whole explanation ends here."},
        *[{"type": audio_kind, "response_id": "output-1", "delta": pcm} for _ in range(45)],
        {"type": "response.done", "response": {"id": "output-1", "status": "completed", "output": []}},
        # The browser still has audio queued; the provider has already completed.
        {"type": "input_audio_buffer.speech_started", "item_id": "input-2"},
        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "input-2", "transcript": "One more question"},
    ])
    gateway = RealtimeGateway(socket, settings())
    stream = gateway.events()
    try:
        # No audio-duration sleeps: control events cannot wait behind 45 seconds
        # of buffered PCM, and completion must not discard any audio delta.
        async with asyncio.timeout(5):
            while True:
                try:
                    event = await anext(stream)
                except EOFError:
                    break
                await conversation.consume(json.loads(event))
    finally:
        await stream.aclose()
    events = [call.args[0] for call in send.await_args_list]
    audio = [event for event in events if event["type"] == "audio"]
    assert len(audio) == 45
    assert sum(len(base64.b64decode(event["data"])) for event in audio) == 45 * 48000
    assert all(event["data"] == pcm for event in audio)
    assert events[-3]["type"] == "turn_complete"
    assert events[-2] == {"type": "input_started"}
    assert events[-1]["type"] == "input_transcript" and events[-1]["text"] == "One more question"
    assert not any(event["type"] == "interrupted" for event in events)
    store.save_turn.assert_awaited_once()
    saved = store.save_turn.await_args.args[2]
    assert saved["assistant"] == "The whole explanation ends here." and not saved["interrupted"]
    assert conversation.input == "One more question" and conversation.output == ""
