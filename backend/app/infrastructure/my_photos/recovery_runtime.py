"""Call-time recovery orchestration and stable public/helper imports."""

from __future__ import annotations

import asyncio
import uuid as uuid
from datetime import UTC, datetime

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import ReferenceDeletionRequest
from app.core.config.settings import Settings, get_settings
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.my_photos import recovery_deletion_claims as _claims
from app.infrastructure.my_photos import recovery_deletion_results as _results
from app.infrastructure.my_photos import recovery_dispatch as _dispatch
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle, build_provider_bundle
from app.infrastructure.my_photos.recovery_contracts import (
    DeletionKind as DeletionKind,
)
from app.infrastructure.my_photos.recovery_contracts import (
    DispatchKind as DispatchKind,
)
from app.infrastructure.my_photos.recovery_contracts import (
    DurableDispatch as DurableDispatch,
)
from app.infrastructure.my_photos.recovery_contracts import (
    ProviderDeletionBatchResult as ProviderDeletionBatchResult,
)
from app.infrastructure.my_photos.recovery_contracts import RecoveryContext
from app.infrastructure.my_photos.recovery_contracts import (
    _DeletionClaim as _DeletionClaim,
)
from app.infrastructure.my_photos.recovery_contracts import (
    _DeletionOutcome as _DeletionOutcome,
)
from app.infrastructure.my_photos.recovery_deletion_policy import (
    _complete_reference as _complete_reference,
)
from app.infrastructure.my_photos.recovery_deletion_policy import (
    _deletion_retry_delay as _deletion_retry_delay,
)
from app.infrastructure.my_photos.recovery_deletion_policy import (
    _due as _due,
)
from app.infrastructure.my_photos.recovery_deletion_policy import (
    _fail_reference as _fail_reference,
)
from app.infrastructure.my_photos.recovery_deletion_policy import (
    _pending_reference as _pending_reference,
)
from app.infrastructure.my_photos.recovery_deletion_policy import (
    _reference_unchanged as _reference_unchanged,
)
from app.infrastructure.my_photos.recovery_deletion_policy import (
    _set_next_attempt as _set_next_attempt,
)
from app.infrastructure.my_photos.recovery_deletion_policy import (
    _stable_error as _stable_error,
)


async def recoverable_dispatches(
    *, settings: Settings | None = None, now: datetime | None = None
) -> tuple[DurableDispatch, ...]:
    """Return a bounded set of due/expired durable jobs; leases make duplicates safe."""
    resolved = settings or get_settings()
    due_at = now or datetime.now(tz=UTC)
    await _terminalize_requested_cancellations(resolved, due_at)
    return await _dispatch._due_dispatches(RecoveryContext(AsyncSessionFactory), resolved, due_at)


async def execute_provider_deletion_batch(
    *,
    settings: Settings | None = None,
    providers: MyPhotosProviderBundle | None = None,
) -> ProviderDeletionBatchResult:
    """Claim, call, and finalize a bounded deletion batch without holding provider locks."""

    resolved = settings or get_settings()
    bundle = providers or build_provider_bundle(resolved)
    claims = await _claim_provider_deletions(resolved)
    if not claims:
        return ProviderDeletionBatchResult(0, 0, 0, 0)
    semaphore = asyncio.Semaphore(resolved.my_photos.provider_deletion_concurrency)

    async def delete_one(claim: _DeletionClaim) -> _DeletionOutcome:
        try:
            async with semaphore:
                async with asyncio.timeout(resolved.my_photos.liveness_provider_timeout_seconds):
                    result = await bundle.liveness.delete_reference(
                        ReferenceDeletionRequest(
                            tenant_scope=str(claim.agency_id),
                            group_scope=str(claim.group_id),
                            passenger_scope=str(claim.passenger_identity_id),
                            provider_reference=claim.provider_reference,
                            deletion_identity=claim.deletion_identity,
                        )
                    )
            if result.outcome not in {"deleted", "not_found"}:
                return _DeletionOutcome(claim, False, "PROVIDER_DELETION_RESULT_INVALID")
            return _DeletionOutcome(claim, True, None)
        except MyPhotosUnavailable as exc:
            return _DeletionOutcome(claim, False, _stable_error(exc.code))
        except TimeoutError:
            return _DeletionOutcome(claim, False, "PROVIDER_DELETION_TIMEOUT")
        except Exception:
            return _DeletionOutcome(claim, False, "PROVIDER_DELETION_UNAVAILABLE")

    outcomes = await asyncio.gather(*(delete_one(claim) for claim in claims))
    return await _finalize_provider_deletions(outcomes, resolved)


async def _terminalize_requested_cancellations(settings: Settings, now: datetime) -> int:
    """Finalize a bounded cancellation batch, including expired worker leases."""
    return await _dispatch._terminalize_requested_cancellations(
        RecoveryContext(AsyncSessionFactory), settings, now
    )


async def _claim_provider_deletions(settings: Settings) -> tuple[_DeletionClaim, ...]:
    return await _claims._claim_provider_deletions(RecoveryContext(AsyncSessionFactory), settings)


async def _finalize_provider_deletions(
    outcomes: tuple[_DeletionOutcome, ...] | list[_DeletionOutcome], settings: Settings
) -> ProviderDeletionBatchResult:
    return await _results._finalize_provider_deletions(
        RecoveryContext(AsyncSessionFactory), outcomes, settings
    )


__all__ = [
    "DurableDispatch",
    "ProviderDeletionBatchResult",
    "execute_provider_deletion_batch",
    "recoverable_dispatches",
]
