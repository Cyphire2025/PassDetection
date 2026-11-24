"""Call-time dependencies, stable imports and passenger-search dispatch."""

from __future__ import annotations

import asyncio
import time
import uuid

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import FaceSearchRequest, FaceSearchResult
from app.core.config.settings import Settings, get_settings
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.my_photos import (
    search_job_claims,
    search_job_lifecycle,
    search_job_publication,
)
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle, build_provider_bundle
from app.infrastructure.my_photos.search_job_contracts import (
    SearchJobExecutionResult as SearchJobExecutionResult,
)
from app.infrastructure.my_photos.search_job_contracts import SearchWorkerContext
from app.infrastructure.my_photos.search_job_contracts import WorkerState as WorkerState
from app.infrastructure.my_photos.search_job_contracts import _SearchClaim as _SearchClaim
from app.infrastructure.my_photos.search_job_lifecycle import _audit_search as _audit_search
from app.infrastructure.my_photos.search_job_lifecycle import (
    _mark_terminal_failure as _mark_terminal_failure,
)
from app.infrastructure.my_photos.search_job_policy import (
    _gallery_window_closed as _gallery_window_closed,
)
from app.infrastructure.my_photos.search_job_policy import _retry_delay as _retry_delay
from app.infrastructure.my_photos.search_job_policy import _stable_error_code as _stable_error_code
from app.infrastructure.my_photos.search_job_policy import _utc as _utc
from app.infrastructure.my_photos.search_job_policy import (
    _validated_provider_result as _validated_provider_result,
)
from app.infrastructure.my_photos.search_job_queries import _locked_claim_rows as _locked_claim_rows
from app.infrastructure.my_photos.telemetry import my_photos_metrics


async def execute_search_job(
    search_run_id: uuid.UUID,
    *,
    settings: Settings | None = None,
    providers: MyPhotosProviderBundle | None = None,
    lease_owner: str | None = None,
) -> SearchJobExecutionResult:
    """Claim, invoke, and conditionally finalize one pre-indexed collection search."""

    resolved_settings = settings or get_settings()
    resolved_providers = providers or build_provider_bundle(resolved_settings)
    owner = lease_owner or f"my-photos-search:{uuid.uuid4().hex}"
    claim_or_result = await _claim_search(search_run_id, owner, resolved_settings)
    if isinstance(claim_or_result, SearchJobExecutionResult):
        return claim_or_result
    claim = claim_or_result

    started = time.perf_counter()
    try:
        async with asyncio.timeout(
            resolved_settings.my_photos.face_search_provider_timeout_seconds
        ):
            provider_result = await resolved_providers.face_search.search(
                FaceSearchRequest(
                    tenant_scope=str(claim.agency_id),
                    group_scope=str(claim.group_id),
                    collection_reference=claim.collection_reference,
                    reference_face_handle=claim.reference_face_handle,
                    maximum_results=resolved_settings.my_photos.maximum_search_results,
                )
            )
    except MyPhotosUnavailable as exc:
        category = "throttled" if "THROTTLED" in exc.code else "unavailable"
        my_photos_metrics.provider(category)  # type: ignore[arg-type]
        outcome = await _retry_or_fail(
            claim,
            error_code=_stable_error_code(exc.code),
            settings=resolved_settings,
        )
        my_photos_metrics.search_finished(
            outcome="retrying" if outcome.state == "retrying" else "failed",
            duration_ms=(time.perf_counter() - started) * 1_000,
        )
        return outcome
    except Exception:
        # Provider adapters must sanitize their own errors. This boundary still
        # persists a stable retry category without logging payloads or references.
        my_photos_metrics.provider("unavailable")
        outcome = await _retry_or_fail(
            claim,
            error_code="PROVIDER_UNAVAILABLE",
            settings=resolved_settings,
        )
        my_photos_metrics.search_finished(
            outcome="retrying" if outcome.state == "retrying" else "failed",
            duration_ms=(time.perf_counter() - started) * 1_000,
        )
        return outcome

    try:
        validated_result = _validated_provider_result(
            provider_result,
            maximum_results=resolved_settings.my_photos.maximum_search_results,
        )
    except ValueError:
        outcome = await _terminal_claim_failure(claim, "PROVIDER_RESULT_INVALID")
        my_photos_metrics.search_finished(
            outcome="failed",
            duration_ms=(time.perf_counter() - started) * 1_000,
        )
        return outcome

    try:
        outcome = await _finalize_search(claim, validated_result, resolved_settings)
    except Exception:
        # A crash after provider success is safe to redeliver: no matches are
        # published until the final transaction commits, and publication is
        # protected by the passenger lock plus active-match uniqueness.
        outcome = await _retry_or_fail(
            claim,
            error_code="SEARCH_FINALIZE_FAILED",
            settings=resolved_settings,
        )
    metric_outcome = "complete" if outcome.state == "succeeded" else outcome.state
    my_photos_metrics.search_finished(
        outcome=metric_outcome,
        duration_ms=(time.perf_counter() - started) * 1_000,
    )
    return outcome


async def _claim_search(
    search_run_id: uuid.UUID, lease_owner: str, settings: Settings
) -> _SearchClaim | SearchJobExecutionResult:
    return await search_job_claims._claim_search(
        SearchWorkerContext(AsyncSessionFactory), search_run_id, lease_owner, settings
    )


async def _retry_or_fail(
    claim: _SearchClaim, *, error_code: str, settings: Settings
) -> SearchJobExecutionResult:
    return await search_job_lifecycle._retry_or_fail(
        SearchWorkerContext(AsyncSessionFactory), claim, error_code=error_code, settings=settings
    )


async def _terminal_claim_failure(claim: _SearchClaim, error_code: str) -> SearchJobExecutionResult:
    return await search_job_lifecycle._terminal_claim_failure(
        SearchWorkerContext(AsyncSessionFactory), claim, error_code
    )


async def _finalize_search(
    claim: _SearchClaim, result: FaceSearchResult, settings: Settings
) -> SearchJobExecutionResult:
    return await search_job_publication._finalize_search(
        SearchWorkerContext(AsyncSessionFactory), claim, result, settings
    )


__all__ = ["SearchJobExecutionResult", "execute_search_job"]
