from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr
from sqlalchemy.dialects import postgresql

from app.infrastructure.documents import storage_cleanup
from app.infrastructure.documents.storage_cleanup import (
    StorageCleanupCipher,
    StorageCleanupClaim,
    StorageCleanupPayloadError,
    stage_storage_cleanup_job,
    stage_storage_cleanup_jobs,
)


class _AsyncContext:
    def __init__(self, value) -> None:
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        return None


class _SessionFactory:
    def __init__(self, *sessions) -> None:
        self.sessions = list(sessions)

    def __call__(self):
        session = self.sessions.pop(0)
        return _AsyncContext(session)


def _session_with_result(value) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.delete = AsyncMock()
    session.begin = MagicMock(return_value=_AsyncContext(None))
    return session


def test_cleanup_tombstone_encrypts_keys_and_supports_key_rotation() -> None:
    old_cipher = StorageCleanupCipher(
        "old-cleanup-secret-123456",
        key_version=1,
    )
    rotated_cipher = StorageCleanupCipher(
        "new-cleanup-secret-654321",
        key_version=2,
        decryption_keys={1: "old-cleanup-secret-123456"},
    )
    session = MagicMock()
    session.add = MagicMock()
    key = "document-rename/batch/passenger-visa.pdf"

    job = stage_storage_cleanup_job(
        session,
        agency_id=uuid.uuid4(),
        source="document_rename_batch_delete",
        context_id=str(uuid.uuid4()),
        storage_keys=[key, key],
        cipher=old_cipher,
    )

    assert job is not None
    assert key.encode() not in job.storage_keys_ciphertext
    assert job.encryption_key_version == 1
    assert job.object_count == 1
    assert rotated_cipher.decrypt(
        job.storage_keys_ciphertext,
        key_version=job.encryption_key_version,
    ) == (key,)
    session.add.assert_called_once_with(job)


def test_bulk_cleanup_tombstones_chunk_3000_keys_deterministically() -> None:
    cipher = StorageCleanupCipher("cleanup-secret-123456789")
    session = MagicMock()
    keys = [f"document-rename/batch/{index:04d}.pdf" for index in range(3_000)]

    jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=uuid.uuid4(),
        source="document_rename_batch_delete",
        context_id="bulk-delete",
        storage_keys=[*reversed(keys), keys[0]],
        cipher=cipher,
        now=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert [job.object_count for job in jobs] == [2_000, 1_000]
    decrypted = tuple(
        key
        for job in jobs
        for key in cipher.decrypt(
            job.storage_keys_ciphertext,
            key_version=job.encryption_key_version,
        )
    )
    assert decrypted == tuple(sorted(keys))
    assert jobs[0].context_fingerprint != jobs[1].context_fingerprint
    assert session.add.call_count == 2


def test_cleanup_cipher_rejects_unavailable_version_and_wrong_key() -> None:
    old_cipher = StorageCleanupCipher("old-cleanup-secret-123456", key_version=1)
    ciphertext = old_cipher.encrypt(["document-distribution/group/visa.pdf"])
    new_cipher = StorageCleanupCipher("new-cleanup-secret-654321", key_version=2)

    with pytest.raises(StorageCleanupPayloadError, match="version is unavailable"):
        new_cipher.decrypt(ciphertext, key_version=1)
    with pytest.raises(StorageCleanupPayloadError, match="payload is invalid"):
        new_cipher.decrypt(ciphertext, key_version=2)


def test_cleanup_cipher_loads_active_and_fallback_versions_from_settings(monkeypatch) -> None:
    old_cipher = StorageCleanupCipher("old-cleanup-secret-123456", key_version=1)
    ciphertext = old_cipher.encrypt(["document-rename/batch/visa.pdf"])
    monkeypatch.setattr(
        storage_cleanup,
        "get_settings",
        lambda: SimpleNamespace(
            app_secret_key="unused-app-secret-123456",
            storage_cleanup_encryption_key=SecretStr("new-cleanup-secret-654321"),
            storage_cleanup_encryption_key_version=2,
            storage_cleanup_decryption_keys={1: SecretStr("old-cleanup-secret-123456")},
        ),
    )

    rotated = StorageCleanupCipher.from_settings()

    assert rotated.key_version == 2
    assert rotated.decrypt(ciphertext, key_version=1) == ("document-rename/batch/visa.pdf",)


def test_cleanup_tombstone_rejects_cross_namespace_key() -> None:
    with pytest.raises(StorageCleanupPayloadError, match="scope is invalid"):
        stage_storage_cleanup_job(
            MagicMock(),
            agency_id=uuid.uuid4(),
            source="document_rename_batch_delete",
            context_id=str(uuid.uuid4()),
            storage_keys=["document-distribution/group/visa.pdf"],
            cipher=StorageCleanupCipher("cleanup-secret-123456789"),
        )


def test_distribution_abort_cleanup_accepts_only_distribution_namespace() -> None:
    cipher = StorageCleanupCipher("cleanup-secret-123456789")
    session = MagicMock()
    session.add = MagicMock()

    job = stage_storage_cleanup_job(
        session,
        agency_id=uuid.uuid4(),
        source="document_distribution_abort",
        context_id=str(uuid.uuid4()),
        storage_keys=["document-distribution/group/incomplete-visa.pdf"],
        cipher=cipher,
    )

    assert job is not None
    assert job.source == "document_distribution_abort"
    with pytest.raises(StorageCleanupPayloadError, match="scope is invalid"):
        stage_storage_cleanup_job(
            MagicMock(),
            agency_id=uuid.uuid4(),
            source="document_distribution_abort",
            context_id=str(uuid.uuid4()),
            storage_keys=["document-rename/foreign.pdf"],
            cipher=cipher,
        )


def test_bulk_cleanup_validates_every_key_before_staging_any_chunk() -> None:
    session = MagicMock()
    valid_keys = [f"document-distribution/group/{index:04d}.pdf" for index in range(2_500)]

    with pytest.raises(StorageCleanupPayloadError, match="scope is invalid"):
        stage_storage_cleanup_jobs(
            session,
            agency_id=uuid.uuid4(),
            source="document_distribution_delete",
            context_id="bulk-delete",
            storage_keys=[*valid_keys, "document-rename/wrong-prefix.pdf"],
            cipher=StorageCleanupCipher("cleanup-secret-123456789"),
        )

    session.add.assert_not_called()


def test_passport_cleanup_accepts_only_owned_passport_namespaces() -> None:
    session = MagicMock()
    cipher = StorageCleanupCipher("cleanup-secret-123456789")
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    submission_id = uuid.uuid4()
    keys = [
        "front/legacy-front.jpg",
        "thumbnail/legacy-thumbnail.jpg",
        "back/legacy-back.jpg",
        "photo/legacy-photo.jpg",
        "visa-photo/legacy-visa-photo.jpg",
        "visa_photo/legacy-ai-visa-photo.jpg",
        "drafts/agency/group/front.jpg",
        "excel-imports/group/passenger.placeholder",
        "passport-bulk/agency/group/passenger/front.jpg",
        "passport-crops/agency/passenger/front/1.jpg",
        "passport-edits/agency/passenger/photo/1.jpg",
        f"{agency_id}/{group_id}/{submission_id}.jpg",
        f"{agency_id}/{group_id}/{submission_id}-photo.jpg",
        f"{agency_id}/{group_id}/{submission_id}-back.jpg",
    ]

    jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=uuid.uuid4(),
        source="passport_submission_delete",
        context_id="passport-bulk-delete",
        storage_keys=keys,
        cipher=cipher,
    )

    assert len(jobs) == 1
    assert jobs[0].object_count == len(keys)
    with pytest.raises(StorageCleanupPayloadError, match="scope is invalid"):
        stage_storage_cleanup_jobs(
            MagicMock(),
            agency_id=uuid.uuid4(),
            source="passport_submission_delete",
            context_id="cross-scope",
            storage_keys=["document-rename/other-agency/file.pdf"],
            cipher=cipher,
        )
    with pytest.raises(StorageCleanupPayloadError, match="scope is invalid"):
        stage_storage_cleanup_jobs(
            MagicMock(),
            agency_id=agency_id,
            source="passport_submission_delete",
            context_id="malformed-canonical-key",
            storage_keys=[f"{agency_id}/{group_id}/../../other-agency/secret.jpg"],
            cipher=cipher,
        )


@pytest.mark.asyncio
async def test_compensation_tombstone_commits_in_independent_transaction() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.begin = MagicMock(return_value=_AsyncContext(None))

    job_id = await storage_cleanup.persist_storage_cleanup_job(
        agency_id=uuid.uuid4(),
        source="document_distribution_compensation",
        context_id=str(uuid.uuid4()),
        storage_keys=["document-distribution/group/batch/visa.pdf"],
        session_factory=_SessionFactory(session),
        cipher=StorageCleanupCipher("cleanup-secret-123456789"),
    )

    assert isinstance(job_id, uuid.UUID)
    session.add.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_claim_uses_skip_locked_lease_and_stable_order() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    job = SimpleNamespace(
        id=uuid.uuid4(),
        context_fingerprint="f" * 64,
        storage_keys_ciphertext=b"ciphertext",
        encryption_key_version=1,
        source="document_rename_batch_delete",
        object_count=1,
        attempts=0,
        status="pending",
        lease_expires_at=None,
        updated_at=now,
    )
    session = _session_with_result(job)

    claim = await storage_cleanup._claim_storage_cleanup_job(
        job_id=job.id,
        session_factory=_SessionFactory(session),
        now=now,
    )

    assert claim is not None
    assert claim.job_id == job.id
    assert job.status == "running"
    assert job.attempts == 1
    assert job.lease_expires_at > now
    statement = session.execute.await_args.args[0]
    rendered = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in rendered
    assert "SKIP LOCKED" in rendered
    assert "ORDER BY storage_cleanup_jobs.next_attempt_at" in rendered
    assert statement.get_execution_options()["populate_existing"] is True


@pytest.mark.asyncio
async def test_cleanup_storage_failure_schedules_retry_without_logging_keys(
    monkeypatch,
) -> None:
    cipher = StorageCleanupCipher("cleanup-secret-123456789")
    key = "document-rename/batch/passenger-visa.pdf"
    claim = StorageCleanupClaim(
        job_id=uuid.uuid4(),
        context_fingerprint="c" * 64,
        ciphertext=cipher.encrypt([key]),
        encryption_key_version=cipher.key_version,
        source="document_rename_batch_delete",
        object_count=1,
        attempts=1,
    )
    defer = AsyncMock(return_value=False)
    monkeypatch.setattr(storage_cleanup, "_defer_storage_cleanup_job", defer)
    warning = MagicMock()
    monkeypatch.setattr(storage_cleanup.logger, "warning", warning)
    storage = MagicMock()
    storage.delete_files = AsyncMock(side_effect=RuntimeError("offline"))

    result = await storage_cleanup._execute_storage_cleanup_claim(
        claim,
        session_factory=MagicMock(),
        storage_factory=lambda: storage,
        cipher=cipher,
    )

    assert result.completed is False
    defer.assert_awaited_once()
    assert defer.await_args.kwargs["blocked"] is False
    logged = repr(warning.call_args)
    assert key not in logged
    assert "RuntimeError" in logged


@pytest.mark.asyncio
async def test_cleanup_terminal_failure_is_blocked_and_audited_after_bounded_attempts() -> None:
    cipher = StorageCleanupCipher("cleanup-secret-123456789")
    claim = StorageCleanupClaim(
        job_id=uuid.uuid4(),
        context_fingerprint="f" * 64,
        ciphertext=cipher.encrypt(["document-rename/batch/passenger-visa.pdf"]),
        encryption_key_version=cipher.key_version,
        source="document_rename_batch_delete",
        object_count=1,
        attempts=storage_cleanup.MAX_STORAGE_CLEANUP_ATTEMPTS,
        agency_id=uuid.uuid4(),
    )
    job = SimpleNamespace(id=claim.job_id)
    session = _session_with_result(job)
    storage = MagicMock()
    storage.delete_files = AsyncMock(side_effect=RuntimeError("offline"))

    result = await storage_cleanup._execute_storage_cleanup_claim(
        claim,
        session_factory=_SessionFactory(session),
        storage_factory=lambda: storage,
        cipher=cipher,
    )

    assert result.completed is False
    assert job.status == "blocked"
    assert job.last_error_code == "RuntimeError"
    terminal_audits = [
        item
        for item in session.add.call_args_list
        if item.args[0].action == "document_storage_cleanup_terminal_failure"
    ]
    assert len(terminal_audits) == 1
    assert terminal_audits[0].args[0].result == "failed"
    metadata = terminal_audits[0].args[0].metadata_json
    assert metadata["attempts"] == storage_cleanup.MAX_STORAGE_CLEANUP_ATTEMPTS
    assert "passenger-visa.pdf" not in repr(metadata)


@pytest.mark.asyncio
async def test_cleanup_partial_storage_acknowledgement_remains_retryable() -> None:
    cipher = StorageCleanupCipher("cleanup-secret-123456789")
    claim = StorageCleanupClaim(
        job_id=uuid.uuid4(),
        context_fingerprint="e" * 64,
        ciphertext=cipher.encrypt(["document-rename/batch/passenger-visa.pdf"]),
        encryption_key_version=cipher.key_version,
        source="document_rename_batch_delete",
        object_count=1,
        attempts=1,
    )
    job = SimpleNamespace(id=claim.job_id)
    session = _session_with_result(job)
    storage = MagicMock()
    storage.delete_files = AsyncMock(return_value=0)

    result = await storage_cleanup._execute_storage_cleanup_claim(
        claim,
        session_factory=_SessionFactory(session),
        storage_factory=lambda: storage,
        cipher=cipher,
    )

    assert result.completed is False
    assert result.deleted_count == 0
    assert job.status == "pending"
    assert job.last_error_code == "StorageCleanupIncompleteError"


@pytest.mark.asyncio
async def test_cleanup_success_removes_tombstone_after_idempotent_delete(
    monkeypatch,
) -> None:
    cipher = StorageCleanupCipher("cleanup-secret-123456789")
    keys = (
        "document-distribution/group/first.pdf",
        "document-distribution/group/second.pdf",
    )
    claim = StorageCleanupClaim(
        job_id=uuid.uuid4(),
        context_fingerprint="d" * 64,
        ciphertext=cipher.encrypt(keys),
        encryption_key_version=cipher.key_version,
        source="document_distribution_delete",
        object_count=2,
        attempts=1,
    )
    complete = AsyncMock()
    monkeypatch.setattr(storage_cleanup, "_complete_storage_cleanup_job", complete)
    storage = MagicMock()
    storage.delete_files = AsyncMock(return_value=2)
    session_factory = MagicMock()

    result = await storage_cleanup._execute_storage_cleanup_claim(
        claim,
        session_factory=session_factory,
        storage_factory=lambda: storage,
        cipher=cipher,
    )

    assert result.completed is True
    assert result.deleted_count == 2
    storage.delete_files.assert_awaited_once_with(list(keys))
    complete.assert_awaited_once_with(claim, session_factory=session_factory)


@pytest.mark.asyncio
async def test_cleanup_completion_replaces_tombstone_with_redacted_audit_result() -> None:
    agency_id = uuid.uuid4()
    job = SimpleNamespace(id=uuid.uuid4())
    session = _session_with_result(job)
    session.add = MagicMock()
    claim = StorageCleanupClaim(
        job_id=job.id,
        context_fingerprint="a" * 64,
        ciphertext=b"never-audited",
        encryption_key_version=1,
        source="passport_submission_delete",
        object_count=4,
        attempts=2,
        agency_id=agency_id,
    )

    await storage_cleanup._complete_storage_cleanup_job(
        claim,
        session_factory=_SessionFactory(session),
    )

    session.delete.assert_awaited_once_with(job)
    audit = session.add.call_args.args[0]
    assert audit.action == "document_storage_cleanup_completed"
    assert audit.agency_id == agency_id
    assert audit.entity_id == str(job.id)
    assert audit.metadata_json == {
        "source": "passport_submission_delete",
        "context_fingerprint": "a" * 64,
        "object_count": 4,
        "attempts": 2,
    }
    assert "never-audited" not in repr(audit.metadata_json)


def test_cleanup_task_is_registered_and_scheduled_on_general_worker() -> None:
    from app.infrastructure.processing.celery_app import (
        DOCUMENT_STORAGE_CLEANUP_TASK,
        DOCUMENT_STORAGE_ORPHAN_RECONCILIATION_TASK,
        celery_app,
    )

    assert celery_app.conf.task_routes[DOCUMENT_STORAGE_CLEANUP_TASK] == {"queue": "passport_ocr"}
    schedule = celery_app.conf.beat_schedule["cleanup-deferred-document-storage"]
    assert schedule["task"] == DOCUMENT_STORAGE_CLEANUP_TASK
    assert schedule["options"] == {"queue": "passport_ocr"}
    assert celery_app.conf.task_routes[DOCUMENT_STORAGE_ORPHAN_RECONCILIATION_TASK] == {
        "queue": "passport_ocr"
    }
    orphan_schedule = celery_app.conf.beat_schedule[
        "reconcile-orphaned-document-storage"
    ]
    assert orphan_schedule["task"] == DOCUMENT_STORAGE_ORPHAN_RECONCILIATION_TASK
    assert orphan_schedule["schedule"] == 3_600.0
    assert orphan_schedule["options"] == {"queue": "passport_ocr"}
