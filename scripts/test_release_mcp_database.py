"""Retained backup and exact migration requests cannot bypass fence/source proofs."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release_mcp_contract import CHAIN, SOURCE, source_contract
from release_mcp_database import DUMP_COMMAND, MCPDatabaseRelease, ReleaseBindings
from release_traveller_whatsapp import ReleaseError

ROOT = Path(__file__).resolve().parents[1]


class DatabaseReleaseTests(unittest.TestCase):
    def setUp(self):
        legacy = tempfile.TemporaryDirectory()
        self.addCleanup(legacy.cleanup)
        self.legacy_root = Path(legacy.name)
        relative = "backend/app/core/config/release_manifest.json"
        (self.legacy_root / relative).parent.mkdir(parents=True)
        (self.legacy_root / relative).write_text(json.dumps({"deployment_kind": "mcp_additive_v1",
            "previous_schema_revision": SOURCE, "schema_revision": CHAIN[-1]}))
        for revision in CHAIN:
            relative = f"backend/alembic/versions/{revision}.py"
            (self.legacy_root / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, self.legacy_root / relative)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.directory.chmod(0o700)
        self.bindings = ReleaseBindings(
            "a" * 40, "sha256:" + "b" * 64, "c" * 64, "d" * 64
        )
        self.schema, self.fenced, self.fence_checks = SOURCE, True, 0
        self.commands, self.failure = [], None
        self.release = MCPDatabaseRelease(
            self.legacy_root,
            self.directory,
            self.bindings,
            database_command=self.command,
            verify_fence=self.fence,
            read_schema=lambda: self.schema,
        )

    def fence(self):
        self.fence_checks += 1
        if not self.fenced:
            raise ReleaseError("writers_are_not_fenced")

    def command(self, arguments, *, timeout, stdin_file=None, stdout_file=None):
        self.commands.append(arguments)
        if arguments == ("sh", "-c", DUMP_COMMAND):
            stdout_file.write(b"PGDMPsynthetic-retained-archive")
            if self.failure == "dump":
                raise RuntimeError("SECRET_DATABASE_PASSWORD")
            if self.failure == "unfence":
                self.fenced = False
            return ""
        self.assertIsNotNone(stdin_file)
        self.assertTrue(stdin_file.read().startswith(b"PGDMP"))
        if arguments == ("pg_restore", "--list"):
            return (
                "TABLE DATA public alembic_version\nTABLE DATA public agencies"
                if self.failure != "toc"
                else "invalid archive"
            )
        self.assertEqual(arguments, ("pg_restore", "--file=/dev/null"))
        if self.failure == "decode":
            raise RuntimeError("SECRET_DATABASE_ROW")
        return ""

    def test_verified_backup_is_exclusive_bound_and_decoded_before_migration_plan(self):
        # Named /dev/stdout causes pg_dump to fsync Docker's non-seekable pipe.
        # Its default stdout mode delegates durability to backup() on the host.
        dump_arguments = shlex.split(DUMP_COMMAND.split("exec pg_dump ", 1)[1])
        self.assertFalse(
            any(value == "-f" or value.startswith("--file") for value in dump_arguments)
        )
        self.assertIn("--format=custom", dump_arguments)
        backup = self.release.backup()
        archive = self.release.verify_backup(backup)
        self.assertEqual(archive.read_bytes(), b"PGDMPsynthetic-retained-archive")
        self.assertEqual(len(list(self.directory.iterdir())), 2)
        self.assertGreaterEqual(self.fence_checks, 3)
        request = self.release.migration_request(backup)
        self.assertEqual(request["image_id"], self.bindings.image_id)
        self.assertTrue(request["retain_helper_container"])
        self.assertFalse(request["automatic_downgrade"])
        self.assertIn("lock_timeout=5000", request["environment"]["PGOPTIONS"])
        self.assertIn("statement_timeout=120000", request["environment"]["PGOPTIONS"])
        self.assertEqual(json.loads(request["arguments"][-1]), source_contract(self.legacy_root))
        self.assertFalse(request["already_at_target"])
        if os.name == "posix":
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    def test_partial_or_invalid_backup_is_retained_and_never_has_success_receipt(self):
        for failure in ("dump", "toc", "decode"):
            with self.subTest(failure=failure):
                self.failure = failure
                with self.assertRaises(ReleaseError) as error:
                    self.release.backup()
                self.assertNotIn("SECRET", str(error.exception))
        self.assertEqual(len(list(self.directory.glob("*.pgdump"))), 3)
        self.assertEqual(list(self.directory.glob("*.json")), [])

    def test_unfenced_before_backup_performs_no_command_or_file_creation(self):
        self.fenced = False
        with self.assertRaises(ReleaseError):
            self.release.backup()
        self.assertEqual(self.commands, [])
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_lost_fence_after_dump_prevents_decode_and_migration(self):
        self.failure = "unfence"
        with self.assertRaises(ReleaseError):
            self.release.backup()
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(len(list(self.directory.glob("*.pgdump"))), 1)

    def test_target_retry_requires_original_archive_and_exact_receipt(self):
        backup = self.release.backup()
        self.schema = CHAIN[-1]
        self.assertTrue(self.release.migration_request(backup)["already_at_target"])
        self.release.verify_target(backup)
        path = self.directory / backup["filename"]
        path.write_bytes(b"PGDMPchanged")
        with self.assertRaises(ReleaseError):
            self.release.migration_request(backup)

    def test_backup_binding_unknown_schema_source_drift_and_missing_receipt_rejected(
        self,
    ):
        backup = self.release.backup()
        changed = copy.deepcopy(backup)
        changed["bindings"]["database_binding_sha256"] = "0" * 64
        with self.assertRaises(ReleaseError):
            self.release.migration_request(changed)
        self.schema = CHAIN[2]
        with self.assertRaises(ReleaseError):
            self.release.migration_request(backup)
        self.schema = SOURCE
        with (
            patch("release_mcp_database.source_contract", return_value={}),
            self.assertRaises(ReleaseError),
        ):
            self.release.migration_request(backup)
        receipt = self.directory / (backup["filename"] + ".json")
        receipt.rename(self.directory / "retained-original-receipt.json")
        with self.assertRaises(ReleaseError):
            self.release.migration_request(backup)

    def test_exclusive_receipt_never_overwrites_existing_evidence(self):
        backup = self.release.backup()
        before = (self.directory / (backup["filename"] + ".json")).read_bytes()
        with self.assertRaises(FileExistsError):
            self.release.write_receipt(backup["filename"] + ".json", {})
        self.assertEqual(
            (self.directory / (backup["filename"] + ".json")).read_bytes(), before
        )

    def test_malformed_or_nonprivate_receipt_has_only_a_static_failure(self):
        backup = self.release.backup()
        receipt = self.directory / (backup["filename"] + ".json")
        original = receipt.read_bytes()
        for invalid in (b"SECRET raw exception text", b"\xff\xfe", b""):
            receipt.write_bytes(invalid)
            with self.assertRaises(ReleaseError) as error:
                self.release.migration_request(backup)
            self.assertEqual(
                str(error.exception),
                "The original exclusive backup receipt is required",
            )
        receipt.write_bytes(original)
        if os.name == "posix":
            receipt.chmod(0o644)
            with self.assertRaises(ReleaseError):
                self.release.migration_request(backup)

    def test_in_image_source_validation_matches_reviewed_chain_and_rejects_mutations(
        self,
    ):
        spec = importlib.util.spec_from_file_location(
            "mcp_apply_test", ROOT / "backend/scripts/apply_mcp_additive_upgrade.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        contract = source_contract(self.legacy_root)
        module.verify_sources(ROOT / "backend", contract)
        for mutation in ("hash", "order", "parent", "enable", "cleanup", "unknown"):
            changed = copy.deepcopy(contract)
            if mutation == "hash":
                changed["migrations"][0]["sha256"] = "0" * 64
            if mutation == "order":
                changed["migrations"].reverse()
            if mutation == "parent":
                changed["migrations"][0]["parent"] = CHAIN[-1]
            if mutation == "enable":
                changed["initial_mcp_enabled"] = True
            if mutation == "cleanup":
                changed["retention"]["cleanup"] = "allowed"
            if mutation == "unknown":
                changed["arbitrary_command"] = "forbidden"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                module.verify_sources(ROOT / "backend", changed)


if __name__ == "__main__":
    unittest.main()
