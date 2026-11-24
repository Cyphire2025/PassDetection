"""Summary precedence and bounded query/output controls for active snapshots."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.infrastructure.my_photos.summary_projector import MyPhotosSummaryProjector
from app.infrastructure.my_photos.summary_state import SummaryStateInputs, experience_state


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"gallery": None}, "feature_unavailable"),
        ({"gallery": SimpleNamespace(feature_enabled=False)}, "feature_unavailable"),
        ({"window_state": "expired", "provider_configured": False}, "access_expired"),
        ({"feature_enabled": False}, "feature_unavailable"),
        ({"provider_configured": False}, "provider_not_configured"),
        ({"provider_transient": True}, "provider_unavailable"),
        ({"gallery_status": "not_uploaded"}, "gallery_not_uploaded"),
        ({"gallery_status": "awaiting_upload"}, "gallery_processing"),
        ({"gallery_status": "processing"}, "gallery_processing"),
        ({"gallery_status": "indexing"}, "gallery_indexing"),
        ({"gallery_status": "failed"}, "nonrecoverable_error"),
        ({"gallery_status": "removed"}, "nonrecoverable_error"),
        (
            {"enrollment": SimpleNamespace(status="deleted"), "consent_required": True},
            "enrollment_deleted",
        ),
        (
            {"enrollment": SimpleNamespace(status="revoked"), "consent_required": True},
            "access_revoked",
        ),
        ({"consent_required": True}, "consent_required"),
        ({"enrollment": None}, "ready_to_scan"),
        ({"enrollment": SimpleNamespace(status="ready")}, "ready_to_scan"),
        ({"enrollment": SimpleNamespace(status="session_pending")}, "scan_running"),
        ({"enrollment": SimpleNamespace(status="processing")}, "scan_running"),
        ({"enrollment": SimpleNamespace(status="rejected")}, "liveness_rejected"),
        ({"enrollment": SimpleNamespace(status="cooldown")}, "cooldown"),
        ({"stale_search": True}, "search_queued"),
        ({"stale_search": True, "refresh_failed": True}, "recoverable_error"),
        ({"search": SimpleNamespace(status="queued")}, "search_queued"),
        ({"search": SimpleNamespace(status="searching")}, "searching"),
        ({"search": SimpleNamespace(status="failed")}, "recoverable_error"),
        ({"search": SimpleNamespace(status="cancelled")}, "recoverable_error"),
        ({"result_counts": SimpleNamespace(match_count=0, preparing_count=0)}, "no_matches"),
        ({"result_counts": SimpleNamespace(match_count=2, preparing_count=1)}, "matches_preparing"),
        ({}, "matches_ready"),
        (
            {"search": None, "result_counts": SimpleNamespace(match_count=0, preparing_count=0)},
            "ready_to_scan",
        ),
    ],
)
def test_existing_experience_precedence(changes, expected):
    values = dict(
        gallery=SimpleNamespace(feature_enabled=True),
        window_state="active",
        feature_enabled=True,
        provider_configured=True,
        provider_transient=False,
        gallery_status="ready",
        enrollment=SimpleNamespace(status="enrolled"),
        consent_required=False,
        stale_search=False,
        refresh_failed=False,
        search=SimpleNamespace(status="complete"),
        result_counts=SimpleNamespace(match_count=2, preparing_count=0),
    )
    values.update(changes)
    assert experience_state(SummaryStateInputs(**values)) == expected


@pytest.mark.parametrize(
    ("effective", "prior", "counts", "refresh_failed", "expected", "new_count", "query_count"),
    [
        (2, 1, (3, 2, 1), False, "matches_preparing", 1, 4),
        (2, None, (3, 3, 0), False, "matches_ready", 0, 3),
        (None, None, (0, 0, 0), False, "no_matches", 0, 3),
        (1, None, (3, 3, 0), False, "search_queued", 0, 4),
        (1, None, (3, 3, 0), True, "recoverable_error", 0, 4),
    ],
)
async def test_active_summary_retains_snapshot_counts_and_bounded_scoped_queries(
    effective, prior, counts, refresh_failed, expected, new_count, query_count
):
    group_id, passenger_id = uuid.uuid4(), uuid.uuid4()
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    search_revision = 1 if effective == 1 else 2
    values = [effective, prior, (*counts, timestamp)]
    if effective == 2 and prior is not None:
        values.append(new_count)
    if search_revision == 1:
        values.append(int(refresh_failed))
    statements = []

    class Session:
        async def execute(self, statement):
            statements.append(statement)
            value = values.pop(0)
            return SimpleNamespace(scalar_one=lambda: value, one=lambda: value)

    gallery = SimpleNamespace(
        id=uuid.uuid4(),
        feature_enabled=True,
        status="ready",
        published_revision=2,
        media_version=2,
        face_index_version=2,
        total_asset_count=4,
        indexed_asset_count=4,
        failed_asset_count=0,
        all_group_photos_enabled=False,
        published_at=timestamp,
        updated_at=timestamp,
    )
    enrollment = SimpleNamespace(
        status="enrolled",
        consent_version="synthetic-v1",
        consented_at=timestamp,
        reference_version=1,
        attempt_count=0,
        max_attempts=3,
        cooldown_until=None,
        enrolled_at=timestamp,
        updated_at=timestamp,
    )
    search = SimpleNamespace(
        status="complete", stable_error_code=None, gallery_revision=search_revision
    )
    settings = SimpleNamespace(my_photos=SimpleNamespace(consent_version="synthetic-v1"))
    providers = SimpleNamespace(
        liveness=SimpleNamespace(ready=True, client_flow="development_simulator"),
        face_search=SimpleNamespace(ready=True),
    )
    projector = MyPhotosSummaryProjector(
        Session(),
        settings=settings,
        providers=providers,
        gallery_window_state=lambda _gallery, _now: "active",
        search_response=lambda _search: None,
    )
    result = await projector.build(
        group_name="Synthetic trip",
        group_id=group_id,
        gallery=gallery,
        enrollment=enrollment,
        search=search,
        passenger_identity_id=passenger_id,
    )
    assert result.experience_state == expected
    assert result.results.snapshot_revision == (effective or search_revision)
    assert result.results.match_count == counts[0]
    assert result.results.downloadable_count == counts[1]
    assert result.results.preparing_count == counts[2]
    assert result.results.new_photo_count == new_count
    assert len(statements) == query_count and values == []
    for statement in statements[:3]:
        compiled = statement.compile(dialect=postgresql.dialect())
        assert group_id in compiled.params.values()
        assert passenger_id in compiled.params.values()
