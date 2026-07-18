"""Bounded, shared Gemini observability contract tests."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from app.infrastructure.ai_priority.metrics import (
    AiPriorityMetrics,
    InMemoryAiMetricsStore,
    RedisAiMetricsStore,
    ResilientAiMetricsStore,
)
from app.infrastructure.ai_priority.state import (
    AdmissionStatus,
    AiWorkload,
    PriorityLease,
    QueueCounts,
)
from app.infrastructure.observability.metrics import MetricsRegistry


class _UnavailableRemote:
    def __init__(self) -> None:
        self.calls = 0

    def _fail(self) -> None:
        self.calls += 1
        raise ConnectionError("redis unavailable")

    def increment(self, name: str, amount: int = 1) -> None:
        self._fail()

    def observe(self, name: str, value: float) -> None:
        self._fail()

    def set_gauge(self, name: str, value: float) -> None:
        self._fail()

    def set_gauges(self, values: Any) -> None:
        self._fail()

    def mark_queued(self, **kwargs: Any) -> None:
        self._fail()

    def mark_started(self, **kwargs: Any) -> float | None:
        self._fail()

    def mark_completed(self, **kwargs: Any) -> float | None:
        self._fail()

    def snapshot(self) -> dict[str, Any]:
        self._fail()
        raise AssertionError("unreachable")


class AiPriorityMetricsTests(unittest.TestCase):
    def test_latest_n_window_exposes_p50_p95_and_p99(self) -> None:
        store = InMemoryAiMetricsStore(max_samples=5)

        for value in range(1, 101):
            store.observe("ai_provider.duration_ms.extraction", float(value))

        histogram = store.snapshot()["histograms"][
            "ai_provider.duration_ms.extraction"
        ]
        self.assertEqual(histogram["count_total"], 100)
        self.assertEqual(histogram["count_window"], 5)
        self.assertEqual(histogram["min"], 96.0)
        self.assertEqual(histogram["p50"], 98.0)
        self.assertEqual(histogram["p95"], 100.0)
        self.assertEqual(histogram["p99"], 100.0)
        self.assertEqual(histogram["max"], 100.0)

    def test_lifecycle_records_queue_wait_and_end_to_end_once_without_pii(
        self,
    ) -> None:
        store = InMemoryAiMetricsStore()
        raw_reference = "delegate@example.com:secret-upload-token"

        store.mark_queued(
            workload=AiWorkload.EXTRACTION,
            job_key=raw_reference,
            generation=7,
            now_ms=100,
        )
        self.assertEqual(
            store.mark_started(
                workload=AiWorkload.EXTRACTION,
                job_key=raw_reference,
                generation=7,
                now_ms=250,
            ),
            150.0,
        )
        self.assertIsNone(
            store.mark_started(
                workload=AiWorkload.EXTRACTION,
                job_key=raw_reference,
                generation=7,
                now_ms=300,
            )
        )
        self.assertEqual(
            store.mark_completed(
                workload=AiWorkload.EXTRACTION,
                job_key=raw_reference,
                generation=7,
                now_ms=900,
            ),
            800.0,
        )
        self.assertIsNone(
            store.mark_completed(
                workload=AiWorkload.EXTRACTION,
                job_key=raw_reference,
                generation=7,
                now_ms=950,
            )
        )

        snapshot = store.snapshot()
        self.assertEqual(
            snapshot["histograms"][
                "ai_priority.queue_wait_ms.extraction"
            ]["count_total"],
            1,
        )
        self.assertEqual(
            snapshot["histograms"][
                "ai_priority.end_to_end_latency_ms.extraction"
            ]["p99"],
            800.0,
        )
        self.assertNotIn("delegate@example.com", str(snapshot))
        self.assertNotIn("secret-upload-token", str(snapshot))

    def test_multiple_metrics_clients_share_low_cardinality_aggregates(
        self,
    ) -> None:
        shared = InMemoryAiMetricsStore()
        first = AiPriorityMetrics(MetricsRegistry(), shared)
        second = AiPriorityMetrics(MetricsRegistry(), shared)

        first.record_request(AiWorkload.EXTRACTION)
        second.record_request(AiWorkload.EXTRACTION)
        first.record_admission(
            workload=AiWorkload.EXTRACTION,
            status=AdmissionStatus.ADMITTED,
            reason="attacker-controlled-reason",
            duration_ms=5.0,
        )
        second.record_provider_event(
            workload=AiWorkload.VERIFICATION,
            event="attacker-controlled-event",
            duration_ms=20.0,
            retry_number=2,
        )
        first.record_capacity(extraction_max=32, verification_max=1)
        first.record_counts(
            QueueCounts(
                extraction_waiting=4,
                extraction_dispatching=2,
                extraction_active=3,
                verification_waiting=5,
                verification_active=1,
            )
        )

        snapshot = shared.snapshot()
        self.assertEqual(
            snapshot["counters"]["ai_priority.requests.total.extraction"],
            2,
        )
        self.assertIn(
            "ai_priority.admissions.reason.extraction.other",
            snapshot["counters"],
        )
        self.assertIn(
            "ai_provider.events.total.verification.other",
            snapshot["counters"],
        )
        self.assertNotIn("attacker-controlled", str(snapshot))
        self.assertEqual(
            snapshot["gauges"]["ai_priority.capacity.extraction_max"],
            32.0,
        )
        self.assertEqual(
            snapshot["gauges"]["ai_priority.queue.verification_waiting"],
            5.0,
        )

    def test_resilient_store_fails_safe_to_bounded_process_snapshot(self) -> None:
        current_time = [100.0]
        remote = _UnavailableRemote()
        store = ResilientAiMetricsStore(
            remote,
            monotonic=lambda: current_time[0],
            circuit_seconds=30.0,
        )

        store.increment("ai_priority.requests.total.extraction")
        store.increment("ai_priority.requests.total.extraction")
        snapshot = store.snapshot()

        self.assertEqual(remote.calls, 1)
        self.assertEqual(snapshot["status"], "degraded")
        self.assertEqual(snapshot["source"], "process_fallback")
        self.assertEqual(snapshot["scope"], "current_process_only")
        self.assertEqual(
            snapshot["counters"]["ai_priority.requests.total.extraction"],
            2,
        )

        current_time[0] += 31.0
        store.increment("ai_priority.requests.total.extraction")
        self.assertEqual(remote.calls, 2)

    def test_redis_snapshot_parses_shared_counts_gauges_and_percentiles(
        self,
    ) -> None:
        redis_client = MagicMock()
        pipeline = redis_client.pipeline.return_value
        pipeline.execute.return_value = [
            {"ai_priority.requests.total.extraction": "12"},
            {"ai_priority.active.extraction": "3"},
            {"ai_priority.admission_latency_ms.extraction": "20"},
            ["30", "20", "10"],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
        ]
        store = RedisAiMetricsStore(redis_client, max_samples=3)

        snapshot = store.snapshot()

        self.assertEqual(
            snapshot["counters"]["ai_priority.requests.total.extraction"],
            12,
        )
        self.assertEqual(
            snapshot["gauges"]["ai_priority.active.extraction"],
            3.0,
        )
        histogram = snapshot["histograms"][
            "ai_priority.admission_latency_ms.extraction"
        ]
        self.assertEqual(histogram["count_total"], 20)
        self.assertEqual(histogram["p50"], 20.0)
        self.assertEqual(histogram["p95"], 30.0)
        self.assertEqual(histogram["p99"], 30.0)
        redis_client.pipeline.assert_called_once_with(transaction=False)

    def test_redis_lifecycle_key_never_contains_raw_job_reference(self) -> None:
        redis_client = MagicMock()
        store = RedisAiMetricsStore(redis_client)

        store.mark_queued(
            workload=AiWorkload.VERIFICATION,
            job_key="person@example.com:bearer-token",
            generation=4,
            now_ms=1_000,
        )

        redis_arguments = str(redis_client.eval.call_args.args)
        self.assertNotIn("person@example.com", redis_arguments)
        self.assertNotIn("bearer-token", redis_arguments)

    def test_registry_shared_provider_is_isolated_from_diagnostics(self) -> None:
        registry = MetricsRegistry()
        registry.register_snapshot_provider(
            "shared-ai",
            lambda: {"status": "ok", "p99": 42.0},
        )
        registry.register_snapshot_provider(
            "broken",
            lambda: (_ for _ in ()).throw(RuntimeError("no metrics")),
        )

        snapshot = registry.snapshot()

        self.assertEqual(snapshot["shared"]["shared_ai"]["p99"], 42.0)
        self.assertEqual(
            snapshot["shared"]["broken"]["source"],
            "snapshot_provider_error",
        )

    def test_metric_adapter_does_not_expose_lifecycle_identity(self) -> None:
        registry = MetricsRegistry()
        shared = InMemoryAiMetricsStore()
        adapter = AiPriorityMetrics(registry, shared)
        lease = PriorityLease(
            workload=AiWorkload.VERIFICATION,
            job_key="not-a-hash:traveller@example.com",
            generation=3,
            lease_ms=1_000,
        )

        adapter.record_queued(lease, now_ms=1_000)
        adapter.record_started(lease, now_ms=1_100)
        adapter.record_completed(lease, now_ms=1_400)

        combined = {
            "local": registry.snapshot(),
            "shared": shared.snapshot(),
        }
        self.assertNotIn("traveller@example.com", str(combined))
        self.assertEqual(
            combined["shared"]["histograms"][
                "ai_priority.queue_wait_ms.verification"
            ]["p50"],
            100.0,
        )


if __name__ == "__main__":
    unittest.main()
