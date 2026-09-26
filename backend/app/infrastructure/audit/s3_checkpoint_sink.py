"""Dedicated S3 COMPLIANCE/WORM adapter; never use application storage credentials."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.application.interfaces.audit_integrity_sink import AuditIntegrityCheckpoint
from app.infrastructure.audit.checkpoint_codec import (
    AuditIntegrityError,
    decode,
    encode,
    key_id,
    object_key,
)


class S3AuditIntegritySink:
    """Conditional writes plus signed retained versions, with explicit readback.

    S3 configuration cannot prove independent administration. Provision this
    bucket and identity outside the application operator's control. The writer
    must lack delete, retention reduction and legal-hold removal privileges.
    """

    def __init__(self, client: Any, bucket: str, *, public_keys: list[Ed25519PublicKey],
                 private_key: Ed25519PrivateKey | None = None, retention_days: int = 365) -> None:
        if not bucket or not public_keys or retention_days < 1:
            raise ValueError("A dedicated bucket, verification keys and positive retention are required")
        self.client, self.bucket, self.retention_days = client, bucket, retention_days
        self.keys = {key_id(key): key for key in public_keys}
        self.private_key = private_key
        if private_key is not None and key_id(private_key.public_key()) not in self.keys:
            raise ValueError("Signing key must belong to the verification key ring")
        # The pinned botocore predates the IfNoneMatch model parameter. Inject
        # the supported S3 header before signing, on this dedicated client only.
        client.meta.events.register("before-sign.s3.PutObject", self._conditional_create)

    @staticmethod
    def _conditional_create(request: Any, **_: Any) -> None:
        request.headers["If-None-Match"] = "*"

    async def validate_destination(self) -> None:
        versioning = await asyncio.to_thread(self.client.get_bucket_versioning, Bucket=self.bucket)
        lock = await asyncio.to_thread(self.client.get_object_lock_configuration, Bucket=self.bucket)
        if versioning.get("Status") != "Enabled" or lock.get("ObjectLockConfiguration", {}).get("ObjectLockEnabled") != "Enabled":
            raise AuditIntegrityError("checkpoint_destination_not_versioned_and_locked")

    async def publish(self, checkpoint: AuditIntegrityCheckpoint) -> None:
        if self.private_key is None:
            raise AuditIntegrityError("checkpoint_signing_key_required")
        await self.validate_destination()
        key = object_key(checkpoint)
        raw = encode(checkpoint, self.private_key)
        try:
            response = await asyncio.to_thread(
                self.client.put_object, Bucket=self.bucket, Key=key, Body=raw,
                ContentType="application/json", ContentMD5=base64.b64encode(hashlib.md5(raw).digest()).decode("ascii"),
                ObjectLockMode="COMPLIANCE", ObjectLockLegalHoldStatus="ON",
                # S3 HTTP timestamps have whole-second precision. Round up so
                # readback still proves the full promised retention interval.
                ObjectLockRetainUntilDate=(checkpoint.observed_at + timedelta(days=self.retention_days)).replace(microsecond=0) + timedelta(seconds=1),
            )
            version = response.get("VersionId")
            if not version or version == "null":
                raise AuditIntegrityError("checkpoint_write_missing_version")
            stored = await self._read(key, version)
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                raise
            # Do not retry an unconditional PUT after a race. Read the retained
            # version and require the original signed identity to agree.
            versions = await asyncio.to_thread(self.client.list_object_versions, Bucket=self.bucket, Prefix=key, MaxKeys=3)
            exact = [item for item in versions.get("Versions", []) if item["Key"] == key]
            if versions.get("DeleteMarkers") or len(exact) != 1 or versions.get("IsTruncated"):
                raise AuditIntegrityError("checkpoint_version_history_ambiguous") from exc
            stored = await self._read(key, exact[0]["VersionId"])
        if (stored.scope_key, stored.integrity_version, stored.last_sequence, stored.last_hash) != (
                checkpoint.scope_key, checkpoint.integrity_version, checkpoint.last_sequence, checkpoint.last_hash):
            raise AuditIntegrityError("checkpoint_conflicts_with_retained_anchor")

    async def _read(self, key: str, version: str) -> AuditIntegrityCheckpoint:
        response = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key, VersionId=version)
        body = response["Body"]
        try:
            raw = await asyncio.to_thread(body.read, 4097)
        finally:
            await asyncio.to_thread(body.close)
        checkpoint = decode(raw, self.keys)
        # Read the version-specific protection APIs: some compatible stores
        # omit these headers on GetObject even though protection is enforced.
        options = {"Bucket": self.bucket, "Key": key, "VersionId": version}
        retained = await asyncio.to_thread(self.client.get_object_retention, **options)
        held = await asyncio.to_thread(self.client.get_object_legal_hold, **options)
        retention = retained.get("Retention", {}).get("RetainUntilDate")
        if (object_key(checkpoint) != key or response.get("VersionId") != version
                or retained.get("Retention", {}).get("Mode") != "COMPLIANCE"
                or held.get("LegalHold", {}).get("Status") != "ON"
                or retention is None or retention < checkpoint.observed_at + timedelta(days=self.retention_days)):
            raise AuditIntegrityError("checkpoint_retention_or_identity_invalid")
        return checkpoint

    async def checkpoints(self) -> AsyncIterator[AuditIntegrityCheckpoint]:
        await self.validate_destination()
        markers: dict[str, str] = {}
        previous_key: str | None = None
        while True:
            page = await asyncio.to_thread(self.client.list_object_versions, Bucket=self.bucket,
                                          Prefix="audit-checkpoints/v1/", MaxKeys=1000, **markers)
            if page.get("DeleteMarkers"):
                raise AuditIntegrityError("checkpoint_delete_marker_detected")
            for item in page.get("Versions", []):
                key = item["Key"]
                if key == previous_key or not item.get("IsLatest"):
                    raise AuditIntegrityError("checkpoint_overwrite_detected")
                previous_key = key
                yield await self._read(key, item["VersionId"])
            if not page.get("IsTruncated"):
                break
            next_markers = {"KeyMarker": page["NextKeyMarker"], "VersionIdMarker": page["NextVersionIdMarker"]}
            if next_markers == markers:
                raise AuditIntegrityError("checkpoint_pagination_stalled")
            markers = next_markers
