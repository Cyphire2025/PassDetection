"""Official OpenAI HTTP interfaces with fixed destinations and bounded streaming."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.application.assistant.contracts import AssistantError
from app.core.assistant_config import AssistantSettings
from app.infrastructure.assistant.realtime_speech import realtime_speech

OPENAI_ORIGIN = "https://api.openai.com/v1"


class OpenAIAssistantProvider:
    def __init__(
        self, settings: AssistantSettings, transport: httpx.AsyncBaseTransport | None = None
    ):
        self.settings = settings
        self.transport = transport

    def require_ready(self) -> None:
        if not self.settings.configured:
            raise AssistantError(
                "setup_pending",
                "Your assistant is being connected. Please try again when setup is complete.",
            )

    def _client(self) -> httpx.AsyncClient:
        self.require_ready()
        return httpx.AsyncClient(
            base_url=OPENAI_ORIGIN,
            headers={"Authorization": f"Bearer {self.settings.openai_api_key.get_secret_value()}"},
            timeout=httpx.Timeout(self.settings.timeout_seconds, connect=10),
            follow_redirects=False,
            transport=self.transport,
            limits=httpx.Limits(max_connections=2),
        )

    @staticmethod
    def _status(response: httpx.Response) -> None:
        if response.is_success:
            return
        if response.status_code == 429:
            raise AssistantError(
                "provider_limit",
                "The AI service has reached a usage limit. Please try again later.",
                429,
            )
        if response.status_code in {400, 401, 403, 404}:
            raise AssistantError(
                "provider_configuration",
                "The AI connection needs attention. Please contact your administrator.",
            )
        raise AssistantError(
            "provider_unavailable",
            "The AI service is temporarily unavailable. Your saved workspace is safe.",
        )

    async def responses(
        self, inputs: list[dict[str, Any]], tools: list[dict[str, Any]], instructions: str
    ) -> AsyncIterator[dict[str, Any]]:
        payload = {
            "model": self.settings.model,
            "reasoning": {"effort": "high"},
            "instructions": instructions,
            "input": inputs,
            "tools": tools,
            "max_output_tokens": self.settings.max_output_tokens,
            "store": False,
            "stream": True,
            "include": ["reasoning.encrypted_content"],
            "parallel_tool_calls": False,
        }
        terminal = False
        try:
            async with self._client() as client:
                async with client.stream("POST", "/responses", json=payload) as response:
                    self._status(response)
                    size = 0
                    async for line in response.aiter_lines():
                        size += len(line)
                        if size > 2 * 1024 * 1024 or len(line) > 256 * 1024:
                            raise AssistantError(
                                "response_limit",
                                "The AI response exceeded its safe size limit. Try a narrower question.",
                                413,
                            )
                        if not line.startswith("data: ") or line[6:] == "[DONE]":
                            continue
                        item = json.loads(line[6:])
                        event = item.get("type")
                        if event == "response.output_text.delta":
                            yield {"type": "delta", "text": item.get("delta", "")}
                        elif event == "response.completed":
                            terminal = True
                            yield {"type": "completed", "response": item["response"]}
                        elif event in {"response.failed", "response.incomplete", "error"}:
                            raise AssistantError(
                                "response_incomplete",
                                "The AI could not finish this answer. Try a shorter or more specific question.",
                            )
            if not terminal:
                raise AssistantError(
                    "connection_interrupted",
                    "The connection ended before the answer completed. Please try again.",
                )
        except AssistantError:
            raise
        except (httpx.HTTPError, ValueError, KeyError):
            raise AssistantError(
                "provider_unavailable", "The AI connection was interrupted. Please try again."
            ) from None

    async def transcribe(self, content: bytes, mime: str) -> str:
        try:
            async with self._client() as client:
                extension = "m4a" if "mp4" in mime else "ogg" if "ogg" in mime else "webm"
                response = await client.post(
                    "/audio/transcriptions",
                    data={"model": self.settings.transcription_model},
                    files={"file": (f"speech.{extension}", content, mime)},
                )
                self._status(response)
                text = response.json().get("text", "")
                if not isinstance(text, str) or len(text) > 8000:
                    raise AssistantError(
                        "transcript_limit", "Please use a shorter voice message.", 413
                    )
                return text.strip()
        except httpx.HTTPError:
            raise AssistantError(
                "speech_unavailable", "Your speech could not be transcribed. Please try again."
            ) from None

    async def speak(self, text: str) -> bytes:
        if not self.settings.speech_model:
            raise AssistantError(
                "speech_setup_pending",
                "Spoken replies will be available once your voice setup is selected.",
            )
        self.require_ready()
        if self.settings.speech_model.startswith("gpt-realtime-"):
            return await realtime_speech(self.settings, text)
        payload = {
            "model": self.settings.speech_model,
            "input": text,
            "voice": self.settings.voice
            if self.settings.speech_model == "gpt-4o-mini-tts"
            else "alloy",
            "response_format": "mp3",
        }
        try:
            async with self._client() as client:
                async with client.stream("POST", "/audio/speech", json=payload) as response:
                    self._status(response)
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > 8 * 1024 * 1024:
                            raise AssistantError(
                                "speech_limit",
                                "This reply is too long to speak. Read the full reply in the conversation.",
                                413,
                            )
                        data.extend(chunk)
                    return bytes(data)
        except httpx.HTTPError:
            raise AssistantError(
                "speech_unavailable",
                "The spoken reply is unavailable. You can still read the answer.",
            ) from None

    async def images(self, prompt: str, count: int) -> list[bytes]:
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST",
                    "/images/generations",
                    json={
                        "model": self.settings.image_model,
                        "prompt": prompt[:4000],
                        "n": count,
                        "size": "1536x1024",
                        "quality": "medium",
                        "output_format": "png",
                    },
                ) as response:
                    self._status(response)
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > 48 * 1024 * 1024:
                            raise AssistantError(
                                "image_limit",
                                "The generated images exceeded their safe size limit.",
                                413,
                            )
                        data.extend(chunk)
                    payload = json.loads(data)
                    rows = payload.get("data", [])
                    if not rows or len(rows) > count:
                        raise AssistantError(
                            "image_incomplete", "The image service could not complete this request."
                        )
                    return [base64.b64decode(row["b64_json"], validate=True) for row in rows]
        except (httpx.HTTPError, ValueError, KeyError):
            raise AssistantError(
                "image_unavailable", "The image service could not finish. Please try again."
            ) from None
