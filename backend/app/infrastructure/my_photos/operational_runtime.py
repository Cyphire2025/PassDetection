"""Call-time dependencies and dispatch for durable gallery/media workers."""

from __future__ import annotations

import uuid

from app.core.config.settings import Settings, get_settings
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.my_photos.operational_index_jobs import _execute_index_batch
from app.infrastructure.my_photos.operational_job_claims import _claim_job
from app.infrastructure.my_photos.operational_job_contracts import MediaVariant as MediaVariant
from app.infrastructure.my_photos.operational_job_contracts import (
    OperationalJobResult as OperationalJobResult,
)
from app.infrastructure.my_photos.operational_job_contracts import (
    OperationalJobType as OperationalJobType,
)
from app.infrastructure.my_photos.operational_job_contracts import (
    OperationalState as OperationalState,
)
from app.infrastructure.my_photos.operational_job_contracts import OperationalWorkerContext
from app.infrastructure.my_photos.operational_job_contracts import (
    _OperationalClaim as _OperationalClaim,
)
from app.infrastructure.my_photos.operational_job_lifecycle import _retry_or_fail, _terminal_claim
from app.infrastructure.my_photos.operational_media_jobs import _execute_media_job
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle, build_provider_bundle
from app.infrastructure.my_photos.revision_runtime import execute_refresh_fanout


async def execute_operational_job(
    job_id: uuid.UUID,
    *,
    settings: Settings | None = None,
    providers: MyPhotosProviderBundle | None = None,
    lease_owner: str | None = None,
    allowed_job_types: frozenset[OperationalJobType] | None = None,
) -> OperationalJobResult:
    ctx = OperationalWorkerContext(AsyncSessionFactory)
    resolved_settings = settings or get_settings()
    resolved_providers = providers or build_provider_bundle(resolved_settings)
    owner = lease_owner or f"my-photos-operation:{uuid.uuid4().hex}"
    claim_or_result = await _claim_job(
        ctx, job_id, owner, resolved_settings, allowed_job_types=allowed_job_types
    )
    if isinstance(claim_or_result, OperationalJobResult):
        return claim_or_result
    claim = claim_or_result
    if claim.job_type == "refresh_searches":
        try:
            refresh = await execute_refresh_fanout(
                job_id=claim.job_id, lease_owner=claim.lease_owner, settings=resolved_settings
            )
        except (TypeError, ValueError):
            return await _terminal_claim(ctx, claim, "REFRESH_CHECKPOINT_INVALID")
        except Exception:
            return await _retry_or_fail(ctx, claim, resolved_settings, "REFRESH_FANOUT_UNAVAILABLE")
        return OperationalJobResult(
            "retrying" if refresh.state == "continuing" else refresh.state,
            1 if refresh.state == "continuing" else None,
            search_run_ids=refresh.search_run_ids,
        )
    if claim.job_type == "index_gallery":
        return await _execute_index_batch(ctx, claim, resolved_settings, resolved_providers)
    return await _execute_media_job(ctx, claim, resolved_settings, resolved_providers)
