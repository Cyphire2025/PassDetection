"""Failure evidence must stay truthful without retaining credentials or content."""

import asyncio
import hashlib
import io
import json
import unittest
import uuid
from unittest.mock import patch

import httpx
from mcp_capacity import (
    measured_read,
    serialized_exports,
    verified_export,
    verify_workbook,
)
from mcp_capacity_profile import (
    CAPABILITIES,
    EXPORT_FAMILIES,
    EXPORT_SCHEDULING,
    SOURCE_BYTES,
    SOURCE_ROWS,
    export_selection,
    require_minimum_profile,
)
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
    async def test_serialization_does_not_overlap_and_includes_wait_in_unchanged_latency(self):
        active, finished = [], []
        actors = [{**ACTOR, "cohort": cohort} for cohort in ("mcp_large_group", "mcp_small_group")]

        async def export(_client, samples, actor, run_id, stage):
            self.assertEqual(active, [])
            active.append(actor["cohort"])
            await asyncio.sleep(0)
            self.assertEqual(finished, [] if actor is actors[0] else [actors[0]["cohort"]])
            self.assertEqual((run_id, stage), ("same-run", "expected"))
            record = {"started_at": actor["cohort"], "milliseconds": 25, "valid": True}
            samples.append(record)
            finished.append(active.pop())
            return record

        samples = []
        with patch("mcp_capacity.verified_export", side_effect=export), patch(
            "mcp_capacity.time.perf_counter", side_effect=[10, 10, 30]
        ):
            await serialized_exports(None, samples, actors, "same-run", "expected")
        self.assertEqual([row["export_order"] for row in samples], [0, 1])
        self.assertTrue(all(row["export_scheduling"] == EXPORT_SCHEDULING for row in samples))
        self.assertEqual([row["serialization_wait_ms"] for row in samples], [0, 20000])
        self.assertEqual([row["milliseconds"] for row in samples], [25, 20025])
        self.assertEqual([row["execution_started_at"] for row in samples], [actor["cohort"] for actor in actors])
        self.assertEqual(samples[0]["started_at"], samples[1]["started_at"])

    async def test_large_group_retains_5000_reads_but_exports_exact_first_100(self):
        run_id = uuid.uuid4().hex
        actor = {**ACTOR, "group_size": 5000, "cohort": "mcp_large_group",
                 **export_selection(run_id, {"group_size": 5000, "tenant": 1})}
        content, requests = workbook_bytes(), []
        checksum = hashlib.sha256(content).hexdigest()

        def route(request):
            if request.url.path == "/mcp":
                body = json.loads(request.content)
                requests.append(body["params"])
                if body["params"]["name"] == "list_group_passports":
                    return httpx.Response(200, json=envelope({"items": [{}] * 50,
                        "group_total": 5000, "group_id": actor["group_id"]}))
                selection = body["params"]["arguments"]["export"]
                self.assertEqual(selection["selection"], "selected_passports")
                self.assertEqual(selection["submission_ids"], actor["export_submission_ids"])
                self.assertEqual(len(selection["submission_ids"]), 100)
                if body["params"]["name"] == "inspect_excel_export":
                    return httpx.Response(200, json=envelope({"expected_revision": "a" * 64,
                        "passenger_count": 100, "pending_recipient_count": 0}))
                return httpx.Response(200, json=envelope({"artifact": {
                    "artifact_id": "gcmcp_artifact_fixture", "byte_size": len(content), "sha256": checksum,
                }}))
            if request.method == "GET":
                return httpx.Response(200, content=content)
            return httpx.Response(200, json={"delivered_at": "verified", "sha256": checksum})

        samples = []
        async with httpx.AsyncClient(base_url="https://localhost:58443", transport=httpx.MockTransport(route)) as client:
            await measured_read(client, samples, actor, 1)
            await verified_export(client, samples, actor, run_id, "expected")
        self.assertTrue(all(row["valid"] for row in samples))
        self.assertEqual(samples[1]["rows"], 100)
        self.assertEqual([row["name"] for row in requests], [
            "list_group_passports", "inspect_excel_export", "prepare_excel_export",
        ])

    async def test_busy_is_not_success_or_a_retry_with_a_new_key(self):
        calls = []

        def route(request):
            calls.append(json.loads(request.content)["params"])
            if len(calls) == 1:
                return httpx.Response(200, json=envelope({"expected_revision": "a" * 64,
                    "passenger_count": 100, "pending_recipient_count": 0}))
            return httpx.Response(200, json=envelope({"error": "export_busy"}))

        async with httpx.AsyncClient(base_url="https://localhost:58443", transport=httpx.MockTransport(route)) as client:
            samples = []
            await serialized_exports(client, samples, [ACTOR], "same-run", "expected")
        self.assertEqual(len(calls), 2)
        self.assertFalse(samples[0]["valid"])
        self.assertEqual(calls[1]["arguments"]["idempotency_key"], "capacity-same-run-expected-mcp_small_group")

    async def test_oversized_selection_fails_before_any_http_request(self):
        def route(_request):
            self.fail("An oversized fixture must not reach HTTP")

        for actor in (
            {**ACTOR, "export_size": 1500},
            {**ACTOR, "group_size": 5000, "export_submission_ids": []},
        ):
            with self.subTest(actor=actor):
                samples = []
                async with httpx.AsyncClient(base_url="https://localhost:58443", transport=httpx.MockTransport(route)) as client:
                    await verified_export(client, samples, actor, "same-run", "expected")
                self.assertFalse(samples[0]["valid"])
                self.assertEqual(samples[0]["rows"], 0)

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
                        lambda _, payload=payload: httpx.Response(200, json=payload))) as client:
                    samples = []
                    await measured_read(client, samples, ACTOR, 1)
                self.assertEqual(samples[0]["valid"], valid)
                self.assertNotIn("secret-test-token", str(samples))

    async def test_checksum_failure_never_acknowledges_delivery_and_untrusted_path_is_ignored(self):
        for correct_digest in (False, True):
            content = workbook_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            requests = []

            def route(request, requests=requests, content=content, checksum=checksum, correct_digest=correct_digest):
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


class MinimumProfileTests(unittest.TestCase):
    def test_only_exact_deployed_profile_is_accepted(self):
        values = {"enabled": True, "capabilities": CAPABILITIES, "families": EXPORT_FAMILIES,
                  "rows": SOURCE_ROWS, "byte_limit": SOURCE_BYTES}
        require_minimum_profile(**values)
        for change in ({"enabled": False}, {"capabilities": ["mcp:read", "mcp:upload", "mcp:export"]},
                       {"families": []}, {"families": ["passport_excel", "passport_images"]},
                       {"rows": 1500}, {"rows": 99}, {"rows": True},
                       {"byte_limit": 16 * 1024 * 1024}, {"byte_limit": 1024}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                require_minimum_profile(**{**values, **change})

    def test_export_selection_is_exact_and_read_cohort_is_unchanged(self):
        run_id = uuid.uuid4().hex
        large, small = {"group_size": 5000, "tenant": 1}, {"group_size": 100, "tenant": 2}
        selection = export_selection(run_id, large)
        self.assertEqual(selection["export_size"], 100)
        self.assertEqual(selection["export_submission_ids"], [
            str(uuid.uuid5(uuid.UUID(run_id), f"passenger-1-{index}")) for index in range(100)
        ])
        self.assertEqual(export_selection(run_id, small), {"export_size": 100, "export_submission_ids": []})
        self.assertEqual(large["group_size"], 5000)


if __name__ == "__main__":
    unittest.main()
