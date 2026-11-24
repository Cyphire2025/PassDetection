"""Hold synthetic validation while real stored WhatsApp authority changes."""

from __future__ import annotations

import asyncio
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import Headers

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
    UserSecurityStateModel,
    WhatsAppBroadcastGroupModel,
)
from app.infrastructure.security.upload_validator import ValidatedUpload
from app.presentation.api.v1.routes import whatsapp_composer as route
from app.presentation.api.v1.routes import whatsapp_composer_media as media
from tests.persistence import persist_graph


@dataclass(frozen=True)
class MediaScope:
    actor: User
    group_id: uuid.UUID
    agency_id: uuid.UUID
    other_agency_id: uuid.UUID


async def media_scope(session: AsyncSession, change: str) -> MediaScope:
    actor_id, agency_id, other_agency_id, group_id = (uuid.uuid4() for _ in range(4))
    access_level = change in {"access_level", "access_level_revoked"}
    global_admin = change == "global_admin"
    actor = User(
        id=actor_id,
        agency_id=None if global_admin else agency_id,
        email="media@example.test",
        hashed_password="unused",
        full_name="Media operator",
        role=UserRole.SUPER_ADMIN if global_admin else UserRole.AGENCY_MANAGER,
        actual_role=UserRole.SUPER_ADMIN if access_level else None,
        actual_agency_id=None,
    )
    records = [
        AgencyModel(id=agency_id, name="Synthetic agency", email="agency@example.test"),
        AgencyModel(id=other_agency_id, name="Other agency", email="other@example.test"),
        UserModel(
            id=actor_id,
            agency_id=None if access_level or global_admin else agency_id,
            email=actor.email,
            hashed_password="unused",
            full_name=actor.full_name,
            role=UserRole.SUPER_ADMIN.value if access_level else actor.role.value,
        ),
        WhatsAppBroadcastGroupModel(id=group_id, agency_id=agency_id, name="Synthetic trip"),
    ]
    if change != "legacy":
        records.append(
            UserSecurityStateModel(user_id=actor_id, credential_state="active", session_version=1)
        )
    await persist_graph(session, records)
    await session.commit()
    return MediaScope(actor, group_id, agency_id, other_agency_id)


async def change_stored_scope(session: AsyncSession, scope: MediaScope, change: str) -> None:
    if change == "disabled":
        statement = update(UserModel).where(UserModel.id == scope.actor.id).values(is_active=False)
    elif change == "account_deleted":
        statement = delete(UserModel).where(UserModel.id == scope.actor.id)
    elif change == "soft_deleted":
        statement = (
            update(UserModel)
            .where(UserModel.id == scope.actor.id)
            .values(deleted_at=datetime.now(UTC))
        )
    elif change in {"role", "access_level_revoked"}:
        statement = (
            update(UserModel).where(UserModel.id == scope.actor.id).values(role="agency_staff")
        )
    elif change == "reassigned":
        statement = (
            update(UserModel)
            .where(UserModel.id == scope.actor.id)
            .values(agency_id=scope.other_agency_id)
        )
    elif change == "profile":
        statement = (
            update(UserModel)
            .where(UserModel.id == scope.actor.id)
            .values(full_name="Updated profile")
        )
    elif change in {"session", "invited"}:
        statement = (
            update(UserSecurityStateModel)
            .where(
                UserSecurityStateModel.user_id == scope.actor.id,
            )
            .values(
                **(
                    {"session_version": 2}
                    if change == "session"
                    else {"credential_state": "invited"}
                )
            )
        )
    elif change == "agency_suspended":
        statement = (
            update(AgencyModel).where(AgencyModel.id == scope.agency_id).values(is_active=False)
        )
    elif change == "archived":
        statement = (
            update(WhatsAppBroadcastGroupModel)
            .where(
                WhatsAppBroadcastGroupModel.id == scope.group_id,
            )
            .values(archived_at=datetime.now(UTC))
        )
    elif change == "group_reassigned":
        statement = (
            update(WhatsAppBroadcastGroupModel)
            .where(
                WhatsAppBroadcastGroupModel.id == scope.group_id,
            )
            .values(agency_id=scope.other_agency_id)
        )
    elif change == "group_deleted":
        statement = delete(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == scope.group_id
        )
    else:
        return
    await session.execute(statement)
    await session.commit()


@pytest.mark.parametrize(
    ("change", "expected_status"),
    [
        ("healthy", None),
        ("profile", None),
        ("legacy", None),
        ("access_level", None),
        ("global_admin", None),
        ("disabled", 403),
        ("account_deleted", 403),
        ("soft_deleted", 403),
        ("role", 403),
        ("reassigned", 403),
        ("session", 403),
        ("invited", 403),
        ("access_level_revoked", 403),
        ("agency_suspended", 403),
        ("archived", 409),
        ("group_reassigned", 404),
        ("group_deleted", 404),
    ],
)
async def test_media_authority_is_current_after_held_validation(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    expected_status: int | None,
) -> None:
    scope = await media_scope(db_session, change)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    upload = AsyncMock(return_value="synthetic-media-id")

    class Validator:
        async def validate_image(self, **kwargs):
            calls.append(kwargs)
            entered.set()
            await release.wait()
            return ValidatedUpload(
                b"synthetic-normalized-image", "image/png", "header.png", 1, 1, "PNG"
            )

    client_closed = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            client_closed.append(True)

    monkeypatch.setattr(media, "UploadSecurityService", Validator)
    monkeypatch.setattr(media, "upload_whatsapp_image", upload)
    monkeypatch.setattr(
        media,
        "httpx",
        SimpleNamespace(AsyncClient=lambda **kwargs: Client(), Timeout=httpx.Timeout),
    )
    image = UploadFile(
        io.BytesIO(b"synthetic-input-image"),
        filename="header.png",
        headers=Headers({"content-type": "image/png"}),
    )
    task = asyncio.create_task(
        route.upload_welcome_media(scope.group_id, image, scope.actor, db_session)
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert image.file.closed  # The owned UploadFile is closed before native/security work.
        writer_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
        async with writer_factory() as writer:
            await change_stored_scope(writer, scope, change)
        release.set()
        if expected_status is None:
            response = await task
            assert response.media_id == "synthetic-media-id"
            upload.assert_awaited_once()
            assert upload.await_args.kwargs["file_content"] == b"synthetic-normalized-image"
            assert client_closed == [True]
        else:
            with pytest.raises(HTTPException) as error:
                await task
            assert error.value.status_code == expected_status
            upload.assert_not_awaited()
            assert client_closed == []
        assert len(calls) == 1
        assert calls[0]["context"].agency_id == scope.agency_id
        assert calls[0]["context"].user_id == scope.actor.id
        assert not db_session.in_transaction()
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancelled_validation_closes_upload_and_never_uploads_media(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = await media_scope(db_session, "healthy")
    entered = asyncio.Event()

    class Validator:
        async def validate_image(self, **kwargs):
            entered.set()
            await asyncio.Event().wait()

    upload = AsyncMock()
    monkeypatch.setattr(media, "UploadSecurityService", Validator)
    monkeypatch.setattr(media, "upload_whatsapp_image", upload)
    image = UploadFile(
        io.BytesIO(b"synthetic"),
        filename="header.png",
        headers=Headers({"content-type": "image/png"}),
    )
    task = asyncio.create_task(
        route.upload_welcome_media(scope.group_id, image, scope.actor, db_session)
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert image.file.closed
    upload.assert_not_awaited()


@pytest.mark.parametrize("outcome", ["success", "provider_error", "cancelled"])
async def test_provider_operation_owns_current_authority_until_closed(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    scope = await media_scope(db_session, "healthy")
    entered, release = asyncio.Event(), asyncio.Event()
    closed = []

    class Validator:
        async def validate_image(self, **kwargs):
            return ValidatedUpload(b"synthetic", "image/png", "header.png", 1, 1, "PNG")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            closed.append(True)

    async def upload(**kwargs):
        assert db_session.in_transaction()
        entered.set()
        await release.wait()
        if outcome == "provider_error":
            raise route.WhatsAppCloudApiError("Synthetic unavailable", transient=True)
        return "synthetic-media-id"

    monkeypatch.setattr(media, "UploadSecurityService", Validator)
    monkeypatch.setattr(media, "upload_whatsapp_image", upload)
    monkeypatch.setattr(
        media,
        "httpx",
        SimpleNamespace(AsyncClient=lambda **kwargs: Client(), Timeout=httpx.Timeout),
    )
    image = UploadFile(
        io.BytesIO(b"synthetic"),
        filename="header.png",
        headers=Headers({"content-type": "image/png"}),
    )
    task = asyncio.create_task(
        route.upload_welcome_media(scope.group_id, image, scope.actor, db_session)
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert image.file.closed
        if outcome == "cancelled":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            if outcome == "provider_error":
                with pytest.raises(HTTPException) as error:
                    await task
                assert error.value.status_code == 503
            else:
                assert (await task).media_id == "synthetic-media-id"
        assert closed == [True]
        assert not db_session.in_transaction()
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
