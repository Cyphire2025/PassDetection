"""Per-extraction diagnostics and processing-budget tracking."""

from __future__ import annotations

import time
import tracemalloc
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.infrastructure.ocr.versioning import (
    CONFIDENCE_VERSION,
    INDIAN_TD3_DOCUMENT_PROFILE,
    OCR_LOGIC_VERSION,
    PIPELINE_VERSION,
)


def _round_ms(value: float) -> float:
    return round(value * 1000, 2)


def _json_safe(value: Any) -> Any:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


@dataclass
class ProcessingBudget:
    """Tracks the extraction budget without forcing arbitrary per-stage timeouts."""

    total_ms: float
    started_at: float = field(default_factory=time.perf_counter)

    @classmethod
    def from_seconds(cls, total_seconds: float) -> ProcessingBudget:
        return cls(total_ms=round(max(0.0, total_seconds) * 1000, 2))

    def elapsed_ms(self) -> float:
        return _round_ms(time.perf_counter() - self.started_at)

    def remaining_ms(self) -> float:
        return round(max(0.0, self.total_ms - self.elapsed_ms()), 2)

    def snapshot(self) -> dict[str, float | bool]:
        elapsed = self.elapsed_ms()
        remaining = round(max(0.0, self.total_ms - elapsed), 2)
        return {
            "total_ms": self.total_ms,
            "elapsed_ms": elapsed,
            "remaining_ms": remaining,
            "over_budget": elapsed > self.total_ms,
        }


@dataclass(frozen=True)
class StageTiming:
    name: str
    started_at_epoch_ms: float
    ended_at_epoch_ms: float
    started_offset_ms: float
    ended_offset_ms: float
    duration_ms: float
    cpu_ms: float
    memory_delta_kb: float | None
    memory_peak_kb: float | None
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "started_at_epoch_ms": self.started_at_epoch_ms,
            "ended_at_epoch_ms": self.ended_at_epoch_ms,
            "started_offset_ms": self.started_offset_ms,
            "ended_offset_ms": self.ended_offset_ms,
            "duration_ms": self.duration_ms,
            "cpu_ms": self.cpu_ms,
            "memory_delta_kb": self.memory_delta_kb,
            "memory_peak_kb": self.memory_peak_kb,
            "metadata": _json_safe(self.metadata),
        }


class PipelineTrace:
    """Collects explainable OCR diagnostics for one extraction."""

    def __init__(
        self,
        *,
        filename: str,
        content_type: str,
        budget: ProcessingBudget,
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        self.budget = budget
        self._started_perf = time.perf_counter()
        self._started_epoch = time.time()
        self._stages: list[StageTiming] = []
        self._skipped_stages: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._cache: dict[str, Any] = {"hit": False}
        self._early_exit: dict[str, Any] | None = None
        self._memory_tracing_available = self._ensure_memory_tracing()

    def stage(self, name: str, **metadata: Any) -> StageRecorder:
        return StageRecorder(self, name, metadata)

    def skip_stage(self, name: str, *, reason: str, **metadata: Any) -> None:
        self._skipped_stages.append(
            {
                "name": name,
                "reason": reason,
                "offset_ms": self.elapsed_ms(),
                "budget": self.budget.snapshot(),
                "metadata": _json_safe(metadata),
            }
        )

    def add_event(self, name: str, **metadata: Any) -> None:
        self._events.append(
            {
                "name": name,
                "offset_ms": self.elapsed_ms(),
                "budget": self.budget.snapshot(),
                "metadata": _json_safe(metadata),
            }
        )

    def set_cache(self, *, hit: bool, **metadata: Any) -> None:
        self._cache = {"hit": hit, **_json_safe(metadata)}

    def mark_early_exit(self, reason: str, **metadata: Any) -> None:
        self._early_exit = {
            "reason": reason,
            "offset_ms": self.elapsed_ms(),
            "budget": self.budget.snapshot(),
            "metadata": _json_safe(metadata),
        }

    def elapsed_ms(self) -> float:
        return _round_ms(time.perf_counter() - self._started_perf)

    def duration_ms_for(self, *names: str) -> float:
        selected = set(names)
        return round(sum(stage.duration_ms for stage in self._stages if stage.name in selected), 2)

    def timing_report(self) -> list[str]:
        if not self._stages:
            return []
        width = max(len(stage.name.replace("_", " ").title()) for stage in self._stages)
        return [
            f"{stage.name.replace('_', ' ').title():.<{width + 3}} {stage.duration_ms:.2f} ms"
            for stage in self._stages
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_version": PIPELINE_VERSION,
            "ocr_logic_version": OCR_LOGIC_VERSION,
            "confidence_version": CONFIDENCE_VERSION,
            "document_profile": INDIAN_TD3_DOCUMENT_PROFILE,
            "filename": self.filename,
            "content_type": self.content_type,
            "started_at_epoch_ms": round(self._started_epoch * 1000, 2),
            "total_duration_ms": self.elapsed_ms(),
            "budget": self.budget.snapshot(),
            "cache": _json_safe(self._cache),
            "early_exit": self._early_exit,
            "stages": [stage.to_dict() for stage in self._stages],
            "skipped_stages": list(self._skipped_stages),
            "events": list(self._events),
            "timing_report": self.timing_report(),
        }

    def _append_stage(self, timing: StageTiming) -> None:
        self._stages.append(timing)

    @staticmethod
    def _ensure_memory_tracing() -> bool:
        try:
            if not tracemalloc.is_tracing():
                tracemalloc.start()
            return tracemalloc.is_tracing()
        except Exception:
            return False


class StageRecorder:
    def __init__(self, trace: PipelineTrace, name: str, metadata: dict[str, Any]) -> None:
        self._trace = trace
        self._name = name
        self._metadata = metadata
        self._started_perf = 0.0
        self._started_cpu = 0.0
        self._started_epoch = 0.0
        self._started_memory_kb: float | None = None

    def __enter__(self) -> StageRecorder:
        self._started_perf = time.perf_counter()
        self._started_cpu = time.process_time()
        self._started_epoch = time.time()
        if self._trace._memory_tracing_available:
            current, _peak = tracemalloc.get_traced_memory()
            self._started_memory_kb = round(current / 1024, 2)
        self._metadata.setdefault("budget_start", self._trace.budget.snapshot())
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        ended_perf = time.perf_counter()
        ended_epoch = time.time()
        memory_delta_kb: float | None = None
        memory_peak_kb: float | None = None
        if self._trace._memory_tracing_available:
            current, peak = tracemalloc.get_traced_memory()
            current_kb = round(current / 1024, 2)
            memory_peak_kb = round(peak / 1024, 2)
            if self._started_memory_kb is not None:
                memory_delta_kb = round(current_kb - self._started_memory_kb, 2)
        self._metadata.setdefault("budget_end", self._trace.budget.snapshot())
        if exc is not None:
            self._metadata["error"] = str(exc)
        self._trace._append_stage(
            StageTiming(
                name=self._name,
                started_at_epoch_ms=round(self._started_epoch * 1000, 2),
                ended_at_epoch_ms=round(ended_epoch * 1000, 2),
                started_offset_ms=_round_ms(self._started_perf - self._trace._started_perf),
                ended_offset_ms=_round_ms(ended_perf - self._trace._started_perf),
                duration_ms=_round_ms(ended_perf - self._started_perf),
                cpu_ms=_round_ms(time.process_time() - self._started_cpu),
                memory_delta_kb=memory_delta_kb,
                memory_peak_kb=memory_peak_kb,
                metadata=dict(self._metadata),
            )
        )
        return False

    def set(self, **metadata: Any) -> None:
        self._metadata.update(metadata)
