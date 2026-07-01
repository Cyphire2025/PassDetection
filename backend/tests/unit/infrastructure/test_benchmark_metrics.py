from __future__ import annotations

import unittest

from app.infrastructure.ocr.benchmark.metrics import calculate_metrics


class BenchmarkMetricsTests(unittest.TestCase):
    def test_exact_document_accuracy_and_field_accuracy(self) -> None:
        metrics = calculate_metrics(
            expected_documents=[
                {
                    "passport_number": "A1234567",
                    "surname": "DOE",
                }
            ],
            actual_documents=[
                {
                    "passport_number": "A1234567",
                    "surname": "DOE",
                }
            ],
            confidences=[0.95],
        )

        self.assertEqual(metrics.field_accuracy, 1.0)
        self.assertEqual(metrics.exact_document_accuracy, 1.0)
        self.assertEqual(metrics.character_error_rate, 0.0)
        self.assertEqual(metrics.word_error_rate, 0.0)
        self.assertEqual(metrics.passport_number_accuracy, 1.0)
        self.assertEqual(metrics.name_accuracy, 1.0)

    def test_partial_error_is_reflected_in_character_error_rate(self) -> None:
        metrics = calculate_metrics(
            expected_documents=[{"passport_number": "A1234567"}],
            actual_documents=[{"passport_number": "A1234568"}],
            confidences=[0.9],
        )

        self.assertLess(metrics.field_accuracy, 1.0)
        self.assertGreater(metrics.character_error_rate, 0.0)
        self.assertEqual(metrics.passport_number_accuracy, 0.0)

    def test_latency_metrics_are_reported_when_durations_are_supplied(self) -> None:
        metrics = calculate_metrics(
            expected_documents=[
                {"passport_number": "A1234567"},
                {"passport_number": "B1234567"},
            ],
            actual_documents=[
                {"passport_number": "A1234567"},
                {"passport_number": "B1234567"},
            ],
            confidences=[0.9, 0.95],
            durations_ms=[120.0, 240.0],
        )

        self.assertEqual(metrics.average_latency_ms, 180.0)
        self.assertEqual(metrics.worst_latency_ms, 240.0)
        self.assertEqual(metrics.p95_latency_ms, 240.0)


if __name__ == "__main__":
    unittest.main()
