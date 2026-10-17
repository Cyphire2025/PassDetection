"""Bounded public payloads; credentials and internal object keys never cross this boundary."""

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    conversation_id: UUID
    text: str = Field(min_length=1, max_length=8000)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=4)
    mode: Literal["chat", "image"] = "chat"
    image_count: int = Field(default=1, ge=1, le=4)


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=6000)


def request_fingerprint(body: ChatRequest) -> str:
    encoded = json.dumps(
        body.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class AssistantError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def public_asset(record: dict[str, Any]) -> dict[str, Any]:
    identifier = str(UUID(str(record["id"])))
    return {
        key: record[key]
        for key in ("id", "name", "mime", "size", "kind", "created_at")
        if key in record
    } | {
        "url": f"/api/v1/ai-assistant/assets/{identifier}/content",
    }
