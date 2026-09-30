"""Signed chain contracts are necessary evidence, never proof of a safe rollout."""

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from release_mcp_contract import (
    CHAIN,
    SOURCE,
    require_same_schema_artifact,
    require_source_contract,
    source_contract,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[1]


class MCPReleaseContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        relative = "backend/app/core/config/release_manifest.json"
        (self.root / relative).parent.mkdir(parents=True)
        (self.root / relative).write_text(json.dumps({"deployment_kind": "mcp_additive_v1",
            "previous_schema_revision": SOURCE, "schema_revision": CHAIN[-1]}))
        for revision in CHAIN:
            relative = f"backend/alembic/versions/{revision}.py"
            (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, self.root / relative)
        self.contract = source_contract(self.root)

    def test_candidate_binds_every_migration_source_and_disabled_forward_recovery(self):
        validate_contract(self.contract, CHAIN[-1])
        self.assertEqual([entry["revision"] for entry in self.contract["migrations"]], list(CHAIN))
        self.assertEqual(self.contract["source_schema"], SOURCE)
        require_source_contract({"deployment": self.contract}, self.root)
        with self.assertRaisesRegex(ValueError, "same-schema recovery is prohibited"):
            require_same_schema_artifact({"deployment": self.contract})
        require_same_schema_artifact({"schema": SOURCE})

    def test_missing_contract_or_changed_source_hash_cannot_promote(self):
        for deployment in (None, {}, copy.deepcopy(self.contract)):
            if deployment:
                deployment["migrations"][0]["sha256"] = "0" * 64
            with self.subTest(deployment=bool(deployment)), self.assertRaises(ValueError):
                require_source_contract({"deployment": deployment}, self.root)

    def test_signed_retention_policy_cannot_allow_recreation_cleanup_or_omission(self):
        for key in self.contract["retention"]:
            for value in ("delete", "recreate", "cleanup", False, None):
                contract = copy.deepcopy(self.contract)
                contract["retention"][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_contract(contract, CHAIN[-1])
        contract = copy.deepcopy(self.contract)
        del contract["retention"]
        with self.assertRaises(ValueError):
            validate_contract(contract, CHAIN[-1])

    def test_unknown_paths_skipped_reordered_chain_and_automatic_enable_are_rejected(self):
        for change in ("source", "target", "skip", "reorder", "path", "hash", "enable", "downgrade", "communication", "unknown"):
            contract = copy.deepcopy(self.contract)
            if change == "source": contract["source_schema"] = "0112_passport_cover_edits"
            if change == "target": contract["target_schema"] = SOURCE
            if change == "skip": contract["migrations"].pop()
            if change == "reorder": contract["migrations"].reverse()
            if change == "path": contract["migrations"][0]["path"] = "../../arbitrary.py"
            if change == "hash": contract["migrations"][0]["sha256"] = "z" * 64
            if change == "enable": contract["initial_mcp_enabled"] = True
            if change == "downgrade": contract["automatic_downgrade"] = True
            if change == "communication": contract["initial_allowed_capabilities"].append("mcp:communicate")
            if change == "unknown": contract["run_command"] = "arbitrary command"
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_contract(contract, CHAIN[-1])

    def test_migration_file_identity_and_source_release_are_checked_without_importing_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ["backend/app/core/config/release_manifest.json", *[entry["path"] for entry in self.contract["migrations"]]]:
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.root / relative, root / relative)
            self.assertEqual(source_contract(root), self.contract)
            path = root / self.contract["migrations"][0]["path"]
            original = path.read_text()
            path.write_text(original.replace(f'down_revision = "{SOURCE}"', 'down_revision = "other_source"'))
            with self.assertRaisesRegex(ValueError, "ancestry"):
                source_contract(root)
            path.write_text(original)
            path = root / "backend/app/core/config/release_manifest.json"
            manifest = json.loads(path.read_text())
            manifest["previous_schema_revision"] = CHAIN[-2]
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "exact reviewed source/target"):
                source_contract(root)


if __name__ == "__main__":
    unittest.main()
