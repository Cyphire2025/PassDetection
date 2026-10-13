"""Synthetic staff master edits preserve frozen trips and tenant boundaries."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.companies.current_record import edit_current_record
from app.application.companies.document_publication import publish_document_upload
from app.application.companies.document_upload import prepare_document_upload
from app.application.companies.people import (
    current_person,
    directory_items,
    document_items,
    person_scope,
    require_person,
)
from app.application.companies.people_contracts import DocumentUpload, PersonEdit
from app.application.travellers.enrollment import enroll_submission
from app.domain.exceptions.exceptions import ConflictError, EntityNotFoundError
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel as Claim,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerContactBindingModel as Contact,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel as Asset,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel as Document,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerMatchCaseModel as MatchCase,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel as Participation,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerProfileModel as Person,
)
from app.infrastructure.repositories.user_repository import UserRepository
from tests.unit.application.test_traveller_enrollment import _fixture


async def people_fixture(session):
    context = await _fixture(session)
    enrolled = await enroll_submission(session, context.request, context.crypto)
    person = await session.get(Person, enrolled.traveller_id)
    user = await UserRepository(session).get_by_id(context.request.actor_id)
    for asset in (await session.scalars(select(Asset))).all():
        asset.availability, asset.byte_size, asset.content_type = "available", 10, "image/jpeg"
        asset.source_object_key = None
    await session.flush()
    return context, person, user


@pytest.mark.asyncio
async def test_current_edit_is_idempotent_revokes_access_and_preserves_trip_sources(db_session):
    ctx, person, user = await people_fixture(db_session)
    trip = await db_session.scalar(select(Participation))
    old_document, old_contact = trip.document_revision_id, dict(trip.confirmations)
    source_fields, source_phone = dict(ctx.source.confirmed_fields), ctx.source.client_phone
    claim = Claim(agency_id=person.agency_id, company_id=person.company_id, group_id=ctx.group.id,
        traveller_id=person.id, secret_hash="e" * 64, method="passport", status="created", max_attempts=5,
        expires_at=datetime.now(UTC) + timedelta(minutes=30), idempotency_key="old-claim")
    db_session.add(claim)
    await db_session.flush()
    body = PersonEdit(expected_revision=person.revision, idempotency_key="edit-1", reason="Correct reviewed name",
        display_name="Synthetic Updated", phone_number="+919111111111", fields={"surname": "Updated"})
    await edit_current_record(db_session, person=person, body=body, actor_id=user.id, crypto=ctx.crypto)
    current = await current_person(db_session, person, ctx.crypto)
    assert current.display_name == "Synthetic Updated" and current.phone_number == "+919111111111"
    assert current.phone_verified is False and current.revision == 2 and current.contact_revision == 2
    assert current.current_document.revision_number == 2
    assert current.current_document.fields["surname"] == "Updated"
    assert trip.document_revision_id == old_document and trip.confirmations == old_contact
    assert ctx.source.confirmed_fields == source_fields and ctx.source.client_phone == source_phone
    await db_session.refresh(claim)
    assert claim.revoked_at is not None and claim.status == "revoked"
    assert await db_session.scalar(select(func.count()).select_from(Contact)) == 2
    await edit_current_record(db_session, person=person, body=body, actor_id=user.id, crypto=ctx.crypto)
    assert person.revision == 2 and await db_session.scalar(select(func.count()).select_from(Document)) == 2
    with pytest.raises(ConflictError, match="differs"):
        await edit_current_record(db_session, person=person,
            body=body.model_copy(update={"display_name": "Another"}), actor_id=user.id, crypto=ctx.crypto)
    with pytest.raises(ConflictError, match="changed"):
        await edit_current_record(db_session, person=person,
            body=body.model_copy(update={"idempotency_key": "new-key"}), actor_id=user.id, crypto=ctx.crypto)


@pytest.mark.asyncio
async def test_directory_deduplicates_person_and_flags_resolved_possible_duplicate(db_session):
    ctx, person, user = await people_fixture(db_session)
    db_session.add(MatchCase(agency_id=person.agency_id, company_id=person.company_id,
        group_id=ctx.group.id, traveller_id=person.id, source_kind="passport_submission",
        source_row_key=str(ctx.source.id), status="resolved", reason_code="operator_historical_registration",
        evidence={"possible_duplicate": True}))
    await db_session.flush()
    rows = list((await db_session.scalars(person_scope(user, person.agency_id, person.company_id))).all())
    items = await directory_items(db_session, rows, user, ctx.crypto)
    assert len(items) == 1 and items[0].duplicate_status == "possible" and items[0].trip_count == 1
    assert "phone" not in items[0].model_dump() and items[0].current_passport_last4 == "4567"
    documents = list((await db_session.scalars(select(Document))).all())
    versions = await document_items(db_session, documents, person, ctx.crypto)
    assert len(versions) == 1 and len(versions[0].assets) == 2
    assert "object_key" not in versions[0].model_dump_json()
    with pytest.raises(EntityNotFoundError):
        await require_person(db_session, user=user, agency_id=person.agency_id,
            company_id=uuid.uuid4(), person_id=person.id)


@pytest.mark.asyncio
async def test_reviewed_upload_keeps_v1_and_retry_reuses_v2_receipt(db_session):
    ctx, person, user = await people_fixture(db_session)
    before = await current_person(db_session, person, ctx.crypto)
    fields = {key: value for key, value in before.current_document.fields.items() if key != "document_type"}
    body = DocumentUpload(expected_revision=1, idempotency_key="scan-v2", reason="Improved current scan",
        change_kind="scan", side="front", issuing_country="IND", document_type=before.current_document.document_type, fields=fields)
    target = await prepare_document_upload(db_session, person=person, actor_id=user.id, body=body,
        checksum="a" * 64, size=10, media="image/jpeg", crypto=ctx.crypto)
    assert not target.already_available and person.revision == 1
    assert (await current_person(db_session, person, ctx.crypto)).current_document.id == before.current_document.id
    await publish_document_upload(db_session, person=person, asset_id=target.asset_id, actor_id=user.id, crypto=ctx.crypto)
    current = await current_person(db_session, person, ctx.crypto)
    assert current.current_document.revision_number == 2
    assert (await db_session.scalar(select(Participation))).document_revision_id == before.current_document.id
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 2
    retry = await prepare_document_upload(db_session, person=person, actor_id=user.id, body=body,
        checksum="a" * 64, size=10, media="image/jpeg", crypto=ctx.crypto)
    assert retry.asset_id == target.asset_id and retry.already_available and person.revision == 2
    with pytest.raises(ConflictError, match="differs"):
        await prepare_document_upload(db_session, person=person, actor_id=user.id, body=body,
            checksum="b" * 64, size=10, media="image/jpeg", crypto=ctx.crypto)


@pytest.mark.asyncio
async def test_upload_cannot_take_another_person_passport(db_session):
    ctx, person, user = await people_fixture(db_session)
    second = Person(agency_id=person.agency_id, company_id=person.company_id, status="active",
        reuse_permission_status="granted", reuse_permission_evidence={"synthetic": True})
    db_session.add(second)
    await db_session.flush()
    current = await current_person(db_session, person, ctx.crypto)
    body = DocumentUpload(expected_revision=1, idempotency_key="foreign", reason="Reviewed renewal",
        change_kind="renewal", side="front", issuing_country="IND", document_type=current.current_document.document_type,
        fields={key: value for key, value in current.current_document.fields.items() if key != "document_type"})
    with pytest.raises(ConflictError, match="cannot be assigned"):
        await prepare_document_upload(db_session, person=second, actor_id=user.id, body=body,
            checksum="a" * 64, size=10, media="image/jpeg", crypto=ctx.crypto)


@pytest.mark.asyncio
async def test_staged_scan_cannot_publish_over_a_newer_staff_edit(db_session):
    ctx, person, user = await people_fixture(db_session)
    before = await current_person(db_session, person, ctx.crypto)
    body = DocumentUpload(expected_revision=1, idempotency_key="late-upload", reason="Improved scan",
        change_kind="scan", side="front", issuing_country="IND", document_type=before.current_document.document_type,
        fields={key: value for key, value in before.current_document.fields.items() if key != "document_type"})
    target = await prepare_document_upload(db_session, person=person, actor_id=user.id, body=body,
        checksum="a" * 64, size=10, media="image/jpeg", crypto=ctx.crypto)
    await edit_current_record(db_session, person=person, actor_id=user.id, crypto=ctx.crypto,
        body=PersonEdit(expected_revision=1, idempotency_key="newer-edit", reason="Newer reviewed name", display_name="Newer name"))
    with pytest.raises(ConflictError, match="changed during upload"):
        await publish_document_upload(db_session, person=person, asset_id=target.asset_id, actor_id=user.id, crypto=ctx.crypto)
    current = await current_person(db_session, person, ctx.crypto)
    assert current.display_name == "Newer name" and current.current_document.id == before.current_document.id
    assert (await db_session.get(Asset, target.asset_id)).availability == "pending"


@pytest.mark.asyncio
async def test_private_history_staff_upload_never_fabricates_personal_consent(db_session):
    ctx, person, user = await people_fixture(db_session)
    person.reuse_permission_status = "unknown"
    person.reuse_permission_evidence = {"authority_kind": "private_history_v1"}
    before = await current_person(db_session, person, ctx.crypto)
    body = DocumentUpload(expected_revision=1, idempotency_key="private-upload", reason="Staff checked original image",
        change_kind="scan", side="front", issuing_country="IND", document_type=before.current_document.document_type,
        fields={key: value for key, value in before.current_document.fields.items() if key != "document_type"})
    target = await prepare_document_upload(db_session, person=person, actor_id=user.id, body=body,
        checksum="a" * 64, size=10, media="image/jpeg", crypto=ctx.crypto)
    assert person.reuse_permission_evidence == {"authority_kind": "private_history_v1"}
    await publish_document_upload(db_session, person=person, asset_id=target.asset_id, actor_id=user.id, crypto=ctx.crypto)
    assert person.reuse_permission_status == "unknown"
    assert person.reuse_permission_evidence["authority_kind"] == "operator_staff_record_v1"
    assert person.reuse_permission_evidence["actor_user_id"] == str(user.id)


@pytest.mark.asyncio
async def test_original_field_fallback_is_scoped_and_does_not_promote_reuse(db_session):
    from app.application.companies.export_source import people_export_page
    from app.infrastructure.database.company_data_export_models import (
        CompanyDataExportJobModel as Job,
    )
    from app.infrastructure.database.traveller_reuse_models import (
        TravellerPassportModel as Passport,
    )
    ctx, person, user = await people_fixture(db_session)
    passport = await db_session.scalar(select(Passport))
    passport.is_default = False
    db_session.add(MatchCase(agency_id=person.agency_id, company_id=person.company_id,
        group_id=ctx.group.id, traveller_id=person.id, source_kind="passport_submission",
        source_row_key=str(ctx.source.id), source_created_at=ctx.source.created_at,
        status="resolved", reason_code="operator_historical_registration"))
    await db_session.flush()
    response = await current_person(db_session, person, ctx.crypto, user=user)
    assert response.current_document is None
    assert response.original_record.source_id == ctx.source.id
    assert response.original_record.fields["passport_number"] == "001234567"
    job = Job(agency_id=person.agency_id, company_id=person.company_id, created_at=datetime.now(UTC))
    rows, _ = await people_export_page(db_session, job, user, ctx.crypto)
    assert rows[0][-2:] == ["original_submission", str(ctx.source.id)]
    assert rows[0][6] == "001234567" and passport.is_default is False
    # No stale original fields survive loss of office source visibility.
    ctx.source.status = "rejected"
    await db_session.flush()
    hidden = await current_person(db_session, person, ctx.crypto, user=user)
    assert hidden.original_record is None


@pytest.mark.asyncio
async def test_original_fallback_uses_source_chronology_not_registration_order(db_session):
    from app.application.companies.original_record import latest_original_records
    from tests.unit.application.test_traveller_enrollment import _source

    ctx, person, user = await people_fixture(db_session)
    now = datetime.now(UTC)
    ctx.source.created_at = now - timedelta(days=100)
    latest = _source(ctx.group, number="009876543")
    latest.created_at = now - timedelta(days=1)
    db_session.add(latest)
    await db_session.flush()
    cases = [MatchCase(agency_id=person.agency_id, company_id=person.company_id,
        group_id=ctx.group.id, traveller_id=person.id, source_kind="passport_submission",
        source_row_key=str(source.id), source_created_at=source.created_at, created_at=registered,
        status="resolved", reason_code="operator_historical_registration") for source, registered in (
            (latest, now - timedelta(hours=2)), (ctx.source, now))]
    db_session.add_all(cases)
    await db_session.flush()
    result = await latest_original_records(db_session, user=user, agency_id=person.agency_id,
        company_id=person.company_id, person_ids=[person.id])
    assert result[person.id].source_id == latest.id
    assert result[person.id].fields["passport_number"] == "009876543"
    assert cases[0].created_at < cases[1].created_at
    # Missing/untrusted chronology is never represented as the latest original.
    cases[0].source_created_at = None
    cases[1].source_created_at = None
    await db_session.flush()
    assert await latest_original_records(db_session, user=user, agency_id=person.agency_id,
        company_id=person.company_id, person_ids=[person.id]) == {}


@pytest.mark.asyncio
async def test_staff_copy_rechecks_parent_scope_retention_and_withdrawal(db_session):
    from app.infrastructure.travellers.staff_record_asset_copy import has_staff_copy_authority

    ctx, person, user = await people_fixture(db_session)
    await edit_current_record(db_session, person=person, actor_id=user.id, crypto=ctx.crypto,
        body=PersonEdit(expected_revision=1, idempotency_key="copy-guard", reason="Reviewed correction",
            display_name="Synthetic Person", fields={"surname": "Correction"}))
    revision = await db_session.scalar(select(Document).where(Document.revision_number == 2))
    asset = await db_session.scalar(select(Asset).where(Asset.document_revision_id == revision.id).limit(1))
    now = datetime.now(UTC)
    assert await has_staff_copy_authority(db_session, asset, now)
    mutations = [
        (person, "reuse_permission_status", "withdrawn"),
        (person, "retention_until", now - timedelta(seconds=1)),
        (asset, "retention_until", now - timedelta(seconds=1)),
        (asset, "purged_at", now),
        (asset, "source_object_key", "other-parent-key"),
        (asset, "retention_basis", None),
        (revision, "status", "candidate"),
        (revision, "accepted_by_user_id", None),
        (revision, "source_provenance", {"staff_record_edit": True, "copy_parent_revision_id": "malformed"}),
        (revision, "source_provenance", {"staff_record_edit": True, "copy_parent_revision_id": str(uuid.uuid4())}),
    ]
    for instance, attribute, value in mutations:
        original = getattr(instance, attribute)
        setattr(instance, attribute, value)
        assert not await has_staff_copy_authority(db_session, asset, now), attribute
        setattr(instance, attribute, original)
    # The destination must itself have the exact joined tenant/person version.
    original_id = asset.document_revision_id
    asset.document_revision_id = uuid.uuid4()
    with db_session.no_autoflush:
        assert not await has_staff_copy_authority(db_session, asset, now)
    asset.document_revision_id = original_id
