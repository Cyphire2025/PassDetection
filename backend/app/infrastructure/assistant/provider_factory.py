"""Choose a configured, fixed-origin provider without sharing other features' keys."""

from app.application.assistant.provider_contract import AssistantProvider
from app.core.assistant_config import AssistantSettings
from app.infrastructure.assistant.gemini_provider import GeminiAssistantProvider
from app.infrastructure.assistant.provider import OpenAIAssistantProvider


def assistant_provider(settings: AssistantSettings) -> AssistantProvider:
    return (
        GeminiAssistantProvider(settings)
        if settings.provider == "gemini"
        else OpenAIAssistantProvider(settings)
    )
