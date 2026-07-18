from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class RelationQualifierMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        migration_path = (
            Path(__file__).resolve().parents[3]
            / "alembic"
            / "versions"
            / "0037_relation_with_qualifier.py"
        )
        spec = importlib.util.spec_from_file_location(
            "relation_qualifier_migration",
            migration_path,
        )
        if spec is None or spec.loader is None:
            raise AssertionError("Could not load qualifier migration")
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(
            sys.modules,
            {"alembic": SimpleNamespace(op=MagicMock())},
        ):
            spec.loader.exec_module(cls.module)

    def test_revision_follows_current_head(self) -> None:
        self.assertEqual(self.module.revision, "0037_relation_qualifier")
        self.assertEqual(self.module.down_revision, "0036_whatsapp_delivery")

    def test_upgrade_and_downgrade_construct_without_database_access(self) -> None:
        operation_proxy = MagicMock()
        with patch.object(self.module, "op", operation_proxy):
            self.module.upgrade()
        operation_proxy.create_table.assert_called_once()
        self.assertTrue(operation_proxy.add_column.called)
        self.assertTrue(operation_proxy.create_check_constraint.called)
        operation_proxy.create_foreign_key.assert_called_once_with(
            "fk_passport_submissions_qualifier_selection",
            "passport_submissions",
            "qualifier_selections",
            ["qualifier_selection_id", "group_id"],
            ["id", "group_id"],
            ondelete="RESTRICT",
        )

        operation_proxy.reset_mock()
        with patch.object(self.module, "op", operation_proxy):
            self.module.downgrade()
        operation_proxy.drop_table.assert_called_once_with(
            "qualifier_selections"
        )
        self.assertTrue(operation_proxy.drop_column.called)


if __name__ == "__main__":
    unittest.main()
