"""Explicit template-name overrides; credentials and language are never editable here."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.infrastructure.whatsapp.template_settings import (
    TEMPLATE_NAME_MAX_LENGTH,
    TEMPLATE_NAME_PATTERN,
    TemplateSlot,
)

TemplateName = Annotated[str, StringConstraints(
    strict=True, min_length=1, max_length=TEMPLATE_NAME_MAX_LENGTH, pattern=TEMPLATE_NAME_PATTERN,
)]


class WhatsAppTemplateOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0, strict=True)
    overrides: dict[TemplateSlot, TemplateName | None] = Field(min_length=1, max_length=7)


class WhatsAppTemplateSettingResponse(BaseModel):
    key: TemplateSlot
    label: str
    environment_name: str
    override_name: str | None
    effective_name: str
    language: str
    source: Literal["environment", "override"]
    contract_description: str


class WhatsAppTemplateSettingsResponse(BaseModel):
    revision: int
    can_edit: bool
    updated_at: datetime | None
    templates: list[WhatsAppTemplateSettingResponse]
