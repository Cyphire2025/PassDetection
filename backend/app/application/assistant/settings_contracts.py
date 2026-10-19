"""Validated configuration and write-only credentials for the assistant workspace."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.application.assistant.model_capabilities import (
    MODEL_ID,
    model_kind,
    reasoning_options,
    split_model,
    voice_options,
)
from app.core.assistant_usage import AssistantUsageLimits

AssistantProviderName = Literal["gemini", "openai"]
AssistantMode = Literal["gemini", "openai", "hybrid"]
OpenAIReasoning = Literal["none", "low", "medium", "high", "xhigh", "max"]
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
    provider: AssistantMode = "gemini"
    # Empty values preserve saved v1 settings until the administrator selects a model.
    chat_model: str = Field(default="", max_length=210)
    voice_model: str = Field(default="", max_length=210)
    chat_reasoning: str = Field(default="", max_length=16)
    voice_reasoning: str = Field(default="", max_length=16)
    voice_name: str = Field(default="", max_length=100)
    voice_presentation: Literal["male", "female"] | None = None
    mcp_write_enabled: bool = False
    mcp_connection_id: UUID | None = None
    gemini_model: GeminiChatModel = "gemini-3.8-flash"
    gemini_live_model: GeminiLiveModel = "gemini-3.8-live"
    gemini_image_model: GeminiImageModel = "gemini-3.1-flash-image"
    gemini_voice: GeminiVoice = "Zephyr"
    reasoning_effort: Literal["low", "medium", "high"] = "high"
    openai_reasoning_effort: OpenAIReasoning = "high"
    openai_speech_model: Literal["", "gpt-realtime-2.1-mini", "gpt-realtime-2.1"] = ""
    openai_voice: Literal["marin", "cedar", "alloy", "coral", "sage"] = "marin"
    usage_limits: AssistantUsageLimits = Field(default_factory=AssistantUsageLimits)

    @model_validator(mode="after")
    def validate_model_choices(self) -> "AssistantConfiguration":
        for selection, effort, kind in ((self.chat_model, self.chat_reasoning, "chat"), (self.voice_model, self.voice_reasoning, "voice")):
            if not selection:
                continue
            provider, model = split_model(selection)
            if model_kind(provider, model) != kind:
                raise ValueError(f"Choose a compatible {kind} model.")
            if effort and effort not in reasoning_options(provider, model):
                raise ValueError("This reasoning level is unavailable for the selected model.")
            if kind == "voice" and self.voice_name:
                if not MODEL_ID.fullmatch(self.voice_name) or provider == "openai" and self.voice_name not in {item["id"] for item in voice_options(provider, model)}:
                    raise ValueError("Choose a voice supported by the selected voice model.")
        return self


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
