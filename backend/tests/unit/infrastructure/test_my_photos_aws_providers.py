from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

import boto3
import pytest
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from pydantic import ValidationError

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
from app.application.my_photos.providers import (
    DeliveryAuthorization,
    DeliveryRequest,
    DeliveryResolutionRequest,
    FaceCollectionRequest,
    FaceDeletionRequest,
    FaceIndexAsset,
    FaceIndexBatchRequest,
    FaceSearchRequest,
    LivenessSessionRequest,
    MediaAvailabilityRequest,
    MediaDeletionRequest,
    MediaPreparationRequest,
    MediaRegistrationRequest,
    ReferenceDeletionRequest,
)
from app.core.config.settings import MyPhotosSettings
from app.infrastructure.my_photos.aws_providers import (
    AwsRekognitionFaceIndexSearchProvider,
    AwsRekognitionLivenessProvider,
    S3DirectMediaDeliveryProvider,
    aws_provider_config,
    media_object_reference,
)
from app.infrastructure.my_photos.providers import build_provider_bundle

TENANT_ID = "11111111-1111-4111-8111-111111111111"
GROUP_ID = "22222222-2222-4222-8222-222222222222"
PASSENGER_ID = "33333333-3333-4333-8333-333333333333"
SESSION_ID = "44444444-4444-4444-8444-444444444444"
FACE_ONE = "55555555-5555-4555-8555-555555555555"
FACE_TWO = "66666666-6666-4666-8666-666666666666"
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
CHECKSUM = "a" * 64
LIVENESS_KMS_ARN = "arn:aws:kms:ap-south-1:123456789012:key/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MEDIA_KMS_ARN = "arn:aws:kms:ap-south-1:123456789012:key/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _client_error(code: str, operation: str = "Operation") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "sensitive provider detail"}},
        operation,
    )


def _settings(**overrides: object) -> MyPhotosSettings:
    values: dict[str, object] = {
        "liveness_provider": "aws_rekognition",
        "face_search_provider": "aws_rekognition",
        "media_provider": "s3",
        "aws_region": "ap-south-1",
        "aws_liveness_output_bucket": "passdetection-my-photos-liveness",
        "aws_liveness_kms_key_id": LIVENESS_KMS_ARN,
        "aws_media_bucket": "passdetection-my-photos-media",
        "aws_media_kms_key_id": MEDIA_KMS_ARN,
        "aws_expected_bucket_owner": "123456789012",
        "aws_scope_hmac_secret": "s" * 48,
        "aws_provider_hmac_key_id": "reference-v2",
        "aws_provider_hmac_secret": "x" * 48,
        "native_temporary_credentials_mode": "cognito_identity_pool",
        "aws_cognito_identity_pool_id": ("ap-south-1:77777777-7777-4777-8777-777777777777"),
        "reference_frame_retention_seconds": 3_600,
        "maximum_search_results": 4_096,
        "match_config_version": "aws-calibrated-v1",
    }
    values.update(overrides)
    return MyPhotosSettings(**values)  # type: ignore[arg-type]


class FakeS3:
    def __init__(self) -> None:
        self.heads: dict[str, dict[str, object]] = {}
        self.head_requests: list[dict[str, object]] = []
        self.deleted: list[dict[str, object]] = []
        self.presigned: list[tuple[str, dict[str, object]]] = []
        self.presigned_location: str | None = None
        self.liveness_version = "version-one"

    def head_object(self, **kwargs: object) -> dict[str, object]:
        self.head_requests.append(kwargs)
        key = str(kwargs["Key"])
        if key.startswith("my-photos/liveness/") and key not in self.heads:
            return {
                "ContentLength": 256_000,
                "ContentType": "image/jpeg",
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": LIVENESS_KMS_ARN,
                "VersionId": self.liveness_version,
            }
        if key not in self.heads:
            raise _client_error("NoSuchKey", "HeadObject")
        return self.heads[key]

    def delete_object(self, **kwargs: object) -> dict[str, object]:
        self.deleted.append(kwargs)
        return {}

    def generate_presigned_url(self, method: str, **kwargs: object) -> str:
        self.presigned.append((method, kwargs))
        if self.presigned_location is not None:
            return self.presigned_location
        parameters = kwargs["Params"]
        assert isinstance(parameters, dict)
        return (
            "https://passdetection-my-photos-media.s3.ap-south-1.amazonaws.com/"
            f"{parameters['Key']}?X-Amz-Signature=fake"
        )


class FakeRekognition:
    def __init__(self, *, confidence: float = 98.2, face_count: int = 1) -> None:
        self.confidence = confidence
        self.face_count = face_count
        self.create_requests: list[dict[str, object]] = []
        self.index_requests: list[dict[str, object]] = []
        self.search_requests: list[dict[str, object]] = []
        self.delete_face_requests: list[dict[str, object]] = []
        self.created_collections: list[dict[str, object]] = []
        self.deleted_collections: list[dict[str, object]] = []
        self.reference_key: str | None = None
        self.reference_version = "version-one"

    def create_face_liveness_session(self, **kwargs: object) -> dict[str, object]:
        self.create_requests.append(kwargs)
        settings = kwargs["Settings"]
        assert isinstance(settings, dict)
        output = settings["OutputConfig"]
        assert isinstance(output, dict)
        self.reference_key = f"{output['S3KeyPrefix']}/reference.jpg"
        return {"SessionId": SESSION_ID}

    def get_face_liveness_session_results(self, **kwargs: object) -> dict[str, object]:
        assert kwargs == {"SessionId": SESSION_ID}
        assert self.reference_key is not None
        return {
            "SessionId": SESSION_ID,
            "Status": "SUCCEEDED",
            "Confidence": self.confidence,
            "ReferenceImage": {
                "S3Object": {
                    "Bucket": "passdetection-my-photos-liveness",
                    "Name": self.reference_key,
                    "Version": self.reference_version,
                }
            },
        }

    def detect_faces(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["Attributes"] == ["DEFAULT"]
        return {"FaceDetails": [{} for _ in range(self.face_count)]}

    def describe_collection(self, **kwargs: object) -> dict[str, object]:
        raise _client_error("ResourceNotFoundException", "DescribeCollection")

    def create_collection(self, **kwargs: object) -> dict[str, object]:
        self.created_collections.append(kwargs)
        return {"StatusCode": 200, "FaceModelVersion": "7.0"}

    def index_faces(self, **kwargs: object) -> dict[str, object]:
        self.index_requests.append(kwargs)
        identity = str(kwargs["ExternalImageId"])
        face_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identity))
        return {
            "FaceModelVersion": "7.0",
            "FaceRecords": [
                {
                    "Face": {
                        "FaceId": face_id,
                        "BoundingBox": {
                            "Left": 0.1,
                            "Top": 0.2,
                            "Width": 0.3,
                            "Height": 0.4,
                        },
                        "Confidence": 99.1,
                    }
                }
            ],
            "UnindexedFaces": [],
        }

    def search_faces_by_image(self, **kwargs: object) -> dict[str, object]:
        self.search_requests.append(kwargs)
        return {
            "FaceModelVersion": "7.0",
            "FaceMatches": [
                {"Face": {"FaceId": FACE_ONE}, "Similarity": 96.4},
                {"Face": {"FaceId": FACE_TWO}, "Similarity": 84.2},
            ],
        }

    def delete_faces(self, **kwargs: object) -> dict[str, object]:
        self.delete_face_requests.append(kwargs)
        return {
            "DeletedFaces": [FACE_ONE],
            "UnsuccessfulFaceDeletions": [{"FaceId": FACE_TWO, "Reasons": ["FACE_NOT_FOUND"]}],
        }

    def delete_collection(self, **kwargs: object) -> dict[str, object]:
        self.deleted_collections.append(kwargs)
        return {"StatusCode": 200}


def _liveness_provider(
    rekognition: FakeRekognition,
    s3: FakeS3,
) -> AwsRekognitionLivenessProvider:
    return AwsRekognitionLivenessProvider(
        rekognition_client=rekognition,
        s3_client=s3,
        config=aws_provider_config(_settings()),
        clock=lambda: NOW,
    )


async def _passed_reference(
    provider: AwsRekognitionLivenessProvider,
    *,
    challenge_mode: str = "movement_and_light",
) -> tuple[str, str]:
    handle = await provider.create_session(
        LivenessSessionRequest(
            session_identity="liveness-request-one",
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            passenger_scope=PASSENGER_ID,
            challenge_mode=challenge_mode,  # type: ignore[arg-type]
            expires_at=NOW + timedelta(seconds=180),
            audit_image_retention_enabled=False,
            reference_frame_retention_seconds=3_600,
        )
    )
    result = await provider.get_result(handle.provider_reference)
    assert result.outcome == "passed"
    assert result.reference_face_handle is not None
    return handle.native_launch_handle or "", result.reference_face_handle


def test_aws_production_provider_configuration_fails_closed_until_complete() -> None:
    with pytest.raises(ValidationError, match="complete AWS Rekognition/S3"):
        MyPhotosSettings(liveness_provider="aws_rekognition")
    with pytest.raises(ValidationError, match="4096"):
        _settings(maximum_search_results=5_000)
    with pytest.raises(ValidationError, match="cognito_identity_pool"):
        _settings(native_temporary_credentials_mode="disabled")
    with pytest.raises(ValidationError, match="cognito_identity_pool"):
        _settings(native_temporary_credentials_mode="custom_temporary_broker")
    with pytest.raises(ValidationError, match="COGNITO_IDENTITY_POOL_ID"):
        _settings(aws_cognito_identity_pool_id=None)
    with pytest.raises(ValidationError, match="canonical key ARNs"):
        _settings(aws_media_kms_key_id="alias/my-photos-media")
    with pytest.raises(ValidationError, match="configured AWS region"):
        _settings(
            aws_media_kms_key_id=(
                "arn:aws:kms:us-east-1:123456789012:key/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            )
        )
    with pytest.raises(ValidationError, match="bucket-owner account"):
        _settings(
            aws_media_kms_key_id=(
                "arn:aws:kms:ap-south-1:999999999999:key/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            )
        )
    assert MyPhotosSettings().aws_region is None
    assert MyPhotosSettings().aws_scope_hmac_secret is None
    assert MyPhotosSettings().aws_provider_hmac_key_id is None
    assert MyPhotosSettings().aws_provider_hmac_secret is None
    assert MyPhotosSettings().aws_liveness_audit_images_limit == 0


def test_custom_s3_endpoint_is_explicitly_development_only() -> None:
    config = _settings(
        aws_s3_endpoint_url="https://objects.internal.example:9443",
        aws_s3_addressing_style="path",
        aws_expected_bucket_owner=None,
    )

    config.validate_runtime_environment("development")
    for app_env in ("staging", "production"):
        with pytest.raises(ValueError, match="distinct AWS S3 object origin"):
            config.validate_runtime_environment(app_env)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="distinct AWS S3 object origin"):
        build_provider_bundle(
            SimpleNamespace(app_env="production", my_photos=config)  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("challenge_mode", "aws_challenge"),
    [
        ("movement_and_light", "FaceMovementAndLightChallenge"),
        ("movement_only", "FaceMovementChallenge"),
    ],
)
async def test_liveness_session_is_idempotent_short_lived_and_server_authoritative(
    challenge_mode: str,
    aws_challenge: str,
) -> None:
    rekognition = FakeRekognition()
    s3 = FakeS3()
    provider = _liveness_provider(rekognition, s3)
    native_handle, reference = await _passed_reference(
        provider,
        challenge_mode=challenge_mode,
    )

    assert native_handle == SESSION_ID
    assert reference != SESSION_ID
    assert "https://" not in reference
    create = rekognition.create_requests[0]
    assert create["ClientRequestToken"] == "liveness-request-one"
    settings = create["Settings"]
    assert isinstance(settings, dict)
    assert settings["AuditImagesLimit"] == 0
    assert settings["ChallengePreferences"] == [{"Type": aws_challenge}]

    deletion = await provider.delete_reference(
        ReferenceDeletionRequest(
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            passenger_scope=PASSENGER_ID,
            provider_reference=reference,
            deletion_identity="delete-reference-one",
        )
    )
    assert deletion.outcome == "deleted"
    assert s3.deleted[-1]["Key"] == rekognition.reference_key
    assert s3.deleted[-1]["VersionId"] == "version-one"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("confidence", "face_count", "outcome", "code"),
    [
        (89.9, 1, "rejected", "LIVENESS_REJECTED"),
        (99.0, 0, "no_face", "NO_FACE"),
        (99.0, 2, "multiple_faces", "MULTIPLE_FACES"),
    ],
)
async def test_liveness_normalizes_threshold_no_face_and_multiple_faces(
    confidence: float,
    face_count: int,
    outcome: str,
    code: str,
) -> None:
    rekognition = FakeRekognition(confidence=confidence, face_count=face_count)
    s3 = FakeS3()
    provider = _liveness_provider(rekognition, s3)
    handle = await provider.create_session(
        LivenessSessionRequest(
            session_identity="liveness-request-two",
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            passenger_scope=PASSENGER_ID,
            challenge_mode="movement_and_light",
            expires_at=NOW + timedelta(seconds=180),
            reference_frame_retention_seconds=3_600,
        )
    )
    result = await provider.get_result(handle.provider_reference)
    assert result.outcome == outcome
    assert result.stable_error_code == code
    assert result.reference_face_handle is None
    assert s3.deleted[-1]["Key"] == rekognition.reference_key


@pytest.mark.asyncio
async def test_liveness_rejects_reference_object_encrypted_with_the_wrong_kms_key() -> None:
    rekognition = FakeRekognition()
    s3 = FakeS3()
    provider = _liveness_provider(rekognition, s3)
    handle = await provider.create_session(
        LivenessSessionRequest(
            session_identity="liveness-kms-mismatch",
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            passenger_scope=PASSENGER_ID,
            challenge_mode="movement_and_light",
            expires_at=NOW + timedelta(seconds=180),
            reference_frame_retention_seconds=3_600,
        )
    )
    assert rekognition.reference_key is not None
    s3.heads[rekognition.reference_key] = {
        "ContentLength": 256_000,
        "ContentType": "image/jpeg",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": (
            "arn:aws:kms:ap-south-1:123456789012:key/cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        ),
        "VersionId": "version-one",
    }
    with pytest.raises(MyPhotosUnavailable) as captured:
        await provider.get_result(handle.provider_reference)
    assert captured.value.code == "MY_PHOTOS_REFERENCE_ENCRYPTION_INVALID"


@pytest.mark.asyncio
async def test_liveness_captures_head_version_when_result_omits_it() -> None:
    rekognition = FakeRekognition()
    original_results = rekognition.get_face_liveness_session_results

    def results_without_version(**kwargs: object) -> dict[str, object]:
        response = original_results(**kwargs)
        reference = response["ReferenceImage"]
        assert isinstance(reference, dict)
        s3_object = reference["S3Object"]
        assert isinstance(s3_object, dict)
        s3_object.pop("Version")
        return response

    rekognition.get_face_liveness_session_results = results_without_version  # type: ignore[method-assign]
    s3 = FakeS3()
    provider = _liveness_provider(rekognition, s3)
    _native, reference = await _passed_reference(provider)
    decoded = provider.reference_image(
        reference,
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
    )
    assert decoded["Version"] == "version-one"
    assert "VersionId" not in s3.head_requests[-1]


@pytest.mark.asyncio
async def test_liveness_fails_closed_without_object_version_evidence() -> None:
    rekognition = FakeRekognition()
    s3 = FakeS3()
    provider = _liveness_provider(rekognition, s3)
    handle = await provider.create_session(
        LivenessSessionRequest(
            session_identity="liveness-version-missing",
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            passenger_scope=PASSENGER_ID,
            challenge_mode="movement_and_light",
            expires_at=NOW + timedelta(seconds=180),
            reference_frame_retention_seconds=3_600,
        )
    )
    assert rekognition.reference_key is not None
    s3.heads[rekognition.reference_key] = {
        "ContentLength": 256_000,
        "ContentType": "image/jpeg",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": LIVENESS_KMS_ARN,
    }
    with pytest.raises(MyPhotosUnavailable) as captured:
        await provider.get_result(handle.provider_reference)
    assert captured.value.code == "MY_PHOTOS_REFERENCE_ENCRYPTION_INVALID"


@pytest.mark.asyncio
async def test_liveness_reference_version_uses_full_s3_1024_byte_boundary() -> None:
    rekognition = FakeRekognition()
    s3 = FakeS3()
    rekognition.reference_version = "v" * 1_024
    s3.liveness_version = rekognition.reference_version
    provider = _liveness_provider(rekognition, s3)

    _native, reference = await _passed_reference(provider)
    assert len(reference.encode("utf-8")) <= 4_096
    assert (
        provider.reference_image(
            reference,
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
        )["Version"]
        == "v" * 1_024
    )

    rekognition.reference_version = "v" * 1_025
    s3.liveness_version = rekognition.reference_version
    with pytest.raises(MyPhotosUnavailable) as captured:
        await _passed_reference(provider)
    assert captured.value.code == "MY_PHOTOS_PROVIDER_RESULT_INVALID"


@pytest.mark.asyncio
async def test_reference_signing_key_rotation_preserves_search_and_exact_deletion() -> None:
    rekognition = FakeRekognition()
    s3 = FakeS3()
    old_config = aws_provider_config(
        _settings(
            aws_provider_hmac_key_id="reference-v1",
            aws_provider_hmac_secret="y" * 48,
        )
    )
    old_provider = AwsRekognitionLivenessProvider(
        rekognition_client=rekognition,
        s3_client=s3,
        config=old_config,
        clock=lambda: NOW,
    )
    _native, old_reference = await _passed_reference(old_provider)

    rotated_config = aws_provider_config(
        _settings(
            aws_provider_hmac_key_id="reference-v2",
            aws_provider_hmac_secret="x" * 48,
            aws_provider_hmac_previous_keys={"reference-v1": "y" * 48},
        )
    )
    rotated_provider = AwsRekognitionLivenessProvider(
        rekognition_client=rekognition,
        s3_client=s3,
        config=rotated_config,
        clock=lambda: NOW,
    )
    image = rotated_provider.reference_image(
        old_reference,
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
    )
    assert image["Name"] == rekognition.reference_key
    result = await rotated_provider.delete_reference(
        ReferenceDeletionRequest(
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            passenger_scope=PASSENGER_ID,
            provider_reference=old_reference,
            deletion_identity="rotate-delete-one",
        )
    )
    assert result.outcome == "deleted"
    assert media_object_reference(
        old_config,
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
        asset_identity="asset-one",
        variant="analysis",
    ) == media_object_reference(
        rotated_config,
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
        asset_identity="asset-one",
        variant="analysis",
    )


@pytest.mark.asyncio
async def test_group_collection_index_search_and_delete_use_exact_aws_shapes() -> None:
    rekognition = FakeRekognition()
    s3 = FakeS3()
    config = aws_provider_config(_settings())
    liveness = _liveness_provider(rekognition, s3)
    face_provider = AwsRekognitionFaceIndexSearchProvider(
        rekognition_client=rekognition,
        liveness_provider=liveness,
        config=config,
    )
    media_provider = S3DirectMediaDeliveryProvider(
        s3_client=s3,
        config=config,
        clock=lambda: NOW,
    )
    collection = face_provider.collection_reference(
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
    )
    assert TENANT_ID not in collection and GROUP_ID not in collection
    ensured = await face_provider.ensure_collection(
        FaceCollectionRequest(
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            collection_reference=collection,
        )
    )
    assert ensured.provider_model_version == "7.0"
    assert rekognition.created_collections[0]["CollectionId"] == collection

    assets_list: list[FaceIndexAsset] = []
    raw_analysis_references: list[str] = []
    for index in range(2):
        asset_identity = f"asset-{index}"
        raw_reference = media_object_reference(
            config,
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            asset_identity=asset_identity,
            variant="analysis",
        )
        s3.heads[raw_reference] = _media_head()
        available = await media_provider.availability(
            MediaAvailabilityRequest(
                tenant_scope=TENANT_ID,
                group_scope=GROUP_ID,
                asset_identity=asset_identity,
                variant="analysis",
            )
        )
        assert available.storage_reference is not None
        raw_analysis_references.append(raw_reference)
        assets_list.append(
            FaceIndexAsset(
                asset_identity=asset_identity,
                analysis_media_reference=available.storage_reference,
                idempotency_identity=f"gallery-index-v1-{index}",
            )
        )
    assets = tuple(assets_list)
    indexed = await face_provider.index_faces(
        FaceIndexBatchRequest(
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            collection_reference=collection,
            index_version=1,
            assets=assets,
        )
    )
    assert len(indexed.occurrences) == 2
    assert not indexed.failures
    assert {
        (
            request["Image"]["S3Object"]["Bucket"],
            request["Image"]["S3Object"]["Name"],
            request["Image"]["S3Object"]["Version"],
        )
        for request in rekognition.index_requests
    } == {
        (
            "passdetection-my-photos-media",
            raw_reference,
            "media-version-one",
        )
        for raw_reference in raw_analysis_references
    }
    assert all(request["MaxFaces"] == 100 for request in rekognition.index_requests)

    _native, reference = await _passed_reference(liveness)
    searched = await face_provider.search(
        FaceSearchRequest(
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            collection_reference=collection,
            reference_face_handle=reference,
            maximum_results=4_096,
        )
    )
    assert [match.similarity for match in searched.matches] == [96.4, 84.2]
    search = rekognition.search_requests[0]
    assert search["CollectionId"] == collection
    assert search["FaceMatchThreshold"] == 80.0
    assert search["MaxFaces"] == 4_096

    deletion = await face_provider.delete_faces(
        FaceDeletionRequest(
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            collection_reference=collection,
            provider_face_references=(FACE_ONE, FACE_TWO),
        )
    )
    assert deletion.deleted_face_references == (FACE_ONE,)
    assert deletion.not_found_face_references == (FACE_TWO,)
    assert rekognition.delete_face_requests[0] == {
        "CollectionId": collection,
        "FaceIds": [FACE_ONE, FACE_TWO],
    }
    assert (
        await face_provider.delete_collection(
            FaceCollectionRequest(
                tenant_scope=TENANT_ID,
                group_scope=GROUP_ID,
                collection_reference=collection,
            )
        )
    ).outcome == "deleted"


@pytest.mark.asyncio
async def test_cross_group_collection_reference_fails_before_provider_io() -> None:
    rekognition = FakeRekognition()
    s3 = FakeS3()
    config = aws_provider_config(_settings())
    face_provider = AwsRekognitionFaceIndexSearchProvider(
        rekognition_client=rekognition,
        liveness_provider=_liveness_provider(rekognition, s3),
        config=config,
    )
    with pytest.raises(MyPhotosUnavailable) as captured:
        await face_provider.ensure_collection(
            FaceCollectionRequest(
                tenant_scope=TENANT_ID,
                group_scope=GROUP_ID,
                collection_reference="pd-my-photos-wrong-group",
            )
        )
    assert captured.value.code == "MY_PHOTOS_COLLECTION_SCOPE_INVALID"
    assert not rekognition.created_collections


def _media_head() -> dict[str, object]:
    return {
        "ContentLength": 123_456,
        "ContentType": "image/jpeg",
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": MEDIA_KMS_ARN,
        "VersionId": "media-version-one",
        "ChecksumSHA256": base64.b64encode(bytes.fromhex(CHECKSUM)).decode("ascii"),
        "ChecksumType": "FULL_OBJECT",
        "Metadata": {
            "sha256": CHECKSUM,
            "width": "1920",
            "height": "1080",
            "delivery-version": "2",
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("byte_size", [MAX_MY_PHOTOS_MEDIA_BYTES, MAX_MY_PHOTOS_MEDIA_BYTES + 1])
async def test_s3_media_metadata_enforces_mobile_item_ceiling(byte_size: int) -> None:
    s3 = FakeS3()
    provider = S3DirectMediaDeliveryProvider(
        s3_client=s3,
        config=aws_provider_config(_settings()),
        clock=lambda: NOW,
    )
    reference = provider.object_reference(
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
        asset_identity="bounded-media-asset",
        variant="original",
    )
    head = _media_head()
    head["ContentLength"] = byte_size
    s3.heads[reference] = head
    request = MediaRegistrationRequest(
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
        asset_identity="bounded-media-asset",
        archive_reference=reference,
        mime_type="image/jpeg",
        byte_size=byte_size,
        checksum_sha256=CHECKSUM,
        width=1920,
        height=1080,
        idempotency_identity="bounded-media-register",
    )

    if byte_size == MAX_MY_PHOTOS_MEDIA_BYTES:
        assert (await provider.register(request)).storage_reference is not None
    else:
        with pytest.raises(MyPhotosUnavailable) as captured:
            await provider.register(request)
        assert captured.value.code == "MY_PHOTOS_MEDIA_METADATA_INVALID"


async def _authorized_media(
    provider: S3DirectMediaDeliveryProvider,
    s3: FakeS3,
    *,
    asset_identity: str,
) -> tuple[str, DeliveryRequest, DeliveryAuthorization]:
    raw_reference = provider.object_reference(
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
        asset_identity=asset_identity,
        variant="original",
    )
    s3.heads[raw_reference] = _media_head()
    registered = await provider.register(
        MediaRegistrationRequest(
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            asset_identity=asset_identity,
            archive_reference=raw_reference,
            mime_type="image/jpeg",
            byte_size=123_456,
            checksum_sha256=CHECKSUM,
            width=1920,
            height=1080,
            idempotency_identity=f"register:{asset_identity}",
        )
    )
    assert registered.storage_reference is not None
    request = DeliveryRequest(
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
        passenger_scope=PASSENGER_ID,
        authorization_identity=f"authorization:{asset_identity}:2",
        asset_identity=asset_identity,
        media_reference=registered.storage_reference,
        quality="original",
        availability_state="original_available_online",
        expected_size_bytes=123_456,
        checksum_sha256=CHECKSUM,
        content_type="image/jpeg",
    )
    authorization = await provider.authorize(request)
    assert authorization.provider_authorization_reference is not None
    assert authorization.expires_at is not None
    return raw_reference, request, authorization


def _real_auto_presigned_location(*, media_key: str, version_id: str) -> str:
    config = aws_provider_config(_settings())
    assert config.region == "ap-south-1"
    assert config.s3_addressing_style == "auto"
    assert config.media_bucket is not None
    assert config.expected_bucket_owner is not None
    client = boto3.client(
        "s3",
        region_name=config.region,
        aws_access_key_id="local-contract-test",
        aws_secret_access_key="local-contract-test",
        config=BotoConfig(
            signature_version="v4",
            s3={"addressing_style": config.s3_addressing_style},
        ),
    )
    return str(
        client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": config.media_bucket,
                "Key": media_key,
                "VersionId": version_id,
                "ExpectedBucketOwner": config.expected_bucket_owner,
            },
            ExpiresIn=300,
            HttpMethod="GET",
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "mismatch", "composite"])
async def test_s3_media_requires_matching_native_full_object_sha256(failure: str) -> None:
    s3 = FakeS3()
    provider = S3DirectMediaDeliveryProvider(
        s3_client=s3,
        config=aws_provider_config(_settings()),
        clock=lambda: NOW,
    )
    reference = provider.object_reference(
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
        asset_identity="checksum-policy-asset",
        variant="original",
    )
    head = _media_head()
    if failure == "missing":
        head.pop("ChecksumSHA256")
    elif failure == "mismatch":
        head["ChecksumSHA256"] = base64.b64encode(bytes.fromhex("b" * 64)).decode("ascii")
    else:
        head["ChecksumType"] = "COMPOSITE"
    s3.heads[reference] = head
    with pytest.raises(MyPhotosUnavailable) as captured:
        await provider.register(
            MediaRegistrationRequest(
                tenant_scope=TENANT_ID,
                group_scope=GROUP_ID,
                asset_identity="checksum-policy-asset",
                archive_reference=reference,
                mime_type="image/jpeg",
                byte_size=123_456,
                checksum_sha256=CHECKSUM,
                width=1920,
                height=1080,
                idempotency_identity="checksum-policy-register",
            )
        )
    assert captured.value.code in {
        "MY_PHOTOS_MEDIA_CHECKSUM_INVALID",
        "MY_PHOTOS_MEDIA_METADATA_INVALID",
    }


@pytest.mark.asyncio
async def test_s3_media_uses_exact_objects_opaque_grants_and_fresh_range_capable_urls() -> None:
    s3 = FakeS3()
    config = aws_provider_config(_settings())
    provider = S3DirectMediaDeliveryProvider(
        s3_client=s3,
        config=config,
        clock=lambda: NOW,
    )
    reference = provider.object_reference(
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
        asset_identity="immutable-asset-one",
        variant="original",
    )
    s3.heads[reference] = _media_head()
    registered = await provider.register(
        MediaRegistrationRequest(
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            asset_identity="immutable-asset-one",
            archive_reference=reference,
            mime_type="image/jpeg",
            byte_size=123_456,
            checksum_sha256=CHECKSUM,
            width=1920,
            height=1080,
            idempotency_identity="register-one",
        )
    )
    assert registered.storage_reference is not None
    assert registered.storage_reference != reference
    assert registered.source_object_reference == reference
    available = await provider.prepare(
        MediaPreparationRequest(
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            asset_identity="immutable-asset-one",
            variant="original",
            idempotency_identity="prepare-one",
        )
    )
    assert available.storage_reference == registered.storage_reference
    assert available.source_object_reference == reference
    assert available.delivery_version == 2
    assert s3.head_requests[-1]["ChecksumMode"] == "ENABLED"

    request = DeliveryRequest(
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
        passenger_scope=PASSENGER_ID,
        authorization_identity="authorization-one:2",
        asset_identity="immutable-asset-one",
        media_reference=available.storage_reference,
        quality="original",
        availability_state="original_available_online",
        expected_size_bytes=123_456,
        checksum_sha256=CHECKSUM,
        content_type="image/jpeg",
    )
    authorization = await provider.authorize(request)
    assert authorization.transport == "direct_object_storage"
    assert authorization.supports_ranges is True
    assert authorization.provider_authorization_reference is not None
    assert "https://" not in authorization.provider_authorization_reference
    assert authorization.expires_at is not None

    resolved = await provider.resolve(
        DeliveryResolutionRequest(
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
            passenger_scope=request.passenger_scope,
            authorization_identity=request.authorization_identity,
            asset_identity=request.asset_identity,
            media_reference=request.media_reference,
            provider_authorization_reference=authorization.provider_authorization_reference,
            quality=request.quality,
            expected_size_bytes=request.expected_size_bytes,
            checksum_sha256=request.checksum_sha256,
            content_type="image/jpeg",
            expires_at=authorization.expires_at,
        )
    )
    assert resolved.location.startswith("https://")
    assert resolved.supports_ranges is True
    method, presign = s3.presigned[0]
    assert method == "get_object"
    assert presign["HttpMethod"] == "GET"
    assert presign["ExpiresIn"] <= 300
    parameters = presign["Params"]
    assert isinstance(parameters, dict)
    assert parameters["Key"] == reference
    assert parameters["VersionId"] == "media-version-one"
    assert "Range" not in parameters

    deleted = await provider.delete(
        MediaDeletionRequest(
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            media_references=(available.storage_reference,),
        )
    )
    assert deleted.deleted_references == (available.storage_reference,)
    assert s3.deleted[-1]["Key"] == reference
    assert s3.deleted[-1]["VersionId"] == "media-version-one"


@pytest.mark.asyncio
async def test_s3_media_version_id_accepts_1024_utf8_bytes_and_rejects_1025() -> None:
    s3 = FakeS3()
    provider = S3DirectMediaDeliveryProvider(
        s3_client=s3,
        config=aws_provider_config(_settings()),
        clock=lambda: NOW,
    )
    reference = provider.object_reference(
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
        asset_identity="version-boundary-asset",
        variant="original",
    )
    accepted = _media_head()
    accepted["VersionId"] = "v" * 1_024
    s3.heads[reference] = accepted
    registered = await provider.register(
        MediaRegistrationRequest(
            tenant_scope=TENANT_ID,
            group_scope=GROUP_ID,
            asset_identity="version-boundary-asset",
            archive_reference=reference,
            mime_type="image/jpeg",
            byte_size=123_456,
            checksum_sha256=CHECKSUM,
            width=1920,
            height=1080,
            idempotency_identity="version-boundary-accepted",
        )
    )
    assert registered.storage_reference is not None
    assert len(registered.storage_reference.encode("utf-8")) <= 4_096

    rejected = _media_head()
    rejected["VersionId"] = "v" * 1_025
    s3.heads[reference] = rejected
    with pytest.raises(MyPhotosUnavailable) as captured:
        await provider.register(
            MediaRegistrationRequest(
                tenant_scope=TENANT_ID,
                group_scope=GROUP_ID,
                asset_identity="version-boundary-asset",
                archive_reference=reference,
                mime_type="image/jpeg",
                byte_size=123_456,
                checksum_sha256=CHECKSUM,
                width=1920,
                height=1080,
                idempotency_identity="version-boundary-rejected",
            )
        )
    assert captured.value.code == "MY_PHOTOS_MEDIA_METADATA_INVALID"


@pytest.mark.asyncio
async def test_s3_media_accepts_real_botocore_auto_presigned_location_for_ap_south_1() -> None:
    s3 = FakeS3()
    provider = S3DirectMediaDeliveryProvider(
        s3_client=s3,
        config=aws_provider_config(_settings()),
        clock=lambda: NOW,
    )
    raw_reference, request, authorization = await _authorized_media(
        provider,
        s3,
        asset_identity="real-presigner-asset",
    )
    s3.presigned_location = _real_auto_presigned_location(
        media_key=raw_reference,
        version_id="media-version-one",
    )

    resolution = await provider.resolve(
        DeliveryResolutionRequest(
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
            passenger_scope=request.passenger_scope,
            authorization_identity=request.authorization_identity,
            asset_identity=request.asset_identity,
            media_reference=request.media_reference,
            provider_authorization_reference=authorization.provider_authorization_reference,
            quality=request.quality,
            expected_size_bytes=request.expected_size_bytes,
            checksum_sha256=request.checksum_sha256,
            content_type="image/jpeg",
            expires_at=authorization.expires_at,
        )
    )

    assert resolution.location == s3.presigned_location
    assert urlsplit(resolution.location).hostname in {
        "passdetection-my-photos-media.s3.amazonaws.com",
        "passdetection-my-photos-media.s3.ap-south-1.amazonaws.com",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_part", ["host", "port", "path"])
async def test_s3_media_rejects_mutated_real_botocore_presigned_location(
    invalid_part: str,
) -> None:
    s3 = FakeS3()
    provider = S3DirectMediaDeliveryProvider(
        s3_client=s3,
        config=aws_provider_config(_settings()),
        clock=lambda: NOW,
    )
    raw_reference, request, authorization = await _authorized_media(
        provider,
        s3,
        asset_identity=f"real-presigner-negative-{invalid_part}",
    )
    valid_location = _real_auto_presigned_location(
        media_key=raw_reference,
        version_id="media-version-one",
    )
    parsed = urlsplit(valid_location)
    if invalid_part == "host":
        mutated = parsed._replace(netloc=f"{parsed.hostname}.evil.test")
    elif invalid_part == "port":
        mutated = parsed._replace(netloc=f"{parsed.hostname}:9443")
    else:
        mutated = parsed._replace(path=f"/wrong/{raw_reference}")
    s3.presigned_location = urlunsplit(mutated)

    with pytest.raises(MyPhotosUnavailable) as captured:
        await provider.resolve(
            DeliveryResolutionRequest(
                tenant_scope=request.tenant_scope,
                group_scope=request.group_scope,
                passenger_scope=request.passenger_scope,
                authorization_identity=request.authorization_identity,
                asset_identity=request.asset_identity,
                media_reference=request.media_reference,
                provider_authorization_reference=authorization.provider_authorization_reference,
                quality=request.quality,
                expected_size_bytes=request.expected_size_bytes,
                checksum_sha256=request.checksum_sha256,
                content_type="image/jpeg",
                expires_at=authorization.expires_at,
            )
        )

    assert captured.value.code == "MY_PHOTOS_PROVIDER_RESULT_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malicious_location",
    [
        "http://passdetection-my-photos-media.s3.ap-south-1.amazonaws.com/key",
        "https://passdetection-my-photos-media.s3.ap-south-1.amazonaws.com.evil.test/key",
        "https://passdetection-my-photos-media.s3.ap-south-1.amazonaws.com@evil.test/key",
        "https://passdetection-my-photos-media.s3.ap-south-1.amazonaws.com:9443/key",
        "https://passdetection-my-photos-media.s3.ap-south-1.amazonaws.com/key#fragment",
        "https://passdetection-my-photos-media.s3.ap-south-1.amazonaws.com/wrong-key",
    ],
)
async def test_s3_media_rejects_presigned_locations_outside_exact_reviewed_origin_and_key(
    malicious_location: str,
) -> None:
    s3 = FakeS3()
    provider = S3DirectMediaDeliveryProvider(
        s3_client=s3,
        config=aws_provider_config(_settings()),
        clock=lambda: NOW,
    )
    _raw_reference, request, authorization = await _authorized_media(
        provider,
        s3,
        asset_identity="redirect-origin-asset",
    )
    s3.presigned_location = malicious_location
    with pytest.raises(MyPhotosUnavailable) as captured:
        await provider.resolve(
            DeliveryResolutionRequest(
                tenant_scope=request.tenant_scope,
                group_scope=request.group_scope,
                passenger_scope=request.passenger_scope,
                authorization_identity=request.authorization_identity,
                asset_identity=request.asset_identity,
                media_reference=request.media_reference,
                provider_authorization_reference=authorization.provider_authorization_reference,
                quality=request.quality,
                expected_size_bytes=request.expected_size_bytes,
                checksum_sha256=request.checksum_sha256,
                content_type="image/jpeg",
                expires_at=authorization.expires_at,
            )
        )
    assert captured.value.code == "MY_PHOTOS_PROVIDER_RESULT_INVALID"


@pytest.mark.asyncio
async def test_custom_s3_presigned_location_requires_exact_configured_port() -> None:
    s3 = FakeS3()
    provider = S3DirectMediaDeliveryProvider(
        s3_client=s3,
        config=aws_provider_config(
            _settings(
                aws_s3_endpoint_url="https://objects.internal.example:9443",
                aws_s3_addressing_style="path",
                aws_expected_bucket_owner=None,
            )
        ),
        clock=lambda: NOW,
    )
    raw_reference, request, authorization = await _authorized_media(
        provider,
        s3,
        asset_identity="custom-endpoint-asset",
    )
    resolution_request = DeliveryResolutionRequest(
        tenant_scope=request.tenant_scope,
        group_scope=request.group_scope,
        passenger_scope=request.passenger_scope,
        authorization_identity=request.authorization_identity,
        asset_identity=request.asset_identity,
        media_reference=request.media_reference,
        provider_authorization_reference=authorization.provider_authorization_reference,
        quality=request.quality,
        expected_size_bytes=request.expected_size_bytes,
        checksum_sha256=request.checksum_sha256,
        content_type="image/jpeg",
        expires_at=authorization.expires_at,
    )
    s3.presigned_location = (
        "https://objects.internal.example:9443/passdetection-my-photos-media/"
        f"{raw_reference}?X-Amz-Signature=fake"
    )
    assert (await provider.resolve(resolution_request)).location == s3.presigned_location

    s3.presigned_location = s3.presigned_location.replace(":9443/", ":9444/")
    with pytest.raises(MyPhotosUnavailable) as captured:
        await provider.resolve(resolution_request)
    assert captured.value.code == "MY_PHOTOS_PROVIDER_RESULT_INVALID"


def test_factory_uses_standard_credential_chain_without_static_key_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def client(service: str, **kwargs: object) -> object:
        calls.append((service, kwargs))
        return SimpleNamespace()

    monkeypatch.setattr(
        "app.infrastructure.my_photos.providers.boto3.client",
        client,
    )
    bundle = build_provider_bundle(
        SimpleNamespace(app_env="production", my_photos=_settings())  # type: ignore[arg-type]
    )
    assert bundle.provider_name == "aws"
    assert [service for service, _kwargs in calls] == ["rekognition", "s3"]
    assert all(
        "aws_access_key_id" not in kwargs
        and "aws_secret_access_key" not in kwargs
        and "aws_session_token" not in kwargs
        for _service, kwargs in calls
    )
