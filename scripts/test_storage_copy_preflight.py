"""Real journal checks reject unsafe work before contacting the destination."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_storage_snapshot_integrity import BUCKET, private_source

SCRIPT_DIRECTORY = Path(__file__).resolve().parents[1] / "backend/scripts"
SPEC = importlib.util.spec_from_file_location("copy_preflight_tests_target", SCRIPT_DIRECTORY / "copy_storage_snapshot.py")
assert SPEC is not None and SPEC.loader is not None
migration = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SCRIPT_DIRECTORY))
try:
    SPEC.loader.exec_module(migration)
finally:
    sys.path.remove(str(SCRIPT_DIRECTORY))


class StorageCopyPreflightTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.journal = Path(directory.name) / "versions.sqlite"
        self.source = private_source()
        self.source.meta = SimpleNamespace(endpoint_url="http://source:9000")
        self.source.get_paginator = Mock(return_value=Mock(paginate=Mock(return_value=[])))
        self.destination = Mock()
        self.destination.meta = SimpleNamespace(endpoint_url="http://destination:9000")
        lock = patch.object(migration, "migration_lock", return_value=nullcontext())
        lock.start()
        self.addCleanup(lock.stop)

    def settings(self, values):
        with closing(sqlite3.connect(self.journal)) as connection:
            connection.execute("CREATE TABLE settings (name TEXT PRIMARY KEY, value TEXT)")
            connection.executemany("INSERT INTO settings VALUES (?,?)", values.items())
            connection.commit()

    def test_wrong_journal_identity_never_heads_or_creates_destination_bucket(self):
        self.settings({"identity": json.dumps(["http://other-source:9000", "http://other-target:9000", BUCKET])})
        with self.assertRaisesRegex(RuntimeError, "different endpoints or bucket"):
            migration.copy_snapshot(self.source, self.destination, BUCKET, self.journal, capacity_bytes=10 * 1024**3)
        self.assertEqual(self.destination.method_calls, [])

    def test_changed_source_never_heads_or_creates_destination_bucket(self):
        self.settings({"identity": json.dumps([self.source.meta.endpoint_url, self.destination.meta.endpoint_url, BUCKET]),
                       "source_digest": "digest-from-another-snapshot"})
        with self.assertRaisesRegex(RuntimeError, "Source changed"):
            migration.copy_snapshot(self.source, self.destination, BUCKET, self.journal, capacity_bytes=10 * 1024**3)
        self.assertEqual(self.destination.method_calls, [])

    def test_insufficient_capacity_never_heads_or_creates_destination_bucket(self):
        with self.assertRaisesRegex(RuntimeError, "Insufficient verified target disk headroom"):
            migration.copy_snapshot(self.source, self.destination, BUCKET, self.journal, capacity_bytes=1)
        self.assertEqual(self.destination.method_calls, [])

    def test_source_policy_rejection_never_contacts_destination(self):
        self.source.get_bucket_policy.side_effect = None
        self.source.get_bucket_policy.return_value = {"Policy": '{"Statement":[{"Effect":"Deny"}]}'}
        with self.assertRaisesRegex(RuntimeError, "separately reviewed migration"):
            migration.copy_snapshot(self.source, self.destination, BUCKET, self.journal, capacity_bytes=10 * 1024**3)
        self.assertEqual(self.destination.method_calls, [])

    def test_main_rejects_extra_or_absent_buckets_before_destination_client(self):
        for bucket_names in ([BUCKET, "other-production-bucket"], ["other-production-bucket"], []):
            with self.subTest(bucket_names=bucket_names):
                source = Mock()
                source.list_buckets.return_value = {"Buckets": [{"Name": name} for name in bucket_names]}
                with patch.dict(migration.os.environ, {"S3_BUCKET_NAME": BUCKET, "STORAGE_AVAILABLE_BYTES": "10000000000"}), \
                        patch.object(migration, "client", return_value=source) as client, \
                        patch.object(migration, "copy_snapshot") as copy_snapshot:
                    with self.assertRaises(RuntimeError):
                        migration.main()
                    client.assert_called_once_with("STORAGE_SOURCE")
                    copy_snapshot.assert_not_called()

    def test_main_requires_positive_measured_capacity_before_any_client(self):
        for capacity in ("0", "-1", "unmeasured"):
            with self.subTest(capacity=capacity), \
                    patch.dict(migration.os.environ, {"S3_BUCKET_NAME": BUCKET, "STORAGE_AVAILABLE_BYTES": capacity}), \
                    patch.object(migration, "client") as client:
                with self.assertRaises((RuntimeError, ValueError)):
                    migration.main()
                client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
