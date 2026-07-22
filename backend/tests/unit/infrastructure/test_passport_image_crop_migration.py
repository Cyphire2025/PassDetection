from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _load_migration(filename: str = "0044_passport_image_crops.py"):
    migration_path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / filename
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


def test_image_edit_migration_is_additive_and_follows_current_head() -> None:
    migration = _load_migration("0047_passport_image_edits.py")
    assert migration.revision == "0047_passport_image_edits"
    assert migration.down_revision == "0046_agent_employee_code"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    assert operation_proxy.add_column.call_count == 2
    operation_proxy.create_check_constraint.assert_called_once_with(
        "ck_passport_image_crops_sharpness",
        "passport_image_crops",
        "sharpness >= 1.0 AND sharpness <= 3.0",
    )
    operation_proxy.drop_table.assert_not_called()


def test_visa_ai_library_migration_is_additive_and_preserves_existing_edits() -> None:
    migration = _load_migration("0048_visa_ai_image_library.py")
    assert migration.revision == "0048_visa_ai_image_library"
    assert migration.down_revision == "0047_passport_image_edits"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    operation_proxy.add_column.assert_called_once()
    operation_proxy.create_check_constraint.assert_called_once_with(
        "ck_passport_image_crops_sharpness_algorithm_version",
        "passport_image_crops",
        "sharpness_algorithm_version IN (1, 2)",
    )
    operation_proxy.create_table.assert_called_once()
    assert operation_proxy.create_index.call_count == 3
    operation_proxy.drop_table.assert_not_called()
