"""Native PCM gateway bounds, sanitized protocol and real session persistence."""

import base64
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.application.assistant.contracts import AssistantError
from app.core.assistant_config import AssistantSettings
from app.domain.entities.entities import User, UserRole
from app.presentation.api.v1.routes import ai_assistant_voice as voice
from app.presentation.assistant import native_session


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "https://attacker.example.test"},
        {"Origin": "http://testserver", "Authorization": "Bearer synthetic"},
    ],
)
def test_voice_rejects_missing_cookie_cross_origin_and_query_credentials_before_upstream(headers):
    app = FastAPI()
    app.include_router(voice.router, prefix="/api/v1/ai-assistant")
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/api/v1/ai-assistant/voice?api_key=synthetic", headers=headers
        ):
            pass


async def test_gateway_sends_pcm_directly_and_typed_input_is_a_caption():
    pcm = base64.b64encode(b"\x00\x00" * 1600).decode()
    messages = iter(
        [
            json.dumps({"type": "audio", "data": pcm}),
            json.dumps({"type": "text", "text": "Check the departure"}),
            json.dumps({"type": "audio_end"}),
            json.dumps({"type": "unexpected"}),
        ]
    )
    socket = SimpleNamespace(receive_text=AsyncMock(side_effect=lambda: next(messages)))
    upstream = SimpleNamespace(send=AsyncMock())
    conversation = SimpleNamespace(caption=AsyncMock())
    with pytest.raises(AssistantError) as invalid:
        await voice._client_audio(socket, upstream, conversation)
    assert invalid.value.code == "voice_protocol"
    sent = [json.loads(call.args[0]) for call in upstream.send.await_args_list]
    assert sent[0] == {
        "realtimeInput": {"audio": {"mimeType": "audio/pcm;rate=16000", "data": pcm}}
    }
    assert sent[1]["clientContent"]["turnComplete"] is True
    assert sent[2]["realtimeInput"]["audioStreamEnd"] is True
    conversation.caption.assert_awaited_once_with("input_transcript", "Check the departure")


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "audio", "data": "eA=="},
        {"type": "audio", "data": "AA==" * 10001},
        {"type": "text", "text": "x" * 8001},
        {"type": "audio", "data": "AAAA", "api_key": "forbidden"},
    ],
)
async def test_gateway_rejects_unbounded_or_arbitrary_protocol(payload):
    socket = SimpleNamespace(receive_text=AsyncMock(return_value=json.dumps(payload)))
    upstream = SimpleNamespace(send=AsyncMock())
    with pytest.raises((AssistantError, ValueError)):
        await voice._client_audio(socket, upstream, SimpleNamespace(caption=AsyncMock()))
    upstream.send.assert_not_awaited()


async def test_native_captions_audio_interruption_and_turn_persistence(monkeypatch):
    actor = User.create("native@example.test", "fixture", "Native", UserRole.SUPER_ADMIN)
    monkeypatch.setattr(native_session, "fresh_actor", AsyncMock(return_value=actor))
    store = SimpleNamespace(save_turn=AsyncMock())
    send = AsyncMock()
    session = native_session.NativeSession(
        Request({"type": "http", "headers": []}),
        actor,
        AssistantSettings(provider="gemini", _env_file=None),
        store,
        uuid4(),
        send,
    )
    pcm = base64.b64encode(b"\x00\x00" * 1600).decode()
    await session.consume(
        {
            "serverContent": {
                "inputTranscription": {"text": "How many pending?"},
                "outputTranscription": {"text": "There are three."},
                "modelTurn": {
                    "parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": pcm}}]
                },
            }
        }
    )
    await session.consume({"serverContent": {"interrupted": True}})
    turn = store.save_turn.await_args.args[2]
    assert turn["user"] == "How many pending?" and turn["interrupted"] is True
    assert turn["assistant"].startswith("There are three.")
    assert "audio" not in turn and "pcm" not in str(turn)
    events = [call.args[0] for call in send.await_args_list]
    assert [event["type"] for event in events] == [
        "input_transcript",
        "text_delta",
        "audio",
        "interrupted",
        "turn_complete",
    ]
    assert events[2]["sample_rate"] == 24000
    assert session.input == session.output == ""


async def test_dashboard_text_alone_cannot_authorize_image_generation(monkeypatch):
    actor = User.create("images@example.test", "fixture", "Images", UserRole.SUPER_ADMIN)
    session = native_session.NativeSession(
        Request({"type": "http", "headers": []}),
        actor,
        AssistantSettings(provider="gemini", _env_file=None),
        SimpleNamespace(),
        uuid4(),
        AsyncMock(),
    )
    with pytest.raises(AssistantError) as denied:
        await session.create_images({"prompt": "A paid image", "count": 4})
    assert denied.value.code == "image_confirmation"


@pytest.mark.parametrize("change", ["revision", "role", "agency", "session"])
async def test_live_heartbeat_ends_on_configuration_or_account_scope_changes(monkeypatch, change):
    actor = User.create("heartbeat@example.test", "fixture", "Heartbeat", UserRole.SUPER_ADMIN)
    settings = AssistantSettings(provider="gemini", revision=1, _env_file=None)
    updated_actor = actor
    updated_settings = settings
    if change == "revision":
        updated_settings = settings.model_copy(update={"revision": 2})
    elif change == "role":
        updated_actor = replace(actor, role=UserRole.AGENCY_MANAGER)
    elif change == "agency":
        updated_actor = replace(actor, agency_id=uuid4())
    else:
        updated_actor = replace(actor, session_version=actor.session_version + 1)
    monkeypatch.setattr(voice.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(
        voice, "authorize_voice", AsyncMock(return_value=(updated_actor, updated_settings))
    )
    send = AsyncMock()
    with pytest.raises(AssistantError) as ended:
        await voice._authorization_heartbeat(SimpleNamespace(), actor, settings, send)
    assert ended.value.status == 403
    send.assert_not_awaited()
