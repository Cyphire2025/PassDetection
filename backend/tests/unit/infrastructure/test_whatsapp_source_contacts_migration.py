"""Upgrade retains delivery history and enables only existing import-only source links."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_source_migration_preserves_existing_rows_and_scopes_backfill_flags():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0104_whatsapp_source_contacts.py"
    spec = importlib.util.spec_from_file_location("whatsapp_source_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE client_groups (id TEXT PRIMARY KEY, agency_id TEXT, import_only BOOLEAN)")
        connection.exec_driver_sql("CREATE TABLE client_group_whatsapp_broadcast_links (id TEXT PRIMARY KEY, agency_id TEXT, client_group_id TEXT)")
        connection.exec_driver_sql("CREATE TABLE whatsapp_broadcast_recipients (id TEXT PRIMARY KEY, name TEXT)")
        connection.exec_driver_sql("INSERT INTO client_groups VALUES ('import', 'agency', 1), ('normal', 'agency', 0)")
        connection.exec_driver_sql("INSERT INTO client_group_whatsapp_broadcast_links VALUES ('one', 'agency', 'import'), ('two', 'agency', 'normal'), ('foreign', 'other', 'import')")
        connection.exec_driver_sql("INSERT INTO whatsapp_broadcast_recipients VALUES ('existing', 'Historical contact')")
        # SQLite exercises the data upgrade; PostgreSQL-specific JSONB storage
        # is replaced only for this isolated migration operation.
        with patch.object(migration.postgresql, "JSONB", sa.JSON), patch.object(
            migration, "op", Operations(MigrationContext.configure(connection)),
        ):
            migration.upgrade()
        assert dict(connection.exec_driver_sql(
            "SELECT id, sync_contacts_from_group FROM client_group_whatsapp_broadcast_links"
        ).all()) == {"one": 1, "two": 0, "foreign": 0}
        assert connection.exec_driver_sql(
            "SELECT name, is_source_managed FROM whatsapp_broadcast_recipients"
        ).one() == ("Historical contact", 0)
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM whatsapp_broadcast_source_contacts").scalar_one() == 0
        inspector = sa.inspect(connection)
        assert {index["name"] for index in inspector.get_indexes("whatsapp_broadcast_source_contacts")} == {
            "ix_whatsapp_source_contacts_agency_source", "ix_whatsapp_source_contacts_broadcast",
            "ix_whatsapp_source_contacts_recipient", "ix_whatsapp_source_contacts_submission",
        }
    engine.dispose()
