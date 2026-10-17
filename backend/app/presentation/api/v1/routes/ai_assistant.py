"""The /ai workspace API. It never grants database, SQL or business-write tools to a model."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.assistant.contracts import AssistantError, ChatRequest, SpeechRequest
from app.core.assistant_config import get_assistant_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User, UserRole
from app.infrastructure.assistant.attachments import MAX_UPLOAD, prepare_attachment
from app.infrastructure.assistant.limits import assistant_admission
from app.infrastructure.assistant.provider import OpenAIAssistantProvider
from app.infrastructure.assistant.store import AssistantStore
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.upload_security import UploadSecurityContext
from app.presentation.assistant.cancellation import client_bound
from app.presentation.assistant.chat import chat_events
from app.presentation.assistant.images import image_events
from app.presentation.assistant.reads import DashboardReader, fresh_actor
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
logger = get_logger(__name__)
PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _http(exc: AssistantError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})


async def assistant_user(
    user: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_db_session)
) -> User:
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(403, "The assistant is currently available to administrators only.")
    # Do not retain an auth transaction/connection while a model is thinking.
    await session.rollback()
    return user


@router.get("/status")
async def assistant_status(
    response: Response, user: User = Depends(assistant_user)
) -> dict[str, Any]:
    response.headers.update(PRIVATE_HEADERS)
    settings = get_assistant_settings()
    return {
        "configured": settings.configured,
        "speech_configured": settings.configured and bool(settings.speech_model),
        "model": settings.model,
        "reasoning_effort": "high",
        "access": "read_only",
        "name": user.full_name,
        "account_id": str(user.id),
        "file_limit_bytes": MAX_UPLOAD,
        "attachment_limit": 4,
        "image_limit": 4,
        "daily_requests": settings.daily_requests,
        "speech_model": settings.speech_model or None,
    }


@router.get("/live")
async def assistant_live(
    request: Request, response: Response, user: User = Depends(assistant_user)
) -> dict[str, Any]:
    response.headers.update(PRIVATE_HEADERS)
    try:
        return await DashboardReader(request, user).overview()
    except AssistantError as exc:
        raise _http(exc) from None


@router.get("/conversations")
async def conversations(
    response: Response,
    cursor: str | None = Query(None, max_length=2048),
    user: User = Depends(assistant_user),
) -> dict[str, Any]:
    response.headers.update(PRIVATE_HEADERS)
    try:
        return await AssistantStore(user.id).conversations(cursor)
    except AssistantError as exc:
        raise _http(exc) from None


@router.get("/conversations/{conversation_id}")
async def conversation(
    conversation_id: UUID,
    response: Response,
    cursor: str | None = Query(None, max_length=2048),
    user: User = Depends(assistant_user),
) -> dict[str, Any]:
    response.headers.update(PRIVATE_HEADERS)
    try:
        return await AssistantStore(user.id).turns(conversation_id, cursor)
    except AssistantError as exc:
        raise _http(exc) from None


@router.get("/assets")
async def assets(
    response: Response,
    cursor: str | None = Query(None, max_length=2048),
    user: User = Depends(assistant_user),
) -> dict[str, Any]:
    response.headers.update(PRIVATE_HEADERS)
    try:
        return await AssistantStore(user.id).assets(cursor)
    except AssistantError as exc:
        raise _http(exc) from None


@router.get("/assets/{asset_id}/content")
async def asset_content(asset_id: UUID, user: User = Depends(assistant_user)) -> Response:
    store = AssistantStore(user.id)
    try:
        record = await store.asset(asset_id)
        content = await store.content(asset_id)
    except AssistantError as exc:
        raise _http(exc) from None
    disposition = (
        "inline" if record["mime"] in {"image/jpeg", "image/png", "image/webp"} else "attachment"
    )
    return Response(
        content,
        media_type=record["mime"],
        headers={
            **PRIVATE_HEADERS,
            "Content-Disposition": f"{disposition}; filename=attachment-{asset_id}; filename*=UTF-8''{quote(record['name'], safe='')}",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post("/attachments", dependencies=[Depends(require_cookie_csrf)])
async def upload_attachment(
    response: Response,
    file: UploadFile = File(...),
    user: User = Depends(assistant_user),
) -> dict[str, Any]:
    response.headers.update(PRIVATE_HEADERS)
    try:
        async with assistant_admission(user.id, operation="uploads", limit=80):
            content = await file.read(MAX_UPLOAD + 1)
            content, name, mime, text = await prepare_attachment(
                content,
                file.filename or "Attachment",
                file.content_type or "application/octet-stream",
                UploadSecurityContext(
                    ingestion_flow="ai_assistant_attachment",
                    user_id=user.id,
                    agency_id=user.agency_id,
                ),
            )
            asset = await AssistantStore(user.id).save_asset(
                content, name=name, mime=mime, kind="uploaded", text=text
            )
            return asset
    except AssistantError as exc:
        raise _http(exc) from None
    finally:
        await file.close()


async def _stream(events: AsyncIterator[dict[str, Any]], request: Request) -> AsyncIterator[str]:
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=12)

    async def produce() -> None:
        try:
            async for event in events:
                await queue.put(event)
        except AssistantError as exc:
            await queue.put({"type": "error", "code": exc.code, "message": exc.message})
        except (TimeoutError, asyncio.TimeoutError):
            await queue.put(
                {
                    "type": "error",
                    "code": "request_timeout",
                    "message": "This request took too long. Please try a narrower question.",
                }
            )
        except Exception as exc:
            logger.warning("assistant_request_failed", error_type=type(exc).__name__)
            await queue.put(
                {
                    "type": "error",
                    "code": "request_failed",
                    "message": "The assistant could not complete this request. Please try again.",
                }
            )
        finally:
            # A cancelled producer must not wait forever on an undrained full queue.
            active_task = asyncio.current_task()
            if active_task is not None and active_task.cancelling():
                with suppress(asyncio.QueueFull):
                    queue.put_nowait(None)
            else:
                await queue.put(None)

    task = asyncio.create_task(produce())
    try:
        while not await request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=12)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if event is None:
                break
            yield "event: assistant\ndata: " + json.dumps(event, ensure_ascii=False) + "\n\n"
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await events.aclose()  # type: ignore[attr-defined]


@router.post(
    "/chat",
    dependencies=[Depends(require_cookie_csrf)],
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
            "description": "Private assistant events; done means the completed answer was saved.",
        }
    },
)
async def chat(
    body: ChatRequest, request: Request, user: User = Depends(assistant_user)
) -> StreamingResponse:
    settings = get_assistant_settings()
    provider = OpenAIAssistantProvider(settings)
    try:
        provider.require_ready()
    except AssistantError as exc:
        raise _http(exc) from None
    store = AssistantStore(user.id)
    events = (
        image_events(request, user, body, settings, store, provider)
        if body.mode == "image"
        else chat_events(request, user, body, settings, store, provider)
    )
    return StreamingResponse(
        _stream(events, request),
        media_type="text/event-stream",
        headers={**PRIVATE_HEADERS, "X-Accel-Buffering": "no"},
    )


@router.post("/transcribe", dependencies=[Depends(require_cookie_csrf)])
async def transcribe(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    user: User = Depends(assistant_user),
) -> dict[str, str]:
    response.headers.update(PRIVATE_HEADERS)
    settings = get_assistant_settings()
    provider = OpenAIAssistantProvider(settings)
    try:
        provider.require_ready()
        async with assistant_admission(user.id, operation="speech", limit=300):
            await fresh_actor(user)
            content = await file.read(MAX_UPLOAD + 1)
            mime = (file.content_type or "").split(";")[0]
            if (
                not content
                or len(content) > MAX_UPLOAD
                or mime not in {"audio/webm", "audio/mp4", "audio/ogg", "audio/wav", "audio/mpeg"}
            ):
                raise AssistantError(
                    "audio_rejected", "Record a voice message of 8 MB or smaller.", 422
                )
            return {"text": await client_bound(request, provider.transcribe(content, mime))}
    except AssistantError as exc:
        raise _http(exc) from None
    finally:
        await file.close()


@router.post("/speech", dependencies=[Depends(require_cookie_csrf)])
async def speech(
    body: SpeechRequest, request: Request, user: User = Depends(assistant_user)
) -> Response:
    settings = get_assistant_settings()
    try:
        async with assistant_admission(user.id, operation="speech", limit=300):
            await fresh_actor(user)
            content = await client_bound(
                request, OpenAIAssistantProvider(settings).speak(body.text)
            )
            mime = (
                "audio/wav" if settings.speech_model.startswith("gpt-realtime-") else "audio/mpeg"
            )
            return Response(content, media_type=mime, headers=PRIVATE_HEADERS)
    except AssistantError as exc:
        raise _http(exc) from None
