"""Generate/import real revisions in isolated scriptdirs without an environment or DB."""

from __future__ import annotations

import hashlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import get_type_hints
from unittest.mock import patch

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

BACKEND = Path(__file__).resolve().parents[3]


def _published_hashes() -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (BACKEND / "alembic/versions").glob("*.py")
    }


class MigrationRevisionTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.published_before = _published_hashes()
        self.temporary = tempfile.TemporaryDirectory(prefix="dashboard-migration-template-")
        self.folder = Path(self.temporary.name).resolve()
        self.assertEqual(self.folder.parent, Path(tempfile.gettempdir()).resolve())
        self.assertTrue(self.folder.name.startswith("dashboard-migration-template-"))
        self.addCleanup(self.temporary.cleanup)
        (self.folder / "versions").mkdir()
        shutil.copyfile(BACKEND / "alembic/script.py.mako", self.folder / "script.py.mako")
        self.config = Config(stdout=io.StringIO())
        self.config.set_main_option("script_location", str(self.folder))
        self.config.set_main_option("revision_environment", "false")
        self.assertIsNone(self.config.get_main_option("sqlalchemy.url"))
        self.assertFalse((self.folder / "env.py").exists())
        guard = patch.object(
            ScriptDirectory,
            "run_env",
            side_effect=AssertionError("Template controls must never run an environment"),
        )
        self.environment = guard.start()
        self.addCleanup(guard.stop)

    def tearDown(self) -> None:
        self.environment.assert_not_called()
        self.assertEqual(_published_hashes(), self.published_before)

    def _revision(self, revision: str, **kwargs):
        result = command.revision(
            self.config,
            message=f"Synthetic {revision}",
            rev_id=revision,
            autogenerate=False,
            **kwargs,
        )
        self.assertIsNotNone(result)
        self.assertTrue(Path(result.path).resolve().is_relative_to(self.folder))
        self.assertEqual(result.module.revision, revision)
        self.assertIsNone(result.module.upgrade())
        self.assertIsNone(result.module.downgrade())
        return result

    def test_new_base_has_real_metadata_and_importable_noop_entrypoints(self) -> None:
        script = self._revision("0a1b2c3d4e5f", head="base")
        self.assertIsNone(script.down_revision)
        self.assertIsNone(script.module.branch_labels)
        self.assertIsNone(script.module.depends_on)
        self.assertEqual(get_type_hints(script.module)["revision"], str)
        source = Path(script.path).read_text(encoding="utf-8")
        self.assertNotIn("${", source)
        self.assertIn("Synthetic 0a1b2c3d4e5f", script.doc)

    def test_followup_revision_resolves_the_real_existing_parent(self) -> None:
        parent = self._revision("1a1b2c3d4e5f", head="base", branch_label="synthetic_main")
        child = self._revision("2a1b2c3d4e5f", head=parent.revision)
        self.assertEqual(child.down_revision, parent.revision)
        self.assertEqual(child.module.down_revision, parent.revision)
        self.assertEqual(parent.module.branch_labels, ("synthetic_main",))
        self.assertEqual(ScriptDirectory.from_config(self.config).get_heads(), [child.revision])

    def test_merge_retains_both_parent_edges_and_one_new_head(self) -> None:
        base = self._revision("3a1b2c3d4e5f", head="base")
        left = self._revision("4a1b2c3d4e5f", head=base.revision, branch_label="left")
        right = self._revision(
            "5a1b2c3d4e5f", head=base.revision, splice=True, branch_label="right"
        )
        merged = command.merge(
            self.config,
            revisions=(left.revision, right.revision),
            rev_id="6a1b2c3d4e5f",
            message="Synthetic merge",
        )
        self.assertEqual(merged.module.down_revision, (left.revision, right.revision))
        self.assertEqual(merged.down_revision, (left.revision, right.revision))
        self.assertIsNone(merged.module.upgrade())
        self.assertIsNone(merged.module.downgrade())
        self.assertEqual(ScriptDirectory.from_config(self.config).get_heads(), [merged.revision])

    def test_custom_imports_operations_dependency_and_branch_metadata_render(self) -> None:
        dependency = self._revision("7a1b2c3d4e5f", head="base", branch_label="dependency")
        scripts = ScriptDirectory.from_config(self.config)
        rendered = scripts.generate_revision(
            "8a1b2c3d4e5f",
            "Synthetic rendered body",
            head="base",
            branch_labels="rendered",
            depends_on=dependency.revision,
            imports="from decimal import Decimal",
            upgrades="op.add_column('synthetic_table', sa.Column('value', sa.Integer(), nullable=True))",
            downgrades="op.drop_column('synthetic_table', 'value')",
        )
        self.assertEqual(rendered.module.branch_labels, ("rendered",))
        self.assertEqual(rendered.module.depends_on, dependency.revision)
        self.assertEqual(rendered.module.Decimal("1.5") + 1, rendered.module.Decimal("2.5"))
        with patch.object(rendered.module.op, "add_column") as add:
            rendered.module.upgrade()
            add.assert_called_once()
            self.assertEqual(add.call_args.args[0], "synthetic_table")
            column = add.call_args.args[1]
            self.assertEqual(column.name, "value")
            self.assertIsInstance(column.type, sa.Integer)
            self.assertTrue(column.nullable)
        with patch.object(rendered.module.op, "drop_column") as drop:
            rendered.module.downgrade()
            drop.assert_called_once_with("synthetic_table", "value")


if __name__ == "__main__":
    unittest.main()
