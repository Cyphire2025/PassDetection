"""Authorized voice recovery, held disclaimers, audio, denial and cancellation."""

import asyncio
import base64
import io
import json
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Request

from app.application.assistant.contracts import AssistantError
from app.core.assistant_config import AssistantSettings
from app.domain.entities.entities import User, UserRole
from app.presentation.assistant import native_session
from app.presentation.assistant.native_recovery import recoverable_access_disclaimer


def fixture_wave():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x00\x00" * 2400)
    return stream.getvalue()


@pytest.fixture
def conversation(monkeypatch):
    actor = User.create("recovery@example.test", "fixture", "Reader", UserRole.SUPER_ADMIN)
    monkeypatch.setattr(native_session, "fresh_actor", AsyncMock(return_value=actor))
    read = AsyncMock(return_value={"view": "passport_details", "observed_at": "2026-10-18T00:00:00Z",
        "completeness": "complete", "data": {"client_email": "ada@example.test"}})
    monkeypatch.setattr(native_session.MCPAssistantBridge, "dispatch", read)
    store = SimpleNamespace(create_conversation=AsyncMock(), turns=AsyncMock(return_value={"items": []}), save_turn=AsyncMock())
    send = AsyncMock()
    session = native_session.NativeSession(Request({"type": "http", "headers": []}), actor,
        AssistantSettings(provider="gemini", _env_file=None), store, uuid4(), send)

    class Provider:
        calls = 0
        speak = AsyncMock(return_value=fixture_wave())

        async def responses(self, inputs, tools, instructions):
            assert "create_images" not in {tool["name"] for tool in tools}
            assert "current workspace write permissions" in instructions
            self.calls += 1
            if self.calls == 1:
                yield {"type": "completed", "response": {"output": [{"type": "function_call",
                    "name": "call_mcp_tool", "call_id": "lookup", "arguments": json.dumps({
                        "tool_name": "passport_details", "arguments_json": json.dumps({"submission_id": str(uuid4())})})}]}}
            else:
                assert "ada@example.test" in json.dumps(inputs)
                yield {"type": "delta", "text": "Ada's saved email is ada@example.test."}
                yield {"type": "completed", "response": {"output": []}}
    session.provider = Provider()
    session.speech_provider = session.provider
    return session, send, store, read


async def refusal(session):
    await session.consume({"serverContent": {
        "inputTranscription": {"text": "Tell me Ada's email in that group."},
        "outputTranscription": {"text": "I'm just a language model and can't help with that."},
        "modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": base64.b64encode(b"\x00\x00" * 1600).decode()}}]},
    }})


async def test_recovery_uses_read_tools_and_replaces_refusal_with_saved_text_and_speech(conversation):
    session, send, store, read = conversation
    await refusal(session)
    assert [call.args[0]["type"] for call in send.await_args_list] == ["input_transcript"]
    await session.consume({"serverContent": {"turnComplete": True}})
    events = [call.args[0] for call in send.await_args_list]
    assert [item["type"] for item in events] == ["input_transcript", "answer_reset", "status", "status", "source", "text_delta", "audio", "turn_complete"]
    assert all("just a language model" not in json.dumps(item) for item in events)
    read.assert_awaited_once()
    turn = store.save_turn.await_args.args[2]
    assert turn["assistant"] == "Ada's saved email is ada@example.test."
    assert turn["sources"][0]["view"] == "passport_details"
    assert turn["recovery_model"] == session.settings.model
    assert not session.recovering and session.recovery_done.is_set()
    assert session.input == session.output == ""
    assert session.recoveries == 1
    assert events[-2]["sample_rate"] == 24000
    assert base64.b64decode(events[-2]["data"]) == b"\x00\x00" * 2400
    assert "audio" not in turn


async def test_explicit_authorization_denial_is_never_retried_or_spoken(conversation):
    session, send, store, read = conversation
    read.side_effect = AssistantError("view_denied", "Outside this account's access.", 403)
    await refusal(session)
    with pytest.raises(AssistantError) as denied:
        await session.consume({"serverContent": {"turnComplete": True}})
    assert denied.value.status == 403
    session.provider.speak.assert_not_awaited()
    store.save_turn.assert_not_awaited()
    assert not any(call.args[0]["type"] == "audio" for call in send.await_args_list)
    assert session.recovery_done.is_set()


async def test_explicit_provider_error_does_not_start_recovery(conversation):
    session, _, store, _ = conversation
    with pytest.raises(AssistantError):
        await session.consume({"error": {"status": "SAFETY"}})
    assert session.provider.calls == 0 and session.recoveries == 0
    store.save_turn.assert_not_awaited()


async def test_uncertain_mcp_operation_is_never_repeated_by_voice_recovery(conversation):
    session, _, store, dispatch = conversation
    dispatch.side_effect = AssistantError("mcp_operation_failed", "Inspect operation status before retrying.", 503)
    await session.tool_calls([{"id": "change-1", "name": "call_mcp_tool", "args": {"tool_name": "update_group", "arguments_json": "{}"}}])
    await refusal(session)
    await session.consume({"serverContent": {"turnComplete": True}})
    dispatch.assert_awaited_once()
    assert session.provider.calls == 0
    assert session.recoveries == 0
    store.save_turn.assert_awaited_once()
    assert not session.attempted_mcp_operation


async def test_normal_reply_releases_early_audio_and_uses_no_recovery(conversation):
    session, send, store, _ = conversation
    await session.caption("input_transcript", "Show my group's people")
    await session.caption("text_delta", "I'm just ")
    assert len(send.await_args_list) == 1
    await session.caption("text_delta", "checking the roster. There are seven people.")
    await session.consume({"serverContent": {"turnComplete": True}})
    assert session.provider.calls == 0 and session.recoveries == 0
    assert store.save_turn.await_args.args[2]["assistant"].endswith("seven people.")


async def test_cancelled_lookup_releases_recovery_gate_and_does_not_save_a_false_answer(conversation, monkeypatch):
    session, _, store, _ = conversation
    entered = asyncio.Event()
    async def pending(_session):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(native_session, "recover_answer", pending)
    await refusal(session)
    task = asyncio.create_task(session.consume({"serverContent": {"turnComplete": True}}))
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert session.recovering and not session.recovery_done.is_set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not session.recovering and session.recovery_done.is_set()
    store.save_turn.assert_not_awaited()


async def test_speech_failure_keeps_verified_text_and_session_usable(conversation):
    session, _, store, _ = conversation
    session.provider.speak.side_effect = AssistantError("speech_unavailable", "Speech unavailable.")
    await refusal(session)
    await session.consume({"serverContent": {"turnComplete": True}})
    saved = store.save_turn.await_args.args[2]
    assert "ada@example.test" in saved["assistant"]
    assert "Spoken playback was unavailable" in saved["assistant"]
    assert not session.recovering


@pytest.mark.parametrize("question, answer, expected", [
    ("How many people in the group?", "The participant counts or member lists are currently unavailable through the dashboard tools.", True),
    ("Show the active WhatsApp topics", "Unfortunately, the active WhatsApp topics are not available through the dashboard tools.", True),
    ("Tell me the weather", "I'm just a language model and can't help with that.", False),
    ("Tell me the group's people", "I'm just checking the roster.", False),
])
def test_recovery_is_limited_to_business_access_disclaimers(question, answer, expected):
    assert recoverable_access_disclaimer(question, answer) is expected
