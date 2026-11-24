"""A rehearsal receipt cannot be reused for a different source baseline."""

from __future__ import annotations

import json
import unittest

from qa.qualify_branding_migration import (
    CHECKS,
    MARKER,
    SOURCE,
    TARGET,
    validate_result,
)
from release_workspace_branding_contract import CHAIN


class BrandingQualificationTests(unittest.TestCase):
    def receipt(self, source=SOURCE):
        return MARKER + json.dumps({
            "source_contract_sha256": "a" * 64,
            "result": {"source": source, "target": TARGET, "checks": CHECKS,
                       "synthetic_only": True, "automatic_downgrade": False, "messages_sent": 0},
        })

    def test_each_source_receipt_requires_its_own_baseline(self):
        for source in (SOURCE, CHAIN[0]):
            with self.subTest(source=source):
                result = validate_result(self.receipt(source), "a" * 64, source)
                self.assertEqual(result["source"], source)
        with self.assertRaisesRegex(ValueError, "incomplete_branding_migration_proof"):
            validate_result(self.receipt(SOURCE), "a" * 64, CHAIN[0])

    def test_receipt_requires_the_matching_contract_and_single_result(self):
        for raw, digest in ((self.receipt(), "b" * 64),
                            (self.receipt() + "\n" + self.receipt(), "a" * 64)):
            with (
                self.subTest(raw=raw, digest=digest),
                self.assertRaisesRegex(ValueError, "one_bound_migration_result_required"),
            ):
                validate_result(raw, digest)


if __name__ == "__main__":
    unittest.main()
