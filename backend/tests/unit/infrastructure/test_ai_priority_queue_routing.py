"""Queue topology and Redis adapter contract tests."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import BackgroundTasks

from app.core.config.settings import Settings
from app.infrastructure.ai_priority import (
    EXTRACTION_QUEUE,
    PREPARED_SETTING_NAMES,
    VERIFICATION_QUEUE,
)
from app.infrastructure.ai_priority.redis_store import (
    _MUTATE_SCRIPT,
    RedisPriorityStore,
)
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.processing.dispatcher import PassportProcessingDispatcher
from app.infrastructure.verification.dispatcher import (
    PostSubmissionVerificationDispatcher,
)


class _CapturingRedis:
    def __init__(self) -> None:
        self.call: tuple | None = None

    def eval(self, *args):  # type: ignore[no-untyped-def]
        self.call = args
        return [b"registered", b"7", b"1", b"0", b"0", b"0", b"0", b"0"]


class _Priority:
    def queue_extraction(self, job_reference: str) -> object:
        return object()

    def mark_extraction_dispatched(self, lease: object) -> bool:
        return True

    def queue_verification(self, job_reference: str) -> object:
        return object()


class AiPriorityQueueRoutingTests(unittest.TestCase):
    def test_exact_durable_queue_names_and_routes(self) -> None:
        self.assertEqual(EXTRACTION_QUEUE, "interactive-passport-extraction")
        self.assertEqual(
            VERIFICATION_QUEUE,
            "post-submission-ai-verification",
        )
        routes = celery_app.conf.task_routes
        self.assertEqual(
            routes["passport.process_submission"]["queue"],
            EXTRACTION_QUEUE,
        )
        self.assertEqual(
            routes["passport.verify_submitted"]["queue"],
            VERIFICATION_QUEUE,
        )
        queues = {queue.name: queue for queue in celery_app.conf.task_queues}
        self.assertTrue(queues[EXTRACTION_QUEUE].durable)
        self.assertTrue(queues[VERIFICATION_QUEUE].durable)

    def test_processing_dispatcher_publishes_to_extraction_queue(self) -> None:
        task = SimpleNamespace(
            apply_async=lambda **kwargs: SimpleNamespace(
                id="task-id",
                captured=kwargs,
            )
        )
        with patch.dict(
            "sys.modules",
            {
                "app.infrastructure.processing.tasks": SimpleNamespace(
                    process_passport_submission=task
                )
            },
        ):
            result = PassportProcessingDispatcher._send_celery(
                job_id=uuid.uuid4(),
                submission_id=uuid.uuid4(),
            )
        self.assertEqual(result.captured["queue"], EXTRACTION_QUEUE)

    def test_verification_dispatcher_publishes_to_verification_queue(self) -> None:
        task = SimpleNamespace(
            apply_async=lambda **kwargs: SimpleNamespace(
                id="task-id",
                captured=kwargs,
            )
        )
        with patch.dict(
            "sys.modules",
            {
                "app.infrastructure.verification.tasks": SimpleNamespace(
                    verify_submitted_passport=task
                )
            },
        ):
            result = PostSubmissionVerificationDispatcher._send_celery(
                job_id=uuid.uuid4(),
                submission_id=uuid.uuid4(),
                verification_revision=3,
            )
        self.assertEqual(result.captured["queue"], VERIFICATION_QUEUE)

    def test_verification_dispatch_records_backlog_before_publish(self) -> None:
        priority = _Priority()
        background_tasks = BackgroundTasks()
        with patch.object(
            PostSubmissionVerificationDispatcher,
            "_send_celery",
            return_value=SimpleNamespace(id="verification-task"),
        ):
            task_id = PostSubmissionVerificationDispatcher(
                backend="celery",
                priority_coordinator=priority,  # type: ignore[arg-type]
            ).dispatch(
                job_id=uuid.uuid4(),
                submission_id=uuid.uuid4(),
                verification_revision=1,
                background_tasks=background_tasks,
            )
        self.assertEqual(task_id, "verification-task")

    def test_redis_adapter_uses_one_cluster_slot_and_one_eval(self) -> None:
        redis = _CapturingRedis()
        store = RedisPriorityStore(redis)
        result = store.mutate(
            operation="register_extraction",
            job_key="a" * 64,
            generation=0,
            now_ms=123,
            lease_ms=1_000,
            waiting_lease_ms=5_000,
            max_concurrency=2,
            quiet_period_ms=50,
        )
        self.assertEqual(result.generation, 7)
        self.assertIsNotNone(redis.call)
        assert redis.call is not None
        self.assertEqual(redis.call[1], 8)
        redis_keys = redis.call[2:10]
        self.assertTrue(all("{ai-priority}" in key for key in redis_keys))
        self.assertEqual(redis.call[11], "a" * 64)

    def test_redis_script_owns_time_and_preserves_waiting_lease(self) -> None:
        self.assertIn('redis.call("TIME")', _MUTATE_SCRIPT)
        self.assertNotIn("tonumber(ARGV[4])", _MUTATE_SCRIPT)
        self.assertEqual(
            _MUTATE_SCRIPT.count("now_ms + waiting_lease_ms"),
            4,
        )

    def test_operational_settings_are_declared_and_bounded(self) -> None:
        expected = {
            "GEMINI_EXTRACTION_MAX_CONCURRENCY",
            "GEMINI_VERIFICATION_MAX_CONCURRENCY",
            "GEMINI_EXTRACTION_TIMEOUT_MS",
            "GEMINI_EXTRACTION_QUIET_PERIOD_MS",
            "GEMINI_RETRY_MAX_ATTEMPTS",
            "GEMINI_PRIORITY_CAPACITY_CALIBRATED",
        }
        self.assertEqual(set(PREPARED_SETTING_NAMES), expected)
        settings = Settings(
            app_secret_key="unit-test-secret",
            gemini_extraction_max_concurrency=6,
            gemini_verification_max_concurrency=2,
            gemini_extraction_timeout_ms=20_000,
            gemini_extraction_quiet_period_ms=750,
            gemini_retry_max_attempts=4,
        )
        self.assertEqual(settings.gemini_extraction_max_concurrency, 6)
        self.assertEqual(settings.gemini_verification_max_concurrency, 2)
        self.assertEqual(settings.gemini_extraction_timeout_ms, 20_000)
        self.assertEqual(settings.gemini_extraction_quiet_period_ms, 750)
        self.assertEqual(settings.gemini_retry_max_attempts, 4)


if __name__ == "__main__":
    unittest.main()
