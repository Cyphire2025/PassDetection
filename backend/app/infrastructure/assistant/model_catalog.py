"""Discover both accounts' models without exposing credentials or provider errors."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from app.application.assistant.contracts import AssistantError
from app.application.assistant.model_capabilities import model_entry
from app.infrastructure.assistant.settings_store import AssistantSnapshot, provider_key
from app.infrastructure.assistant.voice_catalog import gemini_voices

ORIGINS = {"openai": "https://api.openai.com/v1", "gemini": "https://generativelanguage.googleapis.com/v1beta"}


async def discover_provider(snapshot: AssistantSnapshot, provider: str, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    try:
        secret = provider_key(snapshot, provider).get_secret_value()
    except AssistantError:
        return {"provider": provider, "status": "unavailable", "models": [], "message": "Re-enter this provider's API key in AI settings."}
    if not secret:
        return {"provider": provider, "status": "not_connected", "models": [], "message": "Save this provider's API key to load its models."}
    headers = {"x-goog-api-key": secret} if provider == "gemini" else {"Authorization": "Bearer " + secret}
    models: dict[str, dict[str, Any]] = {}
    try:
        async with asyncio.timeout(20), httpx.AsyncClient(base_url=ORIGINS[provider], headers=headers, timeout=10, follow_redirects=False, transport=transport) as client:
            params: dict[str, str | int] = {"pageSize": 100} if provider == "gemini" else {}
            seen: set[str] = set()
            for _ in range(50):
                response = await client.get("/models", params=params)
                if response.status_code != 200 or len(response.content) > 4 * 1024 * 1024:
                    raise ValueError("Unavailable model catalog")
                data = response.json()
                rows = data.get("models" if provider == "gemini" else "data", [])
                if not isinstance(rows, list):
                    raise ValueError("Invalid model catalog")
                for row in rows:
                    identifier = row.get("name", "").removeprefix("models/") if provider == "gemini" else row.get("id", "")
                    entry = model_entry(provider, identifier, row.get("displayName"), row.get("supportedGenerationMethods"))
                    if entry:
                        models[entry["id"]] = {**entry, "available": True}
                token = data.get("nextPageToken") if provider == "gemini" else data.get("last_id") if data.get("has_more") else None
                if not token:
                    break
                if not isinstance(token, str) or token in seen:
                    raise ValueError("Invalid catalog pagination")
                seen.add(token)
                params["pageToken" if provider == "gemini" else "after"] = token
            else:
                raise ValueError("Catalog limit exceeded")
            if provider == "gemini" and any(item["kind"] == "voice" for item in models.values()):
                try:
                    async with asyncio.timeout(3):
                        voices = await gemini_voices(client)
                except TimeoutError:
                    voices = []
                for item in models.values():
                    if item["kind"] == "voice" and voices:
                        item["voices"] = voices
        return {"provider": provider, "status": "ready", "models": list(models.values()), "message": "Models available to your saved API key."}
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
        return {"provider": provider, "status": "unavailable", "models": [], "message": "Model discovery is unavailable. Check the saved key and retry. Your selection is preserved."}


async def model_catalog(snapshot: AssistantSnapshot, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    providers = await asyncio.gather(*(discover_provider(snapshot, provider, transport) for provider in ORIGINS))
    rows = {model["id"]: model for result in providers for model in result["models"]}
    config = snapshot.configuration
    selections = [config.chat_model or (f"gemini:{config.gemini_model}" if config.provider == "gemini" else "openai:gpt-6-luna"),
                  config.voice_model or (f"openai:{config.openai_speech_model or 'gpt-realtime-2.1-mini'}" if config.provider == "openai" else f"gemini:{config.gemini_live_model}")]
    for selection in selections:
        provider, _, identifier = selection.partition(":")
        entry = model_entry(provider, identifier)
        if selection not in rows and entry:
            rows[selection] = {**entry, "available": False}
    return {"models": sorted(rows.values(), key=lambda row: (row["provider"], row["model"])),
            "providers": [{key: value for key, value in item.items() if key != "models"} for item in providers],
            "observed_at": datetime.now(UTC).isoformat(), "revision": snapshot.revision}
