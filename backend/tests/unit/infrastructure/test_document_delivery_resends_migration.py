from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import UniqueConstraint

from app.infrastructure.database.models import DocumentWhatsAppDeliveryModel


def _load_migration():
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0064_document_delivery_resends.py"
    )
    spec = importlib.util.spec_from_file_location(
        "document_delivery_resends_migration",
        migration_path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"alembic": SimpleNamespace(op=MagicMock())}):
        spec.loader.exec_module(module)
    return module


def test_resend_migration_follows_qr_delivery_head_and_is_reversible() -> None:
    migration = _load_migration()
    assert migration.revision == "0064_document_resends"
    assert migration.down_revision == "0063_qr_whatsapp"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()
    operation_proxy.drop_constraint.assert_called_once_with(
        "uq_document_whatsapp_delivery_document",
        "document_whatsapp_deliveries",
        type_="unique",
    )
    assert operation_proxy.execute.call_count == 3

    operation_proxy.reset_mock()
    with patch.object(migration, "op", operation_proxy):
        migration.downgrade()
    operation_proxy.create_unique_constraint.assert_called_once_with(
        "uq_document_whatsapp_delivery_document",
        "document_whatsapp_deliveries",
        ["distributed_document_id"],
    )


def test_delivery_model_allows_multiple_audited_attempts_per_document() -> None:
    unique_column_sets = {
        tuple(column.name for column in constraint.columns)
        for constraint in DocumentWhatsAppDeliveryModel.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("distributed_document_id",) not in unique_column_sets
