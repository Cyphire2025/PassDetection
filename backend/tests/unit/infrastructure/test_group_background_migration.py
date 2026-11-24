"""A manual downgrade cannot silently discard saved workspace image references."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def migration():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0142_group_background.py"
    spec = spec_from_file_location("group_background_migration", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("saved_key", [None, "branding/private/background.jpg"])
def test_downgrade_preserves_saved_background_references(saved_key):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE client_groups (id INTEGER PRIMARY KEY, background_image_key VARCHAR(512))"))
            connection.execute(text("INSERT INTO client_groups VALUES (1, :key)"), {"key": saved_key})
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                if saved_key:
                    with pytest.raises(RuntimeError, match="references must be preserved"):
                        migration().downgrade()
                    assert connection.scalar(text("SELECT background_image_key FROM client_groups")) == saved_key
                else:
                    migration().downgrade()
                    assert [column["name"] for column in inspect(connection).get_columns("client_groups")] == ["id"]
    finally:
        engine.dispose()
