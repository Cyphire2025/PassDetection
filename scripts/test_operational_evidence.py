"""Receipt validation must reject fabricated closure from local CI or missing proof."""

import copy
import hashlib
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from verify_operational_evidence import validate


class OperationalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.now = datetime(2026, 9, 26, tzinfo=UTC)
        evidence = b"Unit test receipt only; not operational evidence"
        (self.directory / "receipt.txt").write_bytes(evidence)
        receipt = {"path": "receipt.txt", "sha256": hashlib.sha256(evidence).hexdigest()}
        timestamp = (self.now - timedelta(hours=1)).isoformat()
        self.valid = {
            "schema_version": 1, "environment": "production", "synthetic": False,
            "reviewed_by": "Test reviewer", "reviewed_at": self.now.isoformat(), "application_failure_domain": "primary-vps",
            "monitoring": {"external_failure_domain": "separate-monitor", "receipt": receipt,
                "primary_responder": "Test primary", "backup_responder": "Test backup",
                "external_probe_url": "https://monitor.example.test/probe", "metrics_retention_days": 30,
                "event_retention_days": 90, "injected_at": timestamp, "received_at": timestamp, "acknowledged_at": timestamp},
            "recovery": {"external_failure_domain": "separate-backup", "receipt": receipt, "completed_at": timestamp,
                "encrypted_off_host_backup": True, "backup_deletion_protected": True, "pitr_verified": True,
                "database_object_checksums_reconciled": True, "restored_application_verified": True, "redis_domains_reconciled": True,
                "rpo_seconds": 60, "rto_seconds": 120, "approved_rpo_seconds": 300, "approved_rto_seconds": 1800},
        }

    def check(self, document):
        return validate(document, self.directory, now=self.now)

    def test_complete_contract_is_accepted_without_claiming_receipt_authenticity(self):
        self.assertEqual(self.check(self.valid), [])

    def test_incomplete_evidence_and_ci_results_fail(self):
        self.assertTrue(self.check({}))
        for section, key, value in ((None, "synthetic", True), ("recovery", "pitr_verified", False),
                                   ("recovery", "redis_domains_reconciled", False),
                                   ("monitoring", "external_failure_domain", "primary-vps"),
                                   ("monitoring", "backup_responder", "Test primary"),
                                   ("recovery", "rpo_seconds", 301)):
            document = copy.deepcopy(self.valid)
            (document if section is None else document[section])[key] = value
            with self.subTest(section=section, key=key):
                self.assertTrue(self.check(document))

    def test_timestamps_must_be_fresh_ordered_and_timezone_aware(self):
        for timestamp in ((self.now - timedelta(days=36)).isoformat(), (self.now + timedelta(days=1)).isoformat(), "2026-09-26T00:00:00"):
            document = copy.deepcopy(self.valid)
            document["monitoring"]["received_at"] = timestamp
            self.assertTrue(self.check(document))
        document = copy.deepcopy(self.valid)
        document["monitoring"]["received_at"] = self.now.isoformat()
        self.assertTrue(self.check(document))

    def test_receipt_bytes_and_directory_boundary_are_enforced(self):
        for replacement in ({"path": "missing.txt", "sha256": "0" * 64},
                            {"path": "receipt.txt", "sha256": "0" * 64},
                            {"path": "../receipt.txt", "sha256": "0" * 64}):
            document = copy.deepcopy(self.valid)
            document["recovery"]["receipt"] = replacement
            self.assertTrue(self.check(document))


if __name__ == "__main__":
    unittest.main()
