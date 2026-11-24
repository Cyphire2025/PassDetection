"""Actual QA owner imports and HTTP traffic with synthetic in-memory transports."""

import json
import pickle
import unittest
from typing import get_type_hints
from unittest.mock import AsyncMock, patch

import httpx
import qualify_workload_capacity as facade
import workload_capacity_gates as acceptance
import workload_capacity_measurements as measurements
import workload_capacity_resources as resources
import workload_capacity_traffic as traffic


class OwnerCompatibilityTests(unittest.TestCase):
    def test_original_functions_remain_direct_public_aliases_with_resolvable_hints(self):
        families = {
            measurements: ("percentile", "summarize", "measured", "begin_stage", "end_stage"),
            traffic: (
                "path_for",
                "paced_actor",
                "scans",
                "synthetic_jpeg",
                "uploads",
                "overload_actor",
                "tenant_negatives",
            ),
            acceptance: ("gates", "observed_queue_drain_seconds"),
            resources: ("fixture", "inspect_backend"),
        }
        for owner, names in families.items():
            for name in names:
                with self.subTest(name=name):
                    function = getattr(owner, name)
                    self.assertIs(getattr(facade, name), function)
                    self.assertIs(pickle.loads(pickle.dumps(function)), function)
                    self.assertTrue(get_type_hints(function))


class TrafficOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_scans_keep_original_actor_scope_event_replay_identity_and_measurement(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"status": "counted"})

        actors = [
            {
                "token": f"synthetic-{index}",
                "group_size": 100,
                "session_id": str(index),
                "qr_payloads": [f"synthetic-qr-{index}"],
            }
            for index in range(10)
        ]
        samples = []
        async with httpx.AsyncClient(
            base_url="https://synthetic.invalid", transport=httpx.MockTransport(respond)
        ) as client:
            with patch.object(traffic.asyncio, "sleep", new=AsyncMock()):
                await traffic.scans(
                    client, samples, {"coordinators": actors, "run_id": "a" * 32}, 20
                )
        self.assertEqual(len(samples), 20)
        self.assertTrue(all(sample["valid"] for sample in samples))
        self.assertEqual(
            len({json.loads(request.content)["client_event_id"] for request in requests}), 10
        )
        for index, request in enumerate(requests):
            self.assertEqual(request.headers["Origin"], facade.ORIGIN)
            self.assertEqual(request.headers["Cookie"], f"access_token=synthetic-{index % 10}")
            self.assertEqual(
                request.url.path, f"/api/v1/tour-operations/coordinator/sessions/{index % 10}/scan"
            )
            self.assertEqual(
                json.loads(request.content)["qr_payload"], f"synthetic-qr-{index % 10}"
            )

    async def test_routed_office_request_rejects_a_foreign_group_response(self):
        actor = {"token": "synthetic", "group_size": 100, "group_id": "owned", "tenant": 0}
        operation, path = traffic.path_for(actor, 2)
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"group_total": 100, "items": [{"group_id": "foreign"}]}
            )
        )
        samples = []
        async with httpx.AsyncClient(
            base_url="https://synthetic.invalid", transport=transport
        ) as client:
            response = await facade.measured(client, samples, operation, "GET", path, actor=actor)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(samples[0]["valid"])
        self.assertEqual(samples[0]["cohort"], "small_tenant")

    async def test_actorless_roster_and_search_stay_invalid_without_dropping_measurements(self):
        for operation, body in (
            ("roster", {"group_total": 100, "items": []}),
            ("search", [{"group_id": "foreign"}]),
        ):
            transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
            samples = []
            async with httpx.AsyncClient(
                base_url="https://synthetic.invalid", transport=transport
            ) as client:
                response = await facade.measured(client, samples, operation, "GET", "/synthetic")
            with self.subTest(operation=operation):
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(samples), 1)
                self.assertFalse(samples[0]["valid"])


if __name__ == "__main__":
    unittest.main()
