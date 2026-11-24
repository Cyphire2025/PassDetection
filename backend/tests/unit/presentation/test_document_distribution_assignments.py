"""Actual assignment mutations retain files/history and durable cleanup ordering."""

from __future__ import annotations

import uuid
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    AuditLogModel,
    DistributedDocumentModel,
    StorageCleanupJobModel,
)
from app.infrastructure.documents.document_approval_provenance import (
    has_manual_document_type_approval,
)
from app.infrastructure.documents.storage_cleanup import StorageCleanupCipher
from app.presentation.api.v1.routes import document_distribution as route
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DeleteDistributionDocumentsRequest,
)
from tests.document_assignment_fixtures import persist_assignment_graph, persist_delivery
from tests.route_dependencies import set_route_dependency


@pytest.fixture
def isolated_io(monkeypatch):
    runner, propagation = AsyncMock(), AsyncMock()

    class Storage:
        async def get_presigned_url(self, key):
            return "https://objects.example.test/" + key

    set_route_dependency(
        monkeypatch,
        "app.presentation.api.v1.routes.document_distribution.MinioStorageRepository",
        Storage,
    )
    set_route_dependency(
        monkeypatch,
        "app.presentation.api.v1.routes.document_distribution.process_storage_cleanup_job",
        runner,
    )
    set_route_dependency(
        monkeypatch,
        "app.presentation.api.v1.routes.document_distribution.propagate_mobile_passenger_change",
        propagation,
    )
    cipher = StorageCleanupCipher("synthetic-assignment-cleanup-key")
    monkeypatch.setattr(StorageCleanupCipher, "from_settings", classmethod(lambda cls: cipher))
    return runner, propagation, cipher


async def invoke(session, graph, action, ids, *, document_type="visa", actor=None):
    endpoint = (
        route.unassign_distribution_documents
        if action == "unassign"
        else route.delete_distribution_documents
    )
    return await endpoint(
        graph.group.id,
        document_type,
        DeleteDistributionDocumentsRequest(document_ids=ids),
        current_user=actor or graph.actor,
        session=session,
    )


async def cleanup_jobs(session):
    return list((await session.scalars(select(StorageCleanupJobModel))).all())


@pytest.mark.parametrize("action", ["unassign", "delete"])
async def test_empty_selection_returns_existing_review_without_mutation(
    db_session: AsyncSession,
    isolated_io,
    action,
):
    graph = await persist_assignment_graph(db_session)
    response = await invoke(db_session, graph, action, [])
    assert response.batch_id == graph.batch.id
    assert response.status == "saved"
    assert response.physical_file_count == 2
    assert response.assigned_file_count == 1
    assert await db_session.get(DistributedDocumentModel, graph.document.id) is graph.document
    assert graph.document.passenger_id == graph.passenger.id
    assert not await cleanup_jobs(db_session)
    assert not (await db_session.scalars(select(AuditLogModel))).all()
    isolated_io[0].assert_not_awaited()
    isolated_io[1].assert_not_awaited()


async def test_unassign_keeps_saved_pdf_approval_and_delivery_history(
    db_session: AsyncSession,
    isolated_io,
):
    graph = await persist_assignment_graph(db_session)
    delivery = await persist_delivery(db_session, graph, status="delivered")
    storage_key, document_id, passenger_id = (
        graph.document.storage_key,
        graph.document.id,
        graph.passenger.id,
    )
    response = await invoke(db_session, graph, "unassign", [document_id, document_id])
    await db_session.refresh(graph.document)
    await db_session.refresh(delivery)
    assert graph.document.passenger_id is None
    assert graph.document.storage_key == storage_key
    assert graph.document.match_status == "needs_review" and graph.document.match_confidence == 0
    assert has_manual_document_type_approval(graph.document.match_reason)
    assert delivery.distributed_document_id == document_id and delivery.status == "delivered"
    assert delivery.provider_message_id == "synthetic-provider-id"
    assert response.uploaded_count == 2 and response.matched_count == 0
    assert graph.batch.status == "draft" and graph.batch.saved_at is None
    assert not await cleanup_jobs(db_session)
    audit = (await db_session.scalars(select(AuditLogModel))).one()
    assert audit.action == "document_distribution_unassigned"
    assert audit.metadata_json["unassigned_count"] == 1
    assert audit.metadata_json["saved_files_retained"] is True
    isolated_io[0].assert_not_awaited()
    isolated_io[1].assert_awaited_once()
    assert isolated_io[1].await_args.kwargs["passenger_submission_ids"] == (passenger_id,)
    assert isolated_io[1].await_args.kwargs["operation"] == "delete"


@pytest.mark.parametrize("action", ["unassign", "delete"])
@pytest.mark.parametrize("delivery_status", ["queued", "processing"])
async def test_active_delivery_blocks_both_mutations_without_cleanup_or_history_changes(
    db_session: AsyncSession,
    isolated_io,
    action,
    delivery_status,
):
    graph = await persist_assignment_graph(db_session)
    delivery = await persist_delivery(db_session, graph, status=delivery_status)
    with pytest.raises(HTTPException) as error:
        await invoke(db_session, graph, action, [graph.document.id])
    assert error.value.status_code == 409
    assert graph.document.passenger_id == graph.passenger.id
    assert graph.document.match_status == "matched" and delivery.status == delivery_status
    assert graph.batch.status == "saved"
    assert not await cleanup_jobs(db_session)
    assert not (await db_session.scalars(select(AuditLogModel))).all()
    isolated_io[0].assert_not_awaited()
    isolated_io[1].assert_not_awaited()


@pytest.mark.parametrize("runner_failure", [False, True])
async def test_delete_commits_rows_and_encrypted_cleanup_before_best_effort_runner(
    db_session: AsyncSession,
    isolated_io,
    runner_failure,
):
    graph = await persist_assignment_graph(db_session)
    delivery = await persist_delivery(db_session, graph, status="delivered")
    document_id, storage_key = graph.document.id, graph.document.storage_key
    observed_committed = []

    async def observe_committed_job(job_id):
        assert not db_session.in_transaction()
        job = await db_session.get(StorageCleanupJobModel, job_id)
        assert job is not None and job.status == "pending"
        assert await db_session.get(DistributedDocumentModel, document_id) is None
        assert (
            await db_session.scalars(select(AuditLogModel))
        ).one().action == "document_distribution_deleted"
        observed_committed.append(job_id)
        if runner_failure:
            raise RuntimeError("Synthetic cleanup runner outage")

    isolated_io[0].side_effect = observe_committed_job
    response = await invoke(db_session, graph, "delete", [document_id, document_id])
    await db_session.refresh(delivery)
    assert await db_session.get(DistributedDocumentModel, document_id) is None
    assert await db_session.get(DistributedDocumentModel, graph.unmatched.id) is graph.unmatched
    assert delivery.distributed_document_id is None and delivery.status == "delivered"
    assert delivery.provider_message_id == "synthetic-provider-id"
    jobs = await cleanup_jobs(db_session)
    assert len(jobs) == 1 and jobs[0].object_count == 1
    # Runner exceptions are deliberately contained by the route. Keep the
    # observation assertion outside that boundary so it cannot be swallowed.
    assert observed_committed == [jobs[0].id]
    assert isolated_io[2].decrypt(
        jobs[0].storage_keys_ciphertext, key_version=jobs[0].encryption_key_version
    ) == (storage_key,)
    assert response.uploaded_count == 1 and response.matched_count == 0
    assert graph.batch.uploaded_count == 1 and graph.batch.matched_count == 0
    assert graph.batch.status == "draft" and graph.batch.saved_at is None
    isolated_io[0].assert_awaited_once_with(jobs[0].id)
    isolated_io[1].assert_awaited_once()


async def test_delete_retains_storage_still_referenced_by_another_assignment(
    db_session: AsyncSession,
    isolated_io,
):
    graph = await persist_assignment_graph(db_session)
    graph.unmatched.storage_key = graph.document.storage_key
    await db_session.commit()
    document_id = graph.document.id
    response = await invoke(db_session, graph, "delete", [document_id])
    assert await db_session.get(DistributedDocumentModel, document_id) is None
    assert response.physical_file_count == 1
    assert not await cleanup_jobs(db_session)
    audit = (await db_session.scalars(select(AuditLogModel))).one()
    assert audit.metadata_json["deleted_count"] == 1
    assert audit.metadata_json["deleted_storage_objects"] == 0
    isolated_io[0].assert_not_awaited()


@pytest.mark.parametrize("action", ["unassign", "delete"])
@pytest.mark.parametrize("scope", ["foreign_actor", "missing_id", "unsupported_type"])
async def test_invalid_scope_never_changes_documents_or_stages_cleanup(
    db_session: AsyncSession,
    isolated_io,
    action,
    scope,
):
    graph = await persist_assignment_graph(db_session)
    actor = (
        replace(graph.actor, agency_id=uuid.uuid4()) if scope == "foreign_actor" else graph.actor
    )
    document_type = "unsupported" if scope == "unsupported_type" else "visa"
    ids = [uuid.uuid4()] if scope == "missing_id" else [graph.document.id]
    with pytest.raises(HTTPException) as error:
        await invoke(db_session, graph, action, ids, document_type=document_type, actor=actor)
    assert error.value.status_code == (400 if scope == "unsupported_type" else 404)
    assert graph.document.passenger_id == graph.passenger.id
    assert graph.document.match_status == "matched"
    assert graph.batch.status == "saved" and graph.batch.uploaded_count == 2
    assert not await cleanup_jobs(db_session)
    assert not (await db_session.scalars(select(AuditLogModel))).all()
    isolated_io[0].assert_not_awaited()
    isolated_io[1].assert_not_awaited()
