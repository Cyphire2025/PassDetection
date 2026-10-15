"""Operational labels are editable without changing passport identity or delivery."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import select

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.documents.document_matcher import DocumentMatcher
from app.infrastructure.passports.roster_view_service import prepared_roster
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    submission_comparison_from_model,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.passport_routes import display_name
from app.presentation.api.v1.schemas.passport_display_name_schemas import (
    UpdatePassportDisplayNameRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf


@pytest.fixture
async def roster(db_session):
    agency = AgencyModel(id=uuid.uuid4(), name="Synthetic", email=f"{uuid.uuid4()}@example.test")
    db_session.add(agency)
    await db_session.flush()
    actor = UserModel(id=uuid.uuid4(), agency_id=agency.id, role="agency_admin", full_name="Staff",
                      email=f"{uuid.uuid4()}@example.test", hashed_password="unused")
    db_session.add(actor)
    await db_session.flush()
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, created_by_user_id=actor.id,
                             name="Synthetic group", token=uuid.uuid4().hex)
    db_session.add(group)
    await db_session.flush()
    passenger = PassportSubmissionModel(id=uuid.uuid4(), group_id=group.id, agency_id=agency.id,
        client_name="SHIVANAND", image_s3_key="synthetic/front.jpg", status="staff_approved",
        extraction_status="extraction_complete", extraction_revision=3,
        post_submission_verification_revision=2,
        confirmed_fields={"passport_number": "P1234567", "given_names": "SHIVANAND"},
        extracted_fields={"given_names": "SHIVANAND", "passport_number": "P1234567"})
    batch = DocumentDistributionBatchModel(id=uuid.uuid4(), group_id=group.id,
        agency_id=agency.id, document_type="visa", status="saved")
    db_session.add_all([passenger, batch])
    await db_session.flush()
    document = DistributedDocumentModel(id=uuid.uuid4(), batch_id=batch.id, agency_id=agency.id,
        group_id=group.id, passenger_id=passenger.id, document_type="visa",
        original_filename="visa.pdf", storage_key="synthetic/visa.pdf", match_status="matched")
    db_session.add(document)
    await db_session.commit()
    return SimpleNamespace(session=db_session, actor=actor, user=UserRepository._to_entity(actor),
                           group=group, passenger=passenger, document=document)


async def save(roster, name="SHIVANAND A", *, expected=None, user=None, group_id=None, passenger_id=None):
    version = expected or roster.passenger.updated_at
    if version.tzinfo is None:
        version = version.replace(tzinfo=UTC)
    return await display_name.update_passport_display_name(
        group_id or roster.group.id, passenger_id or roster.passenger.id,
        UpdatePassportDisplayNameRequest(display_name=name, expected_updated_at=version),
        Response(), current_user=user or roster.user, session=roster.session, _csrf=None,
    )


@pytest.mark.parametrize("role", ["agency_staff", "agency_manager", "agency_admin", "super_admin"])
async def test_edit_restore_preserves_passport_approval_and_assignment(roster, role):
    roster.actor.role = role
    await roster.session.commit()
    roster.user = UserRepository._to_entity(roster.actor)
    original = (roster.passenger.confirmed_fields.copy(), roster.passenger.extracted_fields.copy(),
                roster.passenger.status, roster.passenger.extraction_revision,
                roster.passenger.post_submission_verification_revision, roster.document.passenger_id)
    result = await save(roster, "  SHIVANAND    A  ")
    assert result.display_name == "SHIVANAND A" and result.client_name == "SHIVANAND"
    await roster.session.refresh(roster.passenger)
    await roster.session.refresh(roster.document)
    assert (roster.passenger.confirmed_fields, roster.passenger.extracted_fields,
            roster.passenger.status, roster.passenger.extraction_revision,
            roster.passenger.post_submission_verification_revision, roster.document.passenger_id) == original
    entity = await PassportSubmissionRepository(roster.session).get_by_id(roster.passenger.id)
    assert entity.client_name == "SHIVANAND" and entity.display_name == "SHIVANAND A"
    # Both the new operational label and true passport name remain match candidates.
    matcher = DocumentMatcher()
    names = matcher._normalized_passenger_names(entity, matcher._passport_fields(entity))
    assert ("shivanand", "a") in names and ("shivanand",) in names
    result = await save(roster, "SHIVANAND")
    assert result.client_name == "SHIVANAND" and result.display_name is None
    assert roster.document.passenger_id == original[-1]
    audits = (await roster.session.scalars(select(AuditLogModel))).all()
    assert len(audits) == 2
    assert all(audit.action == "passport_display_name_changed" for audit in audits)
    assert all(audit.metadata_json["changed_fields"] == ["display_name"] for audit in audits)


async def test_same_name_does_not_mutate_or_audit(roster):
    version = roster.passenger.updated_at
    result = await save(roster, "SHIVANAND")
    assert result.updated_at == version
    assert not (await roster.session.scalars(select(AuditLogModel))).all()


async def test_stale_edit_cannot_overwrite_name(roster):
    with pytest.raises(HTTPException) as error:
        await save(roster, expected=datetime.now(UTC) - timedelta(days=1))
    assert error.value.status_code == 409
    assert roster.passenger.client_name == "SHIVANAND"


@pytest.mark.parametrize("restriction", ["client_manager", "coordinator", "other_agency", "unassigned_staff", "inactive", "role_changed"])
async def test_role_tenant_and_current_account_scopes(roster, restriction):
    user = roster.user
    if restriction in {"client_manager", "coordinator"}:
        user = replace(user, role=UserRole.CLIENT_MANAGER if restriction == "client_manager" else UserRole.AGENCY_COORDINATOR)
    elif restriction == "other_agency":
        agency = AgencyModel(id=uuid.uuid4(), name="Other", email=f"{uuid.uuid4()}@example.test")
        roster.session.add(agency)
        await roster.session.flush()
        roster.actor.agency_id = agency.id
    elif restriction == "unassigned_staff":
        roster.actor.role = "agency_staff"
        roster.group.created_by_user_id = None
    elif restriction == "inactive":
        roster.actor.is_active = False
    else:
        roster.actor.role = "agency_coordinator"
    await roster.session.commit()
    if restriction in {"other_agency", "unassigned_staff"}:
        user = UserRepository._to_entity(roster.actor)
    with pytest.raises(HTTPException) as error:
        await save(roster, user=user)
    assert error.value.status_code in {403, 404}
    assert roster.passenger.client_name == "SHIVANAND"


@pytest.mark.parametrize("restriction", ["archived", "deleted", "processing", "other_group", "missing_passenger"])
async def test_active_submitted_passenger_must_belong_to_selected_group(roster, restriction):
    options = {}
    if restriction in {"archived", "deleted"}:
        roster.group.status = restriction
    elif restriction == "processing":
        roster.passenger.status = restriction
    elif restriction == "other_group":
        options["group_id"] = uuid.uuid4()
    else:
        options["passenger_id"] = uuid.uuid4()
    await roster.session.commit()
    with pytest.raises(HTTPException) as error:
        await save(roster, **options)
    assert error.value.status_code == 404
    assert roster.passenger.client_name == "SHIVANAND"


async def test_unknown_delivery_does_not_block_alias_or_change_routing(roster):
    delivery = DocumentWhatsAppDeliveryModel(id=uuid.uuid4(), agency_id=roster.group.agency_id,
        group_id=roster.group.id, passenger_id=roster.passenger.id, send_batch_id=uuid.uuid4(),
        document_type="visa", document_filename="visa.pdf", passenger_name="SHIVANAND",
        phone_number="+919999999999", normalized_phone_number="919999999999",
        template_name="documents_v1", status="delivery_unknown", attempt_count=1)
    roster.session.add(delivery)
    await roster.session.commit()
    before = submission_comparison_from_model(roster.passenger)
    await save(roster)
    after = submission_comparison_from_model(roster.passenger)
    assert before.name == after.name == "SHIVANAND"
    assert before.confirmed_fields == after.confirmed_fields
    assert before.client_phone == after.client_phone
    await roster.session.refresh(delivery)
    assert delivery.status == "delivery_unknown" and delivery.attempt_count == 1
    assert delivery.passenger_name == "SHIVANAND"


async def test_display_alias_search_and_stale_entity_update(roster):
    repository = PassportSubmissionRepository(roster.session)
    stale = await repository.get_by_id(roster.passenger.id)
    await save(roster, "Distinct label")
    view, _ = await prepared_roster(roster.session, group_id=roster.group.id,
        user=roster.user, include_deleted=False, submission_filter="all",
        sort_by="name", sort_order="asc", search="Distinct label", page_size=50)
    assert view.ordered_submission_ids == (roster.passenger.id,)
    await repository.update(stale)
    await roster.session.commit()
    latest = await repository.get_by_id(stale.id)
    assert latest.display_name == "Distinct label" and latest.client_name == "SHIVANAND"


@pytest.mark.parametrize("name", ["", "   ", "x" * 256, "SHIVANAND\nA", "SHIVANAND\x00"])
def test_empty_oversized_and_control_names_rejected(name):
    with pytest.raises(ValidationError):
        UpdatePassportDisplayNameRequest(display_name=name, expected_updated_at=datetime.now(UTC))


def test_auth_csrf_and_extra_passport_fields_rejected():
    dependencies = {item.call for item in display_name.router.routes[0].dependant.dependencies}
    assert {get_current_active_user, require_cookie_csrf} <= dependencies
    with pytest.raises(ValidationError):
        UpdatePassportDisplayNameRequest(display_name="A", expected_updated_at=datetime.now(UTC),
                                         confirmed_fields={"given_names": "A"})
