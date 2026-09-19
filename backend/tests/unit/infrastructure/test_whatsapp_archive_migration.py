from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.infrastructure.database.models import WhatsAppBroadcastGroupModel


def test_archive_migration_adds_nullable_timestamp_and_agency_index():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0100_whatsapp_group_archive.py"
    spec = importlib.util.spec_from_file_location("whatsapp_archive", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with patch.object(module, "op", Operations(context)):
        module.upgrade()
    assert module.down_revision == "0099_gc_group_access_removal"
    assert "ADD COLUMN archived_at TIMESTAMP WITH TIME ZONE" in output.getvalue()
    assert "(agency_id, archived_at, created_at)" in output.getvalue()
    assert WhatsAppBroadcastGroupModel.__table__.c.archived_at.nullable is True
