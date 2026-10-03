"""Exact migration/source/authority bindings for the tracker retained release."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from release_manifest import verify_source_defaults
from release_mcp_contract import (
    require_same_schema_artifact,
    require_source_contract,
    source_contract,
    validate_contract,
)
from release_travel_tracker_contract import KIND, PATH, POLICY, SOURCE, TARGET

ROOT = Path(__file__).resolve().parents[1]


def helper():
    spec = importlib.util.spec_from_file_location(
        "tracker_upgrade_helper", ROOT / "backend/scripts/release_travel_tracker_upgrade.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TrackerContractTests(unittest.TestCase):
    def test_exact_single_migration_and_packaged_helper_policy(self):
        value = source_contract(ROOT)
        validate_contract(value, TARGET)
        verify_source_defaults()
        require_source_contract({"deployment": value}, ROOT)
        module = helper()
        module.verify_sources(ROOT / "backend", value)
        self.assertEqual(module.POLICY, POLICY)
        self.assertEqual(
            (value["kind"], value["source_schema"], value["target_schema"]), (KIND, SOURCE, TARGET)
        )
        self.assertEqual(len(value["migrations"]), 1)
        with self.assertRaises(ValueError):
            require_same_schema_artifact({"deployment": value})

    def test_authority_and_retention_cannot_be_relaxed(self):
        value = source_contract(ROOT)
        for field, changed in [
            ("version", True),
            ("existing_grants", "expand"),
            ("write_section_authority", "enable_all"),
            ("settings", "reset"),
            ("automatic_downgrade", True),
            ("new_tables", "populated"),
            ("historical_rows", "exclude_timestamps"),
            ("unknown", "ignored"),
        ]:
            revised = {**copy.deepcopy(value), field: changed}
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_contract(revised, TARGET)
            with self.subTest(helper_field=field), self.assertRaises(ValueError):
                helper().verify_sources(ROOT / "backend", revised)

    def test_source_hash_parent_path_and_file_mutation_rejected(self):
        value = source_contract(ROOT)
        for field, changed in [
            ("sha256", "0" * 64),
            ("path", "../../arbitrary.py"),
            ("parent", TARGET),
        ]:
            revised = copy.deepcopy(value)
            revised["migrations"][0][field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError):
                require_source_contract({"deployment": revised}, ROOT)
            with self.subTest(helper_field=field), self.assertRaises(ValueError):
                helper().verify_sources(ROOT / "backend", revised)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "backend/app/core/config/release_manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(
                    {
                        "deployment_kind": KIND,
                        "schema_revision": TARGET,
                        "previous_schema_revision": SOURCE,
                    }
                )
            )
            migration = root / PATH
            migration.parent.mkdir(parents=True)
            migration.write_bytes((ROOT / PATH).read_bytes() + b'\ndown_revision = "unreviewed"\n')
            with self.assertRaises(ValueError):
                source_contract(root)


if __name__ == "__main__":
    unittest.main()
