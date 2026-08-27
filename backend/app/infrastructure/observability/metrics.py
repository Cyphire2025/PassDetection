"""In-process metrics registry with safe hooks for shared metric providers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol


class MetricsExportSink(Protocol):
    """Non-authoritative external sink; telemetry may never change a workflow."""

    def increment(self, name: str, amount: int = 1) -> None: ...

    def observe(self, name: str, value: float) -> None: ...

    def set_gauge(self, name: str, value: float) -> None: ...

    def close(self) -> None: ...


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
        self._gauges: dict[str, float] = {}
        self._snapshot_providers: dict[str, Callable[[], dict[str, Any]]] = {}
        self._export_sink: MetricsExportSink | None = None
        self._lock = RLock()

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount
            sink = self._export_sink
        self._export(sink, "increment", name, amount)

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self._histograms[name].observe(value)
            sink = self._export_sink
        self._export(sink, "observe", name, value)

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value
            sink = self._export_sink
        self._export(sink, "set_gauge", name, value)

    @staticmethod
    def _export(
        sink: MetricsExportSink | None,
        operation: str,
        name: str,
        value: int | float,
    ) -> None:
        if sink is None:
            return
        try:
            if operation == "increment":
                sink.increment(name, int(value))
            elif operation == "observe":
                sink.observe(name, float(value))
            else:
                sink.set_gauge(name, float(value))
        except Exception:
            # Metrics are diagnostic. A collector failure must never turn a
            # successful attendance, upload, or deletion command into a 500.
            return

    def configure_export_sink(self, sink: MetricsExportSink | None) -> None:
        """Atomically replace the process-local exporter and close the old one."""

        with self._lock:
            previous = self._export_sink
            self._export_sink = sink
        if previous is not None and previous is not sink:
            try:
                previous.close()
            except Exception:
                pass

    def close_export_sink(self) -> None:
        self.configure_export_sink(None)

    def register_snapshot_provider(
        self,
        name: str,
        provider: Callable[[], dict[str, Any]],
    ) -> None:
        """Register one bounded, non-authoritative shared metrics snapshot."""

        normalized = name.strip().replace("-", "_").replace(".", "_")
        if not normalized:
            raise ValueError("Snapshot provider name cannot be empty")
        with self._lock:
            self._snapshot_providers[normalized] = provider

    def unregister_snapshot_provider(self, name: str) -> None:
        normalized = name.strip().replace("-", "_").replace(".", "_")
        with self._lock:
            self._snapshot_providers.pop(normalized, None)

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

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snapshot = {
                "counters": dict(sorted(self._counters.items())),
                "gauges": dict(sorted(self._gauges.items())),
                "histograms": {
                    name: hist.snapshot()
                    for name, hist in sorted(self._histograms.items())
                },
            }
            providers = tuple(self._snapshot_providers.items())

        shared: dict[str, Any] = {}
        for name, provider in providers:
            try:
                shared[name] = provider()
            except Exception:
                # Diagnostics must remain available when an optional exporter
                # fails. Provider implementations own their detailed,
                # non-sensitive failure status.
                shared[name] = {
                    "status": "unavailable",
                    "source": "snapshot_provider_error",
                }
        if shared:
            snapshot["shared"] = shared
        return snapshot

    def _normalize_path(self, path: str) -> str:
        parts = path.strip("/").split("/")
        if (
            len(parts) >= 6
            and parts[:4] == ["api", "v1", "mobile", "trips"]
            and parts[5] == "my-photos"
        ):
            parts[4] = "trip_id"
            for marker, replacement in (
                ("photos", "asset_id"),
                ("download-authorizations", "authorization_id"),
            ):
                if marker in parts:
                    marker_index = parts.index(marker)
                    if marker_index + 1 < len(parts):
                        parts[marker_index + 1] = replacement
            return "_".join(parts)
        if path.startswith("/api/v1/passports/upload/"):
            return "passports_upload"
        if path.startswith("/api/v1/passports/"):
            return "passports"
        return path.strip("/").replace("/", "_") or "root"


metrics = MetricsRegistry()
