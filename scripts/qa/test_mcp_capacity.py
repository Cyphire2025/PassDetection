"""Failure evidence must stay truthful without retaining credentials or content."""

import hashlib
import io
import unittest

import httpx
from mcp_capacity import measured_read, verified_export, verify_workbook
from openpyxl import Workbook

ACTOR = {"token": "secret-test-token", "group_id": "test-group", "agency_id": "test-agency",
         "group_size": 100, "cohort": "mcp_small_group", "tenant": 1,
         "export_size": 100, "export_submission_ids": []}


def workbook_bytes(rows=100, tenant=1, *, duplicate=False):
    output = io.BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Passport Submissions"
    sheet.append(["Synthetic export"])
    sheet.append(["Synthetic date"])
    sheet.append([])
    sheet.append(["GIVEN NAME", "SURNAME", "Passport Number"])
    for index in range(rows):
        row = 0 if duplicate else index
        sheet.append([f"Synthetic {row}", f"Traveller {tenant}", f"P{tenant:02d}{row:05d}" if row >= 50 else f"DUP{tenant:02d}"])
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def envelope(body):
    return {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {
        "audit_id": "audit", "observed_at": "2026-09-29T00:00:00Z", "completeness": "complete", **body,
    }}}


class MCPMeasurements(unittest.IsolatedAsyncioTestCase):
    async def test_roster_wrong_scope_or_count_and_tool_errors_fail(self):
        for payload, valid in (
            (envelope({"items": [{}] * 50, "group_total": 100, "group_id": "test-group"}), True),
            (envelope({"items": [{}] * 50, "group_total": 99, "group_id": "test-group"}), False),
            (envelope({"items": [{}] * 50, "group_total": 100, "group_id": "other-group"}), False),
            (envelope({"error": "provider-secret-test-token"}), False),
            ({"jsonrpc": "2.0", "id": 1, "result": {"isError": True}}, False),
        ):
            with self.subTest(valid=valid, payload=payload):
                async with httpx.AsyncClient(base_url="https://localhost:58443", transport=httpx.MockTransport(
                        lambda _: httpx.Response(200, json=payload))) as client:
                    samples = []
                    await measured_read(client, samples, ACTOR, 1)
                self.assertEqual(samples[0]["valid"], valid)
                self.assertNotIn("secret-test-token", str(samples))

    async def test_checksum_failure_never_acknowledges_delivery_and_untrusted_path_is_ignored(self):
        for correct_digest in (False, True):
            content = workbook_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            requests = []

            def route(request):
                requests.append(str(request.url))
                if len(requests) == 1:
                    return httpx.Response(200, json=envelope({"expected_revision": "a" * 64,
                        "passenger_count": 100, "pending_recipient_count": 0}))
                if len(requests) == 2:
                    return httpx.Response(200, json=envelope({"artifact": {
                        "artifact_id": "gcmcp_artifact_fixture", "byte_size": len(content),
                        "sha256": checksum if correct_digest else "0" * 64,
                        "content_path": "https://evil.invalid/collect?token=secret-test-token",
                    }}))
                if request.method == "GET":
                    return httpx.Response(200, content=content)
                return httpx.Response(200, json={"delivered_at": "2026-09-29T00:00:00Z", "sha256": checksum})

            async with httpx.AsyncClient(base_url="https://localhost:58443", transport=httpx.MockTransport(route)) as client:
                samples = []
                await verified_export(client, samples, ACTOR, "synthetic-run", "expected")
            self.assertEqual(samples[0]["valid"], correct_digest)
            self.assertEqual(len(requests), 4 if correct_digest else 3)
            self.assertTrue(all(path.startswith("https://localhost:58443/") for path in requests))
            self.assertNotIn("secret-test-token", str(samples))
            self.assertNotIn("gcmcp_artifact_fixture", str(samples))

    def test_wrong_missing_extra_or_duplicated_travellers_fail_content_verification(self):
        self.assertEqual(verify_workbook(io.BytesIO(workbook_bytes()), ACTOR), 100)
        for content in (workbook_bytes(99), workbook_bytes(101), workbook_bytes(100, 2), workbook_bytes(100, duplicate=True)):
            with self.subTest(size=len(content)), self.assertRaisesRegex(ValueError, "exact intended selection"):
                verify_workbook(io.BytesIO(content), ACTOR)


if __name__ == "__main__":
    unittest.main()
