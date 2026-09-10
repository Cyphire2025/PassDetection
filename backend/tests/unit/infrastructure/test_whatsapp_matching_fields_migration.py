from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportVisaAiImageModel,
    WhatsAppBroadcastGroupModel,
)


def _migration():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0092_whatsapp_matching_fields.py"
    spec = importlib.util.spec_from_file_location("whatsapp_matching_fields", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_matching_fields_columns_belong_to_the_expected_models() -> None:
    assert "imported_field_keys" in WhatsAppBroadcastGroupModel.__table__.c
    assert "matching_field_keys" in ClientGroupWhatsAppBroadcastLinkModel.__table__.c
    assert "matching_field_keys" not in PassportVisaAiImageModel.__table__.c
    assert ClientGroupWhatsAppBroadcastLinkModel.__table__.c.matching_field_keys.nullable is True


def test_whatsapp_matching_fields_upgrade_has_default_and_backfill() -> None:
    module = _migration()
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with patch.object(module, "op", Operations(context)):
        module.upgrade()
    ddl = output.getvalue()

    assert module.down_revision == "0091_qualifier_other_relation"
    assert "ADD COLUMN imported_field_keys JSONB DEFAULT '[]'::jsonb NOT NULL" in ddl
    assert "ADD COLUMN matching_field_keys JSONB" in ddl
    assert "UPDATE whatsapp_broadcast_groups AS groups" in ddl
    assert "jsonb_typeof(recipients.imported_fields) = 'object'" in ddl
    assert "jsonb_typeof(rejected.imported_fields) = 'object'" in ddl
    assert "DROP DEFAULT" not in ddl
