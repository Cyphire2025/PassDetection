"""Recover unsupported Live dashboard lookups through the selected text model.

This handles conversational access disclaimers, never provider safety errors or
authorization denials. Both models use the same authorized observational tools.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import wave
from typing import TYPE_CHECKING, Any

from app.application.assistant.contracts import AssistantError

if TYPE_CHECKING:
    from app.presentation.assistant.native_session import NativeSession

DISCLAIMERS = (
    "i'm just a language model", "i am just a language model",
    "i do not have access", "i don't have access", "i cannot access", "i can't access",
    "i do not have the ability to access", "i don't have the ability to access",
    "unfortunately, the", "the participant counts or member lists",
)
BUSINESS = re.compile(r"\b(group|groups|passenger|passengers|people|person|member|members|participant|participants|"
    r"staff|roster|dashboard|workspace|whatsapp|email|contact|phone|passport|visa|document|documents|"
    r"rooming|hotel|trip|traveller|traveler|company|client|name|names|details|address|count|meal|attendance|travel|booking)\b", re.I)


def pending_access_disclaimer(question: str, answer: str) -> bool:
    if not BUSINESS.search(question):
        return False
    text = answer.strip().casefold().replace("’", "'")
    return not text or any(text.startswith(prefix) or prefix.startswith(text) for prefix in DISCLAIMERS)


def recoverable_access_disclaimer(question: str, answer: str) -> bool:
    if not pending_access_disclaimer(question, answer) or len(answer) > 1800:
        return False
    text = answer.strip().casefold().replace("’", "'")
    return any(text.startswith(prefix) for prefix in DISCLAIMERS[:8]) or (
        any(phrase in text for phrase in ("not available", "unavailable", "cannot access", "don't have access"))
        and any(phrase in text for phrase in ("dashboard", "tools", "participant", "member"))
    )


async def recover_answer(conversation: NativeSession) -> str:
    instructions, tools = await conversation.context()
    tools = [tool for tool in tools if tool["name"] != "create_images"]
    instructions += (
        "\nComplete this authenticated dashboard lookup using current read tools. A voice channel's earlier access disclaimer is not an authorization decision. "
        "The server remains the authority. If it denies access, respect that decision. If a person/group is ambiguous, ask one short clarification. "
        "Return a concise answer suitable for speech; use tables only for a requested list."
    )
    inputs: list[dict[str, Any]] = [{"role": "user", "content": conversation.input}]
    answer = ""
    async with asyncio.timeout(55):
        for _ in range(8):
            completed = None
            async for event in conversation.provider.responses(inputs, tools, instructions):
                if event["type"] == "delta":
                    answer += event["text"]
                    if len(answer) > 12000:
                        raise AssistantError("answer_limit", "Please narrow this dashboard question.", 413)
                else:
                    completed = event["response"]
            if completed is None:
                raise AssistantError("response_incomplete", "The dashboard lookup did not complete.")
            output = completed.get("output", [])
            calls = [item for item in output if item.get("type") == "function_call"]
            if not calls:
                if answer.strip():
                    return answer.strip()
                break
            inputs.extend(output)
            responses = await conversation.tool_calls([
                {"id": call["call_id"], "name": call["name"], "args": json.loads(call.get("arguments", "{}"))}
                for call in calls
            ])
            inputs.extend({"type": "function_call_output", "call_id": item["id"],
                "output": json.dumps(item["response"]["result"], separators=(",", ":"))} for item in responses)
    raise AssistantError("query_limit", "Try asking about one dashboard item at a time.", 422)


async def recovery_speech(conversation: NativeSession, answer: str) -> bytes:
    spoken = re.sub(r"[|#*_`]", "", answer)
    spoken = " ".join(spoken.split())
    if len(spoken) > 280:
        spoken = spoken[:240].rsplit(" ", 1)[0] + ". The full details are in the conversation."
    async with asyncio.timeout(25):
        content = await conversation.speech_provider.speak(spoken)
    with wave.open(io.BytesIO(content), "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 24000 or not 0 < audio.getnframes() <= 24000 * 18:
            raise AssistantError("speech_limit", "The text reply is ready; spoken playback was unavailable.")
        return audio.readframes(audio.getnframes())
