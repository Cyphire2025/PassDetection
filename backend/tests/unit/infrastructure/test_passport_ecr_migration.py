import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from app.infrastructure.database.passport_ecr_models import PassportEcrCheckModel


def test_passport_ecr_migration_matches_runtime_and_downgrades():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0107_passport_ecr_checks.py"
    spec = importlib.util.spec_from_file_location("passport_ecr_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0106_ecr_checker"
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = inspect(connection)
        actual = {column["name"]: column for column in inspector.get_columns("passport_ecr_checks")}
        assert set(actual) == set(PassportEcrCheckModel.__table__.columns.keys())
        for column in PassportEcrCheckModel.__table__.columns:
            if not column.primary_key:
                assert actual[column.name]["nullable"] == column.nullable
        assert (
            inspector.get_foreign_keys("passport_ecr_checks")[0]["options"]["ondelete"] == "CASCADE"
        )
        assert inspector.get_indexes("passport_ecr_checks")[0]["column_names"] == [
            "status",
            "next_attempt_at",
            "lease_expires_at",
        ]
        migration.downgrade()
        assert inspect(connection).get_table_names() == []
    engine.dispose()
