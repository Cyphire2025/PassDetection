"""Provider-neutral liveness, recognition, and media delivery contracts.

Provider credentials and native-provider request/response models must remain in
future infrastructure adapters. JavaScript and API callers only observe these
bounded lifecycle results.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from app.application.my_photos.states import ChallengeMode, MediaAvailability

ProviderOutcome = Literal[
    "passed",
    "rejected",
    "expired",
    "throttled",
    "unavailable",
    "no_face",
    "multiple_faces",
    "failed",
]


@dataclass(frozen=True, slots=True)
class LivenessSessionRequest:
    session_identity: str
    tenant_scope: str
    group_scope: str
    passenger_scope: str
    challenge_mode: ChallengeMode
    expires_at: datetime
    # Server-owned retention policy. A provider adapter must not inherit a
    # vendor default that silently retains audit images or reference frames.
    audit_image_retention_enabled: bool = False
    reference_frame_retention_seconds: int = 0


@dataclass(frozen=True, slots=True)
class LivenessSessionHandle:
    provider_reference: str
    expires_at: datetime
    # Opaque data consumed only by the official native liveness component.
    # It is distinct from the server-side lookup reference and never contains
    # provider credentials. The native component may separately obtain
    # short-lived, least-privilege credentials from the configured Cognito
    # Identity Pool. Development simulation must leave this launch handle
    # unset.
    native_launch_handle: str | None = None


@dataclass(frozen=True, slots=True)
class LivenessResult:
    outcome: ProviderOutcome
    reference_face_handle: str | None = None
    retryable: bool = False
    stable_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ReferenceDeletionRequest:
    tenant_scope: str
    group_scope: str
    passenger_scope: str
    provider_reference: str
    deletion_identity: str


@dataclass(frozen=True, slots=True)
class ReferenceDeletionResult:
    outcome: Literal["deleted", "not_found"]


@dataclass(frozen=True, slots=True)
class FaceSearchRequest:
    tenant_scope: str
    group_scope: str
    collection_reference: str
    reference_face_handle: str
    maximum_results: int


@dataclass(frozen=True, slots=True)
class ProviderFaceMatch:
    provider_face_reference: str
    similarity: float


@dataclass(frozen=True, slots=True)
class FaceSearchResult:
    matches: tuple[ProviderFaceMatch, ...]
    provider_model_version: str


@dataclass(frozen=True, slots=True)
class CanonicalFaceBox:
    left: float
    top: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class FaceIndexAsset:
    asset_identity: str
    analysis_media_reference: str
    idempotency_identity: str


@dataclass(frozen=True, slots=True)
class FaceIndexBatchRequest:
    tenant_scope: str
    group_scope: str
    collection_reference: str
    index_version: int
    assets: tuple[FaceIndexAsset, ...]


@dataclass(frozen=True, slots=True)
class IndexedFaceOccurrence:
    asset_identity: str
    provider_face_reference: str
    bounding_box: CanonicalFaceBox
    quality_score: float | None
    provider_model_version: str
    idempotency_identity: str


@dataclass(frozen=True, slots=True)
class FaceIndexFailure:
    asset_identity: str
    stable_error_code: str


@dataclass(frozen=True, slots=True)
class FaceIndexBatchResult:
    occurrences: tuple[IndexedFaceOccurrence, ...]
    failures: tuple[FaceIndexFailure, ...]


@dataclass(frozen=True, slots=True)
class FaceCollectionRequest:
    tenant_scope: str
    group_scope: str
    collection_reference: str


@dataclass(frozen=True, slots=True)
class FaceCollectionResult:
    collection_reference: str
    provider_model_version: str


@dataclass(frozen=True, slots=True)
class FaceDeletionRequest:
    tenant_scope: str
    group_scope: str
    collection_reference: str
    provider_face_references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FaceDeletionResult:
    deleted_face_references: tuple[str, ...]
    not_found_face_references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FaceCollectionDeletionResult:
    outcome: Literal["deleted", "not_found"]


@dataclass(frozen=True, slots=True)
class DeliveryRequest:
    tenant_scope: str
    group_scope: str
    passenger_scope: str
    authorization_identity: str
    # Stable logical identity is separate from the provider-owned object
    # reference. Development fixtures derive deterministic bytes from the
    # former; production storage adapters authorize only the latter.
    asset_identity: str
    media_reference: str
    quality: Literal["thumbnail", "preview", "original", "optimized"]
    availability_state: MediaAvailability
    expected_size_bytes: int
    checksum_sha256: str
    content_type: Literal["image/jpeg", "image/png", "image/webp"] | None


@dataclass(frozen=True, slots=True)
class DeliveryAuthorization:
    state: MediaAvailability
    provider_authorization_reference: str | None
    expected_size_bytes: int | None
    checksum_sha256: str | None
    supports_ranges: bool
    expires_at: datetime | None
    content_type: Literal["image/jpeg", "image/png", "image/webp"] | None
    transport: Literal["unavailable", "development_fixture", "direct_object_storage"] = (
        "unavailable"
    )


@dataclass(frozen=True, slots=True)
class DeliveryResolutionRequest:
    tenant_scope: str
    group_scope: str
    passenger_scope: str
    authorization_identity: str
    asset_identity: str
    media_reference: str
    provider_authorization_reference: str
    quality: Literal["thumbnail", "preview", "original", "optimized"]
    expected_size_bytes: int
    checksum_sha256: str
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryResolution:
    # Internal only. Application schemas must never persist or serialize this
    # short-lived location as an authorization record or permanent media URL.
    location: str
    expires_at: datetime
    supports_ranges: bool


@dataclass(frozen=True, slots=True)
class MediaDeletionRequest:
    tenant_scope: str
    group_scope: str
    media_references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MediaDeletionResult:
    deleted_references: tuple[str, ...]
    not_found_references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MediaRegistrationRequest:
    tenant_scope: str
    group_scope: str
    asset_identity: str
    archive_reference: str
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    byte_size: int
    checksum_sha256: str
    width: int
    height: int
    idempotency_identity: str


@dataclass(frozen=True, slots=True)
class MediaRegistrationResult:
    storage_reference: str | None
    availability_state: MediaAvailability
    # Exact derived object key returned only to bind a direct-upload manifest.
    # Persistence and delivery use storage_reference's version-pinned handle.
    source_object_reference: str | None = None


@dataclass(frozen=True, slots=True)
class MediaPreparationRequest:
    tenant_scope: str
    group_scope: str
    asset_identity: str
    variant: Literal["thumbnail", "preview", "analysis", "original", "optimized"]
    idempotency_identity: str


@dataclass(frozen=True, slots=True)
class MediaAvailabilityRequest:
    tenant_scope: str
    group_scope: str
    asset_identity: str
    variant: Literal["thumbnail", "preview", "analysis", "original", "optimized"]


@dataclass(frozen=True, slots=True)
class MediaAvailabilityResult:
    state: MediaAvailability
    byte_size: int | None
    checksum_sha256: str | None
    delivery_version: int
    storage_reference: str | None = None
    content_type: Literal["image/jpeg", "image/png", "image/webp"] | None = None
    width: int | None = None
    height: int | None = None
    source_object_reference: str | None = None


@runtime_checkable
class LivenessProvider(Protocol):
    @property
    def ready(self) -> bool: ...

    @property
    def client_flow(self) -> Literal["unavailable", "development_simulator", "native"]: ...

    async def create_session(self, request: LivenessSessionRequest) -> LivenessSessionHandle: ...

    async def get_result(self, provider_reference: str) -> LivenessResult: ...

    async def delete_reference(
        self, request: ReferenceDeletionRequest
    ) -> ReferenceDeletionResult: ...


@runtime_checkable
class FaceIndexSearchProvider(Protocol):
    @property
    def ready(self) -> bool: ...

    def collection_reference(self, *, tenant_scope: str, group_scope: str) -> str: ...

    async def ensure_collection(self, request: FaceCollectionRequest) -> FaceCollectionResult: ...

    async def index_faces(self, request: FaceIndexBatchRequest) -> FaceIndexBatchResult: ...

    async def search(self, request: FaceSearchRequest) -> FaceSearchResult: ...

    async def delete_faces(self, request: FaceDeletionRequest) -> FaceDeletionResult: ...

    async def delete_collection(
        self, request: FaceCollectionRequest
    ) -> FaceCollectionDeletionResult: ...


@runtime_checkable
class MediaDeliveryProvider(Protocol):
    @property
    def ready(self) -> bool: ...

    async def register(self, request: MediaRegistrationRequest) -> MediaRegistrationResult: ...

    async def prepare(self, request: MediaPreparationRequest) -> MediaAvailabilityResult: ...

    async def availability(self, request: MediaAvailabilityRequest) -> MediaAvailabilityResult: ...

    async def authorize(self, request: DeliveryRequest) -> DeliveryAuthorization: ...

    async def resolve(self, request: DeliveryResolutionRequest) -> DeliveryResolution: ...

    async def delete(self, request: MediaDeletionRequest) -> MediaDeletionResult: ...
