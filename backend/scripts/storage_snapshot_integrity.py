"""Protection and metadata checks for the explicitly quiesced storage migration."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

COPY_PROPERTIES = ("ContentType", "ContentEncoding", "ContentDisposition", "ContentLanguage",
                   "CacheControl", "Expires", "Metadata")


@contextmanager
def migration_lock(directory: Path, endpoint: str, bucket: str):
    """Serialize Docker copy jobs through their shared host evidence directory.

    Linux advisory locks survive neither a process exit nor a crash, so recovery
    does not require deleting a stale lock. Every production copy job mounts the
    same directory. This is deliberately a single-host migration protocol.
    """
    if os.name != "posix":
        raise RuntimeError("Run the storage migration in its Linux maintenance container")
    import fcntl

    identity = hashlib.sha256(f"{endpoint.rstrip('/')}\n{bucket}".encode()).hexdigest()
    path = directory / f".migration-{identity}.lock"
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o600), "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another copy owns this destination's migration lock") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def require_supported_source(storage: Any, bucket: str) -> None:
    # Silently dropping an object lock, default encryption or lifecycle policy
    # would change retention/security behavior. Such buckets need an explicit
    # provider-specific migration, not this conservative single-host helper.
    checks = (
        ("get_object_lock_configuration", {"ObjectLockConfigurationNotFoundError", "ObjectLockConfigurationNotFound"}),
        ("get_bucket_encryption", {"ServerSideEncryptionConfigurationNotFoundError"}),
        ("get_bucket_lifecycle_configuration", {"NoSuchLifecycleConfiguration"}),
        ("get_bucket_policy", {"NoSuchBucketPolicy"}),
        ("get_bucket_cors", {"NoSuchCORSConfiguration"}),
    )
    for method, absent in checks:
        try:
            response = getattr(storage, method)(Bucket=bucket)
        except ClientError as error:
            if error.response["Error"]["Code"] in absent:
                continue
            raise
        relevant = {key: value for key, value in response.items() if key != "ResponseMetadata"}
        if any(relevant.values()):
            raise RuntimeError("Source protection/retention configuration requires a separately reviewed migration")
    require_private_acl(storage.get_bucket_acl(Bucket=bucket))


def require_private_acl(value: dict[str, Any]) -> None:
    # MinIO's compatibility ACL reports an empty owner ID and one owner-only
    # CanonicalUser FULL_CONTROL grant. It has no user-grant ACL support.
    owner = value.get("Owner", {}).get("ID", "")
    grants = value.get("Grants", [])
    if len(grants) != 1:
        raise RuntimeError("Custom ACL requires a separately reviewed storage migration")
    grant = grants[0]
    if (grant.get("Permission") != "FULL_CONTROL"
            or grant.get("Grantee", {}).get("Type") != "CanonicalUser"
            or grant.get("Grantee", {}).get("ID", "") != owner
            or grant.get("Grantee", {}).get("URI")
            or grant.get("Grantee", {}).get("EmailAddress")):
        raise RuntimeError("Custom ACL requires a separately reviewed storage migration")


def attributes(storage: Any, bucket: str, key: str, version: str) -> str:
    head = storage.head_object(Bucket=bucket, Key=key, VersionId=version)
    require_private_acl(storage.get_object_acl(Bucket=bucket, Key=key, VersionId=version))
    if any(head.get(name) for name in (
        "ServerSideEncryption", "SSECustomerAlgorithm", "ObjectLockMode",
        "ObjectLockRetainUntilDate", "ObjectLockLegalHoldStatus",
    )):
        raise RuntimeError("Protected object requires a separately reviewed migration")
    tags = storage.get_object_tagging(Bucket=bucket, Key=key, VersionId=version).get("TagSet", [])
    value = {name: head.get(name) for name in COPY_PROPERTIES}
    value["Tags"] = sorted(tags, key=lambda item: item["Key"])
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
