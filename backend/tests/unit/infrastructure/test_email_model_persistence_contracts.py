"""Actual persisted email defaults, deferred secrets, and immutable ownership."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event, insert, inspect, select
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import undefer

from app.infrastructure.database import email_models
from app.infrastructure.database.email_models import EmailConnectionModel
from tests.email_model_persistence_fixtures import persist_email_model_graph
from tests.email_ownership_constraints import CASES, assert_email_parent_constraint

OWNER_ROWS = ("connection", "message", "artifact", "link", "review", "activity")


@pytest.mark.parametrize("name", OWNER_ROWS)
async def test_persisted_email_owner_change_is_rejected_and_rolled_back(db_session, name):
    graph = await persist_email_model_graph(db_session)
    row = getattr(graph, name)
    row_type, row_id = type(row), row.id
    row.owner_user_id = graph.other_owner_id
    with pytest.raises(ValueError, match="^Email record ownership cannot be changed$"):
        await db_session.flush()
    await db_session.rollback()
    stored = await db_session.get(row_type, row_id)
    assert stored is not None
    assert stored.owner_user_id == graph.owner_id


@pytest.mark.parametrize("name", OWNER_ROWS)
async def test_persisted_email_same_owner_assignment_remains_valid(db_session, name):
    graph = await persist_email_model_graph(db_session)
    row = getattr(graph, name)
    row.owner_user_id = graph.owner_id
    await db_session.flush()
    assert row.owner_user_id == graph.owner_id


@pytest.mark.parametrize("name,fields", (
    ("connection", {"access_token_ciphertext": b"opaque-test-access", "refresh_token_ciphertext": b"opaque-test-refresh"}),
    ("oauth", {"code_verifier_ciphertext": b"opaque-test-verifier"}),
    ("artifact", {"source_url_ciphertext": b"opaque-test-url"}),
))
async def test_normal_select_defers_secrets_and_explicit_scoped_load_returns_them(db_session, name, fields):
    graph = await persist_email_model_graph(db_session)
    row = getattr(graph, name)
    row_type, row_id = type(row), row.id
    db_session.expunge_all()
    query = select(row_type).where(row_type.id == row_id, row_type.agency_id == graph.agency_id)
    loaded = (await db_session.scalars(query)).one()
    assert set(fields) <= inspect(loaded).unloaded
    assert set(fields).isdisjoint(loaded.__dict__)
    explicit = (await db_session.scalars(query.options(*(undefer(getattr(row_type, field)) for field in fields)))).one()
    assert explicit is loaded
    assert {field: getattr(explicit, field) for field in fields} == fields


@pytest.mark.parametrize("kind", ("orm", "core"))
async def test_insert_uses_real_context_normalization_and_utc_defaults(db_session, kind):
    graph = await persist_email_model_graph(db_session)
    assert graph.connection.normalized_email_address == "owner@example.test"
    row_id = uuid.uuid4()
    values = dict(id=row_id, agency_id=graph.agency_id, owner_user_id=graph.owner_id,
        provider="outlook", provider_account_id="synthetic-second-mailbox", email_address=" Second@Example.TEST ")
    if kind == "orm":
        row = EmailConnectionModel(**values)
        db_session.add(row)
        await db_session.flush()
    else:
        await db_session.execute(insert(EmailConnectionModel).values(**values))
        row = await db_session.get(EmailConnectionModel, row_id)
    assert row is not None
    assert row.normalized_email_address == "second@example.test"
    assert row.created_at is not None
    assert row.updated_at is not None
    assert row.scopes == []
    assert row.ai_processing_enabled is False


@pytest.mark.parametrize("email", (None, "   "))
async def test_insert_context_rejects_missing_or_blank_email_before_persistence(db_session, email):
    graph = await persist_email_model_graph(db_session)
    row_id = uuid.uuid4()
    row = EmailConnectionModel(id=row_id, agency_id=graph.agency_id, owner_user_id=graph.owner_id,
        provider="outlook", provider_account_id="synthetic-empty-mailbox", email_address=email)
    db_session.add(row)
    with pytest.raises(StatementError) as exc:
        await db_session.flush()
    assert isinstance(exc.value.orig, ValueError)
    assert str(exc.value.orig) == "email_address is required to normalize an email connection"
    await db_session.rollback()
    assert await db_session.get(EmailConnectionModel, row_id) is None


def test_owner_listeners_use_one_canonical_callback_on_exactly_six_persisted_owner_models():
    names = ("EmailConnectionModel", "EmailMessageModel", "EmailArtifactModel",
             "EmailArtifactDocumentModel", "EmailReviewItemModel", "EmailActivityEventModel")
    for name in names:
        model = getattr(email_models, name)
        assert event.contains(model, "before_update", email_models._reject_email_owner_change)
        assert len(tuple(model.__mapper__.dispatch.before_update)) == 1
    assert not event.contains(email_models.EmailOAuthStateModel, "before_update", email_models._reject_email_owner_change)
    assert len(tuple(email_models.EmailOAuthStateModel.__mapper__.dispatch.before_update)) == 0


@pytest.mark.parametrize("case", CASES)
async def test_existing_email_parent_scope_controls_remain_enforced(db_session, case):
    await assert_email_parent_constraint(db_session, case)
