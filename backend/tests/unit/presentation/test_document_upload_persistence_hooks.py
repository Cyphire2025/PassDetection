"""Transaction hooks retain the upload snapshot and recheck the locked manifest."""

from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.presentation.api.v1.document_chunk_uploads import (
    DocumentChunkMetadata,
    new_document_chunk_receipt,
)
from app.presentation.api.v1.routes import document_distribution_upload_persistence_scope as owner
from app.presentation.api.v1.routes.document_distribution_storage import (
    _ConcurrentDocumentChunkReplay,
)


def _arrange(monkeypatch, case):
    agency_id, group_id, actor_id, upload_id = (uuid.uuid4() for _ in range(4))
    actor = SimpleNamespace(id=actor_id, email="current@example.test")
    metadata = DocumentChunkMetadata(upload_id, uuid.uuid4(), 0, 1, 1)
    existing = None
    serialized = None
    receipts = []
    if case in {"resume", "closed", "removed"}:
        metadata = replace(metadata, chunk_index=1, expected_chunk_count=2, expected_file_count=2)
        existing = SimpleNamespace(
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            status="processing",
        )
        serialized = existing
        receipts = [
            new_document_chunk_receipt(
                metadata=replace(metadata, chunk_index=0, chunk_id=uuid.uuid4()),
                agency_id=agency_id,
                workflow="distribution",
                group_id=group_id,
                document_type="visa",
                fingerprint="previous",
                file_count=1,
                byte_count=10,
                accepted_count=1,
                rejected_count=0,
            )
        ]
        if case == "closed":
            serialized.status = "saved"
        elif case == "removed":
            serialized = None
    if case in {"agency", "group", "type", "appeared"}:
        serialized = SimpleNamespace(
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            status="processing",
        )
        if case == "agency":
            serialized.agency_id = uuid.uuid4()
        elif case == "group":
            serialized.group_id = uuid.uuid4()
        elif case == "type":
            serialized.document_type = "flight_ticket"
    if case in {"replay", "changed-replay"}:
        receipts = [
            new_document_chunk_receipt(
                metadata=metadata,
                agency_id=agency_id,
                workflow="distribution",
                group_id=group_id,
                document_type="visa",
                fingerprint="same" if case == "replay" else "changed",
                file_count=1,
                byte_count=10,
                accepted_count=1,
                rejected_count=0,
            )
        ]
    results = [
        SimpleNamespace(),
        SimpleNamespace(scalar_one_or_none=lambda: serialized),
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: receipts)),
    ]
    session = MagicMock(execute=AsyncMock(side_effect=results))
    reauthorize = AsyncMock(return_value=(actor, []))
    if case == "revoked":
        reauthorize.side_effect = HTTPException(status_code=403, detail="Scope revoked")
    scope_lock = AsyncMock()
    upload_lock = AsyncMock()
    blocker = AsyncMock(return_value=uuid.uuid4() if case == "blocking" else None)
    monkeypatch.setattr(owner, "_lock_and_validate_document_match_scope", reauthorize)
    monkeypatch.setattr(owner, "acquire_document_upload_scope_advisory_lock", scope_lock)
    monkeypatch.setattr(owner, "acquire_document_upload_advisory_lock", upload_lock)
    monkeypatch.setattr(owner, "_first_blocking_processing_upload_id", blocker)
    guard = owner.DistributionUploadPersistence(
        session=session,
        current_user=SimpleNamespace(id=actor_id, email="before@example.test"),
        group_id=group_id,
        agency_id=agency_id,
        document_type="visa",
        matcher=MagicMock(),
        roster_snapshot=(("passenger",),),
        linked_source=SimpleNamespace(snapshot=(("source",),)),
        supplemental_identifiers=(),
        chunk_metadata=None if case == "legacy" else metadata,
        existing_batch=existing,
        fingerprint="same",
        incoming_file_count=1,
        chunk_byte_count=10,
        replacement_decisions={},
        replacement_actor_id=actor_id,
        replacement_actor_email="before@example.test",
        replacement_cleanup_ids=[],
    )
    return guard, actor, reauthorize, scope_lock, upload_lock


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "legacy",
        "new",
        "resume",
        "agency",
        "group",
        "type",
        "appeared",
        "removed",
        "closed",
        "blocking",
        "replay",
        "changed-replay",
        "revoked",
    ],
)
async def test_locked_upload_manifest_rechecks_preserve_scope_and_actor(monkeypatch, case):
    guard, actor, reauthorize, scope_lock, upload_lock = _arrange(monkeypatch, case)
    if case in {"legacy", "new", "resume"}:
        assert await guard.reauthorize_before_persistence() == (actor.id, actor.email)
        assert guard.replacement_actor_id == actor.id
        assert guard.replacement_actor_email == actor.email
        assert guard.session.execute.await_count == (1 if case == "legacy" else 3)
        for call in guard.session.execute.await_args_list:
            assert "FOR UPDATE" in str(call.args[0].compile(dialect=postgresql.dialect()))
        assert upload_lock.await_count == int(case != "legacy")
    elif case == "replay":
        with pytest.raises(_ConcurrentDocumentChunkReplay):
            await guard.reauthorize_before_persistence()
    else:
        with pytest.raises(HTTPException) as caught:
            await guard.reauthorize_before_persistence()
        assert caught.value.status_code == (403 if case == "revoked" else 409)
    reauthorize.assert_awaited_once_with(
        guard.session,
        current_user=guard.current_user,
        group_id=guard.group_id,
        agency_id=guard.agency_id,
        matcher=guard.matcher,
        expected_roster_snapshot=guard.roster_snapshot,
        expected_source_snapshot=guard.linked_source.snapshot,
        expected_supplemental_identifiers=guard.supplemental_identifiers,
    )
    if case == "revoked":
        scope_lock.assert_not_awaited()
        guard.session.execute.assert_not_awaited()
    if case not in {"legacy", "new", "resume"}:
        assert guard.replacement_actor_email == "before@example.test"
        assert guard.replacement_cleanup_ids == []


@pytest.mark.asyncio
async def test_capacity_and_replacement_hooks_share_the_reauthorized_actor_and_cleanup_list(
    monkeypatch,
):
    guard, actor, *_ = _arrange(monkeypatch, "new")
    cleanup_id = uuid.uuid4()
    capacity = AsyncMock()
    replacements = AsyncMock(return_value=[cleanup_id])
    monkeypatch.setattr(owner, "_enforce_group_document_assignment_capacity", capacity)
    monkeypatch.setattr(owner, "apply_filename_replacements", replacements)
    await guard.reauthorize_before_persistence()
    documents = [SimpleNamespace(id=uuid.uuid4())]
    cleanup = guard.replacement_cleanup_ids
    await guard.enforce_capacity_before_persistence(3)
    capacity.assert_awaited_once_with(
        guard.session,
        group_id=guard.group_id,
        agency_id=guard.agency_id,
        document_type="visa",
        incoming_rows=3,
    )
    await guard.replace_successfully_stored_documents(documents)
    replacements.assert_awaited_once_with(
        guard.session,
        agency_id=guard.agency_id,
        group_id=guard.group_id,
        document_type="visa",
        new_documents=documents,
        replacements=guard.replacement_decisions,
        actor_id=actor.id,
        actor_email=actor.email,
    )
    assert guard.replacement_cleanup_ids is cleanup
    assert cleanup == [cleanup_id]
