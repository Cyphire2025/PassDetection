from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_upgrade_preserves_existing_groups_as_collection_groups():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0101_client_group_import_only.py"
    spec = importlib.util.spec_from_file_location("import_groups_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE client_groups (id INTEGER PRIMARY KEY, name TEXT)")
        connection.exec_driver_sql("INSERT INTO client_groups VALUES (1, 'Existing collection group')")
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
        assert connection.exec_driver_sql("SELECT name, import_only FROM client_groups").one() == (
            "Existing collection group", 0,
        )
        connection.exec_driver_sql("INSERT INTO client_groups (id, name, import_only) VALUES (2, 'Import group', 1)")
        with pytest.raises(RuntimeError, match="downgrade refused"):
            migration.downgrade()
        assert connection.exec_driver_sql("SELECT import_only FROM client_groups WHERE id=2").scalar_one() == 1
    engine.dispose()
