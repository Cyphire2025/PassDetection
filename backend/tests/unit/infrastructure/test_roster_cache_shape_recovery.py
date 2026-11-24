"""Malformed authenticated cache frames remain optional acceleration, not request failures."""

from __future__ import annotations

import json
import zlib
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.passports.roster_cache import RosterCache


@pytest.mark.parametrize(
    "malformed",
    [
        {"pages": [[[]]]},
        {"members": []},
        {"pages": [None]},
        {"v": 1},
    ],
    ids=["truncated-row", "wrong-members-shape", "existing-type-fallback", "existing-version-fallback"],
)
async def test_current_cache_get_recomputes_for_malformed_encrypted_payloads(malformed):
    client = AsyncMock()
    cache = RosterCache(client, secret="synthetic-shape-recovery-key")
    identity = "synthetic-roster-identity"
    payload = {
        "v": 2,
        "identity": identity,
        "members": {},
        "pages": [],
        "clusters": [],
        "ordered": [],
        "group_total": 0,
        "total": 0,
        "page_size": 50,
        "document_follow_up_count": 0,
        "boundaries": True,
        "alerts": [],
        **malformed,
    }
    client.get.return_value = cache.cipher.encrypt(zlib.compress(json.dumps(payload).encode()))
    assert await cache.get(identity) is None
    client.get.assert_awaited_once_with(cache.prefix + identity)
    client.eval.assert_not_awaited()
