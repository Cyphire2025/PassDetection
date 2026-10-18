"""A shared recent-context budget for typed and spoken turns; saved history is unchanged."""

from typing import Any

MAX_CONTEXT_CHARS = 48000


def recent_context(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used = 0
    for item in reversed(sorted(items, key=lambda value: value["created_at"])[-10:]):
        user, assistant = str(item["user"])[:8000], str(item["assistant"])[:16000]
        size = len(user) + len(assistant)
        if used + size > MAX_CONTEXT_CHARS:
            break
        used += size
        selected.append({**item, "user": user, "assistant": assistant})
    return list(reversed(selected))
