from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint, Index, UniqueConstraint

from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailOAuthStateModel,
    EmailReviewItemModel,
)


def _unique_column_sets(model: type) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _foreign_key_column_sets(model: type) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def test_email_provider_secrets_are_deferred_from_normal_orm_queries() -> None:
    connection_mapper = EmailConnectionModel.__mapper__
    oauth_mapper = EmailOAuthStateModel.__mapper__
    artifact_mapper = EmailArtifactModel.__mapper__

    assert connection_mapper.attrs.access_token_ciphertext.deferred is True
    assert connection_mapper.attrs.refresh_token_ciphertext.deferred is True
    assert oauth_mapper.attrs.code_verifier_ciphertext.deferred is True
    assert artifact_mapper.attrs.source_url_ciphertext.deferred is True


def test_email_records_have_tenant_scoped_identity_and_parent_references() -> None:
    assert ("id", "agency_id") in _unique_column_sets(EmailConnectionModel)
    assert ("id", "agency_id") in _unique_column_sets(EmailMessageModel)
    assert ("id", "agency_id") in _unique_column_sets(EmailArtifactModel)
    assert ("id", "agency_id") in _unique_column_sets(EmailReviewItemModel)

    assert ("connection_id", "agency_id") in _foreign_key_column_sets(EmailMessageModel)
    assert ("message_id", "agency_id") in _foreign_key_column_sets(EmailArtifactModel)
    assert (
        "artifact_id",
        "message_id",
        "agency_id",
    ) in _foreign_key_column_sets(EmailReviewItemModel)
    assert (
        "message_id",
        "connection_id",
        "agency_id",
    ) in _foreign_key_column_sets(EmailActivityEventModel)


def test_provider_and_processing_idempotency_constraints_are_database_backed() -> None:
    assert (
        "provider",
        "provider_account_id",
    ) in _unique_column_sets(EmailConnectionModel)
    assert ("state_hash",) in _unique_column_sets(EmailOAuthStateModel)
    assert (
        "connection_id",
        "provider_message_id",
    ) in _unique_column_sets(EmailMessageModel)
    assert (
        "message_id",
        "provider_artifact_id",
    ) in _unique_column_sets(EmailArtifactModel)
    assert (
        "agency_id",
        "event_key",
    ) in _unique_column_sets(EmailActivityEventModel)


def test_review_queue_uses_revision_and_partial_active_uniqueness() -> None:
    table = EmailReviewItemModel.__table__
    indexes = {index.name: index for index in table.indexes if isinstance(index, Index)}

    assert table.c.revision.nullable is False
    assert str(table.c.revision.server_default.arg) == "1"

    message_index = indexes["uq_email_review_items_active_message"]
    artifact_index = indexes["uq_email_review_items_active_artifact"]
    assert message_index.unique is True
    assert artifact_index.unique is True
    assert str(message_index.dialect_options["postgresql"]["where"]) == (
        "artifact_id IS NULL AND status IN ('open', 'deferred')"
    )
    assert str(artifact_index.dialect_options["postgresql"]["where"]) == (
        "artifact_id IS NOT NULL AND status IN ('open', 'deferred')"
    )
