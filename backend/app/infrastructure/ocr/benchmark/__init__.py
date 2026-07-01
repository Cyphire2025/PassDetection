"""OCR benchmark and confidence calibration framework."""

from app.infrastructure.ocr.benchmark.dataset import BenchmarkCase, BenchmarkDataset
from app.infrastructure.ocr.benchmark.metrics import BenchmarkMetrics, calculate_metrics
from app.infrastructure.ocr.benchmark.runner import BenchmarkReport, OCRBenchmarkRunner

__all__ = [
    "BenchmarkCase",
    "BenchmarkDataset",
    "BenchmarkMetrics",
    "BenchmarkReport",
    "OCRBenchmarkRunner",
    "calculate_metrics",
]
