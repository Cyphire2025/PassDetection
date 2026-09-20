"""The public proof migration is additive and guarantees one row per draft."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_contact_proof_table_upgrade_and_constraints():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0102_public_upload_contact_otp.py"
    spec = importlib.util.spec_from_file_location("public_contact_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE client_groups (id UUID PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE passport_submissions (id UUID PRIMARY KEY)")
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
        inspector = sa.inspect(connection)
        assert inspector.get_pk_constraint("public_upload_contact_challenges")["constrained_columns"] == ["submission_id"]
        assert inspector.get_unique_constraints("public_upload_contact_challenges")[0]["column_names"] == ["id"]
        assert len(inspector.get_foreign_keys("public_upload_contact_challenges")) == 2
        assert all(fk["options"]["ondelete"] == "CASCADE" for fk in inspector.get_foreign_keys("public_upload_contact_challenges"))
        assert {row["name"] for row in inspector.get_columns("public_upload_contact_challenges")} >= {
            "code_hash", "email_hash", "upload_session_hash", "phone_number", "status", "proof_expires_at", "consumed_at",
        }
    engine.dispose()
