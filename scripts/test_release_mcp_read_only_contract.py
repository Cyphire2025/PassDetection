import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from release_mcp_contract import (
    require_same_schema_artifact,
    require_source_contract,
    source_contract,
    validate_contract,
)
from release_mcp_database import DUMP_COMMAND, MCPDatabaseRelease, ReleaseBindings
from release_mcp_read_only_contract import SOURCE, TARGET
from release_traveller_whatsapp import ReleaseError

ROOT = Path(__file__).resolve().parents[1]


class ReadOnlyContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = source_contract(ROOT)

    def test_current_source_binds_one_additive_migration_and_denies_same_schema_executor(
        self,
    ):
        validate_contract(self.contract, TARGET)
        require_source_contract({"deployment": self.contract}, ROOT)
        self.assertEqual(self.contract["source_schema"], SOURCE)
        self.assertEqual(len(self.contract["migrations"]), 1)
        with self.assertRaises(ValueError):
            require_same_schema_artifact({"deployment": self.contract})

    def test_no_contract_can_enable_writes_expand_grants_downgrade_or_cleanup(self):
        changes = {
            "read_only_mode": False,
            "allowed_capabilities": ["mcp:read", "mcp:export"],
            "control_enabled": True,
            "existing_grants": "expand",
            "automatic_downgrade": True,
            "retention": {**self.contract["retention"], "cleanup": "permitted"},
            "target_schema": SOURCE,
            "source_schema": "0113_document_follow_up",
            "migrations": [],
        }
        for key, value in changes.items():
            with self.subTest(key=key):
                changed = {**copy.deepcopy(self.contract), key: value}
                with self.assertRaises(ValueError):
                    validate_contract(changed, TARGET)

    def test_changed_migration_hash_or_unknown_policy_cannot_match_source(self):
        for field in ("hash", "unknown"):
            changed = copy.deepcopy(self.contract)
            if field == "hash":
                changed["migrations"][0]["sha256"] = "0" * 64
            else:
                changed["run_command"] = "arbitrary shell"
            with self.subTest(field=field), self.assertRaises(ValueError):
                require_source_contract({"deployment": changed}, ROOT)

    def test_wrong_schema_and_migration_path_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_contract(self.contract, SOURCE)
        value = copy.deepcopy(self.contract)
        value["migrations"][0]["path"] = "../../arbitrary.py"
        with self.assertRaises(ValueError):
            validate_contract(value, TARGET)

    def test_read_only_database_plan_uses_original_backup_and_dedicated_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            current = [SOURCE]
            checks, commands = [], []

            def fence():
                checks.append(True)

            def command(arguments, *, timeout, stdin_file=None, stdout_file=None):
                commands.append(arguments)
                if arguments == ("sh", "-c", DUMP_COMMAND):
                    stdout_file.write(b"PGDMPsynthetic-read-only-backup")
                    return ""
                self.assertTrue(stdin_file.read().startswith(b"PGDMP"))
                return (
                    "TABLE DATA public alembic_version"
                    if arguments == ("pg_restore", "--list")
                    else ""
                )

            release = MCPDatabaseRelease(
                ROOT,
                directory,
                ReleaseBindings("a" * 40, "sha256:" + "b" * 64, "c" * 64, "d" * 64),
                database_command=command,
                verify_fence=fence,
                read_schema=lambda: current[0],
            )
            backup = release.backup()
            self.assertEqual(backup["schema"], SOURCE)
            request = release.migration_request(backup)
            self.assertEqual(
                request["arguments"][1], "scripts/apply_mcp_read_only_upgrade.py"
            )
            self.assertEqual(json.loads(request["arguments"][-1]), self.contract)
            self.assertTrue(request["retain_helper_container"])
            self.assertFalse(request["automatic_downgrade"])
            self.assertFalse(request["already_at_target"])
            current[0] = TARGET
            self.assertTrue(release.migration_request(backup)["already_at_target"])
            release.verify_target(backup)
            self.assertGreaterEqual(len(checks), 5)
            self.assertEqual(len(list(directory.iterdir())), 2)

    def test_read_only_backup_cannot_begin_without_live_writer_fence(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            commands = []

            def fence():
                raise ReleaseError("writers_are_not_fenced")

            release = MCPDatabaseRelease(
                ROOT,
                directory,
                ReleaseBindings("a" * 40, "sha256:" + "b" * 64, "c" * 64, "d" * 64),
                database_command=lambda *args, **kwargs: commands.append(args),
                verify_fence=fence,
                read_schema=lambda: SOURCE,
            )
            with self.assertRaises(ReleaseError):
                release.backup()
            self.assertEqual(commands, [])
            self.assertEqual(list(directory.iterdir()), [])

    def test_in_image_helper_rejects_export_authority_and_changed_source(self):
        spec = importlib.util.spec_from_file_location(
            "read_only_upgrade_test",
            ROOT / "backend/scripts/apply_mcp_read_only_upgrade.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.verify_sources(ROOT / "backend", self.contract)
        for field in ("capability", "hash", "path", "enable", "unknown"):
            changed = copy.deepcopy(self.contract)
            if field == "capability":
                changed["allowed_capabilities"].append("mcp:export")
            if field == "hash":
                changed["migrations"][0]["sha256"] = "0" * 64
            if field == "path":
                changed["migrations"][0]["path"] = "../../arbitrary.py"
            if field == "enable":
                changed["control_enabled"] = True
            if field == "unknown":
                changed["run_command"] = "arbitrary"
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.verify_sources(ROOT / "backend", changed)


if __name__ == "__main__":
    unittest.main()
