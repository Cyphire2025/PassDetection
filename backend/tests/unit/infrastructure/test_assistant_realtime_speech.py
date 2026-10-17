"""Current speech transport is fixed-origin, bounded and completed before playback."""

import base64
import io
import json
import wave

import pytest
from pydantic import SecretStr

from app.application.assistant.contracts import AssistantError
from app.core.assistant_config import AssistantSettings
from app.infrastructure.assistant import realtime_speech
from app.infrastructure.assistant.provider import OpenAIAssistantProvider


class Socket:
    def __init__(self, events):
        self.events = events
        self.sent = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def send(self, value):
        self.sent.append(json.loads(value))

    async def __aiter__(self):
        for event in self.events:
            yield json.dumps(event)


def settings():
    return AssistantSettings(
        openai_api_key=SecretStr("synthetic-not-a-key"),
        speech_model="gpt-realtime-2.1-mini",
        _env_file=None,
    )


async def test_current_model_narrates_supplied_luna_answer_and_returns_valid_pcm_wav(monkeypatch):
    pcm = b"\0\0\1\0" * 2400
    socket = Socket(
        [
            {"type": "session.created"},
            {"type": "session.updated"},
            {"type": "response.output_audio.delta", "delta": base64.b64encode(pcm).decode()},
            {"type": "response.done", "response": {"status": "completed"}},
        ]
    )

    def connection(url, **kwargs):
        assert url == "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1-mini"
        assert kwargs["max_queue"] == 4 and kwargs["max_size"] == 512 * 1024
        assert kwargs["proxy"] is None
        return socket

    monkeypatch.setattr(realtime_speech, "FixedOpenAIConnect", connection)
    audio = await OpenAIAssistantProvider(settings()).speak("There are three pending documents.")
    with wave.open(io.BytesIO(audio), "rb") as decoded:
        assert decoded.getframerate() == 24000 and decoded.getnchannels() == 1
        assert decoded.readframes(decoded.getnframes()) == pcm
    assert socket.closed is True
    assert socket.sent[0]["session"]["tools"] == []
    assert "verbatim" in socket.sent[0]["session"]["instructions"]
    assert socket.sent[1]["item"]["content"][0]["text"].endswith(
        "There are three pending documents."
    )


@pytest.mark.parametrize(
    "event",
    [
        {"type": "error", "error": {"message": "sensitive-provider-message synthetic-not-a-key"}},
        {"type": "response.done", "response": {"status": "failed"}},
        {"type": "response.output_audio.delta", "delta": "invalid-base64"},
    ],
)
async def test_failed_voice_streams_are_sanitized_and_close_the_connection(monkeypatch, event):
    socket = Socket([{"type": "session.updated"}, event])
    monkeypatch.setattr(realtime_speech, "FixedOpenAIConnect", lambda *args, **kwargs: socket)
    with pytest.raises(AssistantError) as exc:
        await realtime_speech.realtime_speech(settings(), "Synthetic narration")
    assert "synthetic-not-a-key" not in str(exc.value)
    assert "sensitive-provider" not in str(exc.value)
    assert socket.closed is True


async def test_redirect_never_receives_provider_authorization():
    connection = realtime_speech.FixedOpenAIConnect("wss://api.openai.com/v1/realtime")
    assert isinstance(connection.process_redirect(Exception("redirect")), PermissionError)
