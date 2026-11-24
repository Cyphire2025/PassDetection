"""Content-free counters for finding a broken native audio boundary."""

from __future__ import annotations

import audioop
import time
from typing import Any


class VoiceStreamDiagnostics:
    """Never retain audio, captions, user identifiers, or provider credentials."""

    def __init__(self) -> None:
        self.started = time.monotonic()
        self.input_frames = 0
        self.input_bytes = 0
        self.non_silent_frames = 0
        self.input_peak = 0
        self.output_frames = 0
        self.output_bytes = 0
        self.first_output_ms: int | None = None

    def input(self, pcm: bytes) -> None:
        self.input_frames += 1
        self.input_bytes += len(pcm)
        self.input_peak = max(self.input_peak, audioop.max(pcm, 2))
        if audioop.rms(pcm, 2) > 96:
            self.non_silent_frames += 1

    def sent(self, event: dict[str, Any]) -> None:
        if event.get("type") != "audio" or not isinstance(event.get("data"), str):
            return
        encoded = event["data"]
        self.output_frames += 1
        padding = len(encoded) - len(encoded.rstrip("="))
        self.output_bytes += len(encoded) * 3 // 4 - padding
        if self.first_output_ms is None:
            self.first_output_ms = round((time.monotonic() - self.started) * 1000)

    def summary(self) -> dict[str, int | float | None]:
        return {
            "elapsed_ms": round((time.monotonic() - self.started) * 1000),
            "input_frames": self.input_frames,
            "input_audio_ms": round(self.input_bytes / 32),
            "non_silent_input_frames": self.non_silent_frames,
            "input_peak": round(self.input_peak / 32768, 3),
            "output_frames": self.output_frames,
            "output_audio_ms": round(self.output_bytes / 48),
            "first_output_ms": self.first_output_ms,
        }
