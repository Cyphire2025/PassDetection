"""Expiring process-local quotas for explicitly permitted Redis fallback."""

from __future__ import annotations

import math
from collections.abc import MutableMapping, Sequence
from typing import TypeVar

_State = TypeVar("_State", bound=Sequence[float])


def discard_expired(state: MutableMapping[str, _State], *, now: float) -> None:
    expired = [key for key, value in state.items() if value[-1] <= now]
    for key in expired:
        del state[key]


def increment_window(
    state: MutableMapping[str, tuple[int, float]],
    key: str,
    *,
    now: float,
    window_seconds: int,
) -> int:
    count, expires_at = state.get(key, (0, now + window_seconds))
    if now >= expires_at:
        count, expires_at = 0, now + window_seconds
    count += 1
    state[key] = (count, expires_at)
    return count


def consume_bucket(
    state: MutableMapping[str, tuple[float, float, float]],
    key: str,
    *,
    now: float,
    refill_per_second: int,
    capacity: int,
    ttl_seconds: float,
) -> tuple[bool, int, int]:
    tokens, updated_at, _ = state.get(key, (float(capacity), now, now + ttl_seconds))
    tokens = min(float(capacity), tokens + max(0.0, now - updated_at) * refill_per_second)
    allowed = tokens >= 1
    if allowed:
        tokens -= 1
    retry_ms = 0 if allowed else math.ceil(((1 - tokens) / refill_per_second) * 1000)
    state[key] = (tokens, now, now + ttl_seconds)
    return allowed, max(0, math.floor(tokens)), retry_ms
