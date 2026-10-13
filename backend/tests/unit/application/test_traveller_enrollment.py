"""Accepted renewals, frozen trips, private copies and withdrawal are separate."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.travellers.enrollment import (
    EnrollmentError,
    EnrollmentRequest,
    enroll_submission,
)
from app.application.travellers.retention import (
    deletable_storage_keys,
    detach_submission_provenance,
    revoke_retained_profile,
)
from app.core.config.traveller_reuse import TravellerReuseSettings
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerContactBindingModel,
    TravellerDocumentAssetModel,
    TravellerDocumentRevisionModel,
    TravellerParticipationModel,
    TravellerPassportModel,
    TravellerProfileModel,
    TravellerReusePolicyModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto
from app.infrastructure.storage.minio_repository import ObjectIntegrityMetadata
from app.infrastructure.travellers.asset_copy import copy_next_asset


async def _fixture(session):
    crypto = TravellerReuseCrypto(TravellerReuseSettings(lookup_key="fixture-lookup-secret-" * 3,
        encryption_key=Fernet.generate_key().decode()))
    agency = AgencyModel(name="Synthetic", email=f"{uuid.uuid4()}@example.invalid")
    session.add(agency)
    await session.flush()
    user = UserModel(agency_id=agency.id, email=f"{uuid.uuid4()}@example.invalid", full_name="Synthetic reviewer",
        hashed_password="unused", role="agency_admin")
    company = ClientOrganizationModel(agency_id=agency.id, name="Company", normalized_name="company")
    session.add_all([user, company])
    await session.flush()
    group = ClientGroupModel(agency_id=agency.id, company_id=company.id, company_revision=1,
        token=uuid.uuid4().hex, name="Historical trip")
    session.add(group)
    session.add(TravellerReusePolicyModel(agency_id=agency.id, company_id=company.id, enabled=True,
        purpose_version="future-trip-v1", notice_version="notice-v1", processing_basis="recorded-authority",
        configured_at=datetime.now(UTC)))
    await session.flush()
    source = _source(group)
    session.add(source)
    await session.flush()
    request = EnrollmentRequest(agency.id, company.id, group.id, source.id, user.id, 1, 1,
        "synthetic-permission-record", "first-source")
    return SimpleNamespace(crypto=crypto, group=group, source=source, request=request)


def _source(group, number="001234567", issue="2020-01-01", expiry="2030-01-01"):
    return PassportSubmissionModel(agency_id=group.agency_id, group_id=group.id,
        client_name="Synthetic Person", client_phone="+919999999999", image_s3_key=f"front/{uuid.uuid4()}.jpg",
        passport_back_s3_key=f"back/{uuid.uuid4()}.jpg", status="staff_approved", extraction_revision=1,
        confirmed_fields={"passport_number": number, "issuing_country": "IND", "document_type": "PASSPORT",
            "given_names": "Synthetic", "surname": "Person", "date_of_birth": "1990-01-01",
            "date_of_issue": issue, "date_of_expiry": expiry})


@pytest.mark.asyncio
async def test_enrollment_preserves_history_and_accepts_next_trip_renewal(db_session):
    ctx = await _fixture(db_session)
    first = await enroll_submission(db_session, ctx.request, ctx.crypto)
    retry = await enroll_submission(db_session, ctx.request, ctx.crypto)
    assert retry == first and first.copies_pending == 2
    contact = await db_session.scalar(select(TravellerContactBindingModel))
    assert contact.verified_at is None and contact.verification_evidence == {"source": "legacy_unverified"}
    old_membership = await db_session.scalar(select(TravellerParticipationModel))
    frozen_revision = old_membership.document_revision_id
    renewal_source = _source(ctx.group, number="009876543", issue="2026-01-01", expiry="2036-01-01")
    db_session.add(renewal_source)
    await db_session.flush()
    renewal = await enroll_submission(db_session, replace(ctx.request, submission_id=renewal_source.id,
        idempotency_key="renewal", traveller_id=first.traveller_id, expected_profile_revision=1, change_kind="renewal"), ctx.crypto)
    passports = list((await db_session.scalars(select(TravellerPassportModel))).all())
    assert [p.id for p in passports if p.is_default] == [renewal.passport_id]
    assert old_membership.document_revision_id == frozen_revision
    older_scan = _source(ctx.group)
    db_session.add(older_scan)
    await db_session.flush()
    await enroll_submission(db_session, replace(ctx.request, submission_id=older_scan.id,
        idempotency_key="later-old-scan", traveller_id=first.traveller_id, expected_profile_revision=2, change_kind="scan"), ctx.crypto)
    assert [p.id for p in passports if p.is_default] == [renewal.passport_id]
    assert await db_session.scalar(select(func.count()).select_from(TravellerProfileModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentRevisionModel)) == 3
    assert old_membership.document_revision_id == frozen_revision


@pytest.mark.asyncio
async def test_candidate_upload_and_unknown_issuer_do_not_become_accepted_history(db_session):
    ctx = await _fixture(db_session)
    ctx.source.status = "ai_approved"
    await db_session.flush()
    with pytest.raises(EnrollmentError, match="accepted_source_revision_required"):
        async with db_session.begin_nested():
            await enroll_submission(db_session, ctx.request, ctx.crypto)
    ctx.source.status = "staff_approved"
    ctx.source.confirmed_fields = {"passport_number": "001234567", "nationality": "IND", "document_type": "PASSPORT"}
    await db_session.flush()
    with pytest.raises(EnrollmentError, match="reliable_issuing_context_required"):
        async with db_session.begin_nested():
            await enroll_submission(db_session, ctx.request, ctx.crypto)
    assert await db_session.scalar(select(func.count()).select_from(TravellerProfileModel)) == 0


@pytest.mark.asyncio
async def test_independent_copy_is_retryable_and_old_group_deletion_cannot_purge_it(db_session):
    ctx = await _fixture(db_session)
    result = await enroll_submission(db_session, ctx.request, ctx.crypto)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    storage = SimpleNamespace(stat_file=AsyncMock(return_value=ObjectIntegrityMetadata(4096, "a" * 64, "image/jpeg")),
                              copy_file=AsyncMock(return_value="ignored"))
    assert await copy_next_asset(session_factory=factory, storage=storage)
    assert await copy_next_asset(session_factory=factory, storage=storage)
    assert not await copy_next_asset(session_factory=factory, storage=storage)
    db_session.expire_all()
    assets = list((await db_session.scalars(select(TravellerDocumentAssetModel))).all())
    assert len(assets) == 2 and all(a.availability == "available" for a in assets)
    keys = [a.object_key for a in assets]
    assert all(key.startswith("travellers/") and key.endswith(".jpg") for key in keys)
    assert await deletable_storage_keys(db_session, keys, agency_id=ctx.request.agency_id) == []
    await detach_submission_provenance(db_session, [ctx.request.submission_id])
    revision = await db_session.get(TravellerDocumentRevisionModel, result.document_revision_id)
    assert revision.source_submission_id is None
    assert revision.source_provenance["submission_id"] == str(ctx.request.submission_id)
    assert await revoke_retained_profile(db_session, agency_id=ctx.request.agency_id, company_id=ctx.request.company_id,
        traveller_id=result.traveller_id, expected_revision=1)
    assert await deletable_storage_keys(db_session, keys, agency_id=ctx.request.agency_id) == keys


@pytest.mark.asyncio
async def test_copy_outage_does_not_publish_asset_or_retry_forever(db_session):
    ctx = await _fixture(db_session)
    await enroll_submission(db_session, ctx.request, ctx.crypto)
    assets = list((await db_session.scalars(select(TravellerDocumentAssetModel))).all())
    for asset in assets:
        asset.copy_attempt_count = 4
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    storage = SimpleNamespace(stat_file=AsyncMock(side_effect=RuntimeError("synthetic unavailable")), copy_file=AsyncMock())
    assert not await copy_next_asset(session_factory=factory, storage=storage)
    assert not await copy_next_asset(session_factory=factory, storage=storage)
    db_session.expire_all()
    assets = list((await db_session.scalars(select(TravellerDocumentAssetModel))).all())
    assert all(a.availability == "unreadable" and a.copy_attempt_count == 5 for a in assets)
    assert not await copy_next_asset(session_factory=factory, storage=storage)
    storage.copy_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_source_revision_fails_before_storage_copy(db_session):
    ctx = await _fixture(db_session)
    await enroll_submission(db_session, ctx.request, ctx.crypto)
    ctx.source.extraction_revision += 1
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    storage = SimpleNamespace(stat_file=AsyncMock(), copy_file=AsyncMock())
    assert not await copy_next_asset(session_factory=factory, storage=storage)
    storage.copy_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_timed_out_provider_keeps_admission_lease_until_thread_timeout_envelope(db_session):
    ctx = await _fixture(db_session)
    await enroll_submission(db_session, ctx.request, ctx.crypto)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    storage = SimpleNamespace(stat_file=AsyncMock(side_effect=TimeoutError()), copy_file=AsyncMock())
    assert not await copy_next_asset(session_factory=factory, storage=storage)
    assert not await copy_next_asset(session_factory=factory, storage=storage)
    assert not await copy_next_asset(session_factory=factory, storage=storage)
    assert storage.stat_file.await_count == 2
    db_session.expire_all()
    assets = list((await db_session.scalars(select(TravellerDocumentAssetModel))).all())
    assert all(a.lease_expires_at is not None and a.copy_attempt_count == 1 for a in assets)


@pytest.mark.asyncio
async def test_missing_context_requires_explicit_attestation_and_retry_binds_full_payload(db_session):
    ctx = await _fixture(db_session)
    ctx.source.confirmed_fields = {key: value for key, value in ctx.source.confirmed_fields.items()
        if key not in {"issuing_country", "document_type"}}
    await db_session.flush()
    request = replace(ctx.request, reviewed_issuing_country="IND", reviewed_document_type="P")
    with pytest.raises(EnrollmentError, match="reviewed_issuing_context_required"):
        async with db_session.begin_nested():
            await enroll_submission(db_session, request, ctx.crypto)
    request = replace(request, reviewed_context_confirmed=True)
    result = await enroll_submission(db_session, request, ctx.crypto)
    revision = await db_session.get(TravellerDocumentRevisionModel, result.document_revision_id)
    assert revision.source_provenance["reviewed_issuing_context"]["actor_user_id"] == str(request.actor_id)
    assert (await enroll_submission(db_session, request, ctx.crypto)) == result
    with pytest.raises(EnrollmentError, match="idempotency_conflict"):
        async with db_session.begin_nested():
            await enroll_submission(db_session, replace(request, reviewed_document_type="PASSPORT"), ctx.crypto)


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type,byte_size", [("text/html", 100), ("image/jpeg", 20 * 1024 * 1024 + 1)])
async def test_copy_rejects_unsupported_or_oversized_objects_before_copy(db_session, content_type, byte_size):
    ctx = await _fixture(db_session)
    await enroll_submission(db_session, ctx.request, ctx.crypto)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    storage = SimpleNamespace(stat_file=AsyncMock(return_value=ObjectIntegrityMetadata(byte_size, None, content_type)), copy_file=AsyncMock())
    assert not await copy_next_asset(session_factory=factory, storage=storage)
    storage.copy_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_copy_rechecks_withdrawal_after_provider_finishes(db_session):
    ctx = await _fixture(db_session)
    result = await enroll_submission(db_session, ctx.request, ctx.crypto)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async def withdraw_during_copy(*args):
        async with factory() as other, other.begin():
            await revoke_retained_profile(other, agency_id=ctx.request.agency_id, company_id=ctx.request.company_id,
                traveller_id=result.traveller_id, expected_revision=1)
    storage = SimpleNamespace(stat_file=AsyncMock(return_value=ObjectIntegrityMetadata(4096, None, "image/jpeg")),
        copy_file=AsyncMock(side_effect=withdraw_during_copy))
    assert not await copy_next_asset(session_factory=factory, storage=storage)
    db_session.expire_all()
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentAssetModel).where(
        TravellerDocumentAssetModel.availability == "available")) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_status", ["lost", "cancelled", "compromised", "disputed", "rejected"])
async def test_scan_cannot_reactivate_blocked_passport_identity(db_session, blocked_status):
    ctx = await _fixture(db_session)
    enrolled = await enroll_submission(db_session, ctx.request, ctx.crypto)
    passport = await db_session.get(TravellerPassportModel, enrolled.passport_id)
    passport.status = blocked_status
    passport.is_default = False
    fresh_source = _source(ctx.group)
    db_session.add(fresh_source)
    await db_session.flush()
    with pytest.raises(EnrollmentError, match="unusable_document_cannot_be_reactivated"):
        async with db_session.begin_nested():
            await enroll_submission(db_session, replace(ctx.request, submission_id=fresh_source.id,
                idempotency_key="blocked-scan", traveller_id=enrolled.traveller_id,
                expected_profile_revision=1, change_kind="scan"), ctx.crypto)
    assert (await db_session.get(TravellerPassportModel, enrolled.passport_id)).status == blocked_status
