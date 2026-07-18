"""Deterministic concurrency tests for global extraction-first admission."""

from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from app.infrastructure.ai_priority.config import AiPriorityConfig
from app.infrastructure.ai_priority.coordinator import AiPriorityCoordinator
from app.infrastructure.ai_priority.state import (
    AdmissionStatus,
    AiWorkload,
    QueueCounts,
    StoreMutation,
)


class _NoopMetrics:
    def record_capacity(self, **kwargs):  # type: ignore[no-untyped-def]
        pass

    def record_request(self, workload):  # type: ignore[no-untyped-def]
        pass

    def record_admission(self, **kwargs):  # type: ignore[no-untyped-def]
        pass

    def record_redis_failure(self, workload):  # type: ignore[no-untyped-def]
        pass

    def record_counts(self, counts):  # type: ignore[no-untyped-def]
        pass

    def record_queued(self, lease, **kwargs):  # type: ignore[no-untyped-def]
        pass

    def record_started(self, lease, **kwargs):  # type: ignore[no-untyped-def]
        pass

    def record_completed(self, lease, **kwargs):  # type: ignore[no-untyped-def]
        pass


class _RecordingMetrics(_NoopMetrics):
    def __init__(self) -> None:
        self.lifecycle: list[tuple[str, str, int]] = []

    def record_queued(self, lease, **kwargs):  # type: ignore[no-untyped-def]
        self.lifecycle.append(("queued", lease.workload.value, kwargs["now_ms"]))

    def record_started(self, lease, **kwargs):  # type: ignore[no-untyped-def]
        self.lifecycle.append(("started", lease.workload.value, kwargs["now_ms"]))

    def record_completed(self, lease, **kwargs):  # type: ignore[no-untyped-def]
        self.lifecycle.append(("completed", lease.workload.value, kwargs["now_ms"]))


class _Clock:
    def __init__(self, now_ms: int = 1_000_000) -> None:
        self.now_ms = now_ms

    def __call__(self) -> int:
        return self.now_ms

    def advance(self, milliseconds: int) -> None:
        self.now_ms += milliseconds


class _AtomicMemoryStore:
    """A lock-backed test double for the production one-script Redis store."""

    _EXTRACTION_STATES = {"ew", "ed", "ea"}

    def __init__(self, *, fail: bool = False) -> None:
        self._lock = threading.Lock()
        self._fail = fail
        self._generation = 0
        self._state: dict[str, tuple[str, int]] = {}
        self._expiry: dict[tuple[str, str], int] = {}
        self._last_extraction_activity_ms = 0
        self.seen_job_keys: set[str] = set()

    def mutate(
        self,
        *,
        operation: str,
        job_key: str,
        generation: int,
        now_ms: int,
        lease_ms: int,
        waiting_lease_ms: int,
        max_concurrency: int,
        quiet_period_ms: int,
    ) -> StoreMutation:
        if self._fail:
            raise ConnectionError("redis unavailable")
        with self._lock:
            self.seen_job_keys.add(job_key)
            self._cleanup(now_ms)
            if operation == "snapshot":
                return self._result("snapshot", 0)
            if operation == "register_extraction":
                return self._register(
                    job_key,
                    workload="extraction",
                    now_ms=now_ms,
                    lease_ms=lease_ms,
                )
            if operation == "register_verification":
                return self._register(
                    job_key,
                    workload="verification",
                    now_ms=now_ms,
                    lease_ms=lease_ms,
                )
            if operation == "dispatch_extraction":
                return self._dispatch(
                    job_key,
                    generation=generation,
                    now_ms=now_ms,
                    lease_ms=lease_ms,
                )
            if operation == "start_extraction":
                return self._start_extraction(
                    job_key,
                    generation=generation,
                    now_ms=now_ms,
                    lease_ms=lease_ms,
                    waiting_lease_ms=waiting_lease_ms,
                    max_concurrency=max_concurrency,
                    retry_after_ms=quiet_period_ms,
                )
            if operation == "start_verification":
                return self._start_verification(
                    job_key,
                    generation=generation,
                    now_ms=now_ms,
                    lease_ms=lease_ms,
                    waiting_lease_ms=waiting_lease_ms,
                    max_concurrency=max_concurrency,
                    quiet_period_ms=quiet_period_ms,
                )
            if operation.startswith("heartbeat_"):
                workload = operation.removeprefix("heartbeat_")
                return self._heartbeat(
                    job_key,
                    generation=generation,
                    workload=workload,
                    now_ms=now_ms,
                    lease_ms=lease_ms,
                )
            if operation.startswith("release_"):
                workload = operation.removeprefix("release_")
                return self._release(
                    job_key,
                    generation=generation,
                    workload=workload,
                    now_ms=now_ms,
                )
            return self._result("invalid_operation", 0)

    def _cleanup(self, now_ms: int) -> None:
        for (state, job_key), expires_at in list(self._expiry.items()):
            if expires_at > now_ms:
                continue
            self._expiry.pop((state, job_key), None)
            if self._state.get(job_key, (None, 0))[0] == state:
                self._state.pop(job_key, None)
            if state in self._EXTRACTION_STATES:
                self._last_extraction_activity_ms = now_ms

    def _register(
        self,
        job_key: str,
        *,
        workload: str,
        now_ms: int,
        lease_ms: int,
    ) -> StoreMutation:
        current = self._state.get(job_key)
        allowed = {"ew", "ed", "ea"} if workload == "extraction" else {"vw", "va"}
        if current and current[0] in allowed:
            state, generation = current
            if state not in {"ea", "va"}:
                self._expiry[(state, job_key)] = now_ms + lease_ms
            code = {
                "ew": "existing_waiting",
                "ed": "existing_dispatching",
                "ea": "existing_active",
                "vw": "existing_waiting",
                "va": "existing_active",
            }[state]
            return self._result(code, generation)
        self._generation += 1
        state = "ew" if workload == "extraction" else "vw"
        self._state[job_key] = (state, self._generation)
        self._expiry[(state, job_key)] = now_ms + lease_ms
        if workload == "extraction":
            self._last_extraction_activity_ms = now_ms
        return self._result("registered", self._generation)

    def _dispatch(
        self,
        job_key: str,
        *,
        generation: int,
        now_ms: int,
        lease_ms: int,
    ) -> StoreMutation:
        current = self._state.get(job_key)
        if current is None:
            return self._result("missing", 0)
        state, current_generation = current
        if current_generation != generation:
            return self._result("stale", current_generation)
        if state == "ed":
            self._expiry[(state, job_key)] = now_ms + lease_ms
            return self._result("already_dispatching", generation)
        if state == "ea":
            return self._result("already_active", generation)
        if state != "ew":
            return self._result("missing", generation)
        self._move(job_key, "ew", "ed", generation, now_ms + lease_ms)
        return self._result("dispatched", generation)

    def _start_extraction(
        self,
        job_key: str,
        *,
        generation: int,
        now_ms: int,
        lease_ms: int,
        waiting_lease_ms: int,
        max_concurrency: int,
        retry_after_ms: int,
    ) -> StoreMutation:
        current = self._state.get(job_key)
        if current is None:
            return self._result("missing", 0)
        state, current_generation = current
        if current_generation != generation:
            return self._result("stale", current_generation)
        if state == "ea":
            return self._result("duplicate_active", generation)
        if state not in {"ew", "ed"}:
            return self._result("missing", generation)
        if self._count("ea") >= max_concurrency:
            self._move(
                job_key,
                state,
                "ew",
                generation,
                now_ms + waiting_lease_ms,
            )
            return self._result(
                "deferred_capacity",
                generation,
                retry_after_ms=retry_after_ms,
            )
        self._move(job_key, state, "ea", generation, now_ms + lease_ms)
        self._last_extraction_activity_ms = now_ms
        return self._result("admitted", generation)

    def _start_verification(
        self,
        job_key: str,
        *,
        generation: int,
        now_ms: int,
        lease_ms: int,
        waiting_lease_ms: int,
        max_concurrency: int,
        quiet_period_ms: int,
    ) -> StoreMutation:
        current = self._state.get(job_key)
        if current is None:
            return self._result("missing", 0)
        state, current_generation = current
        if current_generation != generation:
            return self._result("stale", current_generation)
        if state == "va":
            return self._result("duplicate_active", generation)
        if state != "vw":
            return self._result("missing", generation)
        extraction_count = sum(self._count(item) for item in ("ew", "ed", "ea"))
        if extraction_count:
            self._expiry[("vw", job_key)] = now_ms + waiting_lease_ms
            return self._result(
                "deferred_extraction_priority",
                generation,
                retry_after_ms=quiet_period_ms,
            )
        quiet_remaining = quiet_period_ms - (
            now_ms - self._last_extraction_activity_ms
        )
        if self._last_extraction_activity_ms and quiet_remaining > 0:
            self._expiry[("vw", job_key)] = now_ms + waiting_lease_ms
            return self._result(
                "deferred_quiet_period",
                generation,
                retry_after_ms=quiet_remaining,
            )
        if self._count("va") >= max_concurrency:
            self._expiry[("vw", job_key)] = now_ms + waiting_lease_ms
            return self._result(
                "deferred_capacity",
                generation,
                retry_after_ms=quiet_period_ms,
            )
        self._move(job_key, "vw", "va", generation, now_ms + lease_ms)
        return self._result("admitted", generation)

    def _heartbeat(
        self,
        job_key: str,
        *,
        generation: int,
        workload: str,
        now_ms: int,
        lease_ms: int,
    ) -> StoreMutation:
        active_state = "ea" if workload == "extraction" else "va"
        current = self._state.get(job_key)
        if current == (active_state, generation):
            self._expiry[(active_state, job_key)] = now_ms + lease_ms
            return self._result("heartbeat", generation)
        if current and current[1] != generation:
            return self._result("stale", current[1])
        return self._result("missing", generation)

    def _release(
        self,
        job_key: str,
        *,
        generation: int,
        workload: str,
        now_ms: int,
    ) -> StoreMutation:
        current = self._state.get(job_key)
        if current is None:
            return self._result("released_idempotent", generation)
        state, current_generation = current
        if current_generation != generation:
            return self._result("stale", current_generation)
        self._state.pop(job_key, None)
        self._expiry.pop((state, job_key), None)
        if workload == "extraction" and state == "ea":
            self._last_extraction_activity_ms = now_ms
        return self._result("released", generation)

    def _move(
        self,
        job_key: str,
        old_state: str,
        new_state: str,
        generation: int,
        expires_at: int,
    ) -> None:
        self._expiry.pop((old_state, job_key), None)
        self._state[job_key] = (new_state, generation)
        self._expiry[(new_state, job_key)] = expires_at

    def _count(self, state: str) -> int:
        return sum(current_state == state for current_state, _ in self._state.values())

    def _result(
        self,
        code: str,
        generation: int,
        *,
        retry_after_ms: int = 0,
    ) -> StoreMutation:
        return StoreMutation(
            code=code,
            generation=generation,
            counts=QueueCounts(
                extraction_waiting=self._count("ew"),
                extraction_dispatching=self._count("ed"),
                extraction_active=self._count("ea"),
                verification_waiting=self._count("vw"),
                verification_active=self._count("va"),
            ),
            retry_after_ms=retry_after_ms,
        )


class AiPriorityCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = _Clock()
        self.store = _AtomicMemoryStore()
        self.config = AiPriorityConfig(
            extraction_max_concurrency=4,
            verification_max_concurrency=2,
            extraction_timeout_ms=1_000,
            verification_timeout_ms=1_000,
            extraction_quiet_period_ms=100,
            retry_max_attempts=3,
            waiting_lease_ms=2_000,
            dispatching_lease_ms=1_000,
            lease_grace_ms=100,
            admission_retry_ms=10,
        )
        self.coordinator = self._coordinator()

    def _coordinator(self) -> AiPriorityCoordinator:
        return AiPriorityCoordinator(
            store=self.store,
            config=self.config,
            metrics_sink=_NoopMetrics(),  # type: ignore[arg-type]
            clock_ms=self.clock,
        )

    def test_waiting_dispatching_and_active_extraction_each_block_verification(
        self,
    ) -> None:
        extraction = self.coordinator.queue_extraction("extract-1")
        waiting = self.coordinator.try_start_verification("verify-waiting")
        self.assertEqual(waiting.reason, "deferred_extraction_priority")

        self.assertTrue(self.coordinator.mark_extraction_dispatched(extraction))
        dispatching = self.coordinator.try_start_verification("verify-dispatching")
        self.assertEqual(dispatching.reason, "deferred_extraction_priority")

        active = self.coordinator.try_start_extraction("extract-1")
        self.assertTrue(active.admitted)
        blocked = self.coordinator.try_start_verification("verify-active")
        self.assertEqual(blocked.reason, "deferred_extraction_priority")

    def test_atomic_transition_never_admits_verification_after_demand_exists(
        self,
    ) -> None:
        self.coordinator.queue_extraction("extract-race")
        barrier = threading.Barrier(2)

        def start_extraction():  # type: ignore[no-untyped-def]
            barrier.wait()
            return self._coordinator().try_start_extraction("extract-race")

        def start_verification():  # type: ignore[no-untyped-def]
            barrier.wait()
            return self._coordinator().try_start_verification("verify-race")

        with ThreadPoolExecutor(max_workers=2) as pool:
            extraction_future = pool.submit(start_extraction)
            verification_future = pool.submit(start_verification)
        self.assertTrue(extraction_future.result().admitted)
        self.assertEqual(
            verification_future.result().status,
            AdmissionStatus.DEFERRED,
        )

    def test_one_hundred_concurrent_admissions_obey_global_capacity(self) -> None:
        for index in range(100):
            self.coordinator.queue_extraction(f"extract-{index}")
        with ThreadPoolExecutor(max_workers=24) as pool:
            decisions = list(
                pool.map(
                    lambda index: self._coordinator().try_start_extraction(
                        f"extract-{index}"
                    ),
                    range(100),
                )
            )
        admitted = [decision for decision in decisions if decision.admitted]
        deferred = [
            decision
            for decision in decisions
            if decision.status == AdmissionStatus.DEFERRED
        ]
        self.assertEqual(len(admitted), 4)
        self.assertEqual(len(deferred), 96)
        self.assertEqual(self.coordinator.snapshot().extraction_active, 4)

    def test_quiet_period_then_verification_resume(self) -> None:
        extraction = self.coordinator.try_start_extraction("extract-quiet")
        self.assertTrue(extraction.admitted)
        self.assertTrue(self.coordinator.release(extraction.lease))

        deferred = self.coordinator.try_start_verification("verify-quiet")
        self.assertEqual(deferred.reason, "deferred_quiet_period")
        self.clock.advance(101)
        resumed = self.coordinator.try_start_verification("verify-quiet")
        self.assertTrue(resumed.admitted)

    def test_active_verification_can_finish_after_extraction_arrives(self) -> None:
        verification = self.coordinator.try_start_verification("verify-active")
        self.assertTrue(verification.admitted)
        extraction = self.coordinator.try_start_extraction("extract-arrived")
        self.assertTrue(extraction.admitted)
        self.assertTrue(self.coordinator.heartbeat(verification.lease))
        self.assertTrue(self.coordinator.release(verification.lease))

    def test_distributed_instances_share_capacity_and_state(self) -> None:
        first = self._coordinator()
        second = self._coordinator()
        leases = [
            first.try_start_extraction(f"distributed-{index}")
            for index in range(4)
        ]
        self.assertTrue(all(decision.admitted for decision in leases))
        denied = second.try_start_extraction("distributed-overflow")
        self.assertEqual(denied.reason, "deferred_capacity")
        self.assertEqual(second.snapshot().extraction_active, 4)

    def test_expired_crash_lease_recovers_capacity(self) -> None:
        active = self.coordinator.try_start_extraction("extract-crashed")
        self.assertTrue(active.admitted)
        self.clock.advance(active.lease.lease_ms + 1)
        recovered = self.coordinator.try_start_extraction("extract-crashed")
        self.assertTrue(recovered.admitted)
        self.assertGreater(recovered.lease.generation, active.lease.generation)
        self.assertFalse(self.coordinator.release(active.lease))

    def test_redis_outage_is_fail_open_only_for_extraction(self) -> None:
        failing = AiPriorityCoordinator(
            store=_AtomicMemoryStore(fail=True),
            config=self.config,
            metrics_sink=_NoopMetrics(),  # type: ignore[arg-type]
            clock_ms=self.clock,
        )
        extraction = failing.try_start_extraction("extract-outage")
        verification = failing.try_start_verification("verify-outage")
        self.assertEqual(extraction.status, AdmissionStatus.FAIL_OPEN)
        self.assertTrue(extraction.admitted)
        self.assertEqual(verification.status, AdmissionStatus.DEFERRED)
        self.assertEqual(verification.reason, "redis_unavailable_fail_closed")

    def test_duplicate_start_and_release_are_idempotent(self) -> None:
        first = self.coordinator.try_start_extraction("extract-duplicate")
        duplicate = self.coordinator.try_start_extraction("extract-duplicate")
        self.assertTrue(first.admitted)
        self.assertEqual(duplicate.status, AdmissionStatus.DUPLICATE)
        self.assertEqual(
            duplicate.retry_after_ms,
            self.config.admission_retry_ms,
        )
        self.assertEqual(first.lease.generation, duplicate.lease.generation)
        self.assertTrue(self.coordinator.release(first.lease))
        self.assertTrue(self.coordinator.release(first.lease))

        next_generation = self.coordinator.queue_extraction("extract-duplicate")
        self.assertGreater(next_generation.generation, first.lease.generation)
        self.assertFalse(self.coordinator.release(first.lease))

    def test_capacity_deferral_preserves_waiting_lease(self) -> None:
        active = [
            self.coordinator.try_start_extraction(f"active-{index}")
            for index in range(self.config.extraction_max_concurrency)
        ]
        self.assertTrue(all(decision.admitted for decision in active))

        deferred = self.coordinator.try_start_extraction("waiting")
        self.assertEqual(deferred.reason, "deferred_capacity")

        self.clock.advance(self.config.extraction_active_lease_ms - 100)
        for decision in active:
            self.assertTrue(self.coordinator.heartbeat(decision.lease))
        self.clock.advance(101)

        counts = self.coordinator.snapshot()
        self.assertEqual(counts.extraction_active, len(active))
        self.assertEqual(counts.extraction_waiting, 1)

    def test_priority_deferral_preserves_verification_waiting_lease(
        self,
    ) -> None:
        extraction = self.coordinator.try_start_extraction("active")
        deferred = self.coordinator.try_start_verification("waiting")
        self.assertTrue(extraction.admitted)
        self.assertEqual(
            deferred.reason,
            "deferred_extraction_priority",
        )

        self.clock.advance(self.config.verification_active_lease_ms - 100)
        self.assertTrue(self.coordinator.heartbeat(extraction.lease))
        self.clock.advance(101)

        counts = self.coordinator.snapshot()
        self.assertEqual(counts.extraction_active, 1)
        self.assertEqual(counts.verification_waiting, 1)

    def test_lifecycle_metrics_span_first_queue_through_release(self) -> None:
        recording = _RecordingMetrics()
        coordinator = AiPriorityCoordinator(
            store=self.store,
            config=self.config,
            metrics_sink=recording,  # type: ignore[arg-type]
            clock_ms=self.clock,
        )

        decision = coordinator.try_start_extraction("timed-job")
        self.clock.advance(250)
        self.assertTrue(coordinator.release(decision.lease))
        self.assertTrue(coordinator.release(decision.lease))

        self.assertEqual(
            recording.lifecycle,
            [
                ("queued", "extraction", 1_000_000),
                ("started", "extraction", 1_000_000),
                ("completed", "extraction", 1_000_250),
            ],
        )

    def test_store_receives_only_fixed_length_job_fingerprints(self) -> None:
        raw_reference = "delegate@example.com:secret-upload-token"
        self.coordinator.queue_extraction(raw_reference)
        [stored] = self.store.seen_job_keys
        self.assertNotIn("delegate", stored)
        self.assertNotIn("secret", stored)
        self.assertEqual(len(stored), 64)

    def test_verification_concurrency_is_independent_and_bounded(self) -> None:
        first = self.coordinator.try_start_verification("verify-1")
        second = self.coordinator.try_start_verification("verify-2")
        third = self.coordinator.try_start_verification("verify-3")
        self.assertTrue(first.admitted)
        self.assertTrue(second.admitted)
        self.assertEqual(third.reason, "deferred_capacity")
        self.assertEqual(third.counts.verification_active, 2)

    def test_workload_values_are_non_sensitive(self) -> None:
        self.assertEqual(AiWorkload.EXTRACTION.value, "extraction")
        self.assertEqual(AiWorkload.VERIFICATION.value, "verification")


if __name__ == "__main__":
    unittest.main()
