"""Actual stream ownership during a synthetic versioned-storage copy."""

from __future__ import annotations

import hashlib
import io
import sqlite3
import unittest
from contextlib import closing
from unittest.mock import Mock, patch

from botocore.exceptions import EndpointConnectionError
from botocore.response import StreamingBody
from test_storage_copy_preflight import BUCKET, migration

PAYLOAD = b"Synthetic private storage migration content."


class CountingStream(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.close_count = 0

    def close(self):
        self.close_count += 1
        super().close()


class StorageCopyBodyLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.source_stream = CountingStream(PAYLOAD)
        self.destination_stream = CountingStream(PAYLOAD)
        self.source = Mock()
        self.source.get_object.return_value = {
            "Body": StreamingBody(self.source_stream, len(PAYLOAD)),
            "ContentType": "application/octet-stream", "Metadata": {"purpose": "synthetic"},
        }
        self.tags = [{"Key": "purpose", "Value": "synthetic"}]
        self.source.get_object_tagging.return_value = {"TagSet": self.tags}
        self.destination = Mock()
        self.destination.put_object.return_value = {"VersionId": "copied-version"}
        self.destination.get_object.return_value = {
            "Body": StreamingBody(self.destination_stream, len(PAYLOAD)),
        }
        self.destination.head_object.return_value = {
            "ContentType": "application/octet-stream", "Metadata": {"purpose": "synthetic"},
        }
        self.destination.get_object_tagging.return_value = {"TagSet": self.tags}
        with closing(sqlite3.connect(":memory:")) as db:
            db.row_factory = sqlite3.Row
            self.row = db.execute(
                "SELECT ? AS key, ? AS version, 0 AS deleted, ? AS size, ? AS etag",
                ("synthetic/document.bin", "source-version", len(PAYLOAD), "source-etag"),
            ).fetchone()

    def tearDown(self):
        # Test-owned streams never escape even when the original implementation leaks one.
        for stream in (self.source_stream, self.destination_stream):
            if not stream.closed:
                stream.close()

    def test_tag_request_error_or_operator_interrupt_closes_the_acquired_body(self):
        for error in (EndpointConnectionError(endpoint_url="https://storage.example.invalid"),
                      KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                if self.source_stream.closed:
                    self.source_stream = CountingStream(PAYLOAD)
                    self.source.get_object.return_value["Body"] = StreamingBody(
                        self.source_stream, len(PAYLOAD),
                    )
                self.source.get_object_tagging.side_effect = error
                with self.assertRaises(type(error)) as caught:
                    migration.copy_version(self.source, self.destination, BUCKET, self.row)
                self.assertIs(caught.exception, error)
                self.assertEqual(self.source_stream.close_count, 1)
                self.destination.put_object.assert_not_called()

    def test_success_retains_bytes_properties_tags_and_closes_both_bodies_once(self):
        copied = []

        def put(**kwargs):
            copied.append((kwargs["Body"].read(), kwargs["ContentType"], kwargs["Metadata"],
                           kwargs["Tagging"]))
            return {"VersionId": "copied-version"}

        self.destination.put_object.side_effect = put
        result = migration.copy_version(self.source, self.destination, BUCKET, self.row)
        self.assertEqual(result, ("copied-version", hashlib.sha256(PAYLOAD).hexdigest()))
        self.assertEqual(copied, [(PAYLOAD, "application/octet-stream",
                                  {"purpose": "synthetic"}, "purpose=synthetic")])
        self.assertEqual((self.source_stream.close_count, self.destination_stream.close_count),
                         (1, 1))
        self.source.get_object.assert_called_once_with(
            Bucket=BUCKET, Key=self.row["key"], VersionId=self.row["version"],
            IfMatch=self.row["etag"],
        )

    def test_destination_error_retains_its_identity_and_closes_the_source(self):
        error = EndpointConnectionError(endpoint_url="https://destination.example.invalid")
        self.destination.put_object.side_effect = error
        with self.assertRaises(EndpointConnectionError) as caught:
            migration.copy_version(self.source, self.destination, BUCKET, self.row)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.source_stream.close_count, 1)

    def test_temporary_file_failure_still_closes_the_acquired_source(self):
        error = OSError("Synthetic unavailable temporary storage")
        with patch.object(migration.tempfile, "TemporaryFile", side_effect=error):
            with self.assertRaises(OSError) as caught:
                migration.copy_version(self.source, self.destination, BUCKET, self.row)
        self.assertIs(caught.exception, error)
        self.assertEqual(self.source_stream.close_count, 1)
        self.destination.put_object.assert_not_called()


if __name__ == "__main__":
    unittest.main()
