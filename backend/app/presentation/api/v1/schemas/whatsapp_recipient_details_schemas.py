"""Explicit, conflict-checked edits of an imported broadcast contact."""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class WhatsAppRecipientDetailsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A saved manual contact behind a shared number is edited independently.
    merged_contact_id: uuid.UUID | None = None
    expected_name: str | None = Field(max_length=100)
    expected_imported_fields: dict[str, Annotated[str, Field(strict=True, max_length=256)]] = Field(max_length=260)
    name: str = Field(min_length=1, max_length=100)
    imported_fields: dict[str, Annotated[str, Field(strict=True, max_length=256)]] = Field(
        max_length=256
    )
