"""Fixed-origin Gemini REST adapter, preserving native function thought signatures."""

from __future__ import annotations

import base64
import io
import json
import wave
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
from PIL import Image

from app.application.assistant.contracts import AssistantError
from app.core.assistant_config import AssistantSettings
from app.infrastructure.assistant.provider import OpenAIAssistantProvider

GEMINI_ORIGIN = "https://generativelanguage.googleapis.com/v1beta"


def function_declarations(
    tools: list[dict[str, Any]], *, live: bool = False
) -> list[dict[str, Any]]:
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "parametersJsonSchema": tool["parameters"],
            **({"behavior": "BLOCKING"} if live else {}),
        }
        for tool in tools
    ]


def gemini_contents(inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    names: dict[str, str] = {}
    native_ids: set[str] = set()
    for item in inputs:
        kind = item.get("type")
        if kind == "gemini_content":
            contents.append(item["content"])
            native_ids.update(
                part["functionCall"]["id"]
                for part in item["content"].get("parts", [])
                if isinstance(part.get("functionCall", {}).get("id"), str)
            )
            continue
        if kind == "function_call":
            names[item["call_id"]] = item["name"]
            continue
        if kind == "function_call_output":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": names[item["call_id"]],
                                "response": {"result": json.loads(item["output"])},
                                **(
                                    {"id": item["call_id"]} if item["call_id"] in native_ids else {}
                                ),
                            }
                        }
                    ],
                }
            )
            continue
        if "role" not in item:
            continue
        role = "model" if item["role"] == "assistant" else "user"
        content = item.get("content", "")
        parts: list[dict[str, Any]] = []
        if isinstance(content, str):
            parts.append({"text": content})
        else:
            for part in content:
                if part["type"] == "input_text":
                    parts.append({"text": part["text"]})
                elif part["type"] in {"input_image", "input_file"}:
                    url = part.get("image_url") or part.get("file_data")
                    header, encoded = url.split(",", 1)
                    parts.append(
                        {"inlineData": {"mimeType": header[5:].split(";")[0], "data": encoded}}
                    )
        if parts:
            contents.append({"role": role, "parts": parts})
    return contents


def pcm_wave(content: bytes, rate: int = 24000) -> bytes:
    if not content or len(content) % 2 or len(content) > 8 * 1024 * 1024:
        raise AssistantError("speech_limit", "The spoken reply exceeded its safe size limit.", 413)
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(content)
    return output.getvalue()


class GeminiAssistantProvider:
    def __init__(
        self, settings: AssistantSettings, transport: httpx.AsyncBaseTransport | None = None
    ):
        self.settings = settings
        self.transport = transport

    def require_ready(self) -> None:
        if not self.settings.gemini_api_key.get_secret_value().strip():
            raise AssistantError(
                "setup_pending", "Add your Gemini API key in AI settings to connect the assistant."
            )

    def _client(self) -> httpx.AsyncClient:
        self.require_ready()
        return httpx.AsyncClient(
            base_url=GEMINI_ORIGIN,
            headers={"x-goog-api-key": self.settings.gemini_api_key.get_secret_value()},
            timeout=httpx.Timeout(self.settings.timeout_seconds, connect=10),
            follow_redirects=False,
            transport=self.transport,
            limits=httpx.Limits(max_connections=2),
        )

    async def _json(self, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST", f"/models/{model}:generateContent", json=payload
                ) as response:
                    OpenAIAssistantProvider._status(response)
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > 14 * 1024 * 1024:
                            raise AssistantError(
                                "response_limit", "The generated response is too large.", 413
                            )
                    value = json.loads(chunks)
            if not isinstance(value, dict):
                raise ValueError("Invalid provider response")
            return value
        except AssistantError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise AssistantError(
                "provider_unavailable", "The Gemini connection was interrupted. Please try again."
            ) from None

    async def responses(
        self, inputs: list[dict[str, Any]], tools: list[dict[str, Any]], instructions: str
    ) -> AsyncIterator[dict[str, Any]]:
        payload = {
            "systemInstruction": {"parts": [{"text": instructions}]},
            "contents": gemini_contents(inputs),
            "tools": [{"functionDeclarations": function_declarations(tools)}],
            "generationConfig": {
                "maxOutputTokens": self.settings.max_output_tokens,
                "thinkingConfig": {"thinkingLevel": self.settings.reasoning_effort.upper()},
            },
        }
        parts: list[dict[str, Any]] = []
        usage: dict[str, int] = {}
        finished = False
        if not tools:
            payload.pop("tools", None)
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST",
                    f"/models/{self.settings.model}:streamGenerateContent",
                    params={"alt": "sse"},
                    json=payload,
                ) as response:
                    OpenAIAssistantProvider._status(response)
                    total = 0
                    async for line in response.aiter_lines():
                        total += len(line)
                        if total > 2 * 1024 * 1024 or len(line) > 256 * 1024:
                            raise AssistantError("response_limit", "Try a narrower question.", 413)
                        if not line.startswith("data: "):
                            continue
                        item = json.loads(line[6:])
                        for candidate in item.get("candidates", []):
                            for part in candidate.get("content", {}).get("parts", []):
                                parts.append(part)
                                if "text" in part and not part.get("thought"):
                                    yield {"type": "delta", "text": part["text"]}
                            if candidate.get("finishReason"):
                                if candidate["finishReason"] != "STOP":
                                    raise AssistantError(
                                        "response_incomplete",
                                        "The model could not finish this answer. Try a narrower question.",
                                    )
                                finished = True
                        metadata = item.get("usageMetadata", {})
                        if metadata:
                            usage = {
                                "input_tokens": int(metadata.get("promptTokenCount", 0)),
                                "output_tokens": int(metadata.get("candidatesTokenCount", 0))
                                + int(metadata.get("thoughtsTokenCount", 0)),
                            }
            if not finished or not parts:
                raise AssistantError(
                    "response_incomplete", "The AI response ended before completion."
                )
            output: list[dict[str, Any]] = [
                {"type": "gemini_content", "content": {"role": "model", "parts": parts}}
            ]
            for part in parts:
                if "functionCall" in part:
                    call = part["functionCall"]
                    output.append(
                        {
                            "type": "function_call",
                            "name": call["name"],
                            "arguments": json.dumps(call.get("args", {})),
                            "call_id": call.get("id") or str(uuid4()),
                        }
                    )
            yield {"type": "completed", "response": {"output": output, "usage": usage}}
        except AssistantError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise AssistantError(
                "provider_unavailable", "The Gemini connection was interrupted. Please try again."
            ) from None

    async def transcribe(self, content: bytes, mime: str) -> str:
        value = await self._json(
            self.settings.model,
            {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": "Transcribe this audio accurately in its original language. Return only the spoken words."
                            },
                            {
                                "inlineData": {
                                    "mimeType": mime,
                                    "data": base64.b64encode(content).decode(),
                                }
                            },
                        ],
                    }
                ],
                "generationConfig": {"maxOutputTokens": 2048},
            },
        )
        text = "".join(
            part.get("text", "")
            for part in value.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        )
        if not text.strip() or len(text) > 8000:
            raise AssistantError("transcript_unavailable", "Please try a shorter voice message.")
        return text.strip()

    async def speak(self, text: str) -> bytes:
        value = await self._json(
            "gemini-3.1-flash-tts-preview",
            {
                "contents": [
                    {
                        "parts": [
                            {"text": "Read this answer naturally and exactly as written:\n" + text}
                        ]
                    }
                ],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.settings.voice}}
                    },
                },
            },
        )
        for part in value.get("candidates", [{}])[0].get("content", {}).get("parts", []):
            inline = part.get("inlineData", {})
            if inline.get("mimeType", "").startswith("audio/"):
                return pcm_wave(base64.b64decode(inline["data"], validate=True))
        raise AssistantError(
            "speech_unavailable",
            "The spoken reply is unavailable. Your text answer is still available.",
        )

    async def images(self, prompt: str, count: int) -> list[bytes]:
        if not 1 <= count <= 4:
            raise AssistantError("image_count", "Create between one and four images.", 422)
        images = []
        for _ in range(count):
            value = await self._json(
                self.settings.image_model,
                {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseModalities": ["TEXT", "IMAGE"],
                        "imageConfig": {"aspectRatio": "3:2", "imageSize": "1K"},
                    },
                },
            )
            for part in value.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                inline = part.get("inlineData", {})
                if inline.get("mimeType", "").startswith("image/"):
                    try:
                        raw = base64.b64decode(inline["data"], validate=True)
                        with Image.open(io.BytesIO(raw)) as image:
                            if image.width * image.height > 8_000_000:
                                raise ValueError("Image exceeds size limit")
                            output = io.BytesIO()
                            image.convert("RGB").save(output, format="PNG")
                        if len(output.getvalue()) > 8 * 1024 * 1024:
                            raise ValueError("Image exceeds byte limit")
                        images.append(output.getvalue())
                    except (ValueError, OSError, Image.DecompressionBombError):
                        raise AssistantError(
                            "image_unavailable", "The generated image could not be safely opened."
                        ) from None
                    break
            else:
                raise AssistantError(
                    "image_unavailable", "Gemini did not return an image for this request."
                )
        return images
