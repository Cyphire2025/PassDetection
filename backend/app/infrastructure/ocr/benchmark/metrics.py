"""Dependency-free OCR accuracy and calibration metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

MRZ_FIELDS = ("mrz_line_1", "mrz_line_2")
NAME_FIELDS = ("surname", "given_names")
COUNTRY_FIELDS = ("nationality", "issuing_country")


@dataclass(frozen=True)
class BenchmarkMetrics:
    character_error_rate: float
    word_error_rate: float
    field_accuracy: float
    exact_document_accuracy: float
    mrz_accuracy: float
    passport_number_accuracy: float
    name_accuracy: float
    date_of_birth_accuracy: float
    date_of_expiry_accuracy: float
    country_accuracy: float
    mean_confidence: float
    calibration_error: float
    average_latency_ms: float = 0.0
    worst_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0


def _edit_distance(expected: list[T], actual: list[T]) -> int:
    previous = list(range(len(actual) + 1))
    for expected_index, expected_item in enumerate(expected, start=1):
        current = [expected_index]
        for actual_index, actual_item in enumerate(actual, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[actual_index] + 1,
                    previous[actual_index - 1] + (expected_item != actual_item),
                )
            )
        previous = current
    return previous[-1]


def calculate_metrics(
    expected_documents: list[dict[str, str]],
    actual_documents: list[dict[str, str]],
    confidences: list[float],
    durations_ms: list[float] | None = None,
) -> BenchmarkMetrics:
    if not expected_documents or len(expected_documents) != len(actual_documents):
        raise ValueError("Expected and actual benchmark document counts must match and be non-empty")
    if len(confidences) != len(expected_documents):
        raise ValueError("A confidence value is required for every benchmark document")

    char_errors = char_total = word_errors = word_total = correct_fields = field_total = 0
    group_hits: dict[str, int] = {
        "mrz": 0,
        "passport_number": 0,
        "name": 0,
        "date_of_birth": 0,
        "date_of_expiry": 0,
        "country": 0,
    }
    group_totals = dict.fromkeys(group_hits, 0)
    exact_documents = 0
    correctness: list[float] = []
    for expected, actual in zip(expected_documents, actual_documents, strict=True):
        document_correct = True
        document_field_hits = 0
        for field_name, expected_value in expected.items():
            actual_value = actual.get(field_name, "")
            expected_normalized = expected_value.strip().upper()
            actual_normalized = actual_value.strip().upper()
            char_errors += _edit_distance(list(expected_normalized), list(actual_normalized))
            char_total += max(1, len(expected_normalized))
            expected_words = expected_normalized.split()
            actual_words = actual_normalized.split()
            word_errors += _edit_distance(expected_words, actual_words)
            word_total += max(1, len(expected_words))
            field_total += 1
            if expected_normalized == actual_normalized:
                correct_fields += 1
                document_field_hits += 1
                _record_group_hit(field_name, group_hits)
            else:
                document_correct = False
            _record_group_total(field_name, group_totals)
        if document_correct:
            exact_documents += 1
        correctness.append(document_field_hits / max(1, len(expected)))

    mean_confidence = sum(confidences) / len(confidences)
    latency_values = durations_ms or []
    average_latency_ms = round(sum(latency_values) / len(latency_values), 2) if latency_values else 0.0
    worst_latency_ms = round(max(latency_values), 2) if latency_values else 0.0
    p95_latency_ms = _percentile(latency_values, 0.95)
    calibration_error = sum(
        abs(max(0.0, min(1.0, confidence)) - correct)
        for confidence, correct in zip(confidences, correctness, strict=True)
    ) / len(confidences)
    return BenchmarkMetrics(
        character_error_rate=round(char_errors / char_total, 4),
        word_error_rate=round(word_errors / word_total, 4),
        field_accuracy=round(correct_fields / field_total, 4),
        exact_document_accuracy=round(exact_documents / len(expected_documents), 4),
        mrz_accuracy=_group_accuracy(group_hits, group_totals, "mrz"),
        passport_number_accuracy=_group_accuracy(group_hits, group_totals, "passport_number"),
        name_accuracy=_group_accuracy(group_hits, group_totals, "name"),
        date_of_birth_accuracy=_group_accuracy(group_hits, group_totals, "date_of_birth"),
        date_of_expiry_accuracy=_group_accuracy(group_hits, group_totals, "date_of_expiry"),
        country_accuracy=_group_accuracy(group_hits, group_totals, "country"),
        mean_confidence=round(mean_confidence, 4),
        calibration_error=round(calibration_error, 4),
        average_latency_ms=average_latency_ms,
        worst_latency_ms=worst_latency_ms,
        p95_latency_ms=p95_latency_ms,
    )


def _record_group_hit(field_name: str, group_hits: dict[str, int]) -> None:
    if field_name in MRZ_FIELDS:
        group_hits["mrz"] += 1
    if field_name == "passport_number":
        group_hits["passport_number"] += 1
    if field_name in NAME_FIELDS:
        group_hits["name"] += 1
    if field_name == "date_of_birth":
        group_hits["date_of_birth"] += 1
    if field_name == "date_of_expiry":
        group_hits["date_of_expiry"] += 1
    if field_name in COUNTRY_FIELDS:
        group_hits["country"] += 1


def _record_group_total(field_name: str, group_totals: dict[str, int]) -> None:
    if field_name in MRZ_FIELDS:
        group_totals["mrz"] += 1
    if field_name == "passport_number":
        group_totals["passport_number"] += 1
    if field_name in NAME_FIELDS:
        group_totals["name"] += 1
    if field_name == "date_of_birth":
        group_totals["date_of_birth"] += 1
    if field_name == "date_of_expiry":
        group_totals["date_of_expiry"] += 1
    if field_name in COUNTRY_FIELDS:
        group_totals["country"] += 1


def _group_accuracy(group_hits: dict[str, int], group_totals: dict[str, int], key: str) -> float:
    total = group_totals[key]
    if total == 0:
        return 0.0
    return round(group_hits[key] / total, 4)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 2)
