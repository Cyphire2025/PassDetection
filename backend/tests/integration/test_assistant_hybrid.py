"""Hybrid routing and one private history across text and native voice."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request, Response

from app.application.assistant.contracts import ChatRequest
from app.application.assistant.settings_contracts import (
    AssistantConfiguration,
    AssistantSettingsUpdate,
)
from app.core.assistant_config import AssistantSettings
from app.infrastructure.assistant import settings_store
from app.infrastructure.assistant.provider import OpenAIAssistantProvider
from app.infrastructure.assistant.settings_store import runtime_settings, save_settings
from app.presentation.api.v1.routes.ai_assistant import assistant_status
from app.presentation.assistant import chat, native_session
from tests.integration.test_assistant_read_only import workspace as workspace


@asynccontextmanager
async def admitted(*args, **kwargs):
    yield


@pytest.mark.parametrize("effort", ["none", "low", "medium", "high", "xhigh", "max"])
async def test_combined_mode_routes_keys_and_reasoning_without_exposing_them(workspace, monkeypatch, effort):
    db, actor, *_ = workspace
    monkeypatch.setattr(settings_store, "get_assistant_settings", lambda: AssistantSettings(_env_file=None, openai_api_key="", gemini_api_key=""))
    saved = await save_settings(db, actor, AssistantSettingsUpdate(expected_revision=0,
        configuration=AssistantConfiguration(provider="hybrid", openai_reasoning_effort=effort),
        openai_api_key="synthetic-openai-hybrid", gemini_api_key="synthetic-gemini-hybrid"))
    text = await runtime_settings(db)
    voice = await runtime_settings(db, purpose="voice")
    assert text.provider == "openai" and text.model == "gpt-6-luna" and text.reasoning_effort == effort
    assert voice.provider == "gemini" and voice.live_model == "gemini-3.8-live" and voice.voice == "Zephyr"
    assert text.openai_api_key.get_secret_value() == "synthetic-openai-hybrid"
    assert voice.gemini_api_key.get_secret_value() == "synthetic-gemini-hybrid"
    session = native_session.NativeSession(Request({"type":"http","headers":[]}), actor, voice, SimpleNamespace(), uuid4(), AsyncMock())
    assert isinstance(session.provider, OpenAIAssistantProvider)
    assert session.text_settings.reasoning_effort == effort
    assert session.speech_provider.settings.provider == "gemini"
    status = await assistant_status(Response(), actor, text)
    assert status["native_voice"] and status["speech_configured"] and status["mode"] == "hybrid"
    assert status["provider"] == "openai" and status["voice_provider"] == "gemini"
    assert status["speech_model"] == "gemini-3.1-flash-tts-preview"
    assert "synthetic-openai-hybrid" not in json.dumps(status)
    assert saved.configuration.openai_reasoning_effort == effort


async def test_spoken_captions_and_typed_answers_share_context_both_directions(workspace, monkeypatch):
    _, actor, _, _, _, _, store = workspace
    monkeypatch.setattr(chat, "assistant_admission", admitted)
    monkeypatch.setattr(native_session, "fresh_actor", AsyncMock(return_value=actor))
    conversation = uuid4()
    request = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=False), scope={"type":"http","app":FastAPI()})

    class TextProvider:
        contexts = []
        def require_ready(self):pass
        async def responses(self, inputs, tools, instructions):
            self.contexts.append(json.dumps(inputs))
            yield {"type":"delta","text":"Luna's typed reply."}
            yield {"type":"completed","response":{"output":[],"usage":{}}}

    provider = TextProvider()
    text_settings = AssistantSettings(openai_api_key="synthetic-key", _env_file=None)
    first = ChatRequest(request_id=uuid4(), conversation_id=conversation, text="Remember the synthetic departure.")
    _ = [event async for event in chat.chat_events(request, actor, first, text_settings, store, provider)]
    spoken = native_session.NativeSession(Request({"type":"http","headers":[]}), actor,
        AssistantSettings(provider="gemini", mode="hybrid", openai_api_key="synthetic-key", _env_file=None), store, conversation, AsyncMock())
    instructions, _ = await spoken.context()
    assert "Remember the synthetic departure." in instructions and "Luna's typed reply." in instructions
    await spoken.consume({"serverContent":{"inputTranscription":{"text":"Now check the same trip."},
        "outputTranscription":{"text":"Gemini's spoken reply."},"turnComplete":True}})
    followup = ChatRequest(request_id=uuid4(), conversation_id=conversation, text="Continue from that voice answer.")
    _ = [event async for event in chat.chat_events(request, actor, followup, text_settings, store, provider)]
    assert "Now check the same trip." in provider.contexts[-1] and "Gemini's spoken reply." in provider.contexts[-1]
    assert len((await store.turns(conversation))["items"]) == 3
