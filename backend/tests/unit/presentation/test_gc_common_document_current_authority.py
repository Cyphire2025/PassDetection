"""Current dashboard authority must survive neither validation nor storage waits."""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.gc_mobile_models import GCCommonDocumentModel, GCGroupAccessModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    UserModel,
    UserSecurityStateModel,
)
from app.presentation.api.v1.routes import gc_app_common_documents as routes
from app.presentation.api.v1.routes import gc_app_common_staging as staging
from tests.persistence import persist_graph


@dataclass(frozen=True)
class DocumentScope:
    actor: User
    agency_id: uuid.UUID
    other_agency_id: uuid.UUID
    group_id: uuid.UUID
    access_id: uuid.UUID


async def document_scope(session: AsyncSession, change: str) -> DocumentScope:
    actor_id, agency_id, other_agency_id, group_id, access_id = (uuid.uuid4() for _ in range(5))
    access_level = change in {"access_level", "access_level_revoked"}
    global_admin = change == "global_admin"
    actor = User(
        id=actor_id, email="common-document@example.test", full_name="Synthetic operator",
        hashed_password="unused", agency_id=None if global_admin else agency_id,
        role=UserRole.SUPER_ADMIN if global_admin else UserRole.AGENCY_MANAGER,
        actual_role=UserRole.SUPER_ADMIN if access_level else None, actual_agency_id=None,
    )
    records = [
        AgencyModel(id=agency_id, name="Synthetic agency", email="common-agency@example.test"),
        AgencyModel(id=other_agency_id, name="Other agency", email="common-other@example.test"),
        UserModel(id=actor_id, email=actor.email, full_name=actor.full_name,
                  hashed_password="unused", role="super_admin" if access_level else actor.role.value,
                  agency_id=None if access_level or global_admin else agency_id),
        ClientGroupModel(id=group_id, agency_id=agency_id, name="Synthetic trip",
                         token=uuid.uuid4().hex, status="closed"),
        GCGroupAccessModel(id=access_id, agency_id=agency_id, group_id=group_id,
                           is_enabled=True, revision=1),
    ]
    if change != "legacy":
        records.append(UserSecurityStateModel(user_id=actor_id, credential_state="active", session_version=1))
    await persist_graph(session, records)
    await session.commit()
    return DocumentScope(actor, agency_id, other_agency_id, group_id, access_id)


async def change_stored_authority(session: AsyncSession, scope: DocumentScope, change: str) -> None:
    if change == "disabled":
        statement = update(UserModel).where(UserModel.id == scope.actor.id).values(is_active=False)
    elif change == "soft_deleted":
        statement = update(UserModel).where(UserModel.id == scope.actor.id).values(deleted_at=datetime.now(UTC))
    elif change in {"role", "access_level_revoked"}:
        statement = update(UserModel).where(UserModel.id == scope.actor.id).values(role="agency_staff")
    elif change == "agency":
        statement = update(UserModel).where(UserModel.id == scope.actor.id).values(agency_id=scope.other_agency_id)
    elif change == "profile":
        statement = update(UserModel).where(UserModel.id == scope.actor.id).values(full_name="Changed profile")
    elif change in {"session", "invited"}:
        statement = update(UserSecurityStateModel).where(UserSecurityStateModel.user_id == scope.actor.id).values(
            **({"session_version": 2} if change == "session" else {"credential_state": "invited"})
        )
    elif change == "revision":
        statement = update(GCGroupAccessModel).where(GCGroupAccessModel.id == scope.access_id).values(revision=2)
    elif change == "removed":
        statement = update(GCGroupAccessModel).where(GCGroupAccessModel.id == scope.access_id).values(
            removed_at=datetime.now(UTC), is_enabled=False, revoked_at=datetime.now(UTC)
        )
    elif change == "archived":
        statement = update(ClientGroupModel).where(ClientGroupModel.id == scope.group_id).values(status="archived")
    else:
        return
    await session.execute(statement)
    await session.commit()


@pytest.mark.parametrize("phase", ["validation", "storage"])
@pytest.mark.parametrize(
    ("change", "expected_status"),
    [
        ("healthy", None), ("profile", None), ("legacy", None),
        ("access_level", None), ("global_admin", None),
        ("disabled", 403), ("soft_deleted", 403), ("role", 403),
        ("agency", 403), ("session", 403), ("invited", 403),
        ("access_level_revoked", 403),
        ("revision", 409), ("removed", 404), ("archived", 409),
    ],
)
async def test_common_document_rechecks_current_authority_and_compensates(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
    phase: str, change: str, expected_status: int | None,
) -> None:
    scope = await document_scope(db_session, change)
    entered, release = asyncio.Event(), asyncio.Event()
    objects: dict[str, bytes] = {"unrelated/owned.pdf": b"unrelated"}
    uploads, deletes, validation_calls = [], [], []
    payload = b"%PDF-1.7\nsynthetic normalized document"

    async def wait_at(selected: str) -> None:
        if phase == selected:
            entered.set()
            await release.wait()

    async def validate(file: UploadFile) -> SimpleNamespace:
        validation_calls.append(await file.read())
        await file.close()
        await wait_at("validation")
        return SimpleNamespace(content=payload, content_type="application/pdf",
                               filename="synthetic.pdf", sha256_hex=hashlib.sha256(payload).hexdigest())

    class Storage:
        async def upload_file(self, content: bytes, key: str, content_type: str) -> str:
            assert content_type == "application/pdf"
            uploads.append(key)
            objects[key] = content
            await wait_at("storage")
            return key

        async def delete_files(self, keys: list[str]) -> int:
            deletes.extend(keys)
            for key in keys:
                objects.pop(key, None)
            return len(keys)

    monkeypatch.setattr(staging, "_validated_common_pdf", validate)
    monkeypatch.setattr(staging, "MinioStorageRepository", Storage)
    file = UploadFile(io.BytesIO(b"synthetic input"), filename="synthetic.pdf")
    task = asyncio.create_task(routes.upload_common_document(
        group_id=scope.group_id, request=Request({"type": "http", "headers": []}),
        file=file, category="travel_tips", display_name="Synthetic guide", offline_available=True,
        expected_access_revision=1, agency_id=scope.agency_id, current_user=scope.actor, session=db_session,
    ))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert not db_session.in_transaction()
        assert file.file.closed
        factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
        async with factory() as writer:
            await change_stored_authority(writer, scope, change)
        release.set()
        if expected_status is None:
            response = await task
            assert response.version == 1 and response.status == "draft"
            assert response.display_name == "Synthetic guide"
            assert "storage_key" not in response.model_dump()
            assert deletes == []
        else:
            with pytest.raises(HTTPException) as denied:
                await task
            assert denied.value.status_code == expected_status
            assert deletes == uploads
            assert objects == {"unrelated/owned.pdf": b"unrelated"}
        assert validation_calls == [b"synthetic input"]
        assert len(uploads) == 1
        assert not db_session.in_transaction()
        async with factory() as verification:
            count = await verification.scalar(select(func.count()).select_from(GCCommonDocumentModel))
            assert count == int(expected_status is None)
            access = await verification.get(GCGroupAccessModel, scope.access_id)
            assert access is not None
            assert access.revision == (2 if expected_status is None or change == "revision" else 1)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await file.close()
