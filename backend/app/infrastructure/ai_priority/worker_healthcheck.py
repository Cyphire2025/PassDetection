"""Queue-specific Celery worker container healthcheck."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from app.infrastructure.ai_priority.worker_readiness import (
    _queue_names_from_replies,
)


def _active_queues_for_worker(
    *,
    destination: str,
    timeout_seconds: float,
) -> frozenset[str]:
    from app.infrastructure.processing.celery_app import celery_app

    inspector = celery_app.control.inspect(
        destination=[destination],
        timeout=timeout_seconds,
    )
    replies = inspector.active_queues() or {}
    return _queue_names_from_replies(replies)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True)
    parser.add_argument("--queue", action="append", required=True)
    parser.add_argument("--timeout", type=float, default=1.0)
    args = parser.parse_args(argv)

    if not 0 < args.timeout <= 5:
        return 2
    try:
        available = _active_queues_for_worker(
            destination=args.destination,
            timeout_seconds=args.timeout,
        )
    except Exception:
        return 1
    return 0 if set(args.queue).issubset(available) else 1


if __name__ == "__main__":
    raise SystemExit(main())
