"""Gemini wire contracts use synthetic transports, never billable requests."""

import base64
import io
import json
import wave

import httpx
import pytest
from pydantic import SecretStr

from app.application.assistant.contracts import AssistantError
from app.core.assistant_config import AssistantSettings
from app.infrastructure.assistant.gemini_live import live_setup
from app.infrastructure.assistant.gemini_provider import (
    GeminiAssistantProvider,
    gemini_contents,
    pcm_wave,
)


def settings():
    return AssistantSettings(
        provider="gemini",
        gemini_api_key=SecretStr("synthetic-provider-key"),
        model="gemini-3.8-flash",
        live_model="gemini-3.8-live",
        voice="Zephyr",
        _env_file=None,
    )


async def test_native_function_signature_survives_tool_roundtrip_and_thinking_is_private():
    signature = "synthetic-thought-signature"
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            text="data: "
            + json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"text": "private reasoning", "thought": True},
                                    {
                                        "functionCall": {
                                            "id": "call-1",
                                            "name": "read_dashboard",
                                            "args": {"view": "group_details"},
                                        },
                                        "thoughtSignature": signature,
                                    },
                                ]
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 11,
                        "candidatesTokenCount": 7,
                        "thoughtsTokenCount": 9,
                    },
                }
            )
            + "\n\n",
            headers={"Content-Type": "text/event-stream"},
        )

    provider = GeminiAssistantProvider(settings(), httpx.MockTransport(handler))
    inputs = [{"role": "user", "content": "Check my group"}]
    events = [
        event
        async for event in provider.responses(
            inputs,
            [
                {
                    "name": "read_dashboard",
                    "description": "Read current facts",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
            "Safe instructions",
        )
    ]
    assert len(events) == 1  # Private thought text never becomes a visible delta.
    completed = events[0]["response"]
    assert completed["usage"] == {"input_tokens": 11, "output_tokens": 16}
    rebuilt = gemini_contents(
        [
            *inputs,
            *completed["output"],
            {"type": "function_call_output", "call_id": "call-1", "output": '{"pending":3}'},
        ]
    )
    assert rebuilt[1]["parts"][1]["thoughtSignature"] == signature
    assert rebuilt[-1]["parts"][0]["functionResponse"]["name"] == "read_dashboard"
    assert rebuilt[-1]["parts"][0]["functionResponse"]["id"] == "call-1"
    assert rebuilt[-1]["parts"][0]["functionResponse"]["response"]["result"]["pending"] == 3
    request = seen[0]
    assert request.url.host == "generativelanguage.googleapis.com"
    assert request.url.path == "/v1beta/models/gemini-3.8-flash:streamGenerateContent"
    assert "key" not in request.url.params
    assert request.headers["x-goog-api-key"] == "synthetic-provider-key"
    assert (
        json.loads(request.content)["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "HIGH"
    )


async def test_no_tools_omits_empty_tool_definitions_and_text_streams():
    def handler(request):
        assert "tools" not in json.loads(request.content)
        return httpx.Response(
            200,
            text='data: {"candidates":[{"content":{"parts":[{"text":"Hello"}]},"finishReason":"STOP"}]}\n\n',
        )

    events = [
        event
        async for event in GeminiAssistantProvider(
            settings(), httpx.MockTransport(handler)
        ).responses([{"role": "user", "content": "Hello"}], [], "Safe")
    ]
    assert events[0] == {"type": "delta", "text": "Hello"}


@pytest.mark.parametrize("code", [301, 400, 401, 403, 429, 500])
async def test_provider_errors_do_not_forward_bodies_or_credentials(code):
    def handler(request):
        return httpx.Response(
            code,
            text="private provider details synthetic-provider-key",
            headers={"Location": "https://attacker.example.test"},
        )

    with pytest.raises(AssistantError) as failure:
        _ = [
            event
            async for event in GeminiAssistantProvider(
                settings(), httpx.MockTransport(handler)
            ).responses([{"role": "user", "content": "Hello"}], [], "Safe")
        ]
    assert "private provider" not in str(failure.value)
    assert "synthetic-provider-key" not in str(failure.value)


def test_live_setup_uses_native_audio_and_blocking_reads_without_unsupported_thinking_flag():
    payload = live_setup(
        settings(),
        [
            {
                "name": "read_dashboard",
                "description": "Safe read",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "Read before answering",
    )
    setup = payload["setup"]
    assert setup["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert "thinkingConfig" not in setup["generationConfig"]
    assert "inputAudioTranscription" in setup and "outputAudioTranscription" in setup
    assert setup["tools"][0]["functionDeclarations"][0]["behavior"] == "BLOCKING"
    assert "synthetic-provider-key" not in json.dumps(payload)


def test_audio_wave_has_real_pcm_format_and_rejects_invalid_lengths():
    pcm = base64.b64decode("AAABAAIAAwA=")
    with wave.open(io.BytesIO(pcm_wave(pcm)), "rb") as audio:
        assert audio.getframerate() == 24000 and audio.getnchannels() == 1
        assert audio.readframes(4) == pcm
    for value in (b"", b"x", b"x" * (8 * 1024 * 1024 + 2)):
        with pytest.raises(AssistantError):
            pcm_wave(value)
