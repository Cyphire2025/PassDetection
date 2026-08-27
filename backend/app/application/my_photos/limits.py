"""Canonical bounded-media limits for the My Photos contract."""

from __future__ import annotations

# The Android vault, download manager, and temporary-file policy all enforce
# this same per-item ceiling. Provider metadata and persisted rows must reject
# anything larger before it can be advertised to a mobile client.
MAX_MY_PHOTOS_MEDIA_BYTES = 200 * 1024 * 1024


__all__ = ["MAX_MY_PHOTOS_MEDIA_BYTES"]
