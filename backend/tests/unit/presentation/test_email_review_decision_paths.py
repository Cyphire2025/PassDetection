"""Public decision outcomes preserve ownership, revision and retry semantics."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.domain.entities.entities import UserRole
from app.infrastructure.database.email_models import EmailActivityEventModel
from app.presentation.api.v1.routes import email_integration_review_decisions as decisions
from app.presentation.api.v1.schemas.email_integration_schemas import ResolveEmailReviewRequest
from tests.email_review_decision_fixtures import persist_email_review


@pytest.fixture
async def review_graph(db_session, monkeypatch):
    return await persist_email_review(db_session, monkeypatch)


async def _resolve(session, graph, action, **fields):
    return await decisions.resolve_email_review(
        review_id=graph.review.id,
        payload=ResolveEmailReviewRequest(action=action, expected_revision=1, **fields),
        current_user=graph.user,
        session=session,
    )


@pytest.mark.parametrize(
    "action,expected",
    [
        ("reject", "rejected"),
        ("defer", "deferred"),
        ("retry", "resolved"),
        ("mark_unrelated", "resolved"),
        ("approve", "resolved"),
        ("assign", "resolved"),
    ],
)
async def test_each_available_action_commits_its_existing_result(
    db_session, review_graph, action, expected
):
    graph = review_graph
    before = datetime.now(UTC)
    result = await _resolve(db_session, graph, action)
    assert result.status == expected and result.review_id == graph.review.id
    await db_session.refresh(graph.review)
    assert graph.review.revision == 2
    assert graph.review.resolved_by_user_id == (None if action == "defer" else graph.user.id)
    events = (
        await db_session.scalars(
            select(EmailActivityEventModel).where(
                EmailActivityEventModel.review_item_id == graph.review.id
            )
        )
    ).all()
    assert len(events) == 1 and events[0].summary_code == f"EMAIL_REVIEW_{action.upper()}"
    graph.storage.delete_files.assert_not_awaited()
    if action in {"approve", "assign"}:
        graph.ingest.assert_awaited_once()
        assert graph.review.selected_group_id == graph.group.id
        assert graph.review.selected_passenger_id == graph.passenger.id
    else:
        graph.ingest.assert_not_awaited()
    if action == "retry":
        graph.enqueue.assert_called_once_with(
            graph.connection, provider_message_id=graph.message.provider_message_id
        )
        assert graph.message.processing_status == "queued" and graph.message.processed_at is None
        assert graph.artifact.retrieval_status == "pending"
    else:
        graph.enqueue.assert_not_called()
    if action == "defer":
        stamp = graph.review.deferred_until
        stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp
        assert (stamp - before).total_seconds() >= 86_400
    if action == "mark_unrelated":
        assert graph.message.relevance_status == "ignored"
    if action == "reject":
        assert graph.artifact.processing_status == "ignored"


@pytest.mark.parametrize("role", [UserRole.AGENCY_STAFF, UserRole.SUPER_ADMIN])
async def test_other_personal_mailboxes_are_hidden_even_for_admins(db_session, review_graph, role):
    review_graph.user.id = uuid.uuid4()
    review_graph.user.role = role
    with pytest.raises(HTTPException) as error:
        await _resolve(db_session, review_graph, "reject")
    assert error.value.status_code == 404
    review_graph.ingest.assert_not_awaited()


@pytest.mark.parametrize(
    "field,value,status",
    [("revision", 2, 409), ("status", "resolved", 409), ("artifact_id", None, 422)],
)
async def test_stale_closed_or_unavailable_actions_fail_before_mutation(
    db_session, review_graph, field, value, status
):
    setattr(review_graph.review, field, value)
    if field == "status":
        review_graph.review.resolved_at = datetime.now(UTC)
    await db_session.flush()
    with pytest.raises(HTTPException) as error:
        await _resolve(db_session, review_graph, "assign")
    assert error.value.status_code == status
    review_graph.ingest.assert_not_awaited()


@pytest.mark.parametrize("action", ["approve", "assign", "retry"])
async def test_disabled_feature_blocks_work_actions_before_lookup(db_session, review_graph, action):
    review_graph.settings.email_integrations_enabled = False
    with pytest.raises(HTTPException) as error:
        await _resolve(db_session, review_graph, action)
    assert error.value.status_code == 503
    review_graph.ingest.assert_not_awaited()


async def test_disabled_sync_and_paused_mailbox_reject_retry(db_session, review_graph):
    review_graph.settings.email_sync_enabled = False
    with pytest.raises(HTTPException) as disabled:
        await _resolve(db_session, review_graph, "retry")
    assert disabled.value.status_code == 503
    review_graph.settings.email_sync_enabled = True
    review_graph.connection.status = "paused"
    await db_session.flush()
    with pytest.raises(HTTPException) as paused:
        await _resolve(db_session, review_graph, "retry")
    assert paused.value.status_code == 409
    review_graph.enqueue.assert_not_called()


@pytest.mark.parametrize(
    "missing_table,status,lock_order",
    [
        ("email_messages", 409, ["email_connections", "email_messages"]),
        (
            "email_review_items",
            404,
            ["email_connections", "email_messages", "email_artifacts", "email_review_items"],
        ),
    ],
)
async def test_unavailable_rows_after_identity_lookup_keep_scoped_lock_order_and_error_contract(
    db_session, review_graph, monkeypatch, missing_table, status, lock_order
):
    from sqlalchemy.dialects import postgresql

    scalar = db_session.scalar
    observed = []

    async def load_locked(statement, *args, **kwargs):
        entity = statement.column_descriptions[0]["entity"]
        table = entity.__tablename__
        observed.append(table)
        compiled = statement.compile(dialect=postgresql.dialect())
        assert "FOR UPDATE" in str(compiled)
        assert review_graph.user.id in compiled.params.values()
        assert review_graph.agency.id in compiled.params.values()
        if table == missing_table:
            return None
        return await scalar(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "scalar", load_locked)
    with pytest.raises(HTTPException) as error:
        await _resolve(db_session, review_graph, "reject")
    assert error.value.status_code == status
    assert observed == lock_order
    assert review_graph.review.revision == 1
    review_graph.ingest.assert_not_awaited()
    review_graph.enqueue.assert_not_called()
    review_graph.storage.delete_files.assert_not_awaited()
