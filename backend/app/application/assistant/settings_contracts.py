"""Validated configuration and write-only credentials for the assistant workspace."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

AssistantProviderName = Literal["gemini", "openai"]
GrantRole = Literal["agency_admin", "agency_manager", "agency_staff"]
GeminiChatModel = Literal["gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-3.1-flash-lite"]
GeminiLiveModel = Literal[
    "gemini-3.8-live", "gemini-3.8-live-extended-thinking", "gemini-3.1-flash-live-preview"
]
GeminiImageModel = Literal["gemini-3.1-flash-image", "gemini-3.1-flash-lite-image"]
GeminiVoice = Literal["Zephyr", "Kore", "Puck", "Charon", "Aoede"]


class AssistantConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    allowed_roles: list[GrantRole] = Field(default_factory=list, max_length=3)
    allowed_user_ids: list[UUID] = Field(default_factory=list, max_length=200)
    provider: AssistantProviderName = "gemini"
    gemini_model: GeminiChatModel = "gemini-3.8-flash"
    gemini_live_model: GeminiLiveModel = "gemini-3.8-live"
    gemini_image_model: GeminiImageModel = "gemini-3.1-flash-image"
    gemini_voice: GeminiVoice = "Zephyr"
    reasoning_effort: Literal["low", "medium", "high"] = "high"
    openai_speech_model: Literal["", "gpt-realtime-2.1-mini", "gpt-realtime-2.1"] = ""
    openai_voice: Literal["marin", "cedar", "alloy", "coral", "sage"] = "marin"


class AssistantSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    configuration: AssistantConfiguration
    gemini_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    clear_gemini_key: bool = False
    clear_openai_key: bool = False


class AssistantSettingsResponse(BaseModel):
    revision: int
    configuration: AssistantConfiguration
    credentials: dict[str, bool]
    granted_users: list[dict[str, str]] = Field(default_factory=list)


class AssistantConnectionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: AssistantProviderName
