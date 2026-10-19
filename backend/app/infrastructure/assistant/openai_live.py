"""OpenAI Realtime audio on the same private gateway used for Gemini Live.

The adapter preserves the gateway's 16 kHz input / 24 kHz output contract.
Audio is streamed immediately; transcription is never a prerequisite for speech.
"""

from __future__ import annotations

import asyncio
import audioop
import base64
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

from websockets.asyncio.client import connect

from app.application.assistant.contracts import AssistantError
from app.application.assistant.model_capabilities import reasoning_options
from app.core.assistant_config import AssistantSettings

transport_logger = logging.getLogger("assistant.private_openai_live_transport")
transport_logger.addHandler(logging.NullHandler())
transport_logger.propagate = False


class FixedRealtimeConnect(connect):
    def process_redirect(self, exc: Exception) -> Exception:
        return PermissionError("The voice provider redirected its connection")


def realtime_setup(settings: AssistantSettings, tools: list[dict[str, Any]], instructions: str) -> dict[str, Any]:
    session: dict[str, Any] = {
        "type": "realtime", "model": settings.live_model, "instructions": instructions,
        "output_modalities": ["audio"],
        "audio": {
            "input": {"format": {"type": "audio/pcm", "rate": 24000},
                      "transcription": {"model": "gpt-4o-mini-transcribe"},
                      "turn_detection": {"type": "server_vad", "threshold": 0.5,
                                         "prefix_padding_ms": 300, "silence_duration_ms": 350,
                                         "create_response": True, "interrupt_response": True}},
            "output": {"format": {"type": "audio/pcm", "rate": 24000}, "voice": settings.voice},
        },
        "tools": [{key: value for key, value in tool.items() if key != "strict"} for tool in tools],
        "tool_choice": "auto",
    }
    if settings.live_reasoning in reasoning_options("openai", settings.live_model):
        session["reasoning"] = {"effort": settings.live_reasoning}
    elif "realtime-2" in settings.live_model:
        session["reasoning"] = {"effort": "low"}
    return {"type": "session.update", "session": session}


class RealtimeGateway:
    def __init__(self, socket: Any, settings: AssistantSettings):
        self.socket, self.settings = socket, settings
        self.resample_state: Any = None
        self.pending_done = False
        self.input_item: str | None = None
        self.transcribed: set[str] = set()
        self.closed_items: set[str] = set()
        self.output_active = False
        self.response_active = False
        self.response_id: str | None = None
        self.cancelled_responses: set[str] = set()

    async def send(self, raw: str) -> None:
        packet = json.loads(raw)
        realtime = packet.get("realtimeInput", {})
        if "audio" in realtime:
            pcm = base64.b64decode(realtime["audio"]["data"], validate=True)
            converted, self.resample_state = audioop.ratecv(pcm, 2, 1, 16000, 24000, self.resample_state)
            await self.socket.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(converted).decode()}))
        elif "audioStreamEnd" in realtime:
            # Server VAD commits speech; committing again creates an empty turn.
            return
        elif "clientContent" in packet:
            if self.response_active or self.output_active:
                await self.socket.send(json.dumps({"type": "response.cancel"}))
                if self.response_id:
                    self.cancelled_responses.add(self.response_id)
            for turn in packet["clientContent"]["turns"]:
                text = "".join(part.get("text", "") for part in turn["parts"])
                await self.socket.send(json.dumps({"type": "conversation.item.create", "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}))
            await self.socket.send(json.dumps({"type": "response.create", "response": {"output_modalities": ["audio"]}}))
        elif "toolResponse" in packet:
            for result in packet["toolResponse"]["functionResponses"]:
                await self.socket.send(json.dumps({"type": "conversation.item.create", "item": {
                    "type": "function_call_output", "call_id": result["id"],
                    "output": json.dumps(result["response"], ensure_ascii=False, default=str)}}))
            # Function results do not trigger speech automatically in Realtime.
            await self.socket.send(json.dumps({"type": "response.create", "response": {"output_modalities": ["audio"]}}))

    def complete(self) -> dict[str, Any]:
        self.pending_done = False
        self.output_active = False
        self.response_active = False
        if self.input_item:
            self.closed_items.add(self.input_item)
        return {"serverContent": {"turnComplete": True}}

    async def events(self) -> AsyncIterator[str]:
        while True:
            try:
                raw = await asyncio.wait_for(self.socket.recv(), 1.5) if self.pending_done else await self.socket.recv()
            except TimeoutError:
                yield json.dumps(self.complete())
                continue
            if not isinstance(raw, (str, bytes)) or len(raw) > 512 * 1024:
                raise AssistantError("voice_limit", "The voice response exceeded its safe limit.", 413)
            event = json.loads(raw)
            kind = event.get("type")
            content: dict[str, Any] = {}
            if kind == "error":
                raise AssistantError("provider_unavailable", "OpenAI voice could not complete this session. Check AI settings and reconnect.")
            if kind == "input_audio_buffer.speech_started":
                if self.response_active or self.output_active or self.pending_done:
                    yield json.dumps({"serverContent": {"interrupted": True}})
                if self.input_item:
                    self.closed_items.add(self.input_item)
                if (self.response_active or self.output_active) and self.response_id:
                    self.cancelled_responses.add(self.response_id)
                self.pending_done = False
                self.output_active = False
                self.response_active = False
                self.input_item = event.get("item_id")
            elif kind == "response.created":
                self.response_id = event["response"]["id"]
                self.response_active = True
            elif event.get("response_id") in self.cancelled_responses:
                continue
            elif kind == "input_audio_buffer.speech_stopped":
                content = {"assistantPhase": "thinking"}
            elif kind == "conversation.item.input_audio_transcription.completed":
                identifier = event.get("item_id", "")
                if identifier not in self.transcribed and identifier not in self.closed_items:
                    self.transcribed.add(identifier)
                    content = {"inputTranscription": {"text": event.get("transcript", "")}}
            elif kind in {"response.output_audio.delta", "response.audio.delta"}:
                self.output_active = True
                content = {"modelTurn": {"parts": [{"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": event["delta"]}}]}}
            elif kind in {"response.output_audio_transcript.delta", "response.audio_transcript.delta"}:
                content = {"outputTranscription": {"text": event.get("delta", "")}}
            elif kind == "response.done":
                response = event["response"]
                if response.get("id") in self.cancelled_responses:
                    continue
                self.response_active = False
                if response.get("status") in {"failed", "incomplete"}:
                    raise AssistantError("voice_incomplete", "The voice answer could not finish. Please try again.")
                calls = [{"id": item["call_id"], "name": item["name"], "args": json.loads(item["arguments"])}
                         for item in response.get("output", []) if item.get("type") == "function_call"]
                if calls:
                    yield json.dumps({"toolCall": {"functionCalls": calls}})
                elif response.get("status") != "cancelled":
                    if self.input_item and self.input_item not in self.transcribed:
                        self.pending_done = True
                    else:
                        yield json.dumps(self.complete())
            if content:
                yield json.dumps({"serverContent": content})
            if self.pending_done and self.input_item in self.transcribed:
                yield json.dumps(self.complete())

    def __aiter__(self) -> AsyncIterator[str]:
        return self.events()


@asynccontextmanager
async def openai_live_connection(settings: AssistantSettings, tools: list[dict[str, Any]], instructions: str) -> AsyncIterator[RealtimeGateway]:
    async with FixedRealtimeConnect(
        "wss://api.openai.com/v1/realtime?model=" + quote(settings.live_model, safe=""),
        additional_headers={"Authorization": "Bearer " + settings.openai_api_key.get_secret_value()},
        proxy=None, compression=None, open_timeout=10, close_timeout=3,
        max_size=512 * 1024, max_queue=4, logger=transport_logger,
    ) as socket:
        await socket.send(json.dumps(realtime_setup(settings, tools, instructions)))
        async with asyncio.timeout(15):
            while True:
                event = json.loads(await socket.recv())
                if event.get("type") == "session.updated":
                    break
                if event.get("type") == "error":
                    raise AssistantError("provider_configuration", "OpenAI did not accept this voice model or voice. Check AI settings and API project access.")
        yield RealtimeGateway(socket, settings)
