"""Negative acceptance tests; no Docker, network, database or workload traffic."""

import unittest
from datetime import UTC, datetime, timedelta

import httpx
from qualify_workload_capacity import (
    API_MEMORY_BYTES,
    gates,
    measured,
    observed_queue_drain_seconds,
    summarize,
)


def instant(seconds):
    return (datetime(2026, 9, 27, tzinfo=UTC) + timedelta(seconds=seconds)).isoformat()


def observation(seconds, *, pending=0, queues=None):
    return {
        "at": instant(seconds),
        "pending_durable_jobs": pending,
        "oldest_pending_age_seconds": 0,
        "queues": {"passport_ocr": 0, "ecr_checks": 0} if queues is None else queues,
        "database_connections": 30,
        "database_max_connections": 100,
        "backend_cgroup_memory_bytes": 1024**3,
    }


def sample(operation="stats", *, cohort="small_tenant", milliseconds=50, status=200):
    return {
        "operation": operation,
        "status": status,
        "milliseconds": milliseconds,
        "valid": True,
        "bytes": 100,
        "cohort": cohort,
    }


class QueueDrainTests(unittest.TestCase):
    def test_prepublication_zeroes_and_short_observation_cannot_prove_drain(self):
        metrics = [observation(second) for second in (0, 2, 4, 10, 12)]
        self.assertIsNone(observed_queue_drain_seconds(metrics, instant(10)))

    def test_transient_empty_resets_for_durable_or_broker_backlog(self):
        for occupied in (
            observation(14, pending=1),
            observation(14, queues={"passport_ocr": 1, "ecr_checks": 0}),
            observation(14, queues={"passport_ocr": 0, "ecr_checks": 1}),
        ):
            with self.subTest(occupied=occupied):
                metrics = [
                    observation(10),
                    observation(12),
                    occupied,
                    observation(16),
                    observation(18),
                ]
                self.assertIsNone(observed_queue_drain_seconds(metrics, instant(10)))
                metrics.append(observation(20))
                self.assertEqual(observed_queue_drain_seconds(metrics, instant(10)), 10)

    def test_absent_or_partial_broker_telemetry_is_not_an_empty_queue(self):
        for queues in ({}, {"ecr_checks": 0}, {"passport_ocr": 0}):
            with self.subTest(queues=queues):
                metrics = [
                    observation(second, queues=queues) for second in (10, 12, 14)
                ]
                self.assertIsNone(observed_queue_drain_seconds(metrics, instant(10)))
        metrics = [observation(second) for second in (10, 12, 14)]
        del metrics[1]["queues"]
        self.assertIsNone(observed_queue_drain_seconds(metrics, instant(10)))


class WorkloadGateTests(unittest.TestCase):
    def setUp(self):
        self.samples = {
            "cold": [sample("roster")],
            "expected": [
                sample(cohort="large_tenant" if i % 10 == 0 else "small_tenant")
                for i in range(1200)
            ],
            "overload": [sample(status=429)],
            "recovery": [
                sample(cohort="large_tenant" if i % 10 == 0 else "small_tenant")
                for i in range(600)
            ],
        }
        self.samples["expected"] += [sample("scan") for _ in range(60)]
        self.samples["expected"] += [
            sample("upload", cohort="public_upload", status=201) for _ in range(4)
        ]
        self.windows = {
            name: {
                "started_at": instant(start),
                "finished_at": instant(end),
                "elapsed_seconds": end - start,
            }
            for name, start, end in (
                ("cold", 0, 2),
                ("expected", 10, 70),
                ("overload", 72, 87),
                ("recovery", 91, 121),
            )
        }
        self.metrics = [observation(second) for second in range(0, 126, 2)]
        self.jobs = {
            "durable_jobs_verified": 100,
            "persisted_unique_scans": 30,
            "persisted_uploads": 4,
            "distinct_readable_upload_objects": 8,
        }

    def failures(self):
        stages = {name: summarize(rows) for name, rows in self.samples.items()}
        return gates(
            stages, self.metrics, self.jobs, self.samples, self.windows, instant(8)
        )

    def test_declared_workload_control_passes(self):
        self.assertEqual(self.failures(), [])

    def test_pooled_tail_cannot_hide_large_tenant_latency(self):
        large = [
            row for row in self.samples["expected"] if row["cohort"] == "large_tenant"
        ]
        for row in large[:2]:
            row["milliseconds"] = 1726
        self.assertLess(summarize(self.samples["expected"])["stats"]["p99_ms"], 1500)
        self.assertIn("expected:large_tenant:stats:latency_budget", self.failures())

    def test_overload_tail_and_p95_each_have_an_explicit_ceiling(self):
        for count, delay in ((10, 2001), (1, 5001)):
            with self.subTest(count=count, delay=delay):
                self.samples["overload"] = [sample(status=429) for _ in range(20)]
                for row in self.samples["overload"][:count]:
                    row["milliseconds"] = delay
                self.assertIn("overload:latency_budget", self.failures())

    def test_missing_queue_observation_fails_even_if_later_samples_are_empty(self):
        self.metrics[8]["queues"] = {}
        self.assertIn("durable_queue:missing_queue_observation", self.failures())

    def test_pending_age_and_late_drain_fail_independently(self):
        self.metrics[8]["oldest_pending_age_seconds"] = 900
        self.assertIn("durable_queue:pending_age_budget", self.failures())
        self.metrics[8]["oldest_pending_age_seconds"] = 0
        for row in self.metrics:
            row["pending_durable_jobs"] = 1
        self.metrics += [observation(second) for second in (308, 310, 312)]
        self.assertIn("durable_queue:recovery_deadline", self.failures())

    def test_fewer_scans_cannot_reduce_expected_durable_count(self):
        self.samples["expected"] = [
            row for row in self.samples["expected"] if row["operation"] != "scan"
        ]
        self.samples["expected"] += [sample("scan") for _ in range(40)]
        self.jobs["persisted_unique_scans"] = 20
        failures = self.failures()
        self.assertIn("scan_request_count_or_contract", failures)
        self.assertIn("scan_retry_created_wrong_record_count", failures)

    def test_failed_scan_cannot_be_counted_as_delivered(self):
        scan = next(
            row for row in self.samples["expected"] if row["operation"] == "scan"
        )
        scan.update(status=503, valid=False)
        self.assertIn("scan_request_count_or_contract", self.failures())

    def test_telemetry_must_cover_the_recovery_window(self):
        self.metrics = [row for row in self.metrics if row["at"] < instant(100)]
        self.assertIn(
            "recovery:resource_observation_does_not_cover_stage", self.failures()
        )

    def test_candidate_api_memory_ceiling_is_not_the_earlier_larger_cap(self):
        self.metrics[4]["backend_cgroup_memory_bytes"] = API_MEMORY_BYTES + 1
        self.assertIn("backend_memory_budget", self.failures())


class BackpressureContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_named_429_with_positive_retry_after_is_accepted(self):
        actor = {"token": "synthetic", "group_size": 100}
        for status, code, retry, expected_valid in (
            (429, "DASHBOARD_RATE_LIMITED", "1", True),
            (429, "APP_RATE_LIMITED", "2", True),
            (429, "RATE_LIMIT_EXCEEDED", "1", True),
            (503, "DEPENDENCY_UNAVAILABLE", "1", False),
            (429, "UNREVIEWED_CODE", "1", False),
            (429, "DASHBOARD_RATE_LIMITED", "0", False),
            (429, "DASHBOARD_RATE_LIMITED", "", False),
        ):
            with self.subTest(status=status, code=code, retry=retry):
                transport = httpx.MockTransport(
                    lambda request, status=status, code=code, retry=retry: (
                        httpx.Response(
                            status,
                            json={"error": {"code": code}},
                            headers={"Retry-After": retry},
                        )
                    )
                )
                async with httpx.AsyncClient(
                    base_url="https://example.invalid", transport=transport
                ) as client:
                    samples = []
                    await measured(
                        client,
                        samples,
                        "stats",
                        "GET",
                        "/stats",
                        actor=actor,
                        overload=True,
                    )
                self.assertEqual(samples[0]["valid"], expected_valid)
                self.assertEqual(samples[0]["status"], status)


if __name__ == "__main__":
    unittest.main()
