from __future__ import annotations

import importlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.config.settings import Settings
from app.infrastructure.ai_priority import EXTRACTION_QUEUE, VERIFICATION_QUEUE
from app.infrastructure.ai_priority.worker_readiness import (
    CachedCeleryQueueProbe,
    CeleryQueueSnapshot,
    _queue_names_from_replies,
    celery_queue_available,
    gemini_worker_readiness,
)

_STRONG_APP_SECRET = "9Wv!mR3#kP7@xN2$zQ8&bL5^tY4*cH6+"


class AiPriorityWorkerReadinessTests(unittest.TestCase):
    def test_module_import_is_safe_without_eager_celery_import(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import app.infrastructure.ai_priority.worker_readiness "
                    "as module; "
                    "import sys; "
                    "assert module._queue_probe is not None; "
                    "assert 'app.infrastructure.processing.celery_app' "
                    "not in sys.modules"
                ),
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[3],
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_probe_caches_one_bounded_query_until_ttl_expires(self) -> None:
        clock = [10.0]
        calls: list[float] = []

        def query(timeout_seconds: float) -> CeleryQueueSnapshot:
            calls.append(timeout_seconds)
            return CeleryQueueSnapshot(
                available_queues=frozenset(
                    {EXTRACTION_QUEUE, VERIFICATION_QUEUE}
                ),
                control_reachable=True,
            )

        probe = CachedCeleryQueueProbe(
            query=query,
            clock=lambda: clock[0],
        )
        first = probe.snapshot(timeout_seconds=0.7, cache_seconds=15.0)
        second = probe.snapshot(timeout_seconds=0.7, cache_seconds=15.0)
        self.assertIs(first, second)
        self.assertEqual(calls, [0.7])

        clock[0] = 25.1
        probe.snapshot(timeout_seconds=0.7, cache_seconds=15.0)
        self.assertEqual(calls, [0.7, 0.7])

    def test_probe_fail_closed_result_is_cached(self) -> None:
        calls = 0

        def query(_timeout_seconds: float) -> CeleryQueueSnapshot:
            nonlocal calls
            calls += 1
            raise TimeoutError("control timeout")

        probe = CachedCeleryQueueProbe(query=query, clock=lambda: 10.0)
        first = probe.snapshot(timeout_seconds=1.0, cache_seconds=15.0)
        second = probe.snapshot(timeout_seconds=1.0, cache_seconds=15.0)
        self.assertEqual(calls, 1)
        self.assertFalse(first.control_reachable)
        self.assertEqual(first, second)

    def test_production_celery_requires_both_exact_ai_queues(self) -> None:
        settings = Settings(
            app_secret_key=_STRONG_APP_SECRET,
            app_env="production",
            processing_backend="celery",
        )
        missing_verification = CachedCeleryQueueProbe(
            query=lambda _timeout: CeleryQueueSnapshot(
                available_queues=frozenset({EXTRACTION_QUEUE}),
                control_reachable=True,
            ),
        )
        checks, ready = gemini_worker_readiness(
            settings,
            probe=missing_verification,
        )
        self.assertFalse(ready)
        self.assertEqual(checks["gemini_extraction_worker"], "available")
        self.assertEqual(
            checks["gemini_verification_worker"],
            "queue_not_consumed",
        )

        both = CachedCeleryQueueProbe(
            query=lambda _timeout: CeleryQueueSnapshot(
                available_queues=frozenset(
                    {EXTRACTION_QUEUE, VERIFICATION_QUEUE}
                ),
                control_reachable=True,
            ),
        )
        checks, ready = gemini_worker_readiness(settings, probe=both)
        self.assertTrue(ready)
        self.assertEqual(checks["celery_worker_control"], "reachable")

    def test_disabled_verification_still_requires_extraction_worker(self) -> None:
        settings = Settings(
            app_secret_key=_STRONG_APP_SECRET,
            app_env="production",
            processing_backend="celery",
            gemini_verification_enabled=False,
        )
        probe = CachedCeleryQueueProbe(
            query=lambda _timeout: CeleryQueueSnapshot(
                available_queues=frozenset({EXTRACTION_QUEUE}),
                control_reachable=True,
            ),
        )
        checks, ready = gemini_worker_readiness(settings, probe=probe)
        self.assertTrue(ready)
        self.assertEqual(
            checks["gemini_verification_worker"],
            "not_required_verification_disabled",
        )

    def test_staging_celery_also_requires_queue_consumers(self) -> None:
        settings = Settings(
            app_secret_key=_STRONG_APP_SECRET,
            app_env="staging",
            processing_backend="celery",
        )
        probe = CachedCeleryQueueProbe(
            query=lambda _timeout: CeleryQueueSnapshot(
                available_queues=frozenset(),
                control_reachable=False,
            ),
        )
        checks, ready = gemini_worker_readiness(settings, probe=probe)
        self.assertFalse(ready)
        self.assertEqual(checks["celery_worker_control"], "unreachable")

    def test_background_backend_skips_control_query(self) -> None:
        query = Mock()
        probe = CachedCeleryQueueProbe(query=query)
        production_background = Settings(
            app_secret_key=_STRONG_APP_SECRET,
            app_env="production",
            processing_backend="background",
        )
        _, ready = gemini_worker_readiness(
            production_background,
            probe=probe,
        )
        self.assertTrue(ready)
        query.assert_not_called()

    def test_queue_parser_uses_only_named_active_queues(self) -> None:
        names = _queue_names_from_replies(
            {
                "extraction@worker": [
                    {"name": EXTRACTION_QUEUE},
                    {"name": ""},
                ],
                "verification@worker": [
                    {"name": VERIFICATION_QUEUE},
                    {"routing_key": "ignored"},
                ],
            }
        )
        self.assertEqual(names, {EXTRACTION_QUEUE, VERIFICATION_QUEUE})

    def test_exact_queue_probe_requires_control_and_named_queue(self) -> None:
        with patch(
            "app.infrastructure.ai_priority.worker_readiness."
            "_query_active_queues",
            return_value=CeleryQueueSnapshot(
                available_queues=frozenset({EXTRACTION_QUEUE}),
                control_reachable=True,
            ),
        ) as query:
            self.assertTrue(
                celery_queue_available(
                    EXTRACTION_QUEUE,
                    timeout_seconds=0.75,
                )
            )
            self.assertFalse(
                celery_queue_available(
                    VERIFICATION_QUEUE,
                    timeout_seconds=0.75,
                )
            )

        self.assertEqual(query.call_count, 2)

    def test_container_healthcheck_requires_all_expected_queues(self) -> None:
        healthcheck = importlib.import_module(
            "app.infrastructure.ai_priority.worker_healthcheck"
        )
        with patch.object(
            healthcheck,
            "_active_queues_for_worker",
            return_value=frozenset({"passport_ocr", "whatsapp"}),
        ):
            self.assertEqual(
                healthcheck.main(
                    [
                        "--destination",
                        "general@worker",
                        "--queue",
                        "passport_ocr",
                        "--queue",
                        "whatsapp",
                    ]
                ),
                0,
            )
            self.assertEqual(
                healthcheck.main(
                    [
                        "--destination",
                        "general@worker",
                        "--queue",
                        "missing",
                    ]
                ),
                1,
            )
            self.assertEqual(
                healthcheck.main(
                    [
                        "--destination",
                        "general@worker",
                        "--queue",
                        "passport_ocr",
                        "--timeout",
                        "6",
                    ]
                ),
                2,
            )


if __name__ == "__main__":
    unittest.main()
