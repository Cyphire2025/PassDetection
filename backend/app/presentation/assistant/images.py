"""Explicit image requests, retained privately and replayed without duplicate provider charges."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from app.application.assistant.contracts import AssistantError, ChatRequest, request_fingerprint
from app.application.assistant.provider_contract import AssistantProvider
from app.core.assistant_config import AssistantSettings
from app.domain.entities.entities import User
from app.infrastructure.assistant.attachments import prepare_attachment
from app.infrastructure.assistant.limits import assistant_admission, reserve_images
from app.infrastructure.assistant.store import AssistantStore
from app.infrastructure.security.upload_security import UploadSecurityContext
from app.presentation.assistant.reads import fresh_actor


async def generate_assets(
    user: User,
    prompt: str,
    count: int,
    settings: AssistantSettings,
    store: AssistantStore,
    provider: AssistantProvider,
) -> AsyncIterator[dict[str, Any]]:
    await reserve_images(user.id, count=count, limit=settings.daily_images)
    generated = await provider.images(prompt, count)
    await fresh_actor(user)
    for index, content in enumerate(generated):
        content, name, mime, _ = await prepare_attachment(
            content,
            f"Global Connects image {index + 1}.png",
            "image/png",
            UploadSecurityContext(
                ingestion_flow="ai_assistant_generated", user_id=user.id, agency_id=user.agency_id
            ),
        )
        yield await store.save_asset(content, name=name, mime=mime, kind="generated", prompt=prompt)


async def image_events(
    request: Request,
    user: User,
    body: ChatRequest,
    settings: AssistantSettings,
    store: AssistantStore,
    provider: AssistantProvider,
) -> AsyncIterator[dict[str, Any]]:
    provider.require_ready()
    if body.attachment_ids:
        raise AssistantError(
            "image_edits_unavailable",
            "Create images from a text prompt. Attached image editing is not enabled.",
            422,
        )
    async with assistant_admission(user.id, operation="chat", limit=settings.daily_requests):
        await fresh_actor(user)
        try:
            saved = await store.turn(body.conversation_id, body.request_id)
        except AssistantError as exc:
            if exc.status != 404:
                raise
        else:
            if saved.get("fingerprint") != request_fingerprint(body):
                raise AssistantError(
                    "request_conflict", "Start a new request for a different question.", 409
                )
            yield {"type": "replay", "turn": saved}
            yield {"type": "done", "request_id": str(body.request_id)}
            return
        await store.create_conversation(body.conversation_id, body.text)
        await store.claim_request(body.conversation_id, body.request_id, request_fingerprint(body))
        yield {"type": "status", "message": "Creating your images", "phase": "thinking"}
        images = []
        async for asset in generate_assets(
            user, body.text, body.image_count, settings, store, provider
        ):
            images.append(asset)
            yield {"type": "image", "image": asset}
        answer = f"Created {len(images)} image{'s' if len(images) != 1 else ''}. Open an image to explore it, or find it later in your library."
        turn = {
            "id": str(body.request_id),
            "created_at": datetime.now(UTC).isoformat(),
            "user": body.text,
            "assistant": answer,
            "images": images,
            "sources": [],
            "attachment_ids": [],
            "model": settings.image_model,
            "reasoning_effort": None,
            "fingerprint": request_fingerprint(body),
        }
        await store.save_turn(body.conversation_id, body.request_id, turn)
        yield {"type": "text_delta", "text": answer}
        yield {"type": "done", "request_id": str(body.request_id)}
