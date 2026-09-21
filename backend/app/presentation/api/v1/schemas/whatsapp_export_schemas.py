"""The exact visible row snapshot requested by a broadcast filter export."""

from __future__ import annotations

import uuid
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WhatsAppExportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["recipient", "rejected", "replaced", "unidentified", "source_contact"]
    id: uuid.UUID
    source_group_id: uuid.UUID | None = None


class WhatsAppFilterExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    view: Literal["delivery", "travellers"]
    items: list[WhatsAppExportItem] = Field(min_length=1, max_length=20_000)
    filter_label: str = Field(default="All", max_length=80)
    message_type: Literal["welcome", "passport_link", "reminder", "group_invite"] | None = None

    @model_validator(mode="after")
    def validate_row_identifiers(self) -> Self:
        identities: set[tuple[str, uuid.UUID, uuid.UUID | None]] = set()
        for item in self.items:
            if self.view == "travellers":
                if item.kind != "source_contact" or item.source_group_id is None:
                    raise ValueError("Traveller exports require source-contact and source-group IDs")
            elif item.kind == "source_contact" or item.source_group_id is not None:
                raise ValueError("Delivery exports require delivery row IDs without a source-group ID")
            identity = (item.kind, item.id, item.source_group_id)
            if identity in identities:
                raise ValueError("Export row identifiers must be unique")
            identities.add(identity)
        return self
