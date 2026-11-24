"""Assistant-only policy and envelope-encrypted keys in an existing settings row.

No schema migration or environment-file rewrite is needed. The application secret
derives a domain-separated encryption key; plaintext never appears in responses or
audit metadata. Settings use optimistic concurrency across backend processes.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.assistant.contracts import AssistantError
from app.application.assistant.model_capabilities import (
    GEMINI_VOICES,
    split_model,
    voice_appearance,
)
from app.application.assistant.settings_contracts import (
    AssistantConfiguration,
    AssistantSettingsUpdate,
)
from app.core.assistant_config import AssistantSettings, get_assistant_settings
from app.core.assistant_usage import AssistantUsageLimits
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import PlatformSettingModel, UserModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

SETTINGS_KEY = "ai_assistant_workspace_v1"
OFFICE_ROLES = frozenset({UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF})


def _legacy_limits() -> AssistantUsageLimits:
    base = get_assistant_settings()
    return base.usage_limits.model_copy(update={"daily_requests": base.daily_requests, "daily_images": base.daily_images})


def _cipher() -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"global-connects-assistant-credentials-v1",
        info=b"private-provider-keys",
    ).derive(get_settings().app_secret_key.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_key(value: str) -> str:
    if not 12 <= len(value) <= 512 or any(char.isspace() for char in value):
        raise AssistantError(
            "invalid_api_key", "Enter a valid provider API key without spaces.", 422
        )
    return "v1:" + _cipher().encrypt(value.encode()).decode("ascii")


def decrypt_key(value: str) -> SecretStr:
    try:
        if not value.startswith("v1:"):
            raise ValueError("Unsupported key version")
        return SecretStr(_cipher().decrypt(value[3:].encode("ascii")).decode("utf-8"))
    except (InvalidToken, ValueError, UnicodeError):
        raise AssistantError(
            "credential_unavailable", "Re-enter the assistant API key in AI settings."
        ) from None


@dataclass(frozen=True)
class AssistantSnapshot:
    revision: int = 0
    configuration: AssistantConfiguration = field(default_factory=AssistantConfiguration)
    encrypted_keys: dict[str, str] = field(default_factory=dict, repr=False)

    def allows(self, user: User) -> bool:
        return bool(
            self.configuration.enabled
            and user.is_active
            and (
                user.role == UserRole.SUPER_ADMIN
                or user.role in OFFICE_ROLES
                and user.agency_id is not None
                and (
                    user.role.value in self.configuration.allowed_roles
                    or user.id in self.configuration.allowed_user_ids
                )
            )
        )


async def load_snapshot(session: AsyncSession) -> AssistantSnapshot:
    row = await session.scalar(
        select(PlatformSettingModel).where(PlatformSettingModel.key == SETTINGS_KEY)
    )
    if row is None:
        base = get_assistant_settings()
        config = (
            AssistantConfiguration(provider="openai", usage_limits=_legacy_limits())
            if base.configured
            else AssistantConfiguration(usage_limits=_legacy_limits())
        )
        return AssistantSnapshot(configuration=config)
    try:
        value: dict[str, Any] = dict(row.value)
        revision = value["revision"]
        keys = value.get("encrypted_keys", {})
        if type(revision) is not int or revision < 1 or not isinstance(keys, dict):
            raise ValueError("Invalid settings")
        if any(
            name not in {"gemini", "openai"} or not isinstance(key, str)
            for name, key in keys.items()
        ):
            raise ValueError("Invalid keys")
        configuration = dict(value["configuration"])
        configuration.setdefault("usage_limits", _legacy_limits().model_dump())
        return AssistantSnapshot(revision, AssistantConfiguration.model_validate(configuration), keys)
    except (ValidationError, ValueError, KeyError, TypeError):
        raise AssistantError(
            "settings_unavailable", "AI settings need administrator attention."
        ) from None


def provider_key(snapshot: AssistantSnapshot, provider: str) -> SecretStr:
    if provider in snapshot.encrypted_keys:
        return decrypt_key(snapshot.encrypted_keys[provider])
    base = get_assistant_settings()
    return base.gemini_api_key if provider == "gemini" else base.openai_api_key


async def runtime_settings(session: AsyncSession, *, purpose: Literal["chat", "voice"] = "chat") -> AssistantSettings:
    snapshot = await load_snapshot(session)
    base = get_assistant_settings()
    config = snapshot.configuration
    chat_choice = config.chat_model or (f"gemini:{config.gemini_model}" if config.provider == "gemini" else "openai:gpt-6-luna")
    voice_choice = config.voice_model or (f"openai:{config.openai_speech_model or 'gpt-realtime-2.1-mini'}" if config.provider == "openai" else f"gemini:{config.gemini_live_model}")
    chat_provider, chat_model = split_model(chat_choice)
    voice_provider, live_model = split_model(voice_choice)
    provider = chat_provider if purpose == "chat" else voice_provider
    chat_effort = config.chat_reasoning if config.chat_model else config.reasoning_effort if chat_provider == "gemini" else config.openai_reasoning_effort
    voice = config.voice_name or (config.gemini_voice if voice_provider == "gemini" else config.openai_voice)
    values: dict[str, Any] = {
        "provider": provider,
        "mode": config.provider,
        "voice_provider": voice_provider,
        "revision": snapshot.revision,
        "reasoning_effort": config.reasoning_effort,
        "openai_reasoning_effort": config.openai_reasoning_effort,
        "live_model": config.gemini_live_model,
        "usage_limits": config.usage_limits,
        "daily_requests": config.usage_limits.daily_requests,
        "daily_images": config.usage_limits.daily_images,
        "chat_model": chat_choice,
        "chat_reasoning": chat_effort,
        "live_reasoning": config.voice_reasoning,
        "mcp_write_enabled": config.mcp_write_enabled,
        "mcp_connection_id": str(config.mcp_connection_id) if config.mcp_connection_id else None,
    }
    for name in ("openai", "gemini"):
        values[f"{name}_api_key"] = provider_key(snapshot, name)
    if provider == "gemini":
        values.update(
            model=config.gemini_model,
            live_model=config.gemini_live_model,
            image_model=config.gemini_image_model,
            voice=config.gemini_voice,
            speech_model="gemini-3.1-flash-tts-preview",
        )
    else:
        values["reasoning_effort"] = config.openai_reasoning_effort
        values.update(
            model="gpt-6-luna",
            speech_model=config.openai_speech_model if snapshot.revision else base.speech_model,
            voice=config.openai_voice,
        )
    appearance = config.voice_presentation if voice_provider == "gemini" and voice not in GEMINI_VOICES else voice_appearance(voice_provider, voice)
    values.update(model=chat_model, live_model=live_model, voice=voice, voice_name=voice,
                  avatar_appearance=appearance or "female",
                  reasoning_effort=chat_effort,
                  speech_model="gemini-3.1-flash-tts-preview" if voice_provider == "gemini" else live_model)
    return base.model_copy(update=values)


def revision_conflict() -> AssistantError:
    return AssistantError(
        "settings_conflict", "AI settings changed. Reload before saving your changes.", 409
    )


async def save_settings(
    session: AsyncSession, user: User, body: AssistantSettingsUpdate
) -> AssistantSnapshot:
    if user.role != UserRole.SUPER_ADMIN:
        raise AssistantError(
            "access_denied", "Only super administrators can change AI settings.", 403
        )
    before = await load_snapshot(session)
    if before.revision != body.expected_revision:
        raise revision_conflict()
    requested = set(body.configuration.allowed_user_ids)
    if requested:
        valid = set(
            (
                await session.scalars(
                    select(UserModel.id).where(
                        UserModel.id.in_(requested),
                        UserModel.is_active.is_(True),
                        UserModel.role.in_([role.value for role in OFFICE_ROLES]),
                        UserModel.agency_id.is_not(None),
                    )
                )
            ).all()
        )
        if requested != valid:
            raise AssistantError(
                "invalid_grant", "Choose active dashboard administrators, managers or staff.", 422
            )
    keys = dict(before.encrypted_keys)
    changed = []
    for provider in ("gemini", "openai"):
        supplied: SecretStr | None = getattr(body, f"{provider}_api_key")
        clear: bool = getattr(body, f"clear_{provider}_key")
        if clear and supplied and supplied.get_secret_value().strip():
            raise AssistantError(
                "key_conflict", "Save or remove a provider key in separate actions.", 422
            )
        if clear:
            keys.pop(provider, None)
            # An explicit tombstone also overrides an environment-provided key.
            keys[provider] = "v1:" + _cipher().encrypt(b"").decode("ascii")
            changed.append(provider)
        elif supplied and supplied.get_secret_value().strip():
            keys[provider] = encrypt_key(supplied.get_secret_value().strip())
            changed.append(provider)
    after = AssistantSnapshot(before.revision + 1, body.configuration, keys)
    value = {
        "revision": after.revision,
        "configuration": after.configuration.model_dump(mode="json"),
        "encrypted_keys": keys,
    }
    now = datetime.now(UTC)
    if before.revision == 0:
        result = await session.execute(
            pg_insert(PlatformSettingModel)
            .values(key=SETTINGS_KEY, value=value, updated_at=now)
            .on_conflict_do_nothing(index_elements=[PlatformSettingModel.key])
            .returning(PlatformSettingModel.key)
        )
    else:
        result = await session.execute(
            update(PlatformSettingModel)
            .where(
                PlatformSettingModel.key == SETTINGS_KEY,
                PlatformSettingModel.value["revision"].as_integer() == body.expected_revision,
            )
            .values(value=value, updated_at=now)
            .returning(PlatformSettingModel.key)
        )
    if result.scalar_one_or_none() is None:
        raise revision_conflict()
    await AuditLogRepository(session).record(
        action="ai_assistant_settings_updated",
        entity_type="platform_settings",
        entity_id=SETTINGS_KEY,
        agency_id=None,
        user_id=user.id,
        actor_email=user.email,
        metadata={
            "previous_revision": before.revision,
            "revision": after.revision,
            "configuration": after.configuration.model_dump(mode="json"),
            "credential_providers_changed": changed,
        },
    )
    await session.commit()
    return after
