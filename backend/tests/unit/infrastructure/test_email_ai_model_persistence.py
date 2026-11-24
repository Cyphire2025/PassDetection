"""Actual email-AI defaults, updates and composite owner constraints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError

from app.infrastructure.database import email_ai_models as models
from tests.email_model_persistence_fixtures import persist_email_model_graph

MODEL_NAMES = (
    "EmailAiRolloutPolicyModel",
    "EmailAiAnalysisModel",
    "EmailDetectedDeadlineModel",
    "EmailActionProposalModel",
    "EmailReplyDraftModel",
    "EmailAiFeedbackModel",
)


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _persist_ai_graph(session, *, kind="orm"):
    graph = await persist_email_model_graph(session)
    analysis_id = uuid.uuid4()
    scope = dict(
        agency_id=graph.agency_id,
        owner_user_id=graph.owner_id,
        connection_id=graph.connection.id,
        message_id=graph.message.id,
    )
    derived = dict(**scope, analysis_id=analysis_id)
    values = (
        dict(
            agency_id=graph.agency_id,
            owner_user_id=graph.owner_id,
            connection_id=graph.connection.id,
            scope_type="connection",
            updated_by_user_id=graph.owner_id,
        ),
        dict(
            id=analysis_id,
            **scope,
            input_hash="a" * 64,
            prompt_schema_version="test-v1",
            config_version="test-v1",
            ai_model="synthetic-model",
        ),
        dict(
            **derived,
            deadline_type="payment",
            source_phrase="Pay tomorrow",
            source_fingerprint="b" * 64,
            source_timezone="UTC",
            confidence=0.8,
        ),
        dict(
            **derived,
            action_type="create_task",
            risk_level="low",
            status="approval_required",
            explanation="Needs approval",
            confidence=0.8,
            idempotency_key="c" * 64,
        ),
        dict(**derived, subject="Unsent draft", body_text="Draft body"),
        dict(
            **derived,
            feedback_type="confirmation",
            field_name="summary",
            created_by_user_id=graph.owner_id,
        ),
    )
    rows = []
    for name, data in zip(MODEL_NAMES, values, strict=True):
        cls = getattr(models, name)
        if kind == "orm":
            row = cls(**data)
            session.add(row)
            await session.flush()
        else:
            row_id = await session.scalar(insert(cls).values(**data).returning(cls.id))
            row = await session.get(cls, row_id)
        rows.append(row)
    return graph, rows


@pytest.mark.parametrize("kind", ["orm", "core"])
async def test_real_inserts_and_updates_use_canonical_utc_and_json_defaults(db_session, kind):
    before = datetime.now(UTC)
    _, rows = await _persist_ai_graph(db_session, kind=kind)
    after = datetime.now(UTC)
    policy, analysis, deadline, proposal, draft, feedback = rows
    for row in rows:
        assert isinstance(row.id, uuid.UUID)
        assert before <= _utc(row.created_at) <= after
        if hasattr(row, "updated_at"):
            assert before <= _utc(row.updated_at) <= after
    assert policy.enabled is False
    assert analysis.status == "pending" and analysis.ai_provider == "google"
    assert (
        analysis.result_json == {}
        and analysis.context_manifest == {}
        and analysis.attempt_count == 0
    )
    assert analysis.needs_attention is False
    assert deadline.status == "detected" and deadline.is_ambiguous is False
    assert deadline.resolution_evidence == {}
    assert proposal.requires_approval is True and proposal.revision == 1
    assert proposal.payload_json == {} and proposal.execution_result == {}
    assert draft.recipients_json == [] and draft.status == "prepared" and draft.revision == 1
    assert feedback.original_value == {} and feedback.corrected_value == {}
    mutations = (
        (policy, "enabled", True),
        (analysis, "summary", "Edited summary"),
        (deadline, "source_phrase", "Reviewed phrase"),
        (proposal, "explanation", "Reviewed proposal"),
        (draft, "subject", "Reviewed draft"),
    )
    started = datetime.now(UTC)
    for row, field, value in mutations:
        if kind == "orm":
            setattr(row, field, value)
        else:
            await db_session.execute(
                update(type(row)).where(type(row).id == row.id).values(**{field: value})
            )
    await db_session.flush()
    finished = datetime.now(UTC)
    for row, field, value in mutations:
        await db_session.refresh(row)
        assert getattr(row, field) == value
        assert started <= _utc(row.updated_at) <= finished


@pytest.mark.parametrize("name", MODEL_NAMES)
async def test_composite_parent_ownership_rejects_cross_owner_updates(db_session, name):
    graph, rows = await _persist_ai_graph(db_session)
    row = rows[MODEL_NAMES.index(name)]
    row_type, row_id = type(row), row.id
    await db_session.commit()
    row.owner_user_id = graph.other_owner_id
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
    retained = await db_session.get(row_type, row_id)
    assert retained.owner_user_id == graph.owner_id


async def test_generated_json_values_are_independent_between_analysis_rows(db_session):
    graph, rows = await _persist_ai_graph(db_session)
    first = rows[1]
    second = models.EmailAiAnalysisModel(
        agency_id=graph.agency_id,
        owner_user_id=graph.owner_id,
        connection_id=graph.connection.id,
        message_id=graph.message.id,
        input_hash="d" * 64,
        prompt_schema_version="test-v1",
        config_version="test-v1",
        ai_model="synthetic-model",
    )
    db_session.add(second)
    await db_session.flush()
    assert first.result_json is not second.result_json
    assert first.context_manifest is not second.context_manifest
    first.result_json["synthetic"] = True
    assert second.result_json == {} and second.context_manifest == {}
