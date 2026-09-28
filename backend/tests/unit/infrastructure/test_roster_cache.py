from __future__ import annotations

import json
import uuid
import zlib
from unittest.mock import AsyncMock

import pytest

from app.application.use_cases.passports.submission_view import prepare_submission_view
from app.infrastructure.passports import roster_cache_codec as codec
from app.infrastructure.passports.roster_cache import RosterCache
from tests.unit.application.test_submission_view import _passport_fields, _submission


def prepared():
    rows = [_submission(name=f"Sensitive synthetic {index}",
                        confirmed=_passport_fields("PRIVATE123", "Chennai")) for index in range(303)]
    for index, row in enumerate(rows):
        row.extraction_revision = index
        row.document_follow_up = index < 10
    return prepare_submission_view(rows, submission_filter="all", sort_by="name", sort_order="asc", search=None, page_size=50)


def test_encrypted_roundtrip_preserves_full_cluster_pagination_and_selection_revisions():
    cache = RosterCache(AsyncMock(), secret="synthetic-key-only")
    index = prepared()
    identity = cache.identity(user=uuid.uuid4(), revision=3, search="PRIVATE123")
    raw = codec.encode(index, cache.cipher, identity)
    assert raw is not None and b"Sensitive" not in raw and b"PRIVATE123" not in raw
    decoded = codec.decode(raw, cache.cipher, identity)
    assert decoded.ordered_submission_ids == index.ordered_submission_ids
    assert decoded.clusters == index.clusters
    assert decoded.expiry_alerts == index.expiry_alerts
    assert decoded.document_follow_up_count == index.document_follow_up_count == 10
    for number, page in enumerate(index.pages, start=1):
        cached = decoded.page(number)
        assert len(cached.items) == len(page) <= 50
        assert cached.duplicate_clusters == index.page(number).duplicate_clusters
        assert cached.document_follow_up_count == 10
        for original, restored in zip(page, cached.items, strict=True):
            assert (original.submission.id, original.submission.extraction_revision, original.submission.updated_at) == (
                restored.submission.id, restored.submission.extraction_revision, restored.submission.updated_at)
            assert original.duplicate_cluster_member_ids == restored.duplicate_cluster_member_ids
    with pytest.raises(ValueError, match="identity mismatch"):
        codec.decode(raw, cache.cipher, "different-user-scope")


async def test_missing_tampered_and_unavailable_cache_fall_back_without_returning_data():
    from redis.exceptions import ConnectionError
    redis = AsyncMock()
    cache = RosterCache(redis, secret="synthetic-key-only")
    for response in (None, b"corrupted-data"):
        redis.get.return_value = response
        assert await cache.get("synthetic-identity") is None
    redis.get.side_effect = ConnectionError("synthetic unavailable")
    assert await cache.get("synthetic-identity") is None


async def test_legacy_cached_roster_without_flag_count_is_recomputed():
    redis = AsyncMock()
    cache = RosterCache(redis, secret="synthetic-key-only")
    redis.get.return_value = cache.cipher.encrypt(zlib.compress(json.dumps(
        {"v": 1, "identity": "synthetic-identity"}
    ).encode()))
    assert await cache.get("synthetic-identity") is None


def test_oversized_index_is_not_stored(monkeypatch):
    cache = RosterCache(AsyncMock(), secret="synthetic-key-only")
    monkeypatch.setattr(codec, "MAX_RAW_BYTES", 100)
    assert codec.encode(prepared(), cache.cipher, "synthetic") is None
