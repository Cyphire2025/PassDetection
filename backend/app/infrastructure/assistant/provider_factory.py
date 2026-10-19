"""Choose a configured, fixed-origin provider without sharing other features' keys."""

from app.application.assistant.model_capabilities import split_model
from app.application.assistant.provider_contract import AssistantProvider
from app.core.assistant_config import AssistantSettings
from app.infrastructure.assistant.gemini_provider import GeminiAssistantProvider
from app.infrastructure.assistant.provider import OpenAIAssistantProvider


def native_text_settings(settings: AssistantSettings) -> AssistantSettings:
    """File analysis and delegated tasks use the independently selected chat model."""
    if settings.chat_model:
        provider, model = split_model(settings.chat_model)
        return settings.model_copy(update={"provider": provider, "model": model, "reasoning_effort": settings.chat_reasoning})
    if settings.mode != "hybrid":
        return settings
    return settings.model_copy(update={"provider": "openai", "model": "gpt-6-luna", "reasoning_effort": settings.openai_reasoning_effort})


def assistant_provider(settings: AssistantSettings) -> AssistantProvider:
    return (
        GeminiAssistantProvider(settings)
        if settings.provider == "gemini"
        else OpenAIAssistantProvider(settings)
    )
