"""Content-free diagnostics for the OpenAI voice boundary.

Provider error messages can echo user content and credentials. Only enumerated
protocol fields, counters and timings cross into application logs.
"""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from app.application.assistant.contracts import AssistantError
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

ERROR_CODES = frozenset({
    "invalid_api_key", "authentication_error", "insufficient_quota",
    "rate_limit_exceeded", "model_not_found", "permission_denied",
    "unsupported_parameter", "unsupported_value", "invalid_value", "invalid_type",
    "missing_required_parameter", "invalid_request_error", "invalid_session_update",
    "session_expired", "server_error", "internal_error", "invalid_json",
    "input_audio_buffer_commit_empty", "response_cancel_not_active",
    "conversation_already_has_active_response",
})
ERROR_TYPES = frozenset({
    "invalid_request_error", "authentication_error", "permission_error",
    "rate_limit_error", "insufficient_quota", "server_error", "error",
})
ERROR_PARAMS = frozenset({
    "model", "voice", "audio", "session", "session.model", "session.voice",
    "session.audio", "session.audio.format", "session.audio.input",
    "session.audio.input.format", "session.audio.input.format.rate",
    "session.audio.input.transcription", "session.audio.input.transcription.model",
    "session.audio.input.turn_detection", "session.audio.input.noise_reduction",
    "session.audio.output", "session.audio.output.voice",
    "session.audio.output.format", "session.audio.output.format.rate",
    "session.output_modalities", "session.reasoning", "session.reasoning.effort",
    "session.tools", "session.tool_choice", "session.delegation", "session.input",
    "response", "response.output_modalities",
})


def _enum(value: Any, allowed: frozenset[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "unknown"


def error_metadata(event: dict[str, Any], http_status: int | None = None) -> dict[str, Any]:
    error = event.get("error")
    error = error if isinstance(error, dict) else {}
    return {
        "provider_code": _enum(error.get("code"), ERROR_CODES),
        "provider_type": _enum(error.get("type"), ERROR_TYPES),
        "provider_param": _enum(error.get("param"), ERROR_PARAMS),
        "provider_http_status": http_status if type(http_status) is int and 400 <= http_status <= 599 else None,
        "provider_response_status": _enum(event.get("status"), frozenset({"failed", "incomplete", "cancelled", "completed"})),
        "provider_reason": _enum(event.get("reason"), frozenset({"max_output_tokens", "content_filter", "client_cancelled", "turn_detected"})),
    }


class VoiceDiagnostics:
    def __init__(self, protocol: Literal["realtime", "live"]):
        self.protocol = protocol
        self.started = time.monotonic()
        self.input_frames = self.input_bytes = self.output_frames = self.output_bytes = 0
        self.speech_starts = self.speech_stops = self.completed_responses = 0
        self.last_speech_stop: float | None = None

    def elapsed_ms(self) -> int:
        return round((time.monotonic() - self.started) * 1000)

    def accepted(self, session: dict[str, Any]) -> None:
        audio = session.get("audio")
        audio = audio if isinstance(audio, dict) else {}
        audio_input = audio.get("input")
        audio_input = audio_input if isinstance(audio_input, dict) else {}
        vad = audio_input.get("turn_detection")
        vad = vad if isinstance(vad, dict) else {}
        modalities = session.get("output_modalities")
        logger.info(
            "assistant_openai_voice_ready", protocol=self.protocol,
            handshake_ms=self.elapsed_ms(),
            audio_output_enabled=isinstance(modalities, list) and "audio" in modalities if self.protocol == "realtime" else True,
            automatic_response=vad.get("create_response") is True if self.protocol == "realtime" else True,
            turn_detection=_enum(vad.get("type"), frozenset({"server_vad", "semantic_vad"})),
        )

    def input(self, size: int) -> None:
        self.input_frames += 1
        self.input_bytes += size
        if self.input_frames == 1:
            logger.info("assistant_openai_voice_input_started", protocol=self.protocol, elapsed_ms=self.elapsed_ms())

    def speech_started(self) -> None:
        self.speech_starts += 1
        if self.speech_starts == 1:
            logger.info("assistant_openai_voice_speech_detected", protocol=self.protocol, elapsed_ms=self.elapsed_ms())

    def speech_stopped(self) -> None:
        self.speech_stops += 1
        self.last_speech_stop = time.monotonic()

    def output(self, encoded: str) -> None:
        self.output_frames += 1
        padding = len(encoded) - len(encoded.rstrip("="))
        self.output_bytes += len(encoded) * 3 // 4 - padding
        if self.output_frames == 1:
            logger.info(
                "assistant_openai_voice_audio_started", protocol=self.protocol,
                elapsed_ms=self.elapsed_ms(),
                after_speech_stop_ms=round((time.monotonic() - self.last_speech_stop) * 1000) if self.last_speech_stop is not None else None,
            )

    def error(self, event: dict[str, Any], *, stage: Literal["setup", "stream", "response"], http_status: int | None = None) -> AssistantError:
        fields = error_metadata(event, http_status)
        code, category = fields["provider_code"], fields["provider_type"]
        if code == "insufficient_quota" or category == "insufficient_quota":
            result = AssistantError("provider_quota", "OpenAI voice has exhausted its API quota or credits. Check the OpenAI project's billing and limits.", 429)
        elif code == "rate_limit_exceeded" or category == "rate_limit_error":
            result = AssistantError("provider_rate_limit", "OpenAI voice is rate limited. Wait briefly, then reconnect.", 429)
        elif http_status == 429:
            result = AssistantError("provider_limit", "OpenAI voice reached a provider usage limit. Check the project's quota and rate limits.", 429)
        elif code in {"invalid_api_key", "authentication_error"} or category == "authentication_error" or http_status == 401:
            result = AssistantError("provider_authentication", "OpenAI rejected the saved API key. Check the OpenAI key in AI settings.", 422)
        elif code in {"model_not_found", "permission_denied"} or category == "permission_error" or http_status == 403:
            result = AssistantError("provider_access", "The OpenAI project cannot use this voice model. Choose an available voice model or check the project's access.", 422)
        elif http_status is not None and http_status >= 500:
            result = AssistantError("provider_unavailable", "OpenAI voice is temporarily unavailable. Reconnect to try again.")
        elif stage == "setup" or category == "invalid_request_error":
            result = AssistantError("provider_configuration", "OpenAI did not accept the voice configuration. Check the selected model and voice in AI settings.", 422)
        elif stage == "response":
            result = AssistantError("voice_incomplete", "The voice answer could not finish. Please try again.")
        else:
            result = AssistantError("provider_unavailable", "OpenAI voice could not complete this session. Reconnect to try again.")
        logger.warning("assistant_openai_voice_error", protocol=self.protocol, stage=stage, category=result.code, **fields)
        return result

    def http_error(self, response: Any) -> AssistantError:
        event: dict[str, Any] = {}
        body = getattr(response, "body", None)
        if isinstance(body, (str, bytes, bytearray)) and len(body) <= 32768:
            try:
                decoded = json.loads(body)
                if isinstance(decoded, dict):
                    event = decoded
            except (ValueError, UnicodeError):
                pass
        return self.error(event, stage="setup", http_status=getattr(response, "status_code", None))

    def closed(self) -> None:
        logger.info(
            "assistant_openai_voice_closed", protocol=self.protocol, elapsed_ms=self.elapsed_ms(),
            input_frames=self.input_frames, input_audio_ms=self.input_bytes // 32,
            output_frames=self.output_frames, output_audio_ms=self.output_bytes // 48,
            speech_starts=self.speech_starts, speech_stops=self.speech_stops,
            completed_responses=self.completed_responses,
        )
