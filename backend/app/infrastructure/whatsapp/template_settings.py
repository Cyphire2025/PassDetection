"""Request-scoped WhatsApp template names with durable, explicit ENV overrides."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings, get_settings
from app.infrastructure.database.models import PlatformSettingModel

TEMPLATE_SETTINGS_KEY = "whatsapp_template_names"
TEMPLATE_SETTINGS_MEMO = "whatsapp_template_settings_snapshot"
TEMPLATE_NAME_MAX_LENGTH = 255  # The existing frozen delivery columns are VARCHAR(255).
TEMPLATE_NAME_PATTERN = r"^[a-z0-9_]+$"
TemplateSlot = Literal["welcome", "passport_link", "reminder", "group_invite", "document", "qr", "otp"]


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    key: TemplateSlot
    label: str
    contract_description: str


TEMPLATE_REGISTRY = (
    TemplateDefinition("welcome", "Welcome", "IMAGE header and one BODY variable; preserve the approved welcome format."),
    TemplateDefinition("passport_link", "Passport Link", "IMAGE header and four BODY variables: introduction, passport link, message, support contacts."),
    TemplateDefinition("reminder", "Reminder", "No media header and one BODY variable."),
    TemplateDefinition("group_invite", "Group Invite", "IMAGE header and two BODY variables: invitation message, WhatsApp group link."),
    TemplateDefinition("document", "Document Distribution", "DOCUMENT header and two BODY variables: message, review instruction."),
    TemplateDefinition("qr", "Passenger QR", "IMAGE header and one BODY variable."),
    TemplateDefinition("otp", "WhatsApp OTP", "AUTHENTICATION template with the OTP in the BODY and the existing copy-code button."),
)
TEMPLATE_SLOTS = frozenset(item.key for item in TEMPLATE_REGISTRY)


def valid_template_name(value: object) -> bool:
    return (
        isinstance(value, str) and 0 < len(value) <= TEMPLATE_NAME_MAX_LENGTH
        and re.fullmatch(TEMPLATE_NAME_PATTERN, value) is not None
    )


@dataclass(frozen=True, slots=True)
class TemplateSettingsSnapshot:
    revision: int
    updated_at: datetime | None
    overrides: dict[str, str]

    def name(self, slot: str, *, settings: Settings | None = None) -> str:
        if slot not in TEMPLATE_SLOTS:
            raise ValueError("Unknown WhatsApp template slot")
        return self.overrides.get(slot, environment_template_name(slot, settings=settings))


def environment_template_name(slot: str, *, settings: Settings | None = None) -> str:
    if slot not in TEMPLATE_SLOTS:
        raise ValueError("Unknown WhatsApp template slot")
    return str(getattr(settings or get_settings(), f"whatsapp_{slot}_template_name")).strip()


def template_language(slot: str, *, settings: Settings | None = None) -> str:
    resolved = settings or get_settings()
    if slot in {"group_invite", "otp"}:
        return str(getattr(resolved, f"whatsapp_{slot}_template_language"))
    return resolved.whatsapp_template_language


def snapshot_from_row(row: PlatformSettingModel | None) -> TemplateSettingsSnapshot:
    if row is None:
        return TemplateSettingsSnapshot(0, None, {})
    revision = row.value.get("whatsapp_template_revision", 0)
    overrides = row.value.get("whatsapp_template_overrides", {})
    if (
        type(revision) is not int or revision < 0 or not isinstance(overrides, dict)
        or any(key not in TEMPLATE_SLOTS or not valid_template_name(value) for key, value in overrides.items())
    ):
        raise RuntimeError("Stored WhatsApp template settings are invalid")
    return TemplateSettingsSnapshot(revision, row.updated_at, dict(overrides))


async def load_template_settings(session: AsyncSession) -> TemplateSettingsSnapshot:
    """One small lookup per request/operation; never cache across DB sessions."""
    cached = session.info.get(TEMPLATE_SETTINGS_MEMO)
    if isinstance(cached, TemplateSettingsSnapshot):
        return cached
    result = await session.execute(
        select(PlatformSettingModel).where(PlatformSettingModel.key == TEMPLATE_SETTINGS_KEY)
    )
    snapshot = snapshot_from_row(result.scalar_one_or_none())
    session.info[TEMPLATE_SETTINGS_MEMO] = snapshot
    return snapshot


async def configured_template_name(session: AsyncSession, slot: str) -> str:
    return (await load_template_settings(session)).name(slot)
