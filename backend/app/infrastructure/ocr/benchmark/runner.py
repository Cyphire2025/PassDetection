"""Reusable asynchronous OCR benchmark runner."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from app.application.interfaces.passport_extraction import IPassportExtractionService
from app.infrastructure.ocr.benchmark.dataset import BenchmarkDataset
from app.infrastructure.ocr.benchmark.metrics import BenchmarkMetrics, calculate_metrics


@dataclass(frozen=True)
class BenchmarkReport:
    dataset_name: str
    dataset_version: str
    case_count: int
    elapsed_seconds: float
    metrics: BenchmarkMetrics
    cases: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "dataset_version": self.dataset_version,
            "case_count": self.case_count,
            "elapsed_seconds": self.elapsed_seconds,
            "metrics": asdict(self.metrics),
            "cases": list(self.cases),
        }


class OCRBenchmarkRunner:
    def __init__(self, extraction_service: IPassportExtractionService) -> None:
        self._extraction_service = extraction_service

    async def run(self, dataset: BenchmarkDataset) -> BenchmarkReport:
        started = time.perf_counter()
        expected_documents: list[dict[str, str]] = []
        actual_documents: list[dict[str, str]] = []
        confidences: list[float] = []
        durations_ms: list[float] = []
        cases: list[dict[str, Any]] = []
        for case in dataset.cases:
            content = case.image_path.read_bytes()
            case_started = time.perf_counter()
            result = await self._extraction_service.extract(
                content,
                filename=case.image_path.name,
                content_type="image/jpeg",
            )
            measured_duration_ms = round((time.perf_counter() - case_started) * 1000, 2)
            diagnostics = result.confidence_score.get("diagnostics", {})
            duration_ms = float(diagnostics.get("total_duration_ms") or measured_duration_ms)
            actual = {
                key: str(value)
                for key, value in result.extracted_fields.items()
                if isinstance(value, str)
            }
            expected_documents.append(case.expected_fields)
            actual_documents.append(actual)
            confidences.append(result.overall_confidence)
            durations_ms.append(duration_ms)
            cases.append(
                {
                    "id": case.case_id,
                    "tags": list(case.tags),
                    "duration_ms": duration_ms,
                    "confidence": result.overall_confidence,
                    "expected": case.expected_fields,
                    "actual": actual,
                    "timing_report": result.confidence_score.get("timing_report", []),
                    "timings": result.confidence_score.get("timings", {}),
                    "diagnostics": diagnostics,
                    "cache": result.confidence_score.get("cache") or diagnostics.get("cache", {}),
                }
            )
        return BenchmarkReport(
            dataset_name=dataset.name,
            dataset_version=dataset.version,
            case_count=len(dataset.cases),
            elapsed_seconds=round(time.perf_counter() - started, 3),
            metrics=calculate_metrics(expected_documents, actual_documents, confidences, durations_ms),
            cases=tuple(cases),
        )
