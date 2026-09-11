"""Keep permanent cleanup compatible with keys produced by client submission."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.platform_policies import PlatformPolicies
from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.infrastructure.documents import storage_cleanup
from app.infrastructure.documents.storage_cleanup import (
    StorageCleanupCipher,
    StorageCleanupClaim,
    StorageCleanupPayloadError,
    stage_storage_cleanup_jobs,
)
from app.infrastructure.storage.passport_object_keys import passport_storage_keys


@pytest.mark.parametrize("extension", ["jpg", "jpeg", "png", "webp"])
async def test_cleanup_accepts_cover_keys_from_real_client_submission(
    extension: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = ClientGroup.create(
        name="Synthetic cover upload",
        token="synthetic-cover-upload",
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        upload_configuration={"passport_upload_pages": ["cover", "back_cover"]},
    )
    submission = PassportSubmission.create(group.id, group.agency_id, "Traveller", None, "")
    submission.promote_passport_cover(f"drafts/cover.{extension}")
    submission.promote_passport_back_cover(f"drafts/back_cover.{extension}")
    passports, groups, storage, policies = (AsyncMock() for _ in range(4))
    passports.get_by_id_for_update.return_value = submission
    passports.exists_contact_in_group.return_value = False
    groups.get_by_token.return_value = group
    storage.get_file.return_value = b"synthetic cover image"
    policies.load.return_value = PlatformPolicies(
        require_client_email=False, require_client_phone=False,
    )
    await ClientSubmitPassportUseCase(passports, groups, storage, policies).execute(
        submission.id,
        group_token=group.token,
        confirmed_fields={"given_names": "Synthetic Traveller"},
        client_email=None,
        client_phone=None,
    )
    keys = passport_storage_keys([submission])
    assert keys == [call.args[1] for call in storage.upload_file.await_args_list]
    assert keys == [
        f"{group.agency_id}/{group.id}/{submission.id}-cover.{extension}",
        f"{group.agency_id}/{group.id}/{submission.id}-back_cover.{extension}",
    ]
    session = MagicMock()
    cipher = StorageCleanupCipher("cleanup-secret-123456789")

    jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=group.agency_id,
        source="passport_submission_delete",
        context_id=f"{group.id}:{submission.id}",
        storage_keys=keys,
        cipher=cipher,
    )

    assert len(jobs) == 1
    assert jobs[0].object_count == 2
    assert set(cipher.decrypt(
        jobs[0].storage_keys_ciphertext, key_version=jobs[0].encryption_key_version,
    )) == set(keys)
    session.add.assert_called_once_with(jobs[0])

    claim = StorageCleanupClaim(
        job_id=jobs[0].id,
        context_fingerprint=jobs[0].context_fingerprint,
        ciphertext=jobs[0].storage_keys_ciphertext,
        encryption_key_version=jobs[0].encryption_key_version,
        source=jobs[0].source,
        object_count=jobs[0].object_count,
        attempts=1,
        agency_id=group.agency_id,
    )
    complete, defer = AsyncMock(), AsyncMock()
    monkeypatch.setattr(storage_cleanup, "_claim_storage_cleanup_job", AsyncMock(return_value=claim))
    monkeypatch.setattr(storage_cleanup, "_complete_storage_cleanup_job", complete)
    monkeypatch.setattr(storage_cleanup, "_defer_storage_cleanup_job", defer)
    storage.delete_files.return_value = len(keys)
    session_factory = MagicMock()
    result = await storage_cleanup.process_storage_cleanup_job(
        jobs[0].id, session_factory=session_factory, storage_factory=lambda: storage, cipher=cipher,
    )

    assert result is not None and result.completed
    assert result.deleted_count == len(keys)
    storage.delete_files.assert_awaited_once_with(sorted(keys))
    complete.assert_awaited_once_with(claim, session_factory=session_factory)
    defer.assert_not_awaited()


@pytest.mark.parametrize("invalid_suffix", [
    "-back-cover.jpg", "-cover_extra.jpg", "-cover.pdf", "-cover.jpg/other.jpg",
    "-cover/../../other.jpg", "-other.jpg",
])
def test_cover_cleanup_keeps_rejecting_unproduced_canonical_keys(invalid_suffix: str) -> None:
    agency_id, group_id, submission_id = (uuid.uuid4() for _ in range(3))
    prefix = f"{agency_id}/{group_id}/{submission_id}"
    session = MagicMock()
    with pytest.raises(StorageCleanupPayloadError, match="scope is invalid"):
        stage_storage_cleanup_jobs(
            session,
            agency_id=agency_id,
            source="passport_submission_delete",
            context_id=f"{group_id}:{submission_id}",
            storage_keys=[f"{prefix}.jpg", f"{prefix}{invalid_suffix}"],
            cipher=StorageCleanupCipher("cleanup-secret-123456789"),
        )
    session.add.assert_not_called()
