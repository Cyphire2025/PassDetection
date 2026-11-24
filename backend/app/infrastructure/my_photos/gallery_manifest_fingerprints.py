"""Gallery manifest fingerprints owner."""

from __future__ import annotations

import hashlib
import json


def _content_fingerprint(header_fingerprint: str, batch_fingerprints: list[str]) -> str:
    return _json_fingerprint(
        {"header_fingerprint": header_fingerprint, "batches": batch_fingerprints}
    )


def _json_fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
