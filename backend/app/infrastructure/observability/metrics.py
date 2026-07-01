"""In-process metrics registry for demo and lightweight production diagnostics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass
class Histogram:
    count: int = 0
    total: float = 0.0
    minimum: float | None = None
    maximum: float | None = None

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)

    def snapshot(self) -> dict[str, float | int | None]:
        return {
            "count": self.count,
            "avg": round(self.total / self.count, 4) if self.count else 0.0,
            "min": self.minimum,
            "max": self.maximum,
        }


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._histograms: defaultdict[str, Histogram] = defaultdict(Histogram)

    def increment(self, name: str, amount: int = 1) -> None:
        self._counters[name] += amount

    def observe(self, name: str, value: float) -> None:
        self._histograms[name].observe(value)

    def record_request(self, *, method: str, path: str, status_code: int, duration_ms: float) -> None:
        route = self._normalize_path(path)
        self.increment(f"http.requests.total.{method}.{status_code}.{route}")
        self.observe(f"http.requests.duration_ms.{method}.{route}", duration_ms)

    def record_ocr(self, *, duration_ms: float, confidence: float, fallback_used: bool, cache_hit: bool = False) -> None:
        self.increment("ocr.extractions.total")
        if fallback_used:
            self.increment("ocr.extractions.fallback_used")
        if cache_hit:
            self.increment("ocr.extractions.cache_hit")
        self.observe("ocr.extractions.duration_ms", duration_ms)
        self.observe("ocr.extractions.confidence", confidence)

    def record_ocr_stage(self, *, stage: str, duration_ms: float) -> None:
        normalized_stage = stage.strip().replace(".", "_").replace("-", "_") or "unknown"
        self.observe(f"ocr.stages.duration_ms.{normalized_stage}", duration_ms)

    def snapshot(self) -> dict:
        return {
            "counters": dict(sorted(self._counters.items())),
            "histograms": {name: hist.snapshot() for name, hist in sorted(self._histograms.items())},
        }

    def _normalize_path(self, path: str) -> str:
        if path.startswith("/api/v1/passports/upload/"):
            return "passports_upload"
        if path.startswith("/api/v1/passports/"):
            return "passports"
        return path.strip("/").replace("/", "_") or "root"


metrics = MetricsRegistry()
