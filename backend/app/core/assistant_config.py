"""Independent, opt-in configuration for the /ai workspace only."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AssistantSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AI_ASSISTANT_", extra="ignore")

    # Deliberately do not inherit credentials belonging to other application features.
    openai_api_key: SecretStr = SecretStr("")
    model: Literal["gpt-6-luna"] = "gpt-6-luna"
    reasoning_effort: Literal["high"] = "high"
    speech_model: Literal[
        "", "gpt-realtime-2.1-mini", "gpt-realtime-2.1", "gpt-4o-mini-tts", "tts-1", "tts-1-hd"
    ] = ""
    transcription_model: Literal["gpt-transcribe", "gpt-4o-mini-transcribe"] = "gpt-transcribe"
    voice: Literal["marin", "cedar", "alloy", "coral", "sage"] = "marin"
    image_model: Literal["gpt-image-2.5-flare", "gpt-image-2", "gpt-image-1.5"] = (
        "gpt-image-2.5-flare"
    )
    max_output_tokens: int = Field(default=8192, ge=1024, le=16384)
    daily_requests: int = Field(default=200, ge=1, le=2000)
    daily_images: int = Field(default=12, ge=0, le=50)
    timeout_seconds: int = Field(default=120, ge=15, le=180)

    @property
    def configured(self) -> bool:
        return bool(self.openai_api_key.get_secret_value().strip())


@lru_cache(maxsize=1)
def get_assistant_settings() -> AssistantSettings:
    return AssistantSettings()
