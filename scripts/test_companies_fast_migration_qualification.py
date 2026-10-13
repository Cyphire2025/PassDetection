"""Fail-closed evidence, image binding, resource admission and isolated-client guards."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qa import bounded_qualification_output as bounded
from qa import companies_fast_migration_receipt as receipt
from qa import postgresql_client_fixture as clients
from qa import qualify_companies_fast_migration as qualification


def inner():
    common = {"source_schema": receipt.SOURCE, "target_schema": receipt.TARGET,
              "automatic_downgrade": False, "preservation_sha256": "a" * 64}
    return {"version": 1, "source_revision": receipt.SOURCE, "target_revision": receipt.TARGET,
        "server_major": 16, "production_release_authorization": False,
        "preserved_historical_rows_catalog_acl": True, "new_tables_empty_before_activation": True,
        "runtime_grants_nonempty": True, "wrong_baseline_rejected_before_ddl": True,
        "invalid_concurrent_index_repaired": True,
        "historical_row_counts": {"whatsapp_broadcast_rejected_contacts": 699, "whatsapp_broadcast_recipients": 1},
        "dump": {"bytes": 120000, "sha256": "b" * 64},
        "backup_clients": {key: key + " (PostgreSQL) 16.15 (Debian fixture)" for key in ("pg_dump", "pg_restore")},
        "original_preservation_baseline": {**common, "status": "baseline_captured"},
        "interruption": {"exit_code": 73, "interrupted_before": receipt.CHAIN[2]},
        "resume": {**common, "status": "upgraded", "started_schema": receipt.CHAIN[1],
                   "executed_revisions": list(receipt.CHAIN[2:]), "new_tables_empty": True, "runtime_grants_verified": True},
        "noop": {**common, "status": "already_at_target", "started_schema": receipt.TARGET,
                 "executed_revisions": [], "new_tables_empty": True, "runtime_grants_verified": True}}


def encoded(value=None, contract="c" * 64):
    return receipt.MARKER + json.dumps({"source_contract_sha256": contract, "rehearsal": value or inner()})


def result(output="", code=0):
    return subprocess.CompletedProcess(["docker"], code, output, "")


class MigrationReceiptTests(unittest.TestCase):
    def test_complete_receipt_preserves_exact_scope_and_derives_only_verified_checks(self):
        proof = receipt.validate_inner("synthetic migration log\n" + encoded(), "c" * 64)
        self.assertEqual(proof["fixture_person_count"], 700)
        self.assertEqual(proof["checks"], dict.fromkeys(receipt.CHECKS, True))

    def test_wrong_source_duplicate_or_missing_receipt_is_rejected(self):
        for output in ("migration exited zero", encoded(contract="d" * 64), encoded() + "\n" + encoded(),
                       receipt.MARKER + "x" * 65536):
            with self.subTest(output=output[:40]), self.assertRaises(ValueError):
                receipt.validate_inner(output, "c" * 64)

    def test_each_missing_or_false_positive_condition_is_rejected(self):
        changes = [("preserved_historical_rows_catalog_acl", False), ("runtime_grants_nonempty", 1),
                   ("invalid_concurrent_index_repaired", False), ("wrong_baseline_rejected_before_ddl", False),
                   ("server_major", 17), ("production_release_authorization", True),
                   ("historical_row_counts", {"whatsapp_broadcast_rejected_contacts": 500, "whatsapp_broadcast_recipients": 1}),
                   ("dump", {"bytes": 0, "sha256": "b" * 64}),
                   ("interruption", {"exit_code": 0, "interrupted_before": receipt.CHAIN[2]})]
        for key, value in changes:
            with self.subTest(key=key), self.assertRaises(ValueError):
                receipt.validate_inner(encoded({**inner(), key: value}), "c" * 64)

    def test_stale_baseline_partial_resume_or_skipped_grants_are_rejected(self):
        for phase, key, value in (("resume", "preservation_sha256", "d" * 64),
                                  ("resume", "executed_revisions", [receipt.CHAIN[-1]]),
                                  ("resume", "runtime_grants_verified", False),
                                  ("noop", "executed_revisions", [receipt.CHAIN[-1]])):
            evidence = copy.deepcopy(inner())
            evidence[phase][key] = value
            with self.subTest(phase=phase, key=key), self.assertRaises(ValueError):
                receipt.validate_inner(encoded(evidence), "c" * 64)


class IsolatedMigrationTests(unittest.TestCase):
    def test_success_requires_contact_proof_and_cleanup_before_outer_receipt(self):
        proof = receipt.validate_inner(encoded(), "c" * 64)
        for contact in ({"contact_concurrency_tests": 2, "contact_concurrency_verified": True},
                        {"contact_concurrency_tests": 2, "contact_concurrency_verified": False}):
            with (self.subTest(contact=contact),
                  patch.object(qualification, "inspect_image", return_value="sha256:" + "a" * 64),
                  patch.object(qualification, "admit_memory", return_value={}),
                  patch.object(qualification, "run", return_value=result()),
                  patch.object(qualification, "extract_clients", return_value={}),
                  patch.object(qualification, "create_database", return_value="b" * 64),
                  patch.object(qualification, "run_rehearsal", return_value=copy.deepcopy(proof)),
                  patch("qa.companies_contact_qualification.run_contact_tests", return_value=contact) as tests,
                  patch.object(qualification, "remove_owned") as cleanup):
                if not contact["contact_concurrency_verified"]:
                    with self.assertRaisesRegex(qualification.QualificationError, "targeted contact"):
                        qualification.qualify("sha256:" + "a" * 64, "a" * 40)
                else:
                    value = qualification.qualify("sha256:" + "a" * 64, "a" * 40)
                    self.assertIs(value["full_ci_qualified"], False)
                    self.assertIs(value["owned_resources_removed"], True)
                    self.assertEqual(value["contact_concurrency_tests"], 2)
                    self.assertTrue(value["checks"]["contact_concurrency_verified"])
                    self.assertEqual(value["source_schema"], receipt.SOURCE)
                self.assertEqual(cleanup.call_count, 6)
                cleaned = {call.args[1] for call in cleanup.call_args_list}
                self.assertIn(tests.call_args.kwargs["container_name"], cleaned)
                self.assertIn(tests.call_args.kwargs["dependency_container_name"], cleaned)

    def test_mutable_image_is_refused_without_inspecting_or_starting_resources(self):
        with patch.object(qualification, "inspect_image") as inspect, self.assertRaises(qualification.QualificationError):
            qualification.qualify("candidate:latest", "a" * 40)
        inspect.assert_not_called()

    def test_partial_extraction_failure_cleans_all_preregistered_resources(self):
        with (patch.object(qualification, "inspect_image", return_value="sha256:" + "a" * 64),
              patch.object(qualification, "admit_memory", return_value={}),
              patch.object(qualification, "run", return_value=result()),
              patch.object(qualification, "extract_clients", side_effect=qualification.QualificationError("fixture failed")),
              patch.object(qualification, "remove_owned") as cleanup,
              self.assertRaisesRegex(qualification.QualificationError, "fixture failed")):
            qualification.qualify("sha256:" + "a" * 64, "a" * 40)
        self.assertEqual(cleanup.call_count, 6)
        self.assertEqual(len({call.args[2] for call in cleanup.call_args_list}), 1)

    def test_rehearsal_keeps_candidate_sources_readonly_and_uses_only_private_client_mount(self):
        with patch.object(qualification, "run", return_value=result()) as command, patch.object(qualification, "capture", return_value=encoded()):
            proof = qualification.run_rehearsal("fixture", "sha256:" + "a" * 64, "b" * 64, "owner",
                Path("fixture.env"), Path("private-clients"), "c" * 64, {})
        arguments = command.call_args.args[0]
        self.assertIn("container:" + "b" * 64, arguments)
        self.assertIn("--read-only", arguments)
        self.assertIn("1001:1001", arguments)
        self.assertEqual(arguments.count("--mount"), 1)
        self.assertNotIn("LD_LIBRARY_PATH", " ".join(arguments))
        self.assertEqual(proof["fixture_person_count"], 700)

    def test_failed_helper_does_not_expose_driver_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "private.log"
            with self.assertRaises(qualification.QualificationError) as raised:
                bounded.capture([sys.executable, "-c", "print('synthetic-secret-DSN'); raise SystemExit(1)"],
                                timeout=10, diagnostic_path=log)
            self.assertIn("synthetic-secret", log.read_text())
            self.assertNotIn("synthetic-secret", str(raised.exception))

    def test_capture_stops_at_the_byte_budget_and_refuses_existing_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "private.log"
            with self.assertRaisesRegex(qualification.QualificationError, "output_limit"):
                bounded.capture([sys.executable, "-c", "print('x' * 100000)"], timeout=10,
                                maximum_bytes=1024, diagnostic_path=log)
            self.assertEqual(log.stat().st_size, 1024)
            with self.assertRaises(FileExistsError):
                bounded.capture([sys.executable, "-c", "print('must not start')"], timeout=10, diagnostic_path=log)

    def test_capture_times_out_without_exposing_output(self):
        with self.assertRaisesRegex(qualification.QualificationError, "timed_out"):
            bounded.capture([sys.executable, "-c", "import time; print('synthetic-secret'); time.sleep(60)"], timeout=1)

    def test_resource_admission_counts_every_running_cap_and_host_reserve(self):
        context = [{"Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}]
        running = [{"Id": "unrelated-running-container", "HostConfig": {"Memory": 6 * 1024**3}}]
        outputs = [result(json.dumps(context)), result("a" * 64), result(json.dumps(running))]
        with (patch.object(qualification, "os", SimpleNamespace(name="posix", environ={})),
              patch.object(qualification.Path, "read_text", return_value="MemTotal: 8388608 kB\nMemAvailable: 2097152 kB\n"),
              patch.object(qualification, "run", side_effect=outputs),
              self.assertRaises(qualification.ReleaseError)):
            qualification.admit_memory()


class ClientFixtureTests(unittest.TestCase):
    def test_private_client_tree_requires_complete_bounded_regular_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("bin", "client", "lib"):
                (root / folder).mkdir()
            for relative in ("lib/ld.so", "bin/pg_dump", "bin/pg_restore", "client/pg_dump", "client/pg_restore"):
                (root / relative).write_bytes(b"synthetic")
            self.assertEqual(len(clients.validate_client_tree(root)["files"]), 5)
            (root / "lib/unexpected.txt").write_bytes(b"outside admitted names")
            # Unexpected nested paths are rejected even if they are regular files.
            (root / "application.py").write_bytes(b"unreviewed")
            with self.assertRaises(qualification.QualificationError):
                clients.validate_client_tree(root)


if __name__ == "__main__":
    unittest.main()
