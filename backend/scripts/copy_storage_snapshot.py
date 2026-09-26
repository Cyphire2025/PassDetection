"""Copy a quiesced S3 snapshot, retaining versions and never deleting source data.

Credentials come from the environment. The private SQLite journal records
old/new version IDs and permits a verified retry only when every target write
was recorded. An uncertain PUT stops recovery; retain both stores and use a
fresh target or reconcile manually. Version IDs/timestamps are provider-specific.
No application endpoint is changed by this program.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from storage_snapshot_integrity import (
    COPY_PROPERTIES,
    attributes,
    migration_lock,
    require_supported_source,
)

CHUNK_BYTES = 1024 * 1024


def client(prefix: str) -> Any:
    return boto3.client(
        "s3", endpoint_url=os.environ[f"{prefix}_ENDPOINT"],
        aws_access_key_id=os.environ[f"{prefix}_ACCESS_KEY"],
        aws_secret_access_key=os.environ[f"{prefix}_SECRET_KEY"],
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=60,
                      retries={"total_max_attempts": 3, "mode": "standard"}),
    )


def inventory(storage: Any, bucket: str, db: sqlite3.Connection, table: str) -> str:
    if table not in {"source", "recheck", "destination"}:
        raise ValueError("Invalid local journal table")
    db.execute(f"DROP TABLE IF EXISTS {table}")
    db.execute(f"CREATE TABLE {table} (key TEXT, version TEXT, deleted INTEGER, size INTEGER, "
               "etag TEXT, modified TEXT, latest INTEGER, ordinal INTEGER, attributes TEXT, PRIMARY KEY(key,version))")
    ordinal = 0
    for page in storage.get_paginator("list_object_versions").paginate(Bucket=bucket):
        for deleted, items in ((False, page.get("Versions", [])), (True, page.get("DeleteMarkers", []))):
            for item in items:
                properties = "" if deleted else attributes(storage, bucket, item["Key"], item["VersionId"])
                db.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?,?)", (
                    item["Key"], item["VersionId"], int(deleted), item.get("Size", 0),
                    item.get("ETag", ""), item["LastModified"].isoformat(), int(item["IsLatest"]), ordinal, properties,
                ))
                ordinal += 1
    digest = hashlib.sha256()
    for row in db.execute(f"SELECT key,version,deleted,size,etag,modified,latest,attributes FROM {table} ORDER BY key,version"):
        digest.update(json.dumps(tuple(row), ensure_ascii=True, separators=(",", ":")).encode() + b"\n")
    db.commit()
    return digest.hexdigest()


def body_hash(storage: Any, bucket: str, key: str, version: str) -> tuple[str, int]:
    response = storage.get_object(Bucket=bucket, Key=key, VersionId=version)
    digest, size = hashlib.sha256(), 0
    with closing(response["Body"]) as body:
        for block in iter(lambda: body.read(CHUNK_BYTES), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def copy_version(source: Any, destination: Any, bucket: str, row: sqlite3.Row) -> tuple[str, str]:
    key, version = row["key"], row["version"]
    if row["deleted"]:
        # With versioning enabled this creates a destination delete marker. It
        # preserves the source's current visibility; historical bytes remain.
        result = destination.delete_object(Bucket=bucket, Key=key)
        if not result.get("DeleteMarker") or not result.get("VersionId"):
            raise RuntimeError("Destination did not retain a versioned delete marker")
        return result["VersionId"], ""
    if row["size"] > 5 * 1024**3:
        raise RuntimeError("Object exceeds the reviewed single-object migration limit")
    response = source.get_object(Bucket=bucket, Key=key, VersionId=version, IfMatch=row["etag"])
    properties = {key: response[key] for key in COPY_PROPERTIES if key in response}
    tags = source.get_object_tagging(Bucket=bucket, Key=key, VersionId=version).get("TagSet", [])
    if tags:
        properties["Tagging"] = urlencode([(item["Key"], item["Value"]) for item in tags])
    digest, size = hashlib.sha256(), 0
    with closing(response["Body"]) as body, tempfile.TemporaryFile() as temporary:
        for block in iter(lambda: body.read(CHUNK_BYTES), b""):
            size += len(block)
            if size > row["size"]:
                raise RuntimeError("Source object grew during copy")
            digest.update(block)
            temporary.write(block)
        if size != row["size"]:
            raise RuntimeError("Source object was truncated during copy")
        temporary.seek(0)
        result = destination.put_object(Bucket=bucket, Key=key, Body=temporary, **properties)
    copied_version = result.get("VersionId")
    if not copied_version or copied_version == "null":
        raise RuntimeError("Destination failed to retain a stable object version")
    expected = (digest.hexdigest(), size)
    if body_hash(destination, bucket, key, copied_version) != expected:
        raise RuntimeError("Copied object failed independent full-body SHA-256 verification")
    copied = destination.head_object(Bucket=bucket, Key=key, VersionId=copied_version)
    if any(copied.get(name) != properties.get(name) for name in COPY_PROPERTIES):
        raise RuntimeError("Copied object metadata differs from the source")
    actual_tags = destination.get_object_tagging(Bucket=bucket, Key=key, VersionId=copied_version).get("TagSet", [])
    if sorted(actual_tags, key=lambda value: value["Key"]) != sorted(tags, key=lambda value: value["Key"]):
        raise RuntimeError("Copied object tags differ from the source")
    return copied_version, digest.hexdigest()


def require_expected_destination(db: sqlite3.Connection) -> None:
    extra = db.execute("SELECT key,version FROM destination EXCEPT SELECT key,target_version FROM copied LIMIT 1").fetchone()
    missing = db.execute("SELECT key,target_version FROM copied EXCEPT SELECT key,version FROM destination LIMIT 1").fetchone()
    if extra or missing:
        raise RuntimeError("Destination contains unjournaled or missing versions; no existing object was overwritten")


def copy_snapshot(source: Any, destination: Any, bucket: str, journal: Path, *, capacity_bytes: int | None = None) -> dict[str, Any]:
    journal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if journal.is_symlink():
        raise RuntimeError("Refusing a symbolic-link migration journal")
    if not journal.exists():
        with os.fdopen(os.open(journal, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"):
            pass
    source_endpoint, target_endpoint = source.meta.endpoint_url, destination.meta.endpoint_url
    if source_endpoint.rstrip("/") == target_endpoint.rstrip("/"):
        raise RuntimeError("Source and destination must be independent endpoints")
    with migration_lock(journal.parent, target_endpoint, bucket):
        require_supported_source(source, bucket)
        return _copy_locked_snapshot(source, destination, bucket, journal, capacity_bytes=capacity_bytes)


def _copy_locked_snapshot(source: Any, destination: Any, bucket: str, journal: Path, *, capacity_bytes: int | None) -> dict[str, Any]:
    source_endpoint, target_endpoint = source.meta.endpoint_url, destination.meta.endpoint_url
    with closing(sqlite3.connect(journal)) as db:
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS copied (key TEXT, source_version TEXT, target_version TEXT, sha256 TEXT, PRIMARY KEY(key,source_version))")
        settings = {row[0]: row[1] for row in db.execute("SELECT name,value FROM settings")}
        identity = json.dumps([source_endpoint, target_endpoint, bucket])
        if settings and settings.get("identity") != identity:
            raise RuntimeError("Migration journal belongs to different endpoints or bucket")
        current = inventory(source, bucket, db, "recheck")
        if settings.get("source_digest", current) != current:
            raise RuntimeError("Source changed since the snapshot; pause all writers before migration")
        if not settings:
            db.execute("CREATE TABLE source AS SELECT * FROM recheck")
            db.executemany("INSERT INTO settings VALUES (?,?)", (("identity", identity), ("source_digest", current)))
            db.commit()
        total, largest = db.execute("SELECT coalesce(sum(size),0),coalesce(max(size),0) FROM source").fetchone()
        if capacity_bytes is not None and capacity_bytes < total * 1.25 + largest + 2 * 1024**3:
            raise RuntimeError("Insufficient verified target disk headroom for retained versions, temporary copy and reserve")
        # This first destination mutation is inside the exclusion lock and only
        # after the journal identity, source protections and capacity are known.
        try:
            destination.head_bucket(Bucket=bucket)
        except ClientError as error:
            if error.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            destination.create_bucket(Bucket=bucket)
        inventory(destination, bucket, db, "destination")
        require_expected_destination(db)
        destination.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
        if destination.get_bucket_versioning(Bucket=bucket).get("Status") != "Enabled":
            raise RuntimeError("Destination versioning is not enabled")
        for row in db.execute("SELECT * FROM source ORDER BY key,modified,latest,ordinal DESC"):
            existing = db.execute("SELECT target_version,sha256 FROM copied WHERE key=? AND source_version=?", (row["key"], row["version"])).fetchone()
            if existing:
                if not row["deleted"] and body_hash(destination, bucket, row["key"], existing[0]) != (existing[1], row["size"]):
                    raise RuntimeError("Previously copied object changed or failed integrity validation")
                if not row["deleted"] and attributes(destination, bucket, row["key"], existing[0]) != row["attributes"]:
                    raise RuntimeError("Previously copied object metadata/tags changed")
                continue
            version, digest = copy_version(source, destination, bucket, row)
            db.execute("INSERT INTO copied VALUES (?,?,?,?)", (row["key"], row["version"], version, digest))
            db.commit()
        if inventory(source, bucket, db, "recheck") != current:
            raise RuntimeError("Source changed during copy; cutover is forbidden")
        inventory(destination, bucket, db, "destination")
        require_expected_destination(db)
        mismatched = db.execute("SELECT s.key FROM source s JOIN copied c ON c.key=s.key AND c.source_version=s.version "
                                "JOIN destination d ON d.key=c.key AND d.version=c.target_version "
                                "WHERE s.latest<>d.latest OR s.deleted<>d.deleted OR s.attributes<>d.attributes LIMIT 1").fetchone()
        if mismatched:
            raise RuntimeError("Destination current version/deletion state differs from the source")
        versions, total_bytes = db.execute("SELECT count(*),coalesce(sum(size),0) FROM source").fetchone()
        return {"version": 1, "bucket": bucket, "source_endpoint": source_endpoint,
                "destination_endpoint": target_endpoint, "source_digest": current,
                "versions_including_delete_markers": versions, "bytes": total_bytes,
                "every_copied_body_sha256_verified": True, "source_deleted": False,
                "preserved_original_version_ids_in_journal": True}


def main() -> None:
    bucket = os.environ["S3_BUCKET_NAME"]
    available = int(os.environ["STORAGE_AVAILABLE_BYTES"])
    if available < 1:
        raise RuntimeError("A positive measured target disk capacity is required")
    source = client("STORAGE_SOURCE")
    # The release replaces the whole local provider endpoint. Refuse to strand
    # an additional bucket used by another application or an older workflow.
    buckets = {item["Name"] for item in source.list_buckets().get("Buckets", [])}
    if buckets != {bucket}:
        raise RuntimeError("Source provider bucket inventory differs from the one reviewed application bucket; a separate migration is required")
    report = copy_snapshot(source, client("STORAGE_DESTINATION"), bucket, Path(os.environ["STORAGE_MIGRATION_JOURNAL"]), capacity_bytes=available)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
