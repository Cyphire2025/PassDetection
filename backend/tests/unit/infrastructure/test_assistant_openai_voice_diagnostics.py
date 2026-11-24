"""Exercise OpenAI handshakes and audio boundaries without provider content logs."""

import base64
import json
from unittest.mock import AsyncMock, Mock

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from app.application.assistant.contracts import AssistantError
from app.core.assistant_config import AssistantSettings
from app.infrastructure.assistant import openai_duplex, openai_live
from app.infrastructure.assistant import openai_voice_diagnostics as diagnostics


class Socket:
    def __init__(self, events):
        self.events = iter(events)
        self.send = AsyncMock()
        self.received = 0

    async def recv(self):
        self.received += 1
        return json.dumps(next(self.events))

    async def __aiter__(self):
        for event in self.events:
            yield json.dumps(event)


class Connection:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, *args):
        pass


@pytest.fixture
def recorded(monkeypatch):
    log = Mock()
    monkeypatch.setattr(diagnostics, "logger", log)
    return log


def config(model):
    return AssistantSettings(
        _env_file=None, provider="openai", live_model=model,
        voice="marin", openai_api_key="sk-synthetic-private",
    )


@pytest.mark.parametrize("protocol", ["realtime", "live"])
async def test_connection_waits_for_configuration_then_forwards_audio_without_captions(monkeypatch, recorded, protocol):
    audio = base64.b64encode(b"\x10\x00" * 2400).decode()
    accepted = {
        "audio": {"input": {"turn_detection": {"type": "server_vad", "create_response": True}}},
        "output_modalities": ["audio"],
    }
    events = [
        {"type": "session.created", "session": {"output_modalities": ["text"]}},
        {"type": "session.updated" if protocol == "realtime" else "session.started", "session": accepted},
        {"type": "response.output_audio.delta" if protocol == "realtime" else "session.output_audio.delta", "delta": audio},
    ]
    socket = Socket(events)
    module = openai_live if protocol == "realtime" else openai_duplex
    connect = Mock(return_value=Connection(socket))
    monkeypatch.setattr(module, "FixedRealtimeConnect", connect)
    connection = openai_live.openai_live_connection(config("gpt-realtime-2.1"), [], "Private instructions") if protocol == "realtime" else openai_duplex.duplex_connection(config("gpt-live-1"), "Private instructions")
    async with connection as gateway:
        assert socket.received == 2  # Never expose readiness from session.created.
        payload = base64.b64encode(b"\x01\x00" * 1600).decode()
        await gateway.send(json.dumps({"realtimeInput": {"audio": {"data": payload}}}))
        emitted = json.loads(await anext(gateway.events()))
        assert emitted["serverContent"]["modelTurn"]["parts"][0]["inlineData"]["data"] == audio
        sent = [json.loads(call.args[0]) for call in socket.send.await_args_list]
        assert sent[0]["type"] == ("session.update" if protocol == "realtime" else "session.start")
        assert sent[1]["type"] == ("input_audio_buffer.append" if protocol == "realtime" else "session.input_audio.append")
        assert 4790 <= len(base64.b64decode(sent[1]["audio"])) <= 4800
    assert connect.call_args.kwargs["proxy"] is None
    logs = [(call.args[0], call.kwargs) for call in recorded.info.call_args_list]
    assert logs[0][0] == "assistant_openai_voice_ready"
    assert logs[0][1]["audio_output_enabled"] and logs[0][1]["automatic_response"]
    assert logs[-1][1]["input_audio_ms"] == logs[-1][1]["output_audio_ms"] == 100
    serialized = str(recorded.mock_calls)
    for private in ("sk-synthetic-private", "Private instructions", audio, payload):
        assert private not in serialized


@pytest.mark.parametrize("protocol", ["realtime", "live"])
async def test_rejected_setup_is_classified_without_logging_provider_content(monkeypatch, recorded, protocol):
    socket = Socket([{"type": "error", "event_id": "sk-private", "error": {
        "type": "invalid_request_error", "code": "invalid_value",
        "param": "session.audio.output.voice", "message": "Private user text and sk-private",
    }}])
    module = openai_live if protocol == "realtime" else openai_duplex
    monkeypatch.setattr(module, "FixedRealtimeConnect", lambda *args, **kwargs: Connection(socket))
    connection = openai_live.openai_live_connection(config("gpt-realtime-2.1"), [], "") if protocol == "realtime" else openai_duplex.duplex_connection(config("gpt-live-1"), "")
    with pytest.raises(AssistantError) as failed:
        async with connection:
            pytest.fail("A rejected setup cannot become ready")
    assert failed.value.code == "provider_configuration"
    warning = recorded.warning.call_args
    assert warning.kwargs["provider_code"] == "invalid_value"
    assert warning.kwargs["provider_param"] == "session.audio.output.voice"
    assert warning.kwargs["stage"] == "setup"
    assert "private" not in str(recorded.mock_calls).lower()
    assert "private" not in str(failed.value).lower()


@pytest.mark.parametrize("status,code", [(401, "provider_authentication"), (403, "provider_access"), (429, "provider_limit"), (503, "provider_unavailable")])
@pytest.mark.parametrize("protocol", ["realtime", "live"])
async def test_http_handshake_failure_has_safe_actionable_category(monkeypatch, recorded, protocol, status, code):
    class Rejected(Connection):
        async def __aenter__(self):
            raise InvalidStatus(Response(status, "Private provider detail", Headers(), b"sk-private"))
    module = openai_live if protocol == "realtime" else openai_duplex
    monkeypatch.setattr(module, "FixedRealtimeConnect", lambda *args, **kwargs: Rejected(None))
    connection = openai_live.openai_live_connection(config("gpt-realtime-2.1"), [], "") if protocol == "realtime" else openai_duplex.duplex_connection(config("gpt-live-1"), "")
    with pytest.raises(AssistantError) as failed:
        async with connection:
            pytest.fail("Rejected HTTP handshake cannot become ready")
    assert failed.value.code == code
    assert recorded.warning.call_args.kwargs["provider_http_status"] == status
    assert "private" not in str(recorded.mock_calls).lower()


@pytest.mark.parametrize("stage", ["setup", "stream", "response"])
def test_quota_is_not_misclassified_as_transient_rate_limit(recorded, stage):
    error = diagnostics.VoiceDiagnostics("realtime").error(
        {"error": {"code": "insufficient_quota", "message": "sk-private"}},
        stage=stage, http_status=429,
    )
    assert error.code == "provider_quota"
    assert "billing" in error.message
    assert recorded.warning.call_args.kwargs["category"] == "provider_quota"


def test_untrusted_error_fields_are_never_passed_through(recorded):
    value = diagnostics.error_metadata({
        "error": {"type": "sk-private", "code": "private-transcript", "param": "session.tools.sk-private"},
        "status": "private-status", "reason": "private-reason",
    }, http_status=True)
    assert set(value.values()) == {"unknown", None}


@pytest.mark.parametrize("provider_code,expected", [
    ("insufficient_quota", "provider_quota"),
    ("rate_limit_exceeded", "provider_rate_limit"),
])
def test_http_429_response_body_distinguishes_quota_from_rate_limit(recorded, provider_code, expected):
    body = json.dumps({"error": {"code": provider_code, "message": "sk-private"}}).encode()
    response = Response(429, "Limited", Headers(), body)
    error = diagnostics.VoiceDiagnostics("realtime").http_error(response)
    assert error.code == expected
    assert "private" not in str(recorded.mock_calls)


async def test_failed_response_logs_safe_status_and_preserves_quota_diagnosis(recorded):
    socket = Socket([{"type": "response.done", "response": {
        "status": "failed", "status_details": {"error": {
            "code": "insufficient_quota", "type": "insufficient_quota", "message": "sk-private",
        }},
        "output": [{"text": "private transcript"}],
    }}])
    stream = openai_live.RealtimeGateway(socket, config("gpt-realtime-2.1")).events()
    with pytest.raises(AssistantError) as failed:
        await anext(stream)
    assert failed.value.code == "provider_quota"
    assert recorded.warning.call_args.kwargs["provider_response_status"] == "failed"
    assert "private" not in str(recorded.mock_calls)


def test_lifecycle_counts_and_timings_contain_no_conversation_data(monkeypatch, recorded):
    ticks = iter([10.0, 10.1, 10.2, 10.8, 10.9, 10.9, 11.0])
    monkeypatch.setattr(diagnostics.time, "monotonic", lambda: next(ticks))
    observed = diagnostics.VoiceDiagnostics("realtime")
    observed.input(3200)
    observed.speech_started()
    observed.speech_stopped()
    observed.output(base64.b64encode(b"\x01\x00" * 2400).decode())
    observed.completed_responses = 1
    observed.closed()
    audio_started = recorded.info.call_args_list[-2].kwargs
    assert audio_started["after_speech_stop_ms"] == 100
    closed = recorded.info.call_args_list[-1].kwargs
    assert closed["input_audio_ms"] == closed["output_audio_ms"] == 100
    assert closed["speech_starts"] == closed["speech_stops"] == closed["completed_responses"] == 1
