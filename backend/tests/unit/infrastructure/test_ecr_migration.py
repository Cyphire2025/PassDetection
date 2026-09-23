"""Exercise migration DDL and compare persisted columns with the runtime models."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel


def test_ecr_migration_upgrade_matches_models_and_downgrade_removes_tables():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0106_ecr_checker.py"
    spec = importlib.util.spec_from_file_location("ecr_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = inspect(connection)
        for model in (EcrBatchModel, EcrItemModel):
            actual = {
                column["name"]: column for column in inspector.get_columns(model.__tablename__)
            }
            assert set(actual) == set(model.__table__.columns.keys())
            for column in model.__table__.columns:
                if not column.primary_key:
                    assert actual[column.name]["nullable"] == column.nullable
        assert inspector.get_unique_constraints("ecr_items")[0]["column_names"] == [
            "batch_id",
            "client_id",
        ]
        migration.downgrade()
        assert inspect(connection).get_table_names() == []
    engine.dispose()
