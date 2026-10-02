"""Bind the new source without granting any historical executor authority."""

import copy
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from release_manifest import load_release_manifest, verify_source_defaults
from release_mcp_contract import (
    require_same_schema_artifact,
    require_source_contract,
    source_contract,
    validate_contract,
)
from release_mcp_database import MCPDatabaseRelease, ReleaseBindings
from release_mcp_direct_devices_contract import KIND, PATH, SOURCE, TARGET
from release_mcp_read_only_contract import (
    source_contract as historical_read_only_source,
)
from release_mcp_read_only_contract import (
    validate_contract as validate_historical_read_only,
)
from release_traveller_whatsapp import ReleaseError

ROOT = Path(__file__).resolve().parents[1]


class DirectDeviceContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = source_contract(ROOT)

    def test_current_manifest_and_defaults_bind_exact_one_migration(self):
        manifest = load_release_manifest()
        self.assertEqual((manifest["deployment_kind"], manifest["previous_schema_revision"],
                          manifest["schema_revision"]), (KIND, SOURCE, TARGET))
        self.assertEqual(manifest["worker_nodes"], {
            "worker": "general", "email-worker": "email", "email-ai-worker": "email-ai",
            "extraction-worker": "extraction", "verification-worker": "verification",
            "visa-ai-worker": "visa-ai", "my-photos-worker": "my-photos", "ecr-worker": "ecr",
        })
        verify_source_defaults()
        validate_contract(self.contract, TARGET)
        require_source_contract({"deployment": self.contract}, ROOT)
        self.assertEqual(self.contract["migrations"], [{
            "revision": TARGET, "parent": SOURCE, "path": PATH,
            "sha256": hashlib.sha256((ROOT / PATH).read_bytes()).hexdigest(),
        }])

    def test_policy_changes_cannot_expand_authority_or_discard_state(self):
        changes = {
            "version": True,
            "kind": "mcp_read_only_v1",
            "read_only_mode": False,
            "allowed_capabilities": ["mcp:read", "mcp:export"],
            "control_enabled": True,
            "existing_grants": "expand",
            "read_section_authority": "reset",
            "connection_enabled": "reset",
            "automatic_downgrade": True,
            "retention": {**self.contract["retention"], "cleanup": "permitted"},
            "target_schema": SOURCE,
            "source_schema": "0122_mcp_gc_push",
            "migrations": [],
            "unknown": "arbitrary command",
        }
        for key, value in changes.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_contract({**copy.deepcopy(self.contract), key: value}, TARGET)
        with self.assertRaises(ValueError):
            validate_contract(self.contract, SOURCE)

    def test_changed_migration_hash_or_path_cannot_match_source(self):
        for field, value in (("sha256", "0" * 64), ("path", "../../arbitrary.py"),
                             ("parent", "0122_mcp_gc_push")):
            changed = copy.deepcopy(self.contract)
            changed["migrations"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                require_source_contract({"deployment": changed}, ROOT)

    def test_changed_manifest_or_migration_identity_cannot_generate_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "backend/app/core/config/release_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            migration = root / PATH
            migration.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / PATH, migration)
            original_manifest = load_release_manifest()
            for key, value in (("previous_schema_revision", "0122_mcp_gc_push"),
                               ("schema_revision", SOURCE), ("deployment_kind", "unknown")):
                manifest_path.write_text(json.dumps({**original_manifest, key: value}), "utf-8")
                with self.subTest(key=key), self.assertRaises(ValueError):
                    source_contract(root)
            manifest_path.write_text(json.dumps(original_manifest), "utf-8")
            migration.write_text((ROOT / PATH).read_text("utf-8") +
                                 '\ndown_revision = "0122_mcp_gc_push"\n', "utf-8")
            with self.assertRaises(ValueError):
                source_contract(root)

    def test_historical_guards_refuse_new_release_contract(self):
        with self.assertRaises(ValueError):
            historical_read_only_source(ROOT)
        with self.assertRaises(ValueError):
            validate_historical_read_only(self.contract, TARGET)
        with self.assertRaises(ValueError):
            require_same_schema_artifact({"deployment": self.contract})
        for filename in ("apply_mcp_read_only_upgrade.py", "apply_mcp_additive_upgrade.py"):
            spec = importlib.util.spec_from_file_location(
                "historical_" + filename.removesuffix(".py"), ROOT / "backend/scripts" / filename
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with self.subTest(helper=filename), self.assertRaises(ValueError):
                module.verify_sources(ROOT / "backend", self.contract)

    def test_existing_database_planner_refuses_before_any_command_or_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            commands, fences, reads = [], [], []
            with self.assertRaisesRegex(ReleaseError, "separately qualified migration executor"):
                MCPDatabaseRelease(
                    ROOT, Path(temporary).resolve(),
                    ReleaseBindings("a" * 40, "sha256:" + "b" * 64, "c" * 64, "d" * 64),
                    database_command=lambda *args, **kwargs: commands.append(args),
                    verify_fence=lambda: fences.append(True),
                    read_schema=lambda: reads.append(True),
                )
            self.assertEqual((commands, fences, reads), ([], [], []))
            self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
