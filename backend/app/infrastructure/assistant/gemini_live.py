"""Native audio transport: fixed Google origin, header-only key, no redirects."""

import logging
from typing import Any

from websockets.asyncio.client import connect

from app.core.assistant_config import AssistantSettings
from app.infrastructure.assistant.gemini_provider import function_declarations

LIVE_ORIGIN = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
transport_logger = logging.getLogger("assistant.private_gemini_transport")
transport_logger.addHandler(logging.NullHandler())
transport_logger.propagate = False


class FixedGeminiConnect(connect):
    def process_redirect(self, exc: Exception) -> Exception:
        return PermissionError("The voice provider redirected its connection")


def live_connection(settings: AssistantSettings) -> FixedGeminiConnect:
    return FixedGeminiConnect(
        LIVE_ORIGIN,
        additional_headers={"x-goog-api-key": settings.gemini_api_key.get_secret_value()},
        proxy=None,
        compression=None,
        open_timeout=10,
        close_timeout=3,
        max_size=512 * 1024,
        max_queue=4,
        logger=transport_logger,
    )


def live_setup(
    settings: AssistantSettings, tools: list[dict[str, Any]], instructions: str
) -> dict[str, Any]:
    # 3.8 Live does not accept thinkingConfig. Its Extended Thinking variant is
    # selected by model ID, rather than sending an incompatible thinking level.
    return {
        "setup": {
            "model": "models/" + settings.live_model,
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": settings.voice}}
                },
            },
            "systemInstruction": {"parts": [{"text": instructions}]},
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
            "contextWindowCompression": {"triggerTokens": 24576, "slidingWindow": {"targetTokens": 16384}},
            "tools": [{"functionDeclarations": function_declarations(tools, live=True)}],
        }
    }
