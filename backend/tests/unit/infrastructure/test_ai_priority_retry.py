from __future__ import annotations

import unittest
from datetime import UTC, datetime

from app.infrastructure.ai_priority.retry import (
    parse_retry_after_ms,
    retry_after_delay_seconds,
)


class AiPriorityRetryTests(unittest.TestCase):
    def test_numeric_retry_after_is_parsed_in_milliseconds(self) -> None:
        self.assertEqual(parse_retry_after_ms("2.5"), 2_500)

    def test_http_date_retry_after_is_supported(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        self.assertEqual(
            parse_retry_after_ms(
                "Thu, 01 Jan 2026 00:00:03 GMT",
                now=now,
            ),
            3_000,
        )

    def test_invalid_retry_after_is_ignored(self) -> None:
        self.assertIsNone(parse_retry_after_ms("not-a-delay"))
        self.assertEqual(
            retry_after_delay_seconds(
                "not-a-delay",
                remaining_seconds=5,
                attempt_number=1,
                jitter_unit=0.5,
            ),
            0.25,
        )

    def test_non_finite_retry_after_is_ignored(self) -> None:
        for value in ("nan", "NaN", "inf", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                self.assertIsNone(parse_retry_after_ms(value))

    def test_retry_is_abandoned_when_header_exceeds_deadline(self) -> None:
        self.assertIsNone(
            retry_after_delay_seconds("10", remaining_seconds=5)
        )

    def test_absent_header_uses_exponential_backoff_with_injected_jitter(
        self,
    ) -> None:
        self.assertEqual(
            retry_after_delay_seconds(
                None,
                remaining_seconds=10,
                attempt_number=1,
                jitter_unit=0.5,
            ),
            0.25,
        )
        self.assertEqual(
            retry_after_delay_seconds(
                None,
                remaining_seconds=10,
                attempt_number=3,
                jitter_unit=0.5,
            ),
            1.0,
        )

    def test_jitter_and_backoff_are_bounded(self) -> None:
        self.assertEqual(
            retry_after_delay_seconds(
                None,
                remaining_seconds=10,
                attempt_number=3,
                jitter_unit=-10,
            ),
            0.75,
        )
        self.assertEqual(
            retry_after_delay_seconds(
                None,
                remaining_seconds=10,
                attempt_number=3,
                jitter_unit=10,
            ),
            1.25,
        )
        self.assertEqual(
            retry_after_delay_seconds(
                None,
                remaining_seconds=10,
                attempt_number=20,
                jitter_unit=10,
            ),
            2.0,
        )

    def test_backoff_is_abandoned_when_it_exceeds_deadline(self) -> None:
        self.assertIsNone(
            retry_after_delay_seconds(
                None,
                remaining_seconds=0.2,
                attempt_number=1,
                jitter_unit=0.5,
            )
        )


if __name__ == "__main__":
    unittest.main()
