from __future__ import annotations

import unittest

from app.infrastructure.observability.metrics import MetricsRegistry
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    OperationalEventMetrics,
    is_allowed_operational_reason,
    parse_public_operational_event,
)


class _CounterStore:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def increment(self, name: str, amount: int = 1) -> None:
        self.values[name] = self.values.get(name, 0) + amount


class _FailingCounterStore:
    def increment(self, _name: str, _amount: int = 1) -> None:
        raise ConnectionError("redis://user:password@private-host")


class OperationalEventMetricsTests(unittest.TestCase):
    def test_records_only_fixed_low_cardinality_event_and_reason(self) -> None:
        registry = MetricsRegistry()
        shared = _CounterStore()
        sink = OperationalEventMetrics(
            registry=registry,
            shared_store=shared,
        )

        sink.record(
            OperationalEvent.DOCUMENT_CLASSIFICATION,
            "wrong_document",
        )

        expected_total = (
            "travel_flow.events.total.document_classification"
        )
        expected_reason = (
            "travel_flow.events.reason.document_classification.wrong_document"
        )
        self.assertEqual(registry.snapshot()["counters"][expected_total], 1)
        self.assertEqual(registry.snapshot()["counters"][expected_reason], 1)
        self.assertEqual(shared.values[expected_total], 1)
        self.assertEqual(shared.values[expected_reason], 1)

    def test_arbitrary_reason_is_collapsed_to_other(self) -> None:
        registry = MetricsRegistry()
        sink = OperationalEventMetrics(
            registry=registry,
            shared_store=_CounterStore(),
        )

        sink.record(
            OperationalEvent.UPLOAD_RESULT,
            "passport-P1234567-client@example.com",
        )

        counters = registry.snapshot()["counters"]
        serialized = repr(counters)
        self.assertIn(
            "travel_flow.events.reason.upload_result.other",
            counters,
        )
        self.assertNotIn("P1234567", serialized)
        self.assertNotIn("client@example.com", serialized)

    def test_shared_failure_preserves_local_counter(self) -> None:
        registry = MetricsRegistry()
        sink = OperationalEventMetrics(
            registry=registry,
            shared_store=_FailingCounterStore(),
        )

        sink.record(OperationalEvent.RATE_LIMIT, "app_api")

        self.assertEqual(
            registry.snapshot()["counters"][
                "travel_flow.events.reason.rate_limit.app_api"
            ],
            1,
        )

    def test_non_positive_amount_is_rejected(self) -> None:
        sink = OperationalEventMetrics(
            registry=MetricsRegistry(),
            shared_store=_CounterStore(),
        )
        with self.assertRaises(ValueError):
            sink.record(
                OperationalEvent.PUBLIC_FLOW,
                "connectivity_lost",
                amount=0,
            )

    def test_public_parser_allows_only_client_flow_event_families(self) -> None:
        self.assertEqual(
            parse_public_operational_event("visa_photo_rejection"),
            OperationalEvent.VISA_PHOTO_REJECTION,
        )
        self.assertEqual(
            parse_public_operational_event("passport_scanner_rejection"),
            OperationalEvent.PASSPORT_SCANNER_REJECTION,
        )
        self.assertEqual(
            parse_public_operational_event("public_flow"),
            OperationalEvent.PUBLIC_FLOW,
        )
        self.assertIsNone(parse_public_operational_event("staff_approval"))
        self.assertIsNone(parse_public_operational_event("arbitrary"))

    def test_public_reason_validation_is_event_specific(self) -> None:
        self.assertTrue(
            is_allowed_operational_reason(
                OperationalEvent.VISA_PHOTO_REJECTION,
                "eyewear_detected",
            )
        )
        self.assertFalse(
            is_allowed_operational_reason(
                OperationalEvent.PASSPORT_SCANNER_REJECTION,
                "eyewear_detected",
            )
        )


if __name__ == "__main__":
    unittest.main()
