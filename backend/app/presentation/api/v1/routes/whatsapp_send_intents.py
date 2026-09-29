"""Normal website sends require durable business idempotency at the HTTP boundary."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.access_level_actor import refresh_access_level_actor
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
    UserSecurityStateModel,
    WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.whatsapp_send_intent_models import WhatsAppSendIntentModel
from app.presentation.api.v1.routes.whatsapp_archive_policy import require_active_broadcast
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES, _agency_filter
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppSendRequest,
    WhatsAppSendResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf


class QueueBroadcast(Protocol):
    async def __call__(
        self,
        group_id: uuid.UUID,
        body: WhatsAppSendRequest,
        *,
        current_user: User,
        session: AsyncSession,
        freeze_template_language: bool = False,
        suppress_unknown_reminders: bool = False,
    ) -> tuple[WhatsAppSendResponse, dict[str, object]]: ...


def require_key(value: str) -> str:
    if (
        not 16 <= len(value) <= 256
        or not value.isascii()
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise HTTPException(
            422, "Provide a stable Idempotency-Key containing 16 to 256 printable ASCII characters"
        )
    return value


async def required_send_key(request: Request) -> str:
    values = request.headers.getlist("idempotency-key")
    if len(values) != 1:
        raise HTTPException(422, "Provide exactly one stable Idempotency-Key")
    return require_key(values[0])


async def durable_send(
    group_id: uuid.UUID,
    body: WhatsAppSendRequest,
    *,
    current_user: User,
    session: AsyncSession,
    idempotency_key: str,
    queue: QueueBroadcast,
) -> tuple[WhatsAppSendResponse, uuid.UUID]:
    key_hash = hashlib.sha256(
        ("whatsapp-send-v1\0" + require_key(idempotency_key)).encode()
    ).hexdigest()
    request_hash = hashlib.sha256(
        json.dumps(
            {"broadcast_id": str(group_id), "body": body.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    # One actor lock serializes keys across broadcasts as well as one list. The
    # database unique constraint also protects the retained receipt namespace.
    actor = await session.scalar(
        select(UserModel)
        .where(UserModel.id == current_user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    security = await session.scalar(
        select(UserSecurityStateModel)
        .where(UserSecurityStateModel.user_id == current_user.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if (
        actor is None
        or not actor.is_active
        or actor.deleted_at is not None
        or actor.role not in WHATSAPP_ROLES
        or security is None
        or security.credential_state != "active"
        or security.session_version != current_user.session_version
    ):
        raise HTTPException(403, "Current WhatsApp sending authority is unavailable")
    try:
        fresh_user = await refresh_access_level_actor(session, current_user)
    except AuthorizationError as exc:
        raise HTTPException(403, "Current WhatsApp sending authority is unavailable") from exc
    if fresh_user.role not in WHATSAPP_ROLES:
        raise HTTPException(403, "Current WhatsApp sending authority is unavailable")
    receipt = await session.scalar(
        select(WhatsAppSendIntentModel)
        .where(
            WhatsAppSendIntentModel.user_id == current_user.id,
            WhatsAppSendIntentModel.idempotency_hash == key_hash,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    group = await session.scalar(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(fresh_user),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if group is None:
        raise HTTPException(404, "WhatsApp broadcast group not found")
    require_active_broadcast(group)
    agency = await session.get(AgencyModel, group.agency_id, populate_existing=True)
    if agency is None or not agency.is_active:
        raise HTTPException(403, "Current WhatsApp agency is unavailable")
    if receipt is not None:
        if receipt.request_hash != request_hash:
            raise HTTPException(
                409,
                "This Idempotency-Key already identifies different send details; retry the original request or use a new key for a deliberate new send",
            )
        return WhatsAppSendResponse.model_validate(receipt.initial_response), receipt.id
    response, payload = await queue(
        group_id, body, current_user=fresh_user, session=session, freeze_template_language=True
    )
    now = datetime.now(UTC)
    receipt = WhatsAppSendIntentModel(
        id=uuid.uuid4(),
        user_id=fresh_user.id,
        agency_id=group.agency_id,
        broadcast_id=group.id,
        idempotency_hash=key_hash,
        request_hash=request_hash,
        initial_response=response.model_dump(mode="json"),
        worker_payload=payload,
        batch_id=response.batch_id,
        publication_status="pending" if response.batch_id else "no_batch",
        publication_attempts=0,
        next_attempt_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(receipt)
    await session.flush()
    return response, receipt.id


def register_send_http_route(router: APIRouter, queue: QueueBroadcast) -> None:
    @router.post(
        "/groups/{group_id}/send",
        response_model=WhatsAppSendResponse,
        dependencies=[Depends(require_cookie_csrf)],
    )
    async def send_broadcast_message(
        group_id: uuid.UUID,
        body: WhatsAppSendRequest,
        idempotency_key: str = Depends(required_send_key),
        current_user: User = Depends(require_role(WHATSAPP_ROLES)),
        session: AsyncSession = Depends(get_db_session),
    ) -> WhatsAppSendResponse:
        response, identifier = await durable_send(
            group_id,
            body,
            current_user=current_user,
            session=session,
            idempotency_key=idempotency_key,
            queue=queue,
        )
        await session.commit()
        # The outbox is durable before publishing; broker uncertainty never
        # invalidates this initial receipt or permits a new business batch.
        from app.infrastructure.whatsapp.web_publication import run_whatsapp_send_publication

        await run_whatsapp_send_publication(intent_id=identifier, limit=1)
        return response
