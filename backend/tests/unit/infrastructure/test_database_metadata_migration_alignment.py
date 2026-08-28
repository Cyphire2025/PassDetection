from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from app.infrastructure.database.models import Base


def _index_signatures(table_name: str) -> dict[str, tuple[tuple[str, ...], bool]]:
    table = Base.metadata.tables[table_name]
    return {
        str(index.name): (tuple(column.name for column in index.columns), bool(index.unique))
        for index in table.indexes
    }


def _unique_constraint_signatures(table_name: str) -> dict[str, tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        str(constraint.name): tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_initial_identity_tables_retain_constraint_and_lookup_index_shapes() -> None:
    expected = {
        "agencies": ("agencies_email_key", "ix_agencies_email", "email"),
        "users": ("users_email_key", "ix_users_email", "email"),
        "refresh_tokens": (
            "refresh_tokens_token_key",
            "ix_refresh_tokens_token",
            "token",
        ),
    }

    for table_name, (constraint_name, index_name, column_name) in expected.items():
        assert _unique_constraint_signatures(table_name)[constraint_name] == (column_name,)
        assert _index_signatures(table_name)[index_name] == ((column_name,), False)


def test_historical_operational_indexes_remain_declared_in_orm_metadata() -> None:
    expected = {
        "client_groups": {
            "ix_client_groups_agency_status_created_at": (
                ("agency_id", "status", "created_at"),
                False,
            ),
        },
        "passport_processing_jobs": {
            "ix_passport_processing_jobs_status_created_at": (
                ("status", "created_at"),
                False,
            ),
        },
        "passport_submissions": {
            "ix_passport_submissions_agency_status_created_at": (
                ("agency_id", "status", "created_at"),
                False,
            ),
            "ix_passport_submissions_group_status_created_at": (
                ("group_id", "status", "created_at"),
                False,
            ),
            "ix_passport_submissions_group_email": (
                ("group_id", "client_email"),
                False,
            ),
            "ix_passport_submissions_group_phone": (
                ("group_id", "client_phone"),
                False,
            ),
        },
        "rooming_passenger_preferences": {
            "ix_rooming_preferences_hotel_id": (("hotel_id",), False),
            "ix_rooming_preferences_passenger_id": (("passenger_id",), False),
        },
    }

    for table_name, expected_indexes in expected.items():
        actual = _index_signatures(table_name)
        for index_name, signature in expected_indexes.items():
            assert actual[index_name] == signature

    rooming_indexes = _index_signatures("rooming_passenger_preferences")
    assert "ix_rooming_passenger_preferences_hotel_id" not in rooming_indexes
    assert "ix_rooming_passenger_preferences_passenger_id" not in rooming_indexes


def test_runtime_participant_uses_only_the_migrated_foreign_key_shapes() -> None:
    table = Base.metadata.tables["attendance_session_runtime_participants"]
    signatures = {
        (
            tuple(constraint.column_keys),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }

    assert signatures == {
        (("agency_id",), ("agencies.id",), "CASCADE"),
        (
            ("session_id", "agency_id"),
            ("attendance_sessions.id", "attendance_sessions.agency_id"),
            "CASCADE",
        ),
        (
            ("runtime_registration_id", "agency_id", "coordinator_user_id"),
            (
                "attendance_runtime_registrations.id",
                "attendance_runtime_registrations.agency_id",
                "attendance_runtime_registrations.coordinator_user_id",
            ),
            "RESTRICT",
        ),
    }
