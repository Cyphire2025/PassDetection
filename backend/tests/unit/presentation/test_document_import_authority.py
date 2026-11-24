"""Revocation during actual validation/PUT must precede private publication."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.infrastructure.database.models import (
    AuditLogModel,
    PassportProcessingJobModel,
    PassportSubmissionModel,
    StorageCleanupJobModel,
)
from app.infrastructure.database.passenger_qr_models import PassengerQRTokenModel
from tests.unit.presentation.document_import_authority_fixture import (
    perform_held_import,
    prepare_authority_import,
)

DENIED = {
    "sessions_revoked",
    "credential_reset",
    "inactive",
    "role_changed",
    "agency_changed",
    "assignment_revoked",
    "owned_group_revoked",
    "group_deleted",
    "group_removed",
}
CONFLICTS = {"target_source_changed", "target_staff_changed", "target_group_changed"}
CASES = [
    ("put", transition)
    for transition in [
        "unchanged",
        "profile_refresh",
        "legacy_no_state",
        "manager_unassigned",
        "assigned_staff_unchanged",
        "group_archived",
        "reduced_superadmin",
        *sorted(DENIED),
        *sorted(CONFLICTS),
    ]
] + [
    ("validation", transition)
    for transition in [
        "unchanged",
        "profile_refresh",
        "legacy_no_state",
        "sessions_revoked",
        "assignment_revoked",
        "group_deleted",
    ]
]
CASES.append(("save_validation", "target_staff_changed"))


@pytest.mark.parametrize("phase,transition", CASES)
async def test_inflight_import_uses_current_persisted_authority_before_publication(
    db_session,
    monkeypatch,
    test_settings,
    phase,
    transition,
):
    context = await prepare_authority_import(
        db_session,
        monkeypatch,
        test_settings,
        transition,
        phase,
    )
    outcome = await perform_held_import(context, db_session, phase)
    rejected = transition in DENIED | CONFLICTS
    error_status = outcome.status_code if isinstance(outcome, HTTPException) else None
    # Keep the subsequent observations separate from any uncommitted failed request.
    await db_session.rollback()
    async with context.factory() as fresh:
        image_key = await fresh.scalar(
            select(PassportSubmissionModel.image_s3_key).where(
                PassportSubmissionModel.id == context.passenger_id,
            )
        )
        audits = list(
            await fresh.scalars(
                select(AuditLogModel).where(
                    AuditLogModel.action == "passport_documents_bulk_imported",
                    AuditLogModel.entity_id == str(context.group_id),
                )
            )
        )
        cleanups = list(await fresh.scalars(select(StorageCleanupJobModel)))
        qr = await fresh.get(PassengerQRTokenModel, context.qr_id)
        jobs = list(await fresh.scalars(select(PassportProcessingJobModel)))
    assert error_status == (409 if transition in CONFLICTS else 403 if rejected else None), (
        repr(outcome),
        {
            "image_changed": image_key != context.original_key,
            "business_audits": len(audits),
            "cleanup_jobs": len(cleanups),
        },
    )
    assert not isinstance(outcome, BaseException) or isinstance(outcome, HTTPException)
    if phase == "validation" or rejected:
        expected = (
            "front/concurrent-winner.jpg"
            if transition == "target_source_changed"
            else None
            if transition == "group_removed"
            else context.original_key
        )
        assert image_key == expected and audits == []
    else:
        assert image_key in context.objects and image_key.startswith("passport-bulk/")
        assert len(audits) == 1 and audits[0].user_id == context.actor_id
        assert outcome.saved_count == 1
    if rejected and phase == "put":
        assert len(cleanups) == 1 and cleanups[0].source == "passport_submission_delete"
        keys = context.cipher.decrypt(
            cleanups[0].storage_keys_ciphertext,
            key_version=cleanups[0].encryption_key_version,
        )
        assert set(keys) == set(context.objects)
        assert context.original_key not in keys
    else:
        assert cleanups == []
    if transition == "group_removed":
        assert qr is None
    else:
        assert qr.is_active and qr.token_hash == context.qr_hash and qr.token_version == 3
    assert jobs == []  # This front-only import has no complete three-image AI bundle.
