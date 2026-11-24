"""Account discovery and model-dependent controls without provider billing."""

import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.application.assistant.model_capabilities import (
    gemini_thinking,
    is_nonconversational_voice_model,
    reasoning_options,
    voice_options,
)
from app.application.assistant.settings_contracts import AssistantConfiguration
from app.infrastructure.assistant import model_catalog as catalog
from app.infrastructure.assistant.settings_store import AssistantSnapshot


async def test_discovery_combines_paginated_accounts_and_extended_voices(monkeypatch):
    monkeypatch.setattr(catalog, "provider_key", lambda snapshot, provider: SecretStr("synthetic-" + provider))
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "api.openai.com":
            assert request.headers["authorization"] == "Bearer synthetic-openai"
            assert "x-goog-api-key" not in request.headers
            return httpx.Response(200, json={"data": [{"id": name} for name in ["gpt-6-luna", "gpt-7-future", "gpt-realtime-2.1", "gpt-live-1", "text-embedding-3-small", "gpt-image-1"]]})
        assert request.headers["x-goog-api-key"] == "synthetic-gemini"
        assert "authorization" not in request.headers
        if request.url.path.endswith("/voices"):
            return httpx.Response(200, json={"voices": [{"id": "voice_synthetic", "display_name": "New library voice", "gender": "male"}]})
        if request.url.params.get("pageToken") == "next":
            return httpx.Response(200, json={"models": [{"name": "models/gemini-2.5-flash-native-audio-preview-09-2025", "supportedGenerationMethods": ["bidiGenerateContent"]}]})
        return httpx.Response(200, json={"models": [{"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]}, {"name": "models/gemini-3.8-live"}], "nextPageToken": "next"})

    result = await catalog.model_catalog(AssistantSnapshot(revision=7), httpx.MockTransport(handler))
    models = {item["id"]: item for item in result["models"]}
    assert result["revision"] == 7
    assert all(item["status"] == "ready" for item in result["providers"])
    assert models["openai:gpt-7-future"]["reasoning"] == []
    assert models["openai:gpt-live-1"]["kind"] == "voice"
    assert len(models["openai:gpt-live-1"]["voices"]) == 31
    assert models["gemini:gemini-2.5-flash-native-audio-preview-09-2025"]["kind"] == "voice"
    assert models["gemini:gemini-3.8-live"]["voices"][-1]["appearance"] == "male"
    assert not any("image" in item or "embedding" in item for item in models)
    assert "synthetic-openai" not in json.dumps(result)
    assert all(request.url.path.startswith(("/v1/", "/v1beta/")) for request in requests)


async def test_partial_failure_is_redacted_and_preserves_saved_selection(monkeypatch):
    monkeypatch.setattr(catalog, "provider_key", lambda snapshot, provider: SecretStr("synthetic-secret"))

    def handler(request):
        if request.url.host == "api.openai.com":
            return httpx.Response(403, json={"error": "synthetic-secret private project"})
        return httpx.Response(200, json={"models": [{"name": "models/gemini-3.8-flash"}]})

    snapshot = AssistantSnapshot(configuration=AssistantConfiguration(chat_model="openai:gpt-6-luna"))
    result = await catalog.model_catalog(snapshot, httpx.MockTransport(handler))
    saved = next(item for item in result["models"] if item["id"] == "openai:gpt-6-luna")
    assert not saved["available"]
    assert result["providers"][0]["status"] == "unavailable"
    assert result["providers"][1]["status"] == "ready"
    assert "synthetic-secret" not in json.dumps(result)


async def test_specialized_realtime_models_are_not_offered_as_conversational_voice(monkeypatch):
    monkeypatch.setattr(catalog, "provider_key", lambda snapshot, provider: SecretStr("synthetic-" + provider))

    def handler(request):
        if request.url.host == "api.openai.com":
            return httpx.Response(200, json={"data": [{"id": name} for name in [
                "gpt-realtime-translate", "gpt-realtime-translate-2026-10-06",
                "gpt-realtime-2.1", "gpt-4o-realtime-preview-2025-06-03", "gpt-live-1",
            ]]})
        if request.url.path.endswith("/voices"):
            return httpx.Response(404)
        # These specialized models really advertise Live API support, but their
        # output is text. A bidi method alone cannot establish speech support.
        return httpx.Response(200, json={"models": [
            {"name": "models/" + name, "supportedGenerationMethods": ["bidiGenerateContent"]}
            for name in [
                "gemini-3.5-transcribe-live", "gemini-robotics-er-2-streaming-preview",
                "gemini-3.8-live", "gemini-2.5-flash-native-audio-preview-09-2025",
                "gemini-future-conversation",
            ]
        ]})

    # A selection saved before the filter stays readable, but cannot re-enter
    # the selectable catalog through the "preserve saved model" fallback.
    snapshot = AssistantSnapshot(configuration=AssistantConfiguration(
        voice_model="openai:gpt-realtime-translate",
    ))
    result = await catalog.model_catalog(snapshot, httpx.MockTransport(handler))
    voices = {item["id"] for item in result["models"] if item["kind"] == "voice"}
    assert voices == {
        "openai:gpt-realtime-2.1", "openai:gpt-4o-realtime-preview-2025-06-03",
        "openai:gpt-live-1", "gemini:gemini-3.8-live",
        "gemini:gemini-2.5-flash-native-audio-preview-09-2025",
        "gemini:gemini-future-conversation",
    }
    assert all(item["status"] == "ready" for item in result["providers"])
    assert snapshot.configuration.voice_model == "openai:gpt-realtime-translate"


@pytest.mark.parametrize("provider,model", [
    ("openai", "gpt-realtime-translate"),
    ("openai", "gpt-realtime-translate-2026-10-06"),
    ("gemini", "gemini-3.5-transcribe-live"),
    ("gemini", "gemini-robotics-er-2-streaming-preview"),
])
def test_specialized_voice_protocol_is_identifiable_without_discovery(provider, model):
    assert is_nonconversational_voice_model(provider, model)


@pytest.mark.parametrize("model,efforts", [
    ("openai:gpt-4.1", []),
    ("openai:gpt-6.1-sol", ["low", "medium", "high", "xhigh", "max"]),
    ("openai:gpt-realtime-2.1", ["low", "medium", "high"]),
    ("openai:gpt-realtime", []),
    ("gemini:gemini-3-pro-preview", ["low", "high"]),
    ("gemini:gemini-3.8-live", []),
    ("gemini:gemini-3.8-live-extended-thinking", ["low", "medium", "high"]),
])
def test_reasoning_follows_protocol_capability(model, efforts):
    assert reasoning_options(*model.split(":")) == efforts


@pytest.mark.parametrize("changes", [
    {"chat_model": "openai:gpt-4.1", "chat_reasoning": "high"},
    {"voice_model": "openai:gpt-realtime", "voice_name": "Kore"},
    {"voice_model": "openai:gpt-4o-realtime-preview", "voice_name": "marin"},
    {"voice_model": "gemini:gemini-3.8-live", "voice_reasoning": "high"},
    {"chat_model": "https://attacker.test/model"},
    {"voice_model": "openai:gpt-4.1"},
])
def test_incompatible_settings_are_rejected(changes):
    with pytest.raises(ValidationError):
        AssistantConfiguration(**changes)


def test_gemini_budgets_and_voice_presentations():
    assert gemini_thinking("gemini-2.5-pro", "high") == {"thinkingConfig": {"thinkingBudget": 24576}}
    assert gemini_thinking("gemini-3.8-live", "high") == {}
    assert gemini_thinking("gemini-3.1-pro-preview", "medium") == {"thinkingConfig": {"thinkingLevel": "MEDIUM"}}
    assert len(voice_options("gemini", "gemini-3.8-live")) == 30
    assert len(voice_options("openai", "gpt-4o-realtime-preview")) == 8
    assert {item["appearance"] for item in voice_options("openai", "gpt-live-1")} == {"male", "female"}
