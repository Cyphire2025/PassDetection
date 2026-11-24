"""Persisted account revocation during actual workbook parsing denies writes."""

from __future__ import annotations

import asyncio
import io
import json
import threading
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
    UserSecurityStateModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes import whatsapp_contact_import, whatsapp_groups_manage
from app.presentation.api.v1.routes.whatsapp_scope import _lock_active_whatsapp_actor
from app.presentation.dependencies.auth import get_current_active_user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "expected_status"),
    [
        ("session_revoked", 403),
        ("credential_withdrawn", 403),
        ("deactivated", 403),
        ("healthy", 201),
        ("profile_only", 201),
        ("legacy_no_state", 201),
    ],
)
async def test_actual_workbook_import_rechecks_current_account_before_writes(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    expected_status: int,
) -> None:
    agency_id, user_id = uuid.uuid4(), uuid.uuid4()
    actor = User(
        id=user_id,
        email="admin@example.test",
        hashed_password="unused",
        full_name="Admin",
        role=UserRole.AGENCY_ADMIN,
        agency_id=agency_id,
    )
    db_session.add(AgencyModel(id=agency_id, name="Agency", email="agency@example.test"))
    await db_session.flush()
    db_session.add(
        UserModel(
            id=user_id,
            agency_id=agency_id,
            email=actor.email,
            full_name=actor.full_name,
            hashed_password="unused",
            role=actor.role.value,
            is_active=True,
        )
    )
    await db_session.flush()
    if change != "legacy_no_state":
        db_session.add(
            UserSecurityStateModel(
                user_id=user_id,
                session_version=1,
                credential_state="active",
            )
        )
    await db_session.commit()
    workbook = Workbook()
    workbook.active.append(["Name", "Phone"])
    workbook.active.append(["Traveller", "9876543210"])
    content = io.BytesIO()
    workbook.save(content)
    workbook.close()

    entered, release = threading.Event(), threading.Event()
    original = whatsapp_contact_import._parse_excel_contact_bytes

    def held_parser(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        if not release.wait(10):
            raise RuntimeError("synthetic parser release timed out")
        return result

    monkeypatch.setattr(whatsapp_contact_import, "_parse_excel_contact_bytes", held_parser)
    app = FastAPI()
    app.include_router(whatsapp_groups_manage.router, prefix="/whatsapp")
    app.dependency_overrides[get_current_active_user] = lambda: actor

    async def request_session():
        try:
            yield db_session
            await db_session.commit()
        except BaseException:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db_session] = request_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        task = asyncio.create_task(
            client.post(
                "/whatsapp/groups",
                data={
                    "name": "Imported list",
                    "organizing_company_name": "Agency",
                    "contacts_json": "[]",
                    "rejected_contacts_json": "[]",
                    "support_contacts_json": json.dumps(
                        [{"name": "Support", "phone_number": "9876543211"}]
                    ),
                    "recipient_opt_in_confirmed": "true",
                },
                files={
                    "contacts_file": (
                        "contacts.xlsx",
                        content.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 5), "real workbook parser was not reached"
            async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as writer:
                if change == "session_revoked":
                    state = await writer.get(UserSecurityStateModel, user_id)
                    state.session_version += 1
                elif change == "credential_withdrawn":
                    state = await writer.get(UserSecurityStateModel, user_id)
                    state.credential_state = "invited"
                elif change in {"deactivated", "profile_only"}:
                    account = await writer.get(UserModel, user_id)
                    if change == "deactivated":
                        account.is_active = False
                    else:
                        account.full_name = "Updated profile"
                await writer.commit()
        finally:
            release.set()
            response = await asyncio.wait_for(task, 10)

    assert response.status_code == expected_status, response.text
    expected_rows = int(expected_status == 201)
    for model in (
        WhatsAppBroadcastGroupModel,
        WhatsAppBroadcastRecipientModel,
        WhatsAppBroadcastSupportContactModel,
    ):
        assert await db_session.scalar(select(func.count()).select_from(model)) == expected_rows


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["session_version", "credential_state"])
async def test_current_credential_lock_replaces_cached_security_state(
    db_session: AsyncSession,
    change: str,
) -> None:
    agency_id, user_id = uuid.uuid4(), uuid.uuid4()
    actor = User(
        id=user_id,
        email="cached@example.test",
        hashed_password="unused",
        full_name="Admin",
        role=UserRole.AGENCY_ADMIN,
        agency_id=agency_id,
    )
    db_session.add(AgencyModel(id=agency_id, name="Agency", email="agency@example.test"))
    await db_session.flush()
    db_session.add(
        UserModel(
            id=user_id,
            agency_id=agency_id,
            email=actor.email,
            full_name=actor.full_name,
            hashed_password="unused",
            role=actor.role.value,
            is_active=True,
        )
    )
    await db_session.flush()
    db_session.add(
        UserSecurityStateModel(
            user_id=user_id,
            session_version=1,
            credential_state="active",
        )
    )
    await db_session.commit()
    cached = await db_session.get(UserSecurityStateModel, user_id)
    assert cached is not None
    async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as writer:
        state = await writer.get(UserSecurityStateModel, user_id)
        assert state is not None
        setattr(state, change, 2 if change == "session_version" else "invited")
        await writer.commit()
    assert cached.session_version == 1
    assert cached.credential_state == "active"

    with pytest.raises(HTTPException) as caught:
        await _lock_active_whatsapp_actor(
            db_session,
            current_user=actor,
            require_agency=True,
        )

    assert caught.value.status_code == 403
    assert getattr(cached, change) == (2 if change == "session_version" else "invited")
