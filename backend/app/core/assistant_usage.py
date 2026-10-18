"""Administrator-managed allowances, separate from provider billing."""

from pydantic import BaseModel, ConfigDict, Field


class AssistantUsageLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    daily_voice_chats: int = Field(default=30, ge=0, le=10000)
    voice_connection_minutes: int = Field(default=10, ge=1, le=60)
    daily_requests: int = Field(default=200, ge=0, le=10000)
    daily_images: int = Field(default=12, ge=0, le=500)
    daily_uploads: int = Field(default=80, ge=0, le=2000)
    daily_speech_requests: int = Field(default=300, ge=0, le=10000)
