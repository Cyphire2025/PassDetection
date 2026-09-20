"""Nullable template languages preserve existing snapshots during upgrade."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_language_migration_keeps_old_messages_and_accepts_saved_english():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0103_whatsapp_template_language.py"
    spec = importlib.util.spec_from_file_location("whatsapp_language_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE whatsapp_message_logs (id INTEGER PRIMARY KEY, template_name TEXT)")
        connection.exec_driver_sql("INSERT INTO whatsapp_message_logs VALUES (1, 'existing_template')")
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
        assert connection.exec_driver_sql("SELECT template_name, template_language FROM whatsapp_message_logs WHERE id=1").one() == ("existing_template", None)
        connection.exec_driver_sql("INSERT INTO whatsapp_message_logs VALUES (2, 'whatsapp_group_invite_v1', 'en')")
        assert connection.exec_driver_sql("SELECT template_language FROM whatsapp_message_logs WHERE id=2").scalar_one() == "en"
    engine.dispose()
