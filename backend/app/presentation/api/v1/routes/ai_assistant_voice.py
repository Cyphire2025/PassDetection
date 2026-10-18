"""Same-origin native Gemini voice gateway. No provider key reaches a browser."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from contextlib import suppress
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from websockets.exceptions import WebSocketException

from app.application.assistant.contracts import AssistantError
from app.core.assistant_config import AssistantSettings
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthenticationError, AuthorizationError
from app.infrastructure.assistant.gemini_live import live_connection, live_setup
from app.infrastructure.assistant.limits import assistant_admission, reserve_daily_units
from app.infrastructure.assistant.settings_store import load_snapshot, runtime_settings
from app.infrastructure.assistant.store import assistant_store
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.dashboard_realtime import (
    _dashboard_access_cookie,
    _dashboard_origin_allowed,
)
from app.presentation.assistant.native_session import NativeSession
from app.presentation.dependencies.auth import get_current_user

router = APIRouter()
logger = get_logger(__name__)


def _request(websocket: WebSocket) -> Request:
    scope = dict(websocket.scope)
    scope.update(
        type="http", method="GET", scheme="https" if websocket.url.scheme == "wss" else "http"
    )
    return Request(scope)


async def authorize_voice(websocket: WebSocket) -> tuple[User, AssistantSettings]:
    settings = get_settings()
    if not _dashboard_origin_allowed(websocket, settings) or not _dashboard_access_cookie(
        websocket, settings
    ):
        raise AssistantError("access_denied", "Sign in to use voice from your workspace.", 403)
    async with AsyncSessionFactory() as session:
        user = await get_current_user(_request(websocket), None, UserRepository(session), session)
        snapshot = await load_snapshot(session)
        if not snapshot.allows(user):
            raise AssistantError("access_denied", "AI access is unavailable for this account.", 403)
        runtime = await runtime_settings(session)
    if runtime.provider != "gemini" or not runtime.configured:
        raise AssistantError(
            "setup_pending",
            "Choose Gemini and save its API key in AI settings to use native voice.",
            422,
        )
    return user, runtime


async def _client_audio(websocket: WebSocket, upstream: Any, conversation: NativeSession, max_seconds: int = 600) -> None:
    total, started = 0, time.monotonic()
    messages, text_total, text_turns = 0, 0, 0
    while True:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=20)
        messages += 1
        if len(raw) > 40000 or messages > max(12000, max_seconds * 20):
            raise AssistantError(
                "voice_limit", "The microphone stream exceeded its safe size limit.", 413
            )
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise AssistantError("voice_protocol", "The voice request was invalid.", 422)
        kind = value.get("type")
        if kind == "heartbeat_ack" and set(value) == {"type"}:
            continue
        if kind == "audio" and set(value) == {"type", "data"} and isinstance(value["data"], str):
            pcm = base64.b64decode(value["data"], validate=True)
            total += len(pcm)
            if (
                not pcm
                or len(pcm) % 2
                or len(pcm) > 24000
                or total > max(24 * 1024 * 1024, max_seconds * 40000)
                or total > 64000 + (time.monotonic() - started) * 40000
            ):
                raise AssistantError(
                    "voice_limit", "The microphone stream exceeded its safe rate limit.", 413
                )
            if conversation.recovering:
                continue
            await upstream.send(
                json.dumps(
                    {
                        "realtimeInput": {
                            "audio": {"mimeType": "audio/pcm;rate=16000", "data": value["data"]}
                        }
                    }
                )
            )
        elif (
            kind == "text"
            and set(value) == {"type", "text"}
            and isinstance(value["text"], str)
            and 0 < len(value["text"]) <= 8000
        ):
            text_total += len(value["text"])
            text_turns += 1
            if text_total > 32000 or text_turns > 20:
                raise AssistantError(
                    "voice_limit", "Start another session to send more typed questions.", 413
                )
            await reserve_daily_units(conversation.user.id, operation="chat", count=1, limit=conversation.settings.daily_requests)
            await conversation.recovery_done.wait()
            await conversation.caption("input_transcript", value["text"])
            await upstream.send(
                json.dumps(
                    {
                        "clientContent": {
                            "turns": [{"role": "user", "parts": [{"text": value["text"]}]}],
                            "turnComplete": True,
                        }
                    }
                )
            )
        elif kind == "audio_end" and set(value) == {"type"}:
            await upstream.send(json.dumps({"realtimeInput": {"audioStreamEnd": True}}))
        else:
            raise AssistantError("voice_protocol", "The voice request was invalid.", 422)


async def _server_audio(upstream: Any, conversation: NativeSession) -> None:
    async for raw in upstream:
        if not isinstance(raw, (str, bytes)) or len(raw) > 512 * 1024:
            raise AssistantError("voice_limit", "The voice response exceeded its safe limit.", 413)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise AssistantError("voice_protocol", "The voice response was invalid.")
        calls = await conversation.consume(value)
        if calls:
            responses = await conversation.tool_calls(calls)
            await upstream.send(
                json.dumps(
                    {"toolResponse": {"functionResponses": responses}},
                    ensure_ascii=False,
                    default=str,
                )
            )


async def _authorization_heartbeat(
    websocket: WebSocket, user: User, settings: AssistantSettings, send: Any
) -> None:
    while True:
        await asyncio.sleep(5)
        actor, current = await authorize_voice(websocket)
        if (
            actor.id != user.id
            or actor.role != user.role
            or actor.agency_id != user.agency_id
            or actor.session_version != user.session_version
        ):
            raise AssistantError(
                "access_denied", "Your account permissions changed. Start a new voice session.", 403
            )
        if current.revision != settings.revision:
            raise AssistantError(
                "settings_changed",
                "AI settings changed. Tap the microphone to start a new session.",
                403,
            )
        await send({"type": "heartbeat"})


@router.websocket("/voice")
async def assistant_voice(websocket: WebSocket) -> None:
    tasks: set[asyncio.Task[None]] = set()
    send_lock = asyncio.Lock()
    expires_at = 0.0

    async def send(payload: dict[str, Any]) -> None:
        async with send_lock, asyncio.timeout(5):
            await websocket.send_json(payload)

    try:
        user, settings = await authorize_voice(websocket)
        await websocket.accept()
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        if len(raw) > 2048:
            raise AssistantError("voice_protocol", "The voice request was invalid.", 422)
        start = json.loads(raw)
        if (
            not isinstance(start, dict)
            or start.get("type") != "start"
            or set(start) - {"type", "conversation_id", "session_id", "attachment_ids"}
        ):
            raise AssistantError("voice_protocol", "The voice request was invalid.", 422)
        conversation_id, session_id = UUID(start["conversation_id"]), UUID(start["session_id"])
        identifiers = start.get("attachment_ids", [])
        if not isinstance(identifiers, list) or len(identifiers) > 4:
            raise AssistantError(
                "attachment_limit", "Use up to four attachments in a voice session.", 422
            )
        seconds = settings.usage_limits.voice_connection_minutes * 60
        expires_at = time.monotonic() + seconds
        async with assistant_admission(user.id, operation="voice_chats", limit=settings.usage_limits.daily_voice_chats,
                                       timeout_seconds=seconds, distinct_id=conversation_id) as admission:
            store = assistant_store(user)
            conversation = NativeSession(
                _request(websocket),
                user,
                settings,
                store,
                conversation_id,
                send,
                [UUID(value) for value in identifiers],
            )
            instructions, tools = await conversation.context()
            await store.claim_request(
                conversation_id, session_id, "native-audio-session:" + str(session_id)
            )
            async with live_connection(settings) as upstream:
                await upstream.send(json.dumps(live_setup(settings, tools, instructions)))
                ready = json.loads(await asyncio.wait_for(upstream.recv(), timeout=15))
                if "setupComplete" not in ready:
                    raise AssistantError(
                        "provider_configuration",
                        "Gemini did not accept this voice model. Check AI settings and API project access.",
                    )
                admission.commit()
                await send(
                    {
                        "type": "ready",
                        "conversation_id": str(conversation_id),
                        "max_session_seconds": seconds,
                    }
                )
                logger.info("assistant_voice_ready")
                tasks = {
                    asyncio.create_task(
                        _client_audio(websocket, upstream, conversation, seconds),
                        name="assistant-voice-input",
                    ),
                    asyncio.create_task(
                        _server_audio(upstream, conversation), name="assistant-voice-output"
                    ),
                    asyncio.create_task(
                        _authorization_heartbeat(websocket, user, settings, send),
                        name="assistant-voice-authorization",
                    ),
                }
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    await task
    except WebSocketDisconnect as exc:
        if exc.code not in {1000, 1001}:
            logger.warning("assistant_voice_disconnected", close_code=exc.code)
    except (AuthenticationError, AuthorizationError):
        if websocket.application_state == WebSocketState.CONNECTED:
            with suppress(Exception):
                await send(
                    {
                        "type": "error",
                        "code": "access_denied",
                        "message": "Your session or AI access changed. Sign in again.",
                    }
                )
    except AssistantError as exc:
        if websocket.application_state == WebSocketState.CONNECTED:
            with suppress(Exception):
                await send({"type": "error", "code": exc.code, "message": exc.message})
    except TimeoutError:
        if websocket.application_state == WebSocketState.CONNECTED:
            with suppress(Exception):
                message = "This voice connection reached its time limit." if expires_at and time.monotonic() >= expires_at else "The voice connection timed out."
                await send({"type": "error", "code": "voice_timeout", "message": message + " Reconnect in this chat to continue without using another daily voice chat."})
    except (WebSocketException, ValueError, KeyError, TypeError) as exc:
        logger.warning("assistant_voice_interrupted", error_type=type(exc).__name__)
        if websocket.application_state == WebSocketState.CONNECTED:
            with suppress(Exception):
                await send(
                    {
                        "type": "error",
                        "code": "voice_interrupted",
                        "message": "The voice connection ended. Tap the microphone to reconnect.",
                    }
                )
    except Exception as exc:
        logger.warning("assistant_voice_failed", error_type=type(exc).__name__)
        if websocket.application_state == WebSocketState.CONNECTED:
            with suppress(Exception):
                await send(
                    {
                        "type": "error",
                        "code": "voice_unavailable",
                        "message": "Voice is temporarily unavailable. You can continue by typing.",
                    }
                )
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        with suppress(Exception):
            await websocket.close(
                code=1000 if websocket.application_state == WebSocketState.CONNECTED else 1008
            )
