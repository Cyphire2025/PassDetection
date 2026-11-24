"""Document review keeps cleanup and ambiguous-commit ownership with the route."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.infrastructure.email.sync_contracts import ReviewedArtifactIngestionResult
from app.presentation.api.v1.routes import email_integration_review_decisions as decisions
from app.presentation.api.v1.schemas.email_integration_schemas import ResolveEmailReviewRequest
from tests.email_review_decision_fixtures import persist_email_review


async def _assign(session, graph, **fields):
    return await decisions.resolve_email_review(
        review_id=graph.review.id,
        payload=ResolveEmailReviewRequest(action="assign", expected_revision=1, **fields),
        current_user=graph.user,
        session=session,
    )


@pytest.mark.parametrize("duplicate", [False, True])
async def test_assigning_unknown_type_uses_the_selected_supported_type(
    db_session, monkeypatch, duplicate
):
    graph = await persist_email_review(db_session, monkeypatch)
    graph.artifact.detected_type = "unknown"
    graph.ingest.return_value = ReviewedArtifactIngestionResult(
        document_ids=(), storage_keys=(), duplicate=duplicate
    )
    result = await _assign(db_session, graph, document_type="flight_ticket")
    assert graph.artifact.detected_type == "flight_ticket"
    assert ("duplicate" in result.message) == duplicate
    graph.ingest.assert_awaited_once_with(
        db_session,
        review=graph.review,
        group_id=graph.group.id,
        passenger_id=graph.passenger.id,
        created_by_user_id=graph.user.id,
        actor_email=graph.user.email,
    )


@pytest.mark.parametrize(
    "case", ["unknown_type", "missing_candidate", "mismatched_group", "ingestion_rejected"]
)
async def test_assignment_rejects_incomplete_or_unavailable_document_targets(
    db_session, monkeypatch, case
):
    graph = await persist_email_review(db_session, monkeypatch)
    fields = {}
    if case == "unknown_type":
        graph.artifact.detected_type = "unknown"
    elif case == "missing_candidate":
        graph.review.candidate_passenger_id = None
    elif case == "mismatched_group":
        fields["group_id"] = uuid.uuid4()
    else:
        graph.ingest.side_effect = ValueError("Synthetic ingestion rejection")
    with pytest.raises(HTTPException) as error:
        await _assign(db_session, graph, **fields)
    assert error.value.status_code == 422
    graph.storage.delete_files.assert_not_awaited()


async def test_audit_failure_rolls_back_before_deleting_only_new_objects(db_session, monkeypatch):
    graph = await persist_email_review(db_session, monkeypatch)
    operations = []
    rollback = db_session.rollback

    async def roll_back():
        operations.append("rollback")
        await rollback()

    async def delete(keys):
        operations.append("delete")
        assert keys == ["email-integrations-canonical/synthetic.pdf"]
        assert not db_session.in_transaction()
        return 1

    monkeypatch.setattr(db_session, "rollback", roll_back)
    graph.storage.delete_files.side_effect = delete
    record = AsyncMock(side_effect=RuntimeError("Synthetic audit failure"))
    monkeypatch.setattr(decisions.AuditLogRepository, "record", record)
    with pytest.raises(RuntimeError, match="Synthetic audit failure"):
        await _assign(db_session, graph)
    assert operations == ["rollback", "delete"]
    graph.storage.delete_files.assert_awaited_once_with(
        ["email-integrations-canonical/synthetic.pdf"]
    )


async def test_failed_commit_acknowledgement_retains_potentially_committed_objects(
    db_session, monkeypatch
):
    graph = await persist_email_review(db_session, monkeypatch)
    monkeypatch.setattr(
        db_session,
        "commit",
        AsyncMock(side_effect=RuntimeError("Synthetic commit acknowledgement")),
    )
    with pytest.raises(RuntimeError, match="Synthetic commit acknowledgement"):
        await _assign(db_session, graph)
    graph.storage.delete_files.assert_not_awaited()
    graph.enqueue.assert_not_called()
