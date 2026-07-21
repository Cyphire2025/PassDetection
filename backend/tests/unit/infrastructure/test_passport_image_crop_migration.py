from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _load_migration():
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0044_passport_image_crops.py"
    )
    spec = importlib.util.spec_from_file_location("passport_image_crop_migration", migration_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"alembic": SimpleNamespace(op=MagicMock())}):
        spec.loader.exec_module(module)
    return module


def test_crop_migration_is_additive_and_follows_current_head() -> None:
    migration = _load_migration()
    assert migration.revision == "0044_passport_image_crops"
    assert migration.down_revision == "0043_rejected_imported_fields"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()
    operation_proxy.create_table.assert_called_once()
    operation_proxy.create_index.assert_called_once()
    assert not operation_proxy.drop_table.called


def test_crop_migration_is_reversible_without_touching_submission_images() -> None:
    migration = _load_migration()
    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.downgrade()
    operation_proxy.drop_index.assert_called_once()
    operation_proxy.drop_table.assert_called_once_with("passport_image_crops")
