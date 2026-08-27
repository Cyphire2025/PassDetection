from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from celery.exceptions import Retry
from sqlalchemy.dialects import postgresql

from app.application.my_photos.providers import (
    FaceSearchResult,
    ProviderFaceMatch,
)
from app.core.config.settings import MyPhotosSettings
from app.infrastructure.my_photos import tasks, worker_runtime
from app.infrastructure.my_photos.worker_runtime import (
    SearchJobExecutionResult,
    _claim_search,
    _finalize_search,
    _SearchClaim,
    _validated_provider_result,
    execute_search_job,
)


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def one_or_none(self) -> object:
        return self._value

    def scalar_one_or_none(self) -> object:
        return self._value


class _SessionContext:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, *args: object) -> None:
        del args


def _claim() -> _SearchClaim:
    return _SearchClaim(
        search_run_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        lease_owner="worker-one",
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        passenger_identity_id=uuid.uuid4(),
        enrollment_id=uuid.uuid4(),
        gallery_id=uuid.uuid4(),
        gallery_revision=1,
        face_index_version=1,
        enrollment_version=1,
        collection_reference="collection-one",
        reference_face_handle="reference-one",
        total_face_count=6_000,
        attempt_count=1,
        max_attempts=5,
    )


def test_provider_result_validation_rejects_malformed_values() -> None:
    invalid_results = [
        FaceSearchResult(
            matches=(ProviderFaceMatch("face-one", float("nan")),),
            provider_model_version="model-v1",
        ),
        FaceSearchResult(
            matches=(ProviderFaceMatch("face-one", 100.01),),
            provider_model_version="model-v1",
        ),
        FaceSearchResult(
            matches=(ProviderFaceMatch("x" * 513, 90.0),),
            provider_model_version="model-v1",
        ),
        FaceSearchResult(
            matches=(ProviderFaceMatch("face-one", 90.0),),
            provider_model_version=" model-v1",
        ),
    ]
    for result in invalid_results:
        with pytest.raises(ValueError):
            _validated_provider_result(result, maximum_results=5_000)


def test_provider_result_validation_coalesces_duplicate_face_references() -> None:
    validated = _validated_provider_result(
        FaceSearchResult(
            matches=(
                ProviderFaceMatch("face-two", 81.0),
                ProviderFaceMatch("face-one", 90.0),
                ProviderFaceMatch("face-one", 94.0),
            ),
            provider_model_version="model-v1",
        ),
        maximum_results=5_000,
    )
    assert validated.matches == (
        ProviderFaceMatch("face-one", 94.0),
        ProviderFaceMatch("face-two", 81.0),
    )


def test_provider_result_validation_enforces_requested_hard_limit() -> None:
    result = FaceSearchResult(
        matches=(
            ProviderFaceMatch("face-one", 90.0),
            ProviderFaceMatch("face-two", 89.0),
        ),
        provider_model_version="model-v1",
    )
    with pytest.raises(ValueError):
        _validated_provider_result(result, maximum_results=1)


@pytest.mark.asyncio
async def test_crash_after_provider_before_finalize_becomes_durable_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()

    async def claim_search(*args: object, **kwargs: object) -> _SearchClaim:
        return claim

    async def finalize(*args: object, **kwargs: object) -> SearchJobExecutionResult:
        raise RuntimeError("synthetic database interruption")

    captured: dict[str, str] = {}

    async def retry_or_fail(
        value: _SearchClaim, *, error_code: str, settings: object
    ) -> SearchJobExecutionResult:
        assert value is claim
        del settings
        captured["code"] = error_code
        return SearchJobExecutionResult("retrying", 7)

    class FaceProvider:
        async def search(self, request: object) -> FaceSearchResult:
            del request
            return FaceSearchResult(
                matches=(ProviderFaceMatch("face-one", 95.0),),
                provider_model_version="model-v1",
            )

    monkeypatch.setattr("app.infrastructure.my_photos.worker_runtime._claim_search", claim_search)
    monkeypatch.setattr("app.infrastructure.my_photos.worker_runtime._finalize_search", finalize)
    monkeypatch.setattr("app.infrastructure.my_photos.worker_runtime._retry_or_fail", retry_or_fail)
    settings = SimpleNamespace(
        my_photos=SimpleNamespace(
            maximum_search_results=5_000,
            face_search_provider_timeout_seconds=20,
        )
    )
    providers = SimpleNamespace(face_search=FaceProvider())
    result = await execute_search_job(
        claim.search_run_id,
        settings=settings,  # type: ignore[arg-type]
        providers=providers,  # type: ignore[arg-type]
    )
    assert result == SearchJobExecutionResult("retrying", 7)
    assert captured == {"code": "SEARCH_FINALIZE_FAILED"}


@pytest.mark.asyncio
async def test_invalid_provider_result_is_terminal_not_constraint_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()

    async def claim_search(*args: object, **kwargs: object) -> _SearchClaim:
        return claim

    captured: dict[str, str] = {}

    async def terminal(value: _SearchClaim, error_code: str) -> SearchJobExecutionResult:
        assert value is claim
        captured["code"] = error_code
        return SearchJobExecutionResult("failed")

    class FaceProvider:
        async def search(self, request: object) -> FaceSearchResult:
            del request
            return FaceSearchResult(
                matches=(ProviderFaceMatch("face-one", float("inf")),),
                provider_model_version="model-v1",
            )

    monkeypatch.setattr("app.infrastructure.my_photos.worker_runtime._claim_search", claim_search)
    monkeypatch.setattr(
        "app.infrastructure.my_photos.worker_runtime._terminal_claim_failure", terminal
    )
    result = await execute_search_job(
        claim.search_run_id,
        settings=SimpleNamespace(  # type: ignore[arg-type]
            my_photos=SimpleNamespace(
                maximum_search_results=5_000,
                face_search_provider_timeout_seconds=20,
            )
        ),
        providers=SimpleNamespace(face_search=FaceProvider()),  # type: ignore[arg-type]
    )
    assert result.state == "failed"
    assert captured == {"code": "PROVIDER_RESULT_INVALID"}


@pytest.mark.parametrize("state", ["retrying", "lease_busy", "lease_lost"])
def test_celery_redelivers_every_nonterminal_worker_state(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    def fake_run(coroutine: object) -> SearchJobExecutionResult:
        coroutine.close()  # type: ignore[attr-defined]
        return SearchJobExecutionResult(
            state=state,  # type: ignore[arg-type]
            retry_after_seconds=3,
        )

    monkeypatch.setattr(
        tasks.celery_async_runtime,
        "run",
        fake_run,
    )
    with pytest.raises(Retry):
        tasks.search_passenger_photos.run(str(uuid.uuid4()))


def test_celery_redelivers_unexpected_runtime_failure_without_raw_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(coroutine: object) -> SearchJobExecutionResult:
        coroutine.close()  # type: ignore[attr-defined]
        raise RuntimeError("provider-secret-must-not-be-attached")

    monkeypatch.setattr(tasks.celery_async_runtime, "run", fail)
    with pytest.raises(Retry) as captured:
        tasks.search_passenger_photos.run(str(uuid.uuid4()))
    assert "provider-secret" not in str(captured.value)


def test_default_search_limit_covers_full_v1_gallery() -> None:
    assert MyPhotosSettings().maximum_search_results == 5_000


@pytest.mark.asyncio
async def test_search_claim_rejects_gallery_disabled_after_queueing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()
    search = SimpleNamespace(
        id=claim.search_run_id,
        status="queued",
        passenger_identity_id=claim.passenger_identity_id,
        agency_id=claim.agency_id,
        group_id=claim.group_id,
        enrollment_id=claim.enrollment_id,
        enrollment_version=claim.enrollment_version,
        gallery_id=claim.gallery_id,
        gallery_revision=claim.gallery_revision,
        face_index_version=claim.face_index_version,
        total_face_count=claim.total_face_count,
        attempt_count=0,
        max_attempts=5,
        lease_owner=None,
        lease_expires_at=None,
    )
    job = SimpleNamespace(
        id=claim.job_id,
        cancellation_requested_at=None,
        next_attempt_at=None,
        status="queued",
        attempt_count=0,
        max_attempts=5,
        lease_owner=None,
        lease_expires_at=None,
        started_at=None,
    )
    enrollment = SimpleNamespace(id=claim.enrollment_id)
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(
                    SimpleNamespace(
                        passenger_identity_id=claim.passenger_identity_id,
                        agency_id=claim.agency_id,
                        group_id=claim.group_id,
                    )
                ),
                _Result(None),
                _Result(search),
                _Result(job),
                _Result(enrollment),
                _Result(None),
            ]
        ),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(
        worker_runtime,
        "AsyncSessionFactory",
        lambda: _SessionContext(session),
    )
    monkeypatch.setattr(worker_runtime, "_audit_search", AsyncMock())

    result = await _claim_search(
        claim.search_run_id,
        claim.lease_owner,
        SimpleNamespace(my_photos=SimpleNamespace(job_lease_seconds=30)),  # type: ignore[arg-type]
    )

    assert result == SearchJobExecutionResult("failed")
    assert search.stable_error_code == "SEARCH_SCOPE_STALE"
    gallery_statement = session.execute.await_args_list[5].args[0]
    gallery_sql = str(gallery_statement.compile(dialect=postgresql.dialect()))
    assert "my_photo_galleries.feature_enabled IS true" in gallery_sql


@pytest.mark.asyncio
async def test_search_finalize_rechecks_feature_after_provider_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim()
    search = SimpleNamespace(
        id=claim.search_run_id,
        status="searching",
        lease_owner=claim.lease_owner,
        lease_expires_at=datetime.now(tz=UTC) + timedelta(seconds=30),
    )
    job = SimpleNamespace(
        id=claim.job_id,
        status="running",
        lease_owner=claim.lease_owner,
    )
    enrollment = SimpleNamespace(id=claim.enrollment_id)
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(None),
                _Result(search),
                _Result(job),
                _Result(enrollment),
                _Result(None),
            ]
        ),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(
        worker_runtime,
        "AsyncSessionFactory",
        lambda: _SessionContext(session),
    )
    monkeypatch.setattr(worker_runtime, "_audit_search", AsyncMock())

    result = await _finalize_search(
        claim,
        FaceSearchResult(matches=(), provider_model_version="model-v1"),
        SimpleNamespace(my_photos=SimpleNamespace()),  # type: ignore[arg-type]
    )

    assert result == SearchJobExecutionResult("failed")
    assert search.stable_error_code == "SEARCH_SCOPE_STALE"
    gallery_statement = session.execute.await_args_list[4].args[0]
    gallery_sql = str(gallery_statement.compile(dialect=postgresql.dialect()))
    assert "my_photo_galleries.feature_enabled IS true" in gallery_sql
