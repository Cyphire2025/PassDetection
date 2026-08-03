from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.application.mobile.passenger_identity_reconciliation as reconciliation_module
from app.application.mobile.passenger_identity_reconciliation import (
    PassengerIdentityReconciliationResult,
    _reconcile_passenger_identities_targeted,
    _revoke_passenger_identity_sessions,
    plan_passenger_identities,
    reconcile_passenger_identities_for_changes,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    MatchEvidence,
    SubmissionMatchRow,
)
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
    MobileSyncChangeModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    TargetedPassportWhatsAppMatchContext,
)


def _submission(
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    employee_code: str | None = None,
    client_phone: str | None = None,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=group_id,
        client_phone=client_phone,
        confirmed_fields={},
        staff_metadata={"employee_code": employee_code} if employee_code else {},
    )


def _row(
    *submissions,
    status: str = "submitted",
    phone: str = "+919876543210",
) -> SubmissionMatchRow:
    return SubmissionMatchRow(
        status=status,
        match_basis="phone",
        normalized_phone=phone,
        recipient_ids=(uuid.uuid4(),),
        submission_ids=tuple(item.id for item in submissions),
        broadcast_ids=(uuid.uuid4(),),
        broadcast_names=("Roster",),
        recipient_names=("Passenger",),
        submission_names=tuple("Passenger" for _item in submissions),
        updated_at=datetime.now(tz=UTC),
        confidence="high",
        match_evidence=tuple(
            MatchEvidence(
                submission_id=item.id,
                kind="phone",
                recipient_value=phone,
                submission_value=phone,
                weight=100,
            )
            for item in submissions
        ),
    )


def test_shared_number_requires_distinct_secondary_factors() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    first = _submission(
        agency_id=agency_id, group_id=group_id, employee_code="EMP-001"
    )
    second = _submission(
        agency_id=agency_id, group_id=group_id, employee_code="EMP-002"
    )

    plan = plan_passenger_identities(
        [_row(first, second, status="multiple_submissions")],
        [first, second],
        agency_id=agency_id,
        group_id=group_id,
    )

    assert len(plan.candidates) == 2
    assert {item.secondary_factor_value for item in plan.candidates} == {
        "EMP-001",
        "EMP-002",
    }
    assert all(item.secondary_factor_type == "employee_code" for item in plan.candidates)
    assert all(item.is_shared_number for item in plan.candidates)
    assert all(item.requires_secondary_verification for item in plan.candidates)


def test_unique_group_identity_retains_factor_for_cross_group_otp_collision() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    submission = _submission(
        agency_id=agency_id,
        group_id=group_id,
        employee_code="EMP-UNIQUE",
    )

    plan = plan_passenger_identities(
        [_row(submission)],
        [submission],
        agency_id=agency_id,
        group_id=group_id,
    )

    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.secondary_factor_type == "employee_code"
    assert candidate.secondary_factor_value == "EMP-UNIQUE"
    assert candidate.is_shared_number is False
    assert candidate.requires_secondary_verification is False


def test_shared_number_with_duplicate_factor_fails_closed() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    first = _submission(
        agency_id=agency_id, group_id=group_id, employee_code="EMP-SHARED"
    )
    second = _submission(
        agency_id=agency_id, group_id=group_id, employee_code="emp-shared"
    )

    plan = plan_passenger_identities(
        [_row(first, second, status="multiple_submissions")],
        [first, second],
        agency_id=agency_id,
        group_id=group_id,
    )

    assert plan.candidates == ()
    assert plan.skipped_without_secondary_factor == 2


def test_name_only_or_ambiguous_rows_never_provision() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    submission = _submission(agency_id=agency_id, group_id=group_id)
    row = _row(submission, status="needs_review")
    row = SubmissionMatchRow(
        **{
            **row.__dict__,
            "match_basis": "entered_name",
            "submission_ids": (),
            "candidate_submission_ids": (submission.id,),
            "match_evidence": (),
        }
    )

    plan = plan_passenger_identities(
        [row], [submission], agency_id=agency_id, group_id=group_id
    )

    assert plan.candidates == ()
    assert plan.skipped_ambiguous == 1


def test_direct_submission_phone_provisions_without_a_broadcast_link() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    submission = _submission(
        agency_id=agency_id,
        group_id=group_id,
        client_phone="98765 43210",
    )

    plan = plan_passenger_identities(
        [], [submission], agency_id=agency_id, group_id=group_id
    )

    assert len(plan.candidates) == 1
    assert plan.candidates[0].passenger_submission_id == submission.id
    assert plan.candidates[0].normalized_phone == "+919876543210"
    assert plan.candidates[0].requires_secondary_verification is False


def test_shared_direct_submission_phone_still_fails_closed_without_factors() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    first = _submission(
        agency_id=agency_id,
        group_id=group_id,
        client_phone="9876543210",
    )
    second = _submission(
        agency_id=agency_id,
        group_id=group_id,
        client_phone="+91 98765 43210",
    )

    plan = plan_passenger_identities(
        [], [first, second], agency_id=agency_id, group_id=group_id
    )

    assert plan.candidates == ()
    assert plan.skipped_without_secondary_factor == 2


def test_cross_tenant_submission_is_rejected_even_if_row_references_it() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    other_tenant_submission = _submission(
        agency_id=uuid.uuid4(), group_id=group_id, employee_code="EMP-001"
    )

    plan = plan_passenger_identities(
        [_row(other_tenant_submission)],
        [other_tenant_submission],
        agency_id=agency_id,
        group_id=group_id,
    )

    assert plan.candidates == ()
    assert plan.skipped_ambiguous == 1


@pytest.mark.asyncio
async def test_identity_change_revokes_sessions_where_identity_is_authorized_not_selected() -> None:
    agency_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    session = MagicMock()
    session.execute = AsyncMock()

    await _revoke_passenger_identity_sessions(
        session,
        agency_id,
        identity_id,
        "passenger_identity_changed",
    )

    assert session.execute.await_count == 2
    for call in session.execute.await_args_list:
        sql = str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        assert "mobile_passenger_session_identities" in sql
        assert agency_id.hex in sql
        assert identity_id.hex in sql


def _identity(
    *,
    access: GCGroupAccessModel,
    passenger_id: uuid.UUID,
    phone: str,
) -> MobilePassengerIdentityModel:
    return MobilePassengerIdentityModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        passenger_submission_id=passenger_id,
        normalized_phone_number=phone,
        phone_lookup_hash="8" * 64,
        status="eligible",
        is_shared_number=False,
        requires_secondary_verification=False,
        claim_generation=0,
    )


def _target_context(
    *,
    submissions: tuple[object, ...],
    rows: tuple[SubmissionMatchRow, ...],
    passenger_ids: frozenset[uuid.UUID],
    phones: frozenset[str],
) -> TargetedPassportWhatsAppMatchContext:
    return TargetedPassportWhatsAppMatchContext(
        linked_broadcasts={},
        recipients=(),
        submissions=submissions,  # type: ignore[arg-type]
        rows=rows,
        affected_submission_ids=passenger_ids,
        affected_phone_numbers=phones,
    )


@pytest.mark.asyncio
async def test_single_profile_change_uses_targeted_reconciler_without_full_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = SimpleNamespace()
    passenger_id = uuid.uuid4()
    expected = PassengerIdentityReconciliationResult(0, 0, 1, 0, 0, 0)
    targeted = AsyncMock(return_value=expected)
    full = AsyncMock()
    monkeypatch.setattr(
        reconciliation_module,
        "_reconcile_passenger_identities_targeted",
        targeted,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_passenger_identities",
        full,
    )

    result = await reconcile_passenger_identities_for_changes(
        MagicMock(),
        access=access,  # type: ignore[arg-type]
        actor_user_id=None,
        passenger_submission_ids=(passenger_id,),
    )

    assert result is expected
    targeted.assert_awaited_once()
    assert targeted.await_args.kwargs["passenger_submission_ids"] == (passenger_id,)
    full.assert_not_awaited()


@pytest.mark.asyncio
async def test_targeted_shared_phone_change_updates_all_peers_together(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        client_organization_id=uuid.uuid4(),
        is_enabled=True,
        passenger_access_enabled=True,
    )
    first = _submission(
        agency_id=access.agency_id,
        group_id=access.group_id,
        employee_code="EMP-001",
    )
    second = _submission(
        agency_id=access.agency_id,
        group_id=access.group_id,
        employee_code="EMP-002",
    )
    phone = "+919876543210"
    identities = [
        _identity(access=access, passenger_id=first.id, phone=phone),
        _identity(access=access, passenger_id=second.id, phone=phone),
    ]
    db_session.add_all([access, *identities])
    await db_session.flush()
    context = _target_context(
        submissions=(first, second),
        rows=(_row(first, second, status="multiple_submissions", phone=phone),),
        passenger_ids=frozenset((first.id, second.id)),
        phones=frozenset((phone,)),
    )
    loader = AsyncMock(return_value=context)
    monkeypatch.setattr(
        reconciliation_module,
        "load_targeted_unresolved_passport_whatsapp_match_context",
        loader,
    )

    result = await _reconcile_passenger_identities_targeted(
        db_session,
        access=access,
        actor_user_id=None,
        passenger_submission_ids=(first.id,),
    )

    assert result is not None
    assert result.updated == 2
    assert all(identity.is_shared_number for identity in identities)
    assert all(identity.requires_secondary_verification for identity in identities)
    changes = list(
        (
            await db_session.execute(
                select(MobileSyncChangeModel).where(
                    MobileSyncChangeModel.gc_group_access_id == access.id
                )
            )
        ).scalars()
    )
    assert len(changes) == 2
    assert {change.passenger_identity_id for change in changes} == {
        identity.id for identity in identities
    }
    assert {change.version for change in changes} == {access.manifest_version}
    assert loader.await_count == 2
    assert set(loader.await_args.kwargs["seed_submission_ids"]) == {
        first.id,
        second.id,
    }


@pytest.mark.asyncio
async def test_targeted_phone_change_closes_old_and_new_phone_clusters(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        client_organization_id=uuid.uuid4(),
        is_enabled=True,
        passenger_access_enabled=True,
    )
    submission = _submission(
        agency_id=access.agency_id,
        group_id=access.group_id,
        employee_code="EMP-MOVED",
    )
    old_phone = "+919800000001"
    new_phone = "+919800000002"
    identity = _identity(
        access=access,
        passenger_id=submission.id,
        phone=old_phone,
    )
    db_session.add_all([access, identity])
    await db_session.flush()
    context = _target_context(
        submissions=(submission,),
        rows=(_row(submission, phone=new_phone),),
        passenger_ids=frozenset((submission.id,)),
        phones=frozenset((old_phone, new_phone)),
    )
    loader = AsyncMock(return_value=context)
    monkeypatch.setattr(
        reconciliation_module,
        "load_targeted_unresolved_passport_whatsapp_match_context",
        loader,
    )

    result = await _reconcile_passenger_identities_targeted(
        db_session,
        access=access,
        actor_user_id=None,
        passenger_submission_ids=(submission.id,),
    )

    assert result is not None
    assert result.updated == 1
    assert identity.normalized_phone_number == new_phone
    assert old_phone in loader.await_args.kwargs["seed_phone_numbers"]


@pytest.mark.asyncio
async def test_targeted_deleted_submission_revokes_only_affected_identity(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        client_organization_id=uuid.uuid4(),
        is_enabled=True,
        passenger_access_enabled=True,
    )
    removed_id = uuid.uuid4()
    unaffected_id = uuid.uuid4()
    removed_phone = "+919800000011"
    identities = [
        _identity(access=access, passenger_id=removed_id, phone=removed_phone),
        _identity(
            access=access,
            passenger_id=unaffected_id,
            phone="+919800000012",
        ),
    ]
    db_session.add_all([access, *identities])
    await db_session.flush()
    context = _target_context(
        submissions=(),
        rows=(),
        passenger_ids=frozenset((removed_id,)),
        phones=frozenset((removed_phone,)),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "load_targeted_unresolved_passport_whatsapp_match_context",
        AsyncMock(return_value=context),
    )

    result = await _reconcile_passenger_identities_targeted(
        db_session,
        access=access,
        actor_user_id=None,
        passenger_submission_ids=(removed_id,),
    )

    assert result is not None
    assert result.revoked == 1
    assert identities[0].status == "revoked"
    assert identities[1].status == "eligible"


@pytest.mark.asyncio
async def test_unprovable_target_cluster_falls_back_to_full_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    passenger_id = uuid.uuid4()
    expected = PassengerIdentityReconciliationResult(1, 0, 0, 0, 0, 0)
    targeted = AsyncMock(return_value=None)
    full = AsyncMock(return_value=expected)
    monkeypatch.setattr(
        reconciliation_module,
        "_reconcile_passenger_identities_targeted",
        targeted,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "reconcile_passenger_identities",
        full,
    )

    result = await reconcile_passenger_identities_for_changes(
        MagicMock(),
        access=SimpleNamespace(),  # type: ignore[arg-type]
        actor_user_id=None,
        passenger_submission_ids=(passenger_id,),
    )

    assert result is expected
    targeted.assert_awaited_once()
    full.assert_awaited_once()
