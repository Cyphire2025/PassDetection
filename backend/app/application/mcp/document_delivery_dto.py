"""Exact, bounded input for preparing document sends, never implicit resends."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MCPDocumentDeliveryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: uuid.UUID
    group_id: uuid.UUID
    batch_id: uuid.UUID
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    message_content_1: str = Field(min_length=1, max_length=600)
    message_content_2: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def unique_documents(self) -> MCPDocumentDeliveryDraft:
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("Choose each saved document only once")
        self.document_ids.sort(key=str)
        return self


class MCPDocumentDeliveryConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: uuid.UUID
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    user_confirmed: Literal[True]

    @model_validator(mode="before")
    @classmethod
    def explicit_confirmation(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("user_confirmed") is not True:
            raise ValueError("Final user confirmation is required")
        return value
