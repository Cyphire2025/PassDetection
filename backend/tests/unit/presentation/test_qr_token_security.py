from __future__ import annotations

import re
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from pydantic import ValidationError

from app.presentation.api.v1.routes.tour_operations import _qr_hash, _qr_payload, _qr_status
from app.presentation.api.v1.schemas.tour_operations_schemas import AttendanceScanRequest


class QrTokenSecurityTests(unittest.TestCase):
    def test_payloads_are_random_high_entropy_urlsafe_tokens(self) -> None:
        payloads = {_qr_payload() for _ in range(256)}

        self.assertEqual(len(payloads), 256)
        self.assertTrue(all(re.fullmatch(r"pdatt:[A-Za-z0-9_-]{43}", value) for value in payloads))

    def test_database_hash_does_not_contain_raw_payload(self) -> None:
        payload = _qr_payload()
        digest = _qr_hash(payload)

        self.assertEqual(len(digest), 64)
        self.assertNotIn(payload, digest)
        self.assertEqual(digest, _qr_hash(payload))

    def test_scan_schema_rejects_legacy_deterministic_uuid_payload(self) -> None:
        request_fields = {
            "client_event_id": "event-12345678",
            "sync_source": "online",
        }
        with self.assertRaises(ValidationError):
            AttendanceScanRequest(
                qr_payload="pdatt:12345678-1234-5678-1234-567812345678",
                **request_fields,
            )

        AttendanceScanRequest(qr_payload=_qr_payload(), **request_fields)

    def test_status_precedence_blocks_revoked_expired_and_inactive_tokens(self) -> None:
        now = datetime.now(tz=timezone.utc)
        token = SimpleNamespace(revoked_at=None, expires_at=now + timedelta(days=1), is_active=True)
        self.assertEqual(_qr_status(token, now), "active")

        token.is_active = False
        self.assertEqual(_qr_status(token, now), "inactive")

        token.expires_at = now - timedelta(seconds=1)
        self.assertEqual(_qr_status(token, now), "expired")

        token.revoked_at = now
        self.assertEqual(_qr_status(token, now), "revoked")


if __name__ == "__main__":
    unittest.main()
