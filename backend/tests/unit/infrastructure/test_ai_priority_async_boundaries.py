"""Actual async callers retain native ownership and permit unrelated progress."""

from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import Mock

import httpx

from app.core.config.settings import Settings
from app.core.time_budget import TimeBudget
from app.infrastructure.ai.gemini_post_submission_verification_service import (
    GeminiPostSubmissionVerificationService,
)
from app.infrastructure.ai.passport_extraction_transport import _request_with_retries
from app.infrastructure.ai_priority.coordinator import AiPriorityCoordinator
from app.infrastructure.ai_priority.metrics import (
    AiPriorityMetrics,
    InMemoryAiMetricsStore,
    ResilientAiMetricsStore,
)
from app.infrastructure.ai_priority.provider_metrics import record_provider_event
from app.infrastructure.ai_priority.runtime import MaintainPriorityLease
from app.infrastructure.ai_priority.state import AiWorkload, PriorityLease
from app.infrastructure.observability.metrics import MetricsRegistry


class _BlockingMetricStore(InMemoryAiMetricsStore):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.finish = threading.Event()

    def increment(self, name: str, amount: int = 1) -> None:
        self.entered.set()
        if not self.finish.wait(5):
            raise AssertionError("Synthetic metric write was not released")
        super().increment(name, amount)


class _Transport:
    def __init__(self, metrics: AiPriorityMetrics) -> None:
        self._priority_metrics = metrics

    def _model_route(self) -> tuple[str, ...]:
        return ("synthetic-model",)

    def _endpoint_for_model(self, model: str) -> str:
        return "https://synthetic.invalid/generate"

    def _response_failure(self, status: int) -> tuple[None, bool]:
        return None, False

    def _safe_response_metadata(self, response: httpx.Response) -> dict[str, str]:
        return {}

    def _successful_response_failure(self, response: httpx.Response, **kwargs: object) -> None:
        return None


class _BlockingCoordinator:
    def __init__(self) -> None:
        self.heartbeat_entered = threading.Event()
        self.heartbeat_finish = threading.Event()
        self.release_entered = threading.Event()
        self.release_finish = threading.Event()
        self.operations: list[str] = []

    def heartbeat(self, lease: PriorityLease) -> bool:
        self.heartbeat_entered.set()
        if not self.heartbeat_finish.wait(5):
            raise AssertionError("Synthetic heartbeat was not released")
        self.operations.append("heartbeat_finished")
        return True

    def release(self, lease: PriorityLease) -> bool:
        self.release_entered.set()
        if not self.release_finish.wait(5):
            raise AssertionError("Synthetic lease release was not released")
        self.operations.append("release_finished")
        return True


def _lease(*, redis_available: bool = True) -> PriorityLease:
    return PriorityLease(AiWorkload.EXTRACTION, "a" * 64, 1, 1, redis_available)


class AiPriorityAsyncBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_metric_write_does_not_block_unrelated_coroutine(self) -> None:
        await self._assert_provider_metric_progress(AiWorkload.EXTRACTION)

    async def test_verification_metric_write_does_not_block_unrelated_coroutine(self) -> None:
        await self._assert_provider_metric_progress(AiWorkload.VERIFICATION)

    async def _assert_provider_metric_progress(self, workload: AiWorkload) -> None:
        remote = _BlockingMetricStore()
        loop_progress = threading.Event()
        progressed: list[bool] = []

        def observe() -> None:
            if remote.entered.wait(3):
                progressed.append(loop_progress.wait(0.4))
            remote.finish.set()

        observer = threading.Thread(target=observe)
        observer.start()

        async def unrelated() -> None:
            if await asyncio.to_thread(remote.entered.wait, 3):
                loop_progress.set()

        task = asyncio.create_task(unrelated())
        registry = MetricsRegistry()
        metrics = AiPriorityMetrics(registry, ResilientAiMetricsStore(remote))
        try:
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
            ) as client:
                if workload is AiWorkload.EXTRACTION:
                    response, status, attempts, model = await _request_with_retries(
                        _Transport(metrics),  # type: ignore[arg-type]
                        client,
                        headers={},
                        payload={"generationConfig": {}},
                        budget=TimeBudget.start(3),
                        original={},
                        logger=Mock(),
                    )
                    self.assertIsNotNone(response)
                    self.assertEqual((status, attempts, model), (None, 1, "synthetic-model"))
                else:
                    result = await GeminiPostSubmissionVerificationService(
                        settings=Settings(
                            _env_file=None,
                            app_secret_key="synthetic-only",
                            google_api_key="synthetic-key",
                            gemini_max_retries=0,
                        ),
                        http_client=client,
                        priority_metrics=metrics,
                    ).verify(b"synthetic", content_type="image/jpeg", submitted_fields={})
                    self.assertEqual(result.provider_status, "invalid_response")
            await task
            self.assertEqual(progressed, [True])
            self.assertEqual(
                remote.snapshot()["counters"][f"ai_provider.events.total.{workload.value}.success"],
                1,
            )
        finally:
            remote.finish.set()
            await asyncio.to_thread(observer.join, 3)
            await asyncio.gather(task, return_exceptions=True)

    async def test_release_follows_completion_of_inflight_heartbeat(self) -> None:
        coordinator = _BlockingCoordinator()
        coordinator.release_finish.set()
        body_finished = asyncio.Event()

        async def operation() -> None:
            async with MaintainPriorityLease(coordinator, _lease()):  # type: ignore[arg-type]
                self.assertTrue(await asyncio.to_thread(coordinator.heartbeat_entered.wait, 3))
                body_finished.set()

        task = asyncio.create_task(operation())
        try:
            await asyncio.wait_for(body_finished.wait(), 3)
            await asyncio.sleep(0.03)
            self.assertFalse(task.done(), "Lease context abandoned its running native heartbeat")
            self.assertFalse(coordinator.release_entered.is_set())
        finally:
            coordinator.heartbeat_finish.set()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(coordinator.operations, ["heartbeat_finished", "release_finished"])

    async def test_repeated_cancellation_does_not_abandon_native_release(self) -> None:
        coordinator = _BlockingCoordinator()

        async def operation() -> None:
            async with MaintainPriorityLease(coordinator, _lease(redis_available=False)):
                pass

        task = asyncio.create_task(operation())
        try:
            self.assertTrue(await asyncio.to_thread(coordinator.release_entered.wait, 3))
            task.cancel()
            await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0.01)
            self.assertFalse(task.done(), "Cancelled context abandoned its native release")
            coordinator.release_finish.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            coordinator.release_finish.set()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(coordinator.operations, ["release_finished"])

    async def test_cancelled_metric_write_finishes_before_cancellation_propagates(self) -> None:
        remote = _BlockingMetricStore()
        metrics = AiPriorityMetrics(MetricsRegistry(), ResilientAiMetricsStore(remote))
        task = asyncio.create_task(
            record_provider_event(metrics, workload=AiWorkload.EXTRACTION, event="success")
        )
        try:
            self.assertTrue(await asyncio.to_thread(remote.entered.wait, 3))
            task.cancel()
            await asyncio.sleep(0.01)
            task.cancel()
            await asyncio.sleep(0.01)
            self.assertFalse(task.done())
            remote.finish.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            remote.finish.set()
            await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(
            remote.snapshot()["counters"]["ai_provider.events.total.extraction.success"], 1
        )

    async def test_unexpected_heartbeat_failure_still_releases_and_propagates(self) -> None:
        coordinator = _BlockingCoordinator()
        coordinator.release_finish.set()

        def failed_heartbeat(lease: PriorityLease) -> bool:
            coordinator.heartbeat_entered.set()
            raise ValueError("synthetic heartbeat failure")

        coordinator.heartbeat = failed_heartbeat  # type: ignore[method-assign]
        with self.assertRaisesRegex(ValueError, "synthetic heartbeat failure"):
            async with MaintainPriorityLease(coordinator, _lease()):  # type: ignore[arg-type]
                self.assertTrue(await asyncio.to_thread(coordinator.heartbeat_entered.wait, 3))
                await asyncio.sleep(0.02)
        self.assertEqual(coordinator.operations, ["release_finished"])

    async def test_workload_owners_retain_subclass_queue_overrides(self) -> None:
        class Overridden(AiPriorityCoordinator):
            def queue_extraction(self, job_reference: str) -> PriorityLease:
                return _lease(redis_available=False)

            def queue_verification(self, job_reference: str) -> PriorityLease:
                return PriorityLease(AiWorkload.VERIFICATION, "b" * 64, 1, 1, False)

        store = Mock()
        coordinator = Overridden(
            store=store, metrics_sink=AiPriorityMetrics(MetricsRegistry(), InMemoryAiMetricsStore())
        )
        self.assertTrue(coordinator.try_start_extraction("synthetic").admitted)
        self.assertFalse(coordinator.try_start_verification("synthetic").admitted)
        store.mutate.assert_not_called()
