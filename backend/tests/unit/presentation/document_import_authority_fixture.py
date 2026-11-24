"""Persisted actor/assignment changes while actual import-native work is held."""

from __future__ import annotations

import asyncio
import io
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from types import SimpleNamespace

from fastapi import BackgroundTasks, UploadFile
from PIL import Image
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.datastructures import Headers

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ManagerGroupAccessModel,
    PassportSubmissionModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.passenger_qr_models import PassengerQRTokenModel
from app.infrastructure.documents import passport_import_compensation
from app.infrastructure.documents.storage_cleanup import StorageCleanupCipher
from app.infrastructure.imports.passport_document_importer import PassportDocumentImporter
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.storage import minio_repository
from app.presentation.api.v1.routes import managed_account_sessions
from app.presentation.api.v1.routes.passport_routes import document_import, document_import_failure
from tests.passport_image_mutations import seed_image_mutation_context
from tests.unit.presentation.passport_document_import_fixture import NativeBarrier


async def prepare_authority_import(session, monkeypatch, settings, transition, phase):
    initial = await seed_image_mutation_context(session)
    actor_id, passenger_id = initial.actor.id, initial.submission.id
    group_id, agency_id = initial.submission.group_id, initial.submission.agency_id
    original_key = f"excel-imports/{passenger_id}/placeholder.jpg"
    await session.execute(
        update(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.id == passenger_id,
        )
        .values(staff_metadata={"staff_code": "A1"}, image_s3_key=original_key)
    )
    if transition in {"assignment_revoked", "owned_group_revoked", "assigned_staff_unchanged"}:
        await session.execute(
            update(UserModel).where(UserModel.id == actor_id).values(role="agency_staff")
        )
        if transition != "owned_group_revoked":
            await session.execute(
                update(ClientGroupModel)
                .where(ClientGroupModel.id == group_id)
                .values(created_by_user_id=None)
            )
            session.add(
                ManagerGroupAccessModel(
                    id=uuid.uuid4(),
                    manager_id=actor_id,
                    group_id=group_id,
                    agency_id=agency_id,
                )
            )
    elif transition == "manager_unassigned":
        await session.execute(
            update(UserModel).where(UserModel.id == actor_id).values(role="agency_manager")
        )
        await session.execute(
            update(ClientGroupModel)
            .where(ClientGroupModel.id == group_id)
            .values(created_by_user_id=None)
        )
    elif transition == "reduced_superadmin":
        await session.execute(
            update(UserModel)
            .where(UserModel.id == actor_id)
            .values(role="super_admin", agency_id=None)
        )
    qr = PassengerQRTokenModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        passenger_id=passenger_id,
        token_hash=uuid.uuid4().hex * 2,
        token_version=3,
        is_active=True,
        created_by_user_id=actor_id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    session.add(qr)
    qr_id, qr_hash = qr.id, qr.token_hash
    await session.commit()
    actor = await UserRepository(session).get_by_id(actor_id)
    if transition == "reduced_superadmin":
        actor = replace(
            actor,
            role=UserRole.AGENCY_MANAGER,
            agency_id=agency_id,
            actual_role=UserRole.SUPER_ADMIN,
            actual_agency_id=None,
        )
    await session.rollback()
    payload = io.BytesIO()
    Image.new("RGB", (800, 600), color="white").save(payload, format="JPEG")
    objects = {}

    def put(*, Key, Body, **_kwargs):
        objects[Key] = Body
        return {}

    client = SimpleNamespace(put_object=put)
    monkeypatch.setattr(minio_repository, "get_settings", lambda: settings)
    monkeypatch.setattr(minio_repository, "_shared_s3_clients", lambda: (client, client))
    cipher = StorageCleanupCipher("synthetic-authority-cleanup-key")
    monkeypatch.setattr(StorageCleanupCipher, "from_settings", classmethod(lambda _cls: cipher))
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr(
        document_import_failure,
        "reconcile_failed_passport_import",
        partial(
            passport_import_compensation.reconcile_failed_passport_import, session_factory=factory
        ),
    )
    if phase == "put":
        barrier = NativeBarrier(client.put_object)
        monkeypatch.setattr(client, "put_object", barrier)
    else:
        barrier = NativeBarrier(PassportDocumentImporter.collect)
        monkeypatch.setattr(
            PassportDocumentImporter, "collect", lambda self, *a, **kw: barrier(self, *a, **kw)
        )
    return SimpleNamespace(
        actor=actor,
        actor_id=actor_id,
        group_id=group_id,
        agency_id=agency_id,
        passenger_id=passenger_id,
        original_key=original_key,
        payload=payload.getvalue(),
        objects=objects,
        client=client,
        barrier=barrier,
        factory=factory,
        cipher=cipher,
        qr_id=qr_id,
        qr_hash=qr_hash,
        transition=transition,
    )


async def persist_authority_transition(context):
    """A completed independent AsyncSession transaction, not a mutated actor DTO."""
    async with context.factory() as writer:
        account = await writer.get(UserModel, context.actor_id)
        if context.transition == "sessions_revoked":
            await managed_account_sessions._fence_dashboard_sessions(writer, account)
        elif context.transition == "credential_reset":
            state = await IdentitySecurityRepository(writer).get_state(context.actor_id, lock=True)
            state.credential_state = "invited"
            state.session_version += 1
        elif context.transition == "inactive":
            account.is_active = False
        elif context.transition == "role_changed":
            account.role = "agency_staff"
        elif context.transition == "agency_changed":
            agency = AgencyModel(id=uuid.uuid4(), name="Other", email="other-import@example.test")
            writer.add(agency)
            await writer.flush()
            account.agency_id = agency.id
        elif context.transition == "profile_refresh":
            account.full_name = "Updated import reviewer"
        elif context.transition == "legacy_no_state":
            await writer.execute(
                delete(UserSecurityStateModel).where(
                    UserSecurityStateModel.user_id == context.actor_id
                )
            )
        elif context.transition == "assignment_revoked":
            await writer.execute(
                delete(ManagerGroupAccessModel).where(
                    ManagerGroupAccessModel.manager_id == context.actor_id,
                    ManagerGroupAccessModel.group_id == context.group_id,
                )
            )
        elif context.transition == "owned_group_revoked":
            await writer.execute(
                update(ClientGroupModel)
                .where(ClientGroupModel.id == context.group_id)
                .values(created_by_user_id=None)
            )
        elif context.transition == "group_deleted":
            await writer.execute(
                update(ClientGroupModel)
                .where(ClientGroupModel.id == context.group_id)
                .values(
                    status="deleted",
                    deleted_at=datetime.now(UTC),
                )
            )
        elif context.transition == "group_archived":
            await writer.execute(
                update(ClientGroupModel)
                .where(ClientGroupModel.id == context.group_id)
                .values(status="archived")
            )
        elif context.transition == "target_source_changed":
            await writer.execute(
                update(PassportSubmissionModel)
                .where(
                    PassportSubmissionModel.id == context.passenger_id,
                )
                .values(image_s3_key="front/concurrent-winner.jpg")
            )
        elif context.transition == "group_removed":
            await writer.execute(
                delete(PassportSubmissionModel).where(
                    PassportSubmissionModel.group_id == context.group_id
                )
            )
            await writer.execute(
                delete(ClientGroupModel).where(ClientGroupModel.id == context.group_id)
            )
        elif context.transition == "target_staff_changed":
            await writer.execute(
                update(PassportSubmissionModel)
                .where(
                    PassportSubmissionModel.id == context.passenger_id,
                )
                .values(staff_metadata={"staff_code": "B2"})
            )
        elif context.transition == "target_group_changed":
            group = ClientGroupModel(
                id=uuid.uuid4(),
                agency_id=context.agency_id,
                name="Concurrent target group",
                token=uuid.uuid4().hex,
            )
            writer.add(group)
            await writer.flush()
            await writer.execute(
                update(PassportSubmissionModel)
                .where(
                    PassportSubmissionModel.id == context.passenger_id,
                )
                .values(group_id=group.id)
            )
        await writer.commit()


async def perform_held_import(context, session, phase):
    upload = UploadFile(
        io.BytesIO(context.payload),
        filename=getattr(context, "filename", "STF_A1_FRONT.jpg"),
        headers=Headers({"content-type": "image/jpeg"}),
    )

    async def invoke():
        arguments = dict(
            group_id=context.group_id,
            files=[upload],
            current_user=context.actor,
            session=session,
        )
        if phase in {"put", "save_validation"}:
            return await document_import.save_passport_documents_by_group(
                **arguments,
                background_tasks=BackgroundTasks(),
            )
        return await document_import.preview_passport_documents_by_group(**arguments)

    task = asyncio.create_task(invoke())
    try:
        await asyncio.wait_for(context.barrier.entered.wait(), 3)
        assert not task.done()
        await persist_authority_transition(context)
    finally:
        context.barrier.release.set()
        outcome = (await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5))[0]
        await asyncio.wait_for(context.barrier.completed.wait(), 3)
        await upload.close()
    return outcome
