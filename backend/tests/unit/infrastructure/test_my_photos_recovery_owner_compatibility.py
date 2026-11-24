"""Legacy public annotation, serialization and pure-helper ownership remain valid."""

import inspect
import pickle
import typing
import uuid

from app.infrastructure.my_photos import (
    recovery_contracts,
    recovery_deletion_policy,
    recovery_runtime,
    revision_contracts,
    revision_policy,
    revision_publication,
    revision_runtime,
    summary_projector,
)
from app.presentation.api.v1.schemas.my_photos_schemas import MyPhotosSummaryResponse


def test_recovery_dto_annotations_resolve_through_legacy_module():
    for name in (
        "DurableDispatch",
        "ProviderDeletionBatchResult",
        "_DeletionClaim",
        "_DeletionOutcome",
    ):
        declaration = getattr(recovery_runtime, name)
        assert declaration is getattr(recovery_contracts, name)
        assert declaration.__module__ == recovery_runtime.__name__
        assert declaration.__qualname__ == name
        assert typing.get_type_hints(declaration)
    hints = typing.get_type_hints(recovery_runtime.DurableDispatch)
    assert hints["job_id"] is uuid.UUID
    assert typing.get_args(hints["kind"]) == ("search", "index", "media")
    record = recovery_runtime.DurableDispatch(uuid.uuid4(), "search", uuid.uuid4())
    restored = pickle.loads(pickle.dumps(record))
    assert type(restored) is type(record) and restored == record


def test_revision_result_and_publication_keep_canonical_aliases():
    assert revision_runtime.RefreshFanoutResult is revision_contracts.RefreshFanoutResult
    assert (
        revision_runtime.publish_gallery_revision is revision_publication.publish_gallery_revision
    )
    assert revision_runtime._refresh_claim_current is revision_policy._refresh_claim_current
    assert typing.get_args(
        typing.get_type_hints(revision_runtime.RefreshFanoutResult)["state"]
    ) == ("succeeded", "continuing", "failed", "lease_lost")
    record = revision_runtime.RefreshFanoutResult("continuing", (uuid.uuid4(),))
    restored = pickle.loads(pickle.dumps(record))
    assert type(restored) is type(record) and restored == record
    signature = inspect.signature(revision_runtime.execute_refresh_fanout)
    assert tuple(signature.parameters) == ("job_id", "lease_owner", "settings")
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


def test_summary_and_recovery_helpers_keep_runtime_annotations():
    assert recovery_runtime._reference_unchanged is recovery_deletion_policy._reference_unchanged
    assert recovery_runtime._due is recovery_deletion_policy._due
    assert (
        typing.get_type_hints(summary_projector.MyPhotosSummaryProjector.build)["return"]
        is MyPhotosSummaryResponse
    )
    for function in (
        recovery_runtime.recoverable_dispatches,
        recovery_runtime.execute_provider_deletion_batch,
        recovery_runtime._finalize_provider_deletions,
        revision_runtime.execute_refresh_fanout,
        revision_runtime.publish_gallery_revision,
    ):
        assert typing.get_type_hints(function)
