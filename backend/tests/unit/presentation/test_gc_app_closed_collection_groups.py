"""A closed collection link must not prevent explicit GC App trip access."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from app.application.security.mobile_access_policy import MobileAccessPolicy
from app.application.use_cases.client_groups.revoke_client_group_use_case import (
    RevokeClientGroupUseCase,
)
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.entities.entities import UserRole
from app.infrastructure.database.gc_mobile_models import (
    ClientOrganizationModel,
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
    MobileSyncChangeModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.routes.gc_app import (
    configure_gc_group_access,
    search_gc_groups,
)
from app.presentation.api.v1.schemas.gc_app_schemas import GCGroupAccessUpdateRequest


def _group(agency_id, *, status="closed", deleted=False):
    now = datetime.now(UTC)
    return ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        name="Synthetic collection group",
        token=uuid.uuid4().hex,
        status=status,
        closed_at=now if status == "closed" else None,
        deleted_at=now if deleted else None,
    )


async def _context(session, *, status="closed", deleted=False):
    agency = AgencyModel(
        id=uuid.uuid4(), name="Synthetic agency", email=f"{uuid.uuid4().hex}@example.test"
    )
    actor = UserModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        email=f"{uuid.uuid4().hex}@example.test",
        full_name="Synthetic admin",
        hashed_password="synthetic-not-a-real-password-hash",
        role=UserRole.AGENCY_ADMIN.value,
        is_active=True,
    )
    organization = ClientOrganizationModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        name="Synthetic client",
        normalized_name="synthetic client",
        status="active",
    )
    group = _group(agency.id, status=status, deleted=deleted)
    session.add(agency)
    await session.flush()
    session.add_all([actor, organization, group])
    await session.flush()
    principal = SimpleNamespace(
        id=actor.id,
        agency_id=actor.agency_id,
        email=actor.email,
        role=UserRole.AGENCY_ADMIN,
    )
    return principal, organization, group


async def _configure(session, principal, organization, group, **changes):
    return await configure_gc_group_access(
        group_id=group.id,
        body=GCGroupAccessUpdateRequest(
            client_organization_id=organization.id,
            **{"enabled": True, **changes},
        ),
        request=Request(
            {
                "type": "http",
                "method": "PUT",
                "path": "/",
                "headers": [],
                "client": ("127.0.0.1", 12345),
            }
        ),
        agency_id=None,
        current_user=principal,
        session=session,
    )


async def _search(session, principal, *, offset=0):
    return await search_gc_groups(
        q=None,
        agency_id=None,
        group_id=None,
        gc_enabled=None,
        eligible_only=True,
        lifecycle_status=None,
        offset=offset,
        limit=2,
        current_user=principal,
        session=session,
    )


@pytest.mark.asyncio
async def test_candidate_search_paginates_open_and_closed_groups_with_tenant_and_removal_guards(
    db_session,
):
    actor, organization, closed = await _context(db_session)
    opened = _group(actor.agency_id, status="active")
    disabled = _group(actor.agency_id)
    already_enabled = _group(actor.agency_id, status="active")
    excluded = [
        _group(actor.agency_id, status="archived"),
        _group(actor.agency_id, status="deleted", deleted=True),
        _group(actor.agency_id, status="active", deleted=True),
    ]
    db_session.add_all([opened, disabled, already_enabled, *excluded])
    await db_session.flush()
    for group, enabled in [(disabled, False), (already_enabled, True)]:
        db_session.add(
            GCGroupAccessModel(
                id=uuid.uuid4(),
                agency_id=actor.agency_id,
                group_id=group.id,
                client_organization_id=organization.id,
                is_enabled=enabled,
                revoked_at=None if enabled else datetime.now(UTC),
            )
        )
    await _context(db_session, status="closed")  # Another agency is never a candidate.
    await db_session.flush()
    first = await _search(db_session, actor)
    second = await _search(db_session, actor, offset=2)
    assert first.total == second.total == 3
    assert {item.id for item in [*first.items, *second.items]} == {
        closed.id,
        opened.id,
        disabled.id,
    }
    assert len(first.items) == 2 and len(second.items) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("collection_status", ["active", "closed"])
async def test_new_app_access_reconciles_passengers_without_reopening_collection(
    db_session,
    collection_status,
):
    actor, organization, group = await _context(db_session, status=collection_status)
    closed_at = group.closed_at
    passenger = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=actor.agency_id,
        group_id=group.id,
        client_name="Synthetic passenger",
        client_phone="+919876543210",
        image_s3_key="synthetic/no-real-image",
        status="staff_approved",
        client_reviewed_at=datetime.now(UTC),
        confirmed_fields={"given_names": "SYNTHETIC", "date_of_birth": "1990-01-01"},
    )
    db_session.add(passenger)
    await db_session.flush()
    response = await _configure(db_session, actor, organization, group)
    await db_session.commit()
    assert response.enabled and response.lifecycle_status == collection_status
    assert group.status == collection_status
    # Locking refreshes the group from storage; SQLite loses timezone metadata
    # even though the original UTC closure instant remains unchanged.
    assert (group.closed_at.replace(tzinfo=UTC) if group.closed_at else None) == closed_at
    identity = (await db_session.scalars(select(MobilePassengerIdentityModel))).one()
    assert identity.group_id == group.id and identity.agency_id == actor.agency_id
    assert identity.passenger_submission_id == passenger.id and identity.status == "eligible"
    changes = list(await db_session.scalars(select(MobileSyncChangeModel)))
    assert any(row.entity_type == "group_access" and row.operation == "upsert" for row in changes)


@pytest.mark.asyncio
async def test_closed_collection_app_access_can_be_disabled_and_reenabled_with_revision_guard(
    db_session,
):
    actor, organization, group = await _context(db_session)
    first = await _configure(db_session, actor, organization, group)
    disabled = await _configure(
        db_session,
        actor,
        organization,
        group,
        enabled=False,
        expected_revision=first.revision,
    )
    assert not disabled.enabled and disabled.revoked_at is not None
    with pytest.raises(HTTPException) as stale:
        await _configure(
            db_session,
            actor,
            organization,
            group,
            expected_revision=first.revision,
        )
    assert stale.value.status_code == 409
    enabled = await _configure(
        db_session,
        actor,
        organization,
        group,
        expected_revision=disabled.revision,
    )
    assert enabled.enabled and enabled.revoked_at is None
    assert group.status == "closed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,deleted", [("archived", False), ("deleted", True), ("active", True)]
)
@pytest.mark.parametrize("enabled", [True, False])
async def test_removed_group_cannot_be_newly_added_even_as_disabled_access(
    db_session,
    status,
    deleted,
    enabled,
):
    actor, organization, group = await _context(db_session, status=status, deleted=deleted)
    with pytest.raises(HTTPException) as rejected:
        await _configure(db_session, actor, organization, group, enabled=enabled)
    assert rejected.value.status_code == 409
    assert list(await db_session.scalars(select(GCGroupAccessModel))) == []


@pytest.mark.asyncio
async def test_closed_group_from_another_agency_cannot_be_added(db_session):
    actor, organization, _ = await _context(db_session)
    _, _, foreign = await _context(db_session)
    with pytest.raises(HTTPException) as rejected:
        await _configure(db_session, actor, organization, foreign)
    assert rejected.value.status_code == 404
    assert list(await db_session.scalars(select(GCGroupAccessModel))) == []


async def test_closing_existing_collection_does_not_revoke_configured_mobile_trip(db_session):
    actor, organization, group = await _context(db_session, status="active")
    await _configure(db_session, actor, organization, group)
    submission = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=actor.agency_id,
        group_id=group.id,
        client_name="Synthetic passenger",
        client_phone="+919876543210",
        image_s3_key="synthetic/public.jpg",
        status="needs_review",
        client_reviewed_at=datetime.now(UTC),
    )
    db_session.add(submission)
    await db_session.flush()
    access = (await db_session.scalars(select(GCGroupAccessModel))).one()
    identity = MobilePassengerIdentityModel(
        id=uuid.uuid4(),
        agency_id=actor.agency_id,
        group_id=group.id,
        gc_group_access_id=access.id,
        passenger_submission_id=submission.id,
        normalized_phone_number=submission.client_phone,
        phone_lookup_hash=uuid.uuid4().hex * 2,
        status="eligible",
    )
    db_session.add(identity)
    await db_session.commit()
    await RevokeClientGroupUseCase(ClientGroupRepository(db_session)).execute(
        group.id, actor.agency_id
    )
    await db_session.commit()
    claims = MobileAccessClaims(
        principal_id=identity.id,
        account_id=identity.id,
        principal_type="passenger",
        agency_id=actor.agency_id,
        session_id=uuid.uuid4(),
        session_generation=0,
        password_change_required=False,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    context = await MobileAccessPolicy(db_session).require_trip_access(claims, group.id)
    assert context.group.status == "closed"
    assert context.access.is_enabled and context.access.revoked_at is None
