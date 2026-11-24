"""Bounded exception identity and frames without message, arguments or locals."""

from __future__ import annotations

import re
from collections import deque
from types import TracebackType

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,159}\Z")


def diagnostic_name(value: object, default: str = "unknown") -> str:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else default


def diagnostic_frames(
    trace: TracebackType | None,
    *,
    unavailable: str = "No exception stack frames available",
) -> str:
    frames: deque[str] = deque(maxlen=16)
    while trace is not None:
        frame = trace.tb_frame
        module = diagnostic_name(frame.f_globals.get("__name__"))
        function = diagnostic_name(frame.f_code.co_name)
        frames.append(f"{module}:{function}:{trace.tb_lineno}")
        trace = trace.tb_next
    return "\n".join(frames) or unavailable
