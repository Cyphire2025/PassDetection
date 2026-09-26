"""Actual S3 protocol/retention qualification against an isolated local service."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import boto3
import pytest
from botocore.client import Config
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.application.interfaces.audit_integrity_sink import AuditIntegrityCheckpoint
from app.infrastructure.audit.checkpoint_codec import AuditIntegrityError, object_key
from app.infrastructure.audit.s3_checkpoint_sink import S3AuditIntegritySink

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1" or not os.getenv("AUDIT_TEST_S3_ENDPOINT"),
    reason="explicit isolated immutable S3 service required")]


async def test_actual_signed_conditional_publication_retention_and_overwrite_detection():
    endpoint = os.environ["AUDIT_TEST_S3_ENDPOINT"]
    assert urlsplit(endpoint).hostname in {"localhost", "127.0.0.1", "audit-storage"}
    config = dict(endpoint_url=endpoint, aws_access_key_id=os.environ["AUDIT_TEST_S3_ACCESS_KEY_ID"],
                  aws_secret_access_key=os.environ["AUDIT_TEST_S3_SECRET_ACCESS_KEY"],
                  region_name="us-east-1", config=Config(signature_version="s3v4"))
    client, operator = boto3.client("s3", **config), boto3.client("s3", **config)
    bucket = "ci-audit-" + uuid.uuid4().hex
    client.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
    private = Ed25519PrivateKey.generate()
    sink = S3AuditIntegritySink(client, bucket, public_keys=[private.public_key()], private_key=private)
    checkpoint = AuditIntegrityCheckpoint("global", 1, 1, "a" * 64, datetime.now(UTC))
    try:
        await sink.publish(checkpoint)
        await sink.publish(checkpoint)
        assert [value async for value in sink.checkpoints()] == [checkpoint]
        versions = client.list_object_versions(Bucket=bucket)["Versions"]
        assert len(versions) == 1  # the real If-None-Match header prevented a second version
        with pytest.raises(ClientError) as denied:
            operator.delete_object(Bucket=bucket, Key=object_key(checkpoint), VersionId=versions[0]["VersionId"])
        failure = denied.value.response
        assert (failure["ResponseMetadata"]["HTTPStatusCode"], failure["Error"]["Code"]) in {
            (403, "AccessDenied"), (400, "InvalidRequest"),
        }
        if failure["ResponseMetadata"]["HTTPStatusCode"] == 400:
            assert "WORM protected" in failure["Error"]["Message"]
        # An overprivileged operator can append a new version; the original is
        # still retained, and the verifier must inspect history, not just latest.
        operator.put_object(Bucket=bucket, Key=object_key(checkpoint), Body=b"operator replacement")
        with pytest.raises(AuditIntegrityError):
            _ = [value async for value in sink.checkpoints()]
        retained = operator.get_object(Bucket=bucket, Key=object_key(checkpoint), VersionId=versions[0]["VersionId"])
        assert retained["Body"].read()
        retained["Body"].close()
    finally:
        client.close()
        operator.close()
    # No object/version deletion or bucket cleanup: immutable synthetic data
    # remains in this explicitly disposable container for retained inspection.
