"""Offline boundary controls for shared metrics and workload failure policy."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from app.infrastructure.ai_priority import factory, metrics
from app.infrastructure.ai_priority.config import AiPriorityConfig
from app.infrastructure.ai_priority.coordinator import AiPriorityCoordinator
from app.infrastructure.ai_priority.metrics import (
    AiPriorityMetrics,
    InMemoryAiMetricsStore,
    RedisAiMetricsStore,
    ResilientAiMetricsStore,
)
from app.infrastructure.ai_priority.state import (
    AiWorkload,
    PriorityLease,
    QueueCounts,
    StoreMutation,
)
from app.infrastructure.observability.metrics import MetricsRegistry


class AiPriorityStoreBoundaryTests(unittest.TestCase):
    def test_redis_wire_bounds_values_and_hashes_lifecycle_references(self) -> None:
        client = MagicMock()
        store = RedisAiMetricsStore(client, max_samples=3, retention_seconds=1)
        store.increment("counter", 2)
        client.pipeline.return_value.hincrby.assert_called_once_with(
            "passdetection:{ai-observability}:v1:counters", "counter", 2
        )
        store.observe("duration", float("nan"))
        client.eval.assert_not_called()
        store.observe("duration", 1e20)
        self.assertEqual(client.eval.call_args.args[-3:], ("86400000.0", 3, 60))
        client.pipeline.reset_mock()
        store.set_gauge("invalid", float("inf"))
        client.pipeline.assert_not_called()
        store.set_gauge("gauge", 5)
        client.pipeline.return_value.hset.assert_called_once_with(
            "passdetection:{ai-observability}:v1:gauges", "gauge", "5.0"
        )
        client.pipeline.reset_mock()
        store.set_gauges({"invalid": float("nan")})
        client.pipeline.assert_not_called()
        store.set_gauges({"valid": 2, "invalid": float("nan")})
        client.pipeline.return_value.hset.assert_called_once_with(
            "passdetection:{ai-observability}:v1:gauges", mapping={"valid": "2.0"}
        )
        identity = dict(workload=AiWorkload.EXTRACTION, job_key="synthetic-secret", generation=2)
        client.eval.return_value = b"15.5"
        self.assertEqual(store.mark_started(**identity, now_ms=100), 15.5)
        self.assertNotIn("synthetic-secret", str(client.eval.call_args))
        client.eval.return_value = "25"
        self.assertEqual(store.mark_completed(**identity, now_ms=200), 25)
        for invalid in (None, False, b"", "", {}, "nan", "not-numeric"):
            with self.subTest(value=invalid):
                client.eval.return_value = invalid
                self.assertIsNone(store.mark_started(**identity, now_ms=100))

    def test_redis_adapter_has_short_transport_deadlines_without_connecting(self) -> None:
        with patch("app.infrastructure.ai_priority.metrics_redis.Redis.from_url") as connect:
            RedisAiMetricsStore.from_url("redis://synthetic.invalid")
        self.assertEqual(connect.call_args.kwargs["socket_connect_timeout"], 0.15)
        self.assertEqual(connect.call_args.kwargs["socket_timeout"], 0.25)

    def test_memory_store_evicts_old_lifecycles_and_rejects_nonfinite_metrics(self) -> None:
        store = InMemoryAiMetricsStore(max_samples=2, max_lifecycles=1)
        identity = dict(workload=AiWorkload.EXTRACTION, generation=1)
        store.mark_queued(**identity, job_key="old", now_ms=1)
        store.mark_queued(**identity, job_key="current", now_ms=2)
        self.assertIsNone(store.mark_started(**identity, job_key="old", now_ms=3))
        self.assertIsNone(store.mark_completed(**identity, job_key="missing", now_ms=3))
        store.observe("invalid", float("inf"))
        store.set_gauge("invalid", float("nan"))
        store.set_gauges({"valid": 5, "invalid": float("inf")})
        snapshot = store.snapshot()
        self.assertEqual(snapshot["gauges"], {"valid": 5.0})
        self.assertNotIn("invalid", snapshot["histograms"])
        self.assertEqual(store.mark_started(**identity, job_key="current", now_ms=9), 7)

    def test_resilient_store_mirrors_current_work_and_recovers_without_backfill(self) -> None:
        clock = [1.0]
        remote = InMemoryAiMetricsStore()
        local = InMemoryAiMetricsStore()
        store = ResilientAiMetricsStore(remote, local=local, monotonic=lambda: clock[0])
        store.increment("counter")
        store.observe("duration", 3)
        store.set_gauge("gauge", 2)
        store.set_gauges({"other": 4})
        identity = dict(workload=AiWorkload.VERIFICATION, job_key="secret", generation=1)
        store.mark_queued(**identity, now_ms=100)
        self.assertEqual(store.mark_started(**identity, now_ms=110), 10)
        self.assertEqual(store.mark_completed(**identity, now_ms=150), 50)
        snapshot = store.snapshot()
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(snapshot["histograms"], local.snapshot()["histograms"])
        with patch.object(remote, "snapshot", side_effect=ConnectionError("synthetic")):
            self.assertEqual(store.snapshot()["status"], "degraded")
        store.increment("counter")
        self.assertEqual(remote.snapshot()["counters"]["counter"], 1)
        clock[0] += 31
        store.increment("counter")
        self.assertEqual(store.snapshot()["counters"]["counter"], 2)
        self.assertEqual(local.snapshot()["counters"]["counter"], 3)

    def test_default_metrics_factory_falls_back_when_settings_cannot_load(self) -> None:
        metrics.get_shared_ai_priority_metrics_store.cache_clear()
        try:
            with patch.object(metrics, "get_settings", side_effect=ValueError("synthetic")):
                store = metrics.get_shared_ai_priority_metrics_store()
            self.assertEqual(store.snapshot()["source"], "process_fallback")
        finally:
            metrics.get_shared_ai_priority_metrics_store.cache_clear()

    def test_coordinator_factory_uses_reviewed_settings_and_caches_adapter(self) -> None:
        settings = SimpleNamespace(
            redis=SimpleNamespace(broker_url="redis://synthetic.invalid"),
            gemini_extraction_max_concurrency=7,
            gemini_verification_max_concurrency=2,
            gemini_extraction_timeout_ms=4000,
            gemini_timeout_seconds=3.5,
            gemini_extraction_quiet_period_ms=150,
            gemini_retry_max_attempts=2,
        )
        factory.get_ai_priority_coordinator.cache_clear()
        try:
            with (
                patch.object(factory, "get_settings", return_value=settings),
                patch.object(factory.RedisPriorityStore, "from_url") as connect,
                patch.object(factory, "AiPriorityCoordinator") as construct,
            ):
                first = factory.get_ai_priority_coordinator()
                self.assertIs(factory.get_ai_priority_coordinator(), first)
            connect.assert_called_once_with("redis://synthetic.invalid")
            config = construct.call_args.kwargs["config"]
            self.assertEqual(config.extraction_max_concurrency, 7)
            self.assertEqual(config.verification_max_concurrency, 2)
            self.assertEqual(config.verification_timeout_ms, 3500)
            self.assertEqual(config.extraction_quiet_period_ms, 150)
        finally:
            factory.get_ai_priority_coordinator.cache_clear()

    def test_post_registration_store_failures_preserve_distinct_workload_policies(self) -> None:
        def mutate(*, operation: str, **kwargs: object) -> StoreMutation:
            if operation.startswith("register_"):
                return StoreMutation("registered", 1, QueueCounts())
            raise ConnectionError("synthetic transient failure")

        store = Mock(mutate=Mock(side_effect=mutate))
        coordinator = AiPriorityCoordinator(
            store=store, metrics_sink=AiPriorityMetrics(MetricsRegistry(), InMemoryAiMetricsStore())
        )
        extraction = coordinator.try_start_extraction("synthetic")
        verification = coordinator.try_start_verification("synthetic")
        self.assertTrue(extraction.admitted)
        self.assertFalse(extraction.lease.redis_available)
        self.assertFalse(verification.admitted)
        self.assertGreater(verification.retry_after_ms, 0)
        self.assertTrue(coordinator.mark_extraction_dispatched(extraction.lease))
        live = PriorityLease(AiWorkload.EXTRACTION, "a" * 64, 1, 1000)
        self.assertTrue(coordinator.mark_extraction_dispatched(live))
        self.assertFalse(coordinator.release_public_reservation(live))
        self.assertFalse(coordinator.heartbeat(live))
        self.assertFalse(coordinator.release(live))
        self.assertTrue(coordinator.heartbeat(extraction.lease))
        self.assertTrue(coordinator.release(extraction.lease))
        stale = coordinator._decision(
            workload=AiWorkload.EXTRACTION,
            lease=live,
            result=StoreMutation("stale", 1, QueueCounts()),
        )
        self.assertFalse(stale.admitted)
        self.assertGreater(stale.retry_after_ms, 0)

    def test_policy_configuration_rejects_invalid_capacity_and_quiet_period(self) -> None:
        with self.assertRaises(ValueError):
            AiPriorityConfig(extraction_max_concurrency=0)
        with self.assertRaises(ValueError):
            AiPriorityConfig(extraction_quiet_period_ms=-1)
