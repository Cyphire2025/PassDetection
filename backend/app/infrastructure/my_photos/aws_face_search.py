"""Tenant/group-scoped Rekognition collection indexing and search."""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Mapping
from typing import Any, cast

from botocore.exceptions import ClientError

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import (
    FaceCollectionDeletionResult,
    FaceCollectionRequest,
    FaceCollectionResult,
    FaceDeletionRequest,
    FaceDeletionResult,
    FaceIndexAsset,
    FaceIndexBatchRequest,
    FaceIndexBatchResult,
    FaceIndexFailure,
    FaceSearchRequest,
    FaceSearchResult,
    IndexedFaceOccurrence,
    ProviderFaceMatch,
)
from app.infrastructure.my_photos.aws_client_runtime import (
    _async_client_call,
    _client_error_code,
    _raise_provider_failure,
)
from app.infrastructure.my_photos.aws_face_results import (
    _FACE_ID,
    _PERMANENT_INDEX_FAILURES,
    _indexed_occurrence,
    _provider_model_version,
    _unindexed_reason,
)
from app.infrastructure.my_photos.aws_liveness import (
    AwsRekognitionLivenessProvider,
)
from app.infrastructure.my_photos.aws_provider_config import (
    AwsMyPhotosProviderConfig,
)
from app.infrastructure.my_photos.aws_references import (
    _canonical_uuid_scope,
    _decode_versioned_media_reference,
    _hmac_hex,
    _OpaqueReferenceCodec,
    media_object_reference,
)
from app.infrastructure.my_photos.provider_tasks import gather_provider_results


class AwsRekognitionFaceIndexSearchProvider:
    """One Rekognition collection per HMAC-derived tenant/group scope."""

    def __init__(
        self,
        *,
        rekognition_client: Any,
        liveness_provider: AwsRekognitionLivenessProvider,
        config: AwsMyPhotosProviderConfig,
    ) -> None:
        if config.media_bucket is None:
            raise ValueError("Face indexing media bucket is required")
        self._rekognition = rekognition_client
        self._liveness = liveness_provider
        self._config = config
        self._media_codec = _OpaqueReferenceCodec(
            config.reference_active_key_id,
            config.reference_signing_keys,
            maximum_reference_length=4_096,
        )

    @property
    def ready(self) -> bool:
        return True

    def collection_reference(self, *, tenant_scope: str, group_scope: str) -> str:
        tenant = _canonical_uuid_scope(tenant_scope)
        group = _canonical_uuid_scope(group_scope)
        digest = _hmac_hex(
            self._config.scope_hmac_secret,
            f"collection|{tenant}|{group}",
        )[:48]
        return f"{self._config.collection_prefix}-{digest}"

    async def ensure_collection(self, request: FaceCollectionRequest) -> FaceCollectionResult:
        collection_id = self._required_collection(request)
        try:
            response = await _async_client_call(
                self._rekognition.describe_collection,
                CollectionId=collection_id,
            )
        except ClientError as exc:
            if _client_error_code(exc) != "ResourceNotFoundException":
                _raise_provider_failure(exc, operation="Face collection")
            try:
                response = await _async_client_call(
                    self._rekognition.create_collection,
                    CollectionId=collection_id,
                    Tags={"Application": "PassDetection", "DataClass": "MyPhotos"},
                )
            except ClientError as create_exc:
                if _client_error_code(create_exc) != "ResourceAlreadyExistsException":
                    _raise_provider_failure(create_exc, operation="Face collection")
                try:
                    response = await _async_client_call(
                        self._rekognition.describe_collection,
                        CollectionId=collection_id,
                    )
                except ClientError as describe_exc:
                    _raise_provider_failure(describe_exc, operation="Face collection")
        version = _provider_model_version(response)
        return FaceCollectionResult(
            collection_reference=collection_id,
            provider_model_version=version,
        )

    async def index_faces(self, request: FaceIndexBatchRequest) -> FaceIndexBatchResult:
        self._required_collection(request)
        if not request.assets or len(request.assets) > 500:
            raise ValueError("Face index batch is outside the bounded contract")
        semaphore = asyncio.Semaphore(self._config.index_concurrency)

        async def index_one(
            asset: FaceIndexAsset,
        ) -> tuple[tuple[IndexedFaceOccurrence, ...], FaceIndexFailure | None]:
            async with semaphore:
                return await self._index_one(request, asset)

        results = await gather_provider_results([index_one(asset) for asset in request.assets])
        occurrences = tuple(occurrence for result, _failure in results for occurrence in result)
        failures = tuple(failure for _result, failure in results if failure is not None)
        return FaceIndexBatchResult(occurrences=occurrences, failures=failures)

    async def search(self, request: FaceSearchRequest) -> FaceSearchResult:
        collection_id = self._required_collection(request)
        if not 1 <= request.maximum_results <= 4_096:
            raise ValueError("Search result limit is outside the Rekognition boundary")
        try:
            image = self._liveness.reference_image(
                request.reference_face_handle,
                tenant_scope=request.tenant_scope,
                group_scope=request.group_scope,
            )
        except ValueError as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_REFERENCE_INVALID", "Face reference is no longer available."
            ) from exc
        face_count = await self._liveness.detect_reference_faces(image)
        if face_count == 0:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_REFERENCE_NO_FACE", "Face reference is no longer usable."
            )
        if face_count != 1:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_REFERENCE_MULTIPLE_FACES", "Face reference is no longer usable."
            )
        try:
            response = await _async_client_call(
                self._rekognition.search_faces_by_image,
                CollectionId=collection_id,
                Image={"S3Object": image},
                FaceMatchThreshold=self._config.possible_match_threshold,
                MaxFaces=request.maximum_results,
                QualityFilter=self._config.search_quality_filter,
            )
        except ClientError as exc:
            if _client_error_code(exc) == "InvalidParameterException":
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_REFERENCE_NO_FACE", "Face reference is no longer usable."
                ) from None
            _raise_provider_failure(exc, operation="Face search")
        raw_matches = response.get("FaceMatches", ())
        if not isinstance(raw_matches, (list, tuple)) or len(raw_matches) > request.maximum_results:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face search is temporarily unavailable."
            )
        matches: list[ProviderFaceMatch] = []
        for raw in raw_matches:
            if not isinstance(raw, Mapping):
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                    "Face search is temporarily unavailable.",
                )
            face = raw.get("Face")
            similarity = raw.get("Similarity")
            if not isinstance(face, Mapping):
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                    "Face search is temporarily unavailable.",
                )
            face_id = str(face.get("FaceId", ""))
            if (
                _FACE_ID.fullmatch(face_id) is None
                or isinstance(similarity, bool)
                or not isinstance(similarity, (int, float))
                or not math.isfinite(float(similarity))
                or not 0 <= float(similarity) <= 100
            ):
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                    "Face search is temporarily unavailable.",
                )
            matches.append(
                ProviderFaceMatch(
                    provider_face_reference=face_id,
                    similarity=float(similarity),
                )
            )
        return FaceSearchResult(
            matches=tuple(matches),
            provider_model_version=_provider_model_version(response),
        )

    async def delete_faces(self, request: FaceDeletionRequest) -> FaceDeletionResult:
        collection_id = self._required_collection(request)
        requested = tuple(dict.fromkeys(request.provider_face_references))
        if not requested or len(requested) > 4_096:
            raise ValueError("Face deletion batch is outside the provider boundary")
        if any(_FACE_ID.fullmatch(reference) is None for reference in requested):
            raise ValueError("Face deletion reference is invalid")
        try:
            response = await _async_client_call(
                self._rekognition.delete_faces,
                CollectionId=collection_id,
                FaceIds=list(requested),
            )
        except ClientError as exc:
            if _client_error_code(exc) == "ResourceNotFoundException":
                return FaceDeletionResult(
                    deleted_face_references=(),
                    not_found_face_references=requested,
                )
            _raise_provider_failure(exc, operation="Face deletion")
        deleted = tuple(str(value) for value in response.get("DeletedFaces", ()))
        if any(value not in requested for value in deleted):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face deletion is temporarily unavailable."
            )
        not_found: list[str] = []
        unsuccessful = response.get("UnsuccessfulFaceDeletions", ())
        if not isinstance(unsuccessful, (list, tuple)):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face deletion is temporarily unavailable."
            )
        for item in unsuccessful:
            if not isinstance(item, Mapping):
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                    "Face deletion is temporarily unavailable.",
                )
            face_id = str(item.get("FaceId", ""))
            reasons = item.get("Reasons", ())
            if face_id not in requested or not isinstance(reasons, (list, tuple)):
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                    "Face deletion is temporarily unavailable.",
                )
            if "FACE_NOT_FOUND" in reasons:
                not_found.append(face_id)
                continue
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_DELETION_BLOCKED",
                "Face deletion is temporarily unavailable.",
            )
        accounted = set(deleted) | set(not_found)
        # A successful retry may omit an already-absent ID. Normalize those as
        # not found so callers can complete deletion idempotently.
        not_found.extend(value for value in requested if value not in accounted)
        return FaceDeletionResult(
            deleted_face_references=deleted,
            not_found_face_references=tuple(not_found),
        )

    async def delete_collection(
        self, request: FaceCollectionRequest
    ) -> FaceCollectionDeletionResult:
        collection_id = self._required_collection(request)
        try:
            await _async_client_call(
                self._rekognition.delete_collection,
                CollectionId=collection_id,
            )
        except ClientError as exc:
            if _client_error_code(exc) == "ResourceNotFoundException":
                return FaceCollectionDeletionResult(outcome="not_found")
            _raise_provider_failure(exc, operation="Face collection deletion")
        return FaceCollectionDeletionResult(outcome="deleted")

    async def _index_one(
        self,
        request: FaceIndexBatchRequest,
        asset: FaceIndexAsset,
    ) -> tuple[tuple[IndexedFaceOccurrence, ...], FaceIndexFailure | None]:
        expected_reference = media_object_reference(
            self._config,
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
            asset_identity=asset.asset_identity,
            variant="analysis",
        )
        try:
            media_key, media_version = _decode_versioned_media_reference(
                self._media_codec,
                asset.analysis_media_reference,
                config=self._config,
                tenant_scope=request.tenant_scope,
                group_scope=request.group_scope,
            )
        except ValueError:
            return (), FaceIndexFailure(
                asset_identity=asset.asset_identity,
                stable_error_code="MEDIA_REFERENCE_SCOPE_INVALID",
            )
        if media_key != expected_reference:
            return (), FaceIndexFailure(
                asset_identity=asset.asset_identity,
                stable_error_code="MEDIA_REFERENCE_SCOPE_INVALID",
            )
        external_id = f"pd-{hashlib.sha256(asset.idempotency_identity.encode()).hexdigest()}"
        try:
            response = await _async_client_call(
                self._rekognition.index_faces,
                CollectionId=request.collection_reference,
                Image={
                    "S3Object": {
                        "Bucket": cast(str, self._config.media_bucket),
                        "Name": media_key,
                        "Version": media_version,
                    }
                },
                ExternalImageId=external_id,
                DetectionAttributes=[],
                MaxFaces=self._config.index_max_faces_per_asset,
                QualityFilter=self._config.index_quality_filter,
            )
        except ClientError as exc:
            code = _client_error_code(exc)
            if code in _PERMANENT_INDEX_FAILURES:
                return (), FaceIndexFailure(
                    asset_identity=asset.asset_identity,
                    stable_error_code=_PERMANENT_INDEX_FAILURES[code],
                )
            _raise_provider_failure(exc, operation="Face indexing")
        model_version = _provider_model_version(response)
        records = response.get("FaceRecords", ())
        if not isinstance(records, (list, tuple)) or len(records) > 100:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face indexing is temporarily unavailable."
            )
        occurrences: list[IndexedFaceOccurrence] = []
        for record in records:
            occurrence = _indexed_occurrence(
                record,
                asset=asset,
                model_version=model_version,
            )
            occurrences.append(occurrence)
        if occurrences:
            return tuple(occurrences), None
        return (), FaceIndexFailure(
            asset_identity=asset.asset_identity,
            stable_error_code=_unindexed_reason(response),
        )

    def _required_collection(self, request: Any) -> str:
        expected = self.collection_reference(
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
        )
        if request.collection_reference != expected:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_COLLECTION_SCOPE_INVALID", "Face collection is unavailable."
            )
        return expected
