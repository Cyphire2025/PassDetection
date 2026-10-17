"""Signed image metadata and database planning remain bound to this exact change."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from release_document_distribution_contract import CHAIN, SOURCE, TARGET
from legacy_document_contract_fixture import document_source
from release_mcp_contract import require_same_schema_artifact, require_source_contract, source_contract, validate_contract
from release_mcp_database import DUMP_COMMAND, MCPDatabaseRelease, ReleaseBindings
from release_traveller_whatsapp import ReleaseError

ROOT = Path(__file__).resolve().parents[1]


class DocumentReleaseContractTests(unittest.TestCase):
    def setUp(self):
        fixture = document_source()
        self.source = fixture.__enter__()
        self.addCleanup(fixture.__exit__, None, None, None)

    def test_active_source_is_bound_to_the_two_nullable_additions(self):
        value = source_contract(self.source)
        self.assertEqual(value["kind"], "document_distribution_updates_v1")
        self.assertEqual(value["source_schema"], SOURCE)
        self.assertEqual([row["revision"] for row in value["migrations"]], list(CHAIN))
        validate_contract(value, TARGET)
        require_source_contract({"deployment": value}, self.source)
        with self.assertRaises(ValueError):
            require_same_schema_artifact({"deployment": value})
        changed = copy.deepcopy(value)
        changed["migrations"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            require_source_contract({"deployment": changed}, self.source)

    def test_downgrade_identity_history_and_resume_rules_cannot_be_relaxed(self):
        value = source_contract(self.source)
        for field, replacement in (("version", True), ("automatic_downgrade", True),
            ("identity_and_delivery_history", "rewrite"), ("new_column_values", "backfill"),
            ("resume_schema_revisions", [SOURCE]), ("extra", "ignored")):
            changed = {**copy.deepcopy(value), field: replacement}
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_contract(changed, TARGET)

    def test_intermediate_resume_keeps_original_backup_and_requires_writer_fence(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            directory.chmod(0o700)
            state, fenced = [SOURCE], [True]

            def fence():
                if not fenced[0]:
                    raise ReleaseError("not_fenced")

            def command(arguments, *, timeout, stdin_file=None, stdout_file=None):
                if arguments == ("sh", "-c", DUMP_COMMAND):
                    stdout_file.write(b"PGDMPsynthetic-document-backup")
                return "TABLE DATA public alembic_version" if arguments == ("pg_restore", "--list") else ""

            release = MCPDatabaseRelease(self.source, directory,
                ReleaseBindings("a" * 40, "sha256:" + "b" * 64, "c" * 64, "d" * 64),
                database_command=command, verify_fence=fence, read_schema=lambda: state[0])
            backup = release.backup()
            for revision in CHAIN:
                state[0] = revision
                plan = release.migration_request(backup)
                self.assertEqual(plan["arguments"][1], "scripts/release_document_distribution_upgrade.py")
                self.assertEqual(plan["proof"]["backup_schema"], SOURCE)
                self.assertFalse(plan["automatic_downgrade"])
            with self.assertRaises(ReleaseError):
                release.backup()
            fenced[0] = False
            with self.assertRaises(ReleaseError):
                release.migration_request(backup)


if __name__ == "__main__":
    unittest.main()
