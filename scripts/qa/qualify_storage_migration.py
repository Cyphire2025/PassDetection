"""Synthetic S3-to-SeaweedFS copy proof; never uses production credentials."""

from __future__ import annotations

import json
import multiprocessing
import os
import sqlite3
import sys
import uuid
from contextlib import closing
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, ConnectionClosedError

sys.path.insert(0, "/migration")
from copy_storage_snapshot import copy_snapshot

EVIDENCE = Path("/evidence")


def clients():
    config = Config(signature_version="s3v4", connect_timeout=5, read_timeout=30,
                    retries={"total_max_attempts": 1})
    source = boto3.client("s3", endpoint_url="http://storage-source:9000", region_name="us-east-1",
                         aws_access_key_id="synthetic-source", aws_secret_access_key="synthetic-source-secret", config=config)
    target_endpoint = os.environ.get("QUALIFICATION_DESTINATION_ENDPOINT", "http://object-storage:8333")
    if target_endpoint not in {"http://object-storage:8333", "http://storage-loopback:9000"}:
        raise RuntimeError("Only isolated qualification endpoints are accepted")
    target = boto3.client("s3", endpoint_url=target_endpoint, region_name="us-east-1",
                          aws_access_key_id="synthetic-admin", aws_secret_access_key="synthetic-admin-secret", config=config)
    return source, target


def versions(storage, bucket):
    pages = list(storage.get_paginator("list_object_versions").paginate(Bucket=bucket))
    return pages, [item for page in pages for item in (*page.get("Versions", []), *page.get("DeleteMarkers", []))]


def read(storage, bucket, key, version=None):
    args = {"Bucket": bucket, "Key": key}
    if version is not None:
        args["VersionId"] = version
    with closing(storage.get_object(**args)["Body"]) as body:
        return body.read()


def rejected(call, message):
    try:
        call()
    except RuntimeError as error:
        assert message in str(error), str(error)
        return str(error)
    raise AssertionError(f"Unsafe copy was accepted; expected {message}")


def fixture(source, target, identifier, name):
    bucket = f"passdetection-ci-{name}-{identifier[:20]}"
    for storage in (source, target):
        storage.create_bucket(Bucket=bucket)
    source.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    original = source.put_object(Bucket=bucket, Key="record", Body=b"retained fixture bytes",
                                 ContentType="text/plain", Metadata={"purpose": "original"}, Tagging="purpose=original")
    journal = EVIDENCE / f"{name}-{identifier}.sqlite"
    return bucket, journal, original["VersionId"]


class Proxy:
    def __init__(self, storage):
        self.storage = storage

    def __getattr__(self, name):
        return getattr(self.storage, name)


def metadata_and_tag_changes(source, target, identifier):
    outcomes = {}
    for side in ("source", "destination"):
        for attribute in ("metadata", "tags"):
            bucket, journal, original_version = fixture(source, target, identifier, f"{side}-{attribute}")
            copy_snapshot(source, target, bucket, journal)
            storage = source if side == "source" else target
            previous = storage.head_object(Bucket=bucket, Key="record")
            original_bytes = read(storage, bucket, "record", previous["VersionId"])
            if attribute == "tags":
                # Tag replacement mutates the existing version without changing
                # object bytes, ETag, version ID, or last-modified timestamp.
                storage.put_object_tagging(Bucket=bucket, Key="record", VersionId=previous["VersionId"],
                                           Tagging={"TagSet": [{"Key": "purpose", "Value": "changed"}]})
                changed = storage.head_object(Bucket=bucket, Key="record")
                assert all(previous[key] == changed[key] for key in ("VersionId", "ETag", "LastModified", "ContentLength"))
            else:
                # S3 metadata is immutable per version: replacement creates a
                # new version while preserving the exact body and object name.
                storage.copy_object(Bucket=bucket, Key="record",
                                    CopySource={"Bucket": bucket, "Key": "record", "VersionId": previous["VersionId"]},
                                    MetadataDirective="REPLACE", Metadata={"purpose": "changed"}, ContentType="text/plain")
                changed = storage.head_object(Bucket=bucket, Key="record")
                assert changed["Metadata"] == {"purpose": "changed"}
                assert changed["VersionId"] != previous["VersionId"]
            assert read(storage, bucket, "record") == original_bytes
            expected = "Source changed" if side == "source" else "metadata/tags changed" if attribute == "tags" else "unjournaled"
            failure = rejected(lambda bucket=bucket, journal=journal: copy_snapshot(source, target, bucket, journal), expected)
            assert read(source, bucket, "record", original_version) == b"retained fixture bytes"
            outcomes[f"{side}_{attribute}_only_change"] = {
                "rejected": True, "body_unchanged": True, "source_original_version_preserved": True,
                "same_version_mutation": attribute == "tags", "reason": failure,
            }
            print(f"Verified {side} {attribute}-only change rejection", flush=True)
    return outcomes


def changes_during_copy(source, target, identifier):
    bucket, journal, original_version = fixture(source, target, identifier, "source-during-copy")

    class SourceTagMutatingTarget(Proxy):
        def put_object(self, **kwargs):
            response = self.storage.put_object(**kwargs)
            source.put_object_tagging(Bucket=bucket, Key="record", VersionId=original_version,
                                       Tagging={"TagSet": [{"Key": "purpose", "Value": "changed-during-copy"}]})
            return response

    source_error = rejected(lambda: copy_snapshot(source, SourceTagMutatingTarget(target), bucket, journal), "Source changed during copy")
    assert read(source, bucket, "record", original_version) == b"retained fixture bytes"

    bucket, journal, original_version = fixture(source, target, identifier, "target-final-check")

    class FinalInventoryMutatingTarget(Proxy):
        def __init__(self, storage):
            super().__init__(storage)
            self.inventories = 0

        def get_paginator(self, name):
            if name == "list_object_versions":
                self.inventories += 1
                if self.inventories == 2:
                    current = self.storage.head_object(Bucket=bucket, Key="record")
                    self.storage.put_object_tagging(Bucket=bucket, Key="record", VersionId=current["VersionId"],
                                                    Tagging={"TagSet": [{"Key": "purpose", "Value": "changed-before-final-check"}]})
            return self.storage.get_paginator(name)

    target_error = rejected(lambda: copy_snapshot(source, FinalInventoryMutatingTarget(target), bucket, journal), "differs from the source")
    assert read(source, bucket, "record", original_version) == b"retained fixture bytes"
    print("Verified source recheck and destination final-inventory tag tampering", flush=True)
    return {"source_during_copy_rejected": source_error, "destination_final_tag_tamper_rejected": target_error}


def lock_owner(bucket, journal, acquired, release, outcome):
    source, target = clients()

    class HoldingSource(Proxy):
        def get_object_lock_configuration(self, **kwargs):
            # copy_snapshot obtains the directory lock before this API call.
            acquired.set()
            if not release.wait(30):
                raise RuntimeError("Qualification lock holder was not released")
            return self.storage.get_object_lock_configuration(**kwargs)

    try:
        outcome.put({"report": copy_snapshot(HoldingSource(source), target, bucket, Path(journal))})
    except Exception as error:
        outcome.put({"error": f"{type(error).__name__}: {error}"})
        raise


def overlapping_processes(source, target, identifier):
    bucket, first_journal, original_version = fixture(source, target, identifier, "overlap")
    second_journal = EVIDENCE / f"different-journal-{identifier}.sqlite"
    context = multiprocessing.get_context("spawn")
    acquired, release, outcome = context.Event(), context.Event(), context.Queue()
    owner = context.Process(target=lock_owner, args=(bucket, str(first_journal), acquired, release, outcome))
    owner.start()
    try:
        assert acquired.wait(20), "Child process did not acquire the migration lock"
        failure = rejected(lambda: copy_snapshot(source, target, bucket, second_journal), "migration lock")
        assert versions(target, bucket)[1] == [], "Contender changed the destination while the owner was paused"
    finally:
        release.set()
        owner.join(30)
        if owner.is_alive():
            owner.terminate()
            owner.join(5)
    assert owner.exitcode == 0, "Qualification lock owner did not complete"
    completed = outcome.get(timeout=5)
    assert "report" in completed, completed
    assert read(source, bucket, "record", original_version) == b"retained fixture bytes"
    assert copy_snapshot(source, target, bucket, first_journal) == completed["report"]
    print("Verified separate-process overlap refusal across different journal filenames", flush=True)
    return {"different_processes": True, "same_evidence_directory": True, "different_journals": True,
            "contender_rejected_before_target_write": True, "owner_completed": True, "reason": failure}


def successful_put_lost_response(source, target, identifier):
    bucket, journal, original_version = fixture(source, target, identifier, "lost-response")

    class LostResponseTarget(Proxy):
        def put_object(self, **kwargs):
            self.storage.put_object(**kwargs)
            raise ConnectionClosedError(endpoint_url=self.storage.meta.endpoint_url)

    try:
        copy_snapshot(source, LostResponseTarget(target), bucket, journal)
    except ConnectionClosedError:
        pass
    else:
        raise AssertionError("Injected lost PUT response was accepted")
    _, orphaned = versions(target, bucket)
    assert len(orphaned) == 1
    with sqlite3.connect(journal) as database:
        assert database.execute("SELECT count(*) FROM copied").fetchone()[0] == 0
    failure = rejected(lambda: copy_snapshot(source, target, bucket, journal), "unjournaled")
    assert versions(target, bucket)[1] == orphaned
    assert read(target, bucket, "record", orphaned[0]["VersionId"]) == b"retained fixture bytes"
    assert read(source, bucket, "record", original_version) == b"retained fixture bytes"
    print("Verified successful PUT with lost response fails closed and retains both copies", flush=True)
    return {"actual_put_succeeded": True, "response_loss_simulated": True, "journal_has_no_confirmed_copy": True,
            "retry_rejected": True, "source_preserved": True, "destination_orphan_preserved": True,
            "automatic_crash_recovery_proven": False,
            "recovery_requirement": "Use a fresh isolated destination snapshot, or manually review and reconcile the uncertain write. Do not delete source data.",
            "reason": failure}


def paginated_history(source, target, identifier):
    bucket = f"passdetection-ci-pagination-{identifier}"
    source.create_bucket(Bucket=bucket)
    target.create_bucket(Bucket=bucket)
    source.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    for index in range(1001):
        source.put_object(Bucket=bucket, Key="history", Body=f"synthetic version {index}".encode(), ContentType="text/plain")
        if index % 200 == 0:
            print(f"Pagination fixture: seeded {index + 1}/1001 versions", flush=True)
    pages, original = versions(source, bucket)
    assert len(pages) >= 2 and len(original) == 1001
    assert pages[0]["IsTruncated"] and pages[0].get("NextVersionIdMarker")

    class ProgressTarget(Proxy):
        count = 0

        def put_object(self, **kwargs):
            result = self.storage.put_object(**kwargs)
            self.count += 1
            if self.count % 100 == 0:
                print(f"Pagination copy: verified write {self.count}/1001", flush=True)
            return result

    report = copy_snapshot(source, ProgressTarget(target), bucket, EVIDENCE / f"pagination-{identifier}.sqlite")
    target_pages, copied = versions(target, bucket)
    assert report["versions_including_delete_markers"] == len(copied) == 1001
    assert len(target_pages) >= 2
    assert read(target, bucket, "history") == read(source, bucket, "history") == b"synthetic version 1000"
    assert versions(source, bucket)[1] == original
    print("Verified all 1001 same-key versions across source and target pagination", flush=True)
    return {"source_pages": len(pages), "destination_pages": len(target_pages), "versions": len(copied),
            "version_id_marker_exercised": True, "all_bodies_sha256_verified": True, "source_inventory_unchanged": True}


def insufficient_capacity(source, target, identifier):
    bucket, journal, original_version = fixture(source, target, identifier, "capacity")
    initial_source = versions(source, bucket)[1]
    attempted_writes = []

    class ObservedTarget(Proxy):
        def __getattr__(self, name):
            method = super().__getattr__(name)
            if name.startswith(("put_", "delete_", "copy_")):
                def tracked(**kwargs):
                    attempted_writes.append(name)
                    return method(**kwargs)
                return tracked
            return method

    failure = rejected(
        lambda: copy_snapshot(source, ObservedTarget(target), bucket, journal, capacity_bytes=2 * 1024**3),
        "Insufficient verified target disk headroom",
    )
    assert not attempted_writes, attempted_writes
    assert versions(target, bucket)[1] == []
    assert versions(source, bucket)[1] == initial_source
    assert read(source, bucket, "record", original_version) == b"retained fixture bytes"
    print("Verified insufficient disk headroom rejects before destination writes", flush=True)
    return {"rejected": True, "reason": failure, "destination_writes": 0,
            "source_inventory_unchanged": True, "source_original_version_preserved": True}


def main() -> None:
    source, target = clients()
    identifier = uuid.uuid4().hex
    bucket = f"passdetection-ci-migration-{identifier}"
    source.create_bucket(Bucket=bucket)
    # A fresh production stage has no bucket. Exercise guarded bucket creation
    # inside the copy lock instead of quietly provisioning it in this fixture.
    source.put_object(Bucket=bucket, Key="legacy-null", Body=b"unversioned original")
    source.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    source.put_object(Bucket=bucket, Key="history", Body=b"historical bytes")
    source.put_object(Bucket=bucket, Key="history", Body=b"current bytes", ContentType="text/plain",
                      ContentDisposition="attachment; filename=synthetic.txt", Metadata={"purpose": "qualification"}, Tagging="source=synthetic")
    source.put_object(Bucket=bucket, Key="deleted", Body=b"retained deleted bytes")
    source.delete_object(Bucket=bucket, Key="deleted")
    source.put_object(Bucket=bucket, Key="unicode/旅券.txt", Body=b"utf8 object name")
    source.put_object(Bucket=bucket, Key="empty", Body=b"")
    journal = Path("/evidence") / f"{identifier}.sqlite"
    report = copy_snapshot(source, target, bucket, journal)
    assert target.head_bucket(Bucket=bucket)["ResponseMetadata"]["HTTPStatusCode"] == 200
    assert report["versions_including_delete_markers"] == 7
    assert copy_snapshot(source, target, bucket, journal) == report
    assert target.get_object(Bucket=bucket, Key="history")["Body"].read() == b"current bytes"
    assert source.get_object(Bucket=bucket, Key="history")["Body"].read() == b"current bytes"
    for provider in (source, target):
        try:
            provider.head_object(Bucket=bucket, Key="deleted")
        except ClientError as error:
            assert error.response["ResponseMetadata"]["HTTPStatusCode"] == 404
        else:
            raise AssertionError("Deleted source state was not preserved")
    source.put_object(Bucket=bucket, Key="changed-after-snapshot", Body=b"new source data")
    try:
        copy_snapshot(source, target, bucket, journal)
    except RuntimeError as error:
        assert "Source changed" in str(error)
    else:
        raise AssertionError("Changed source snapshot was accepted")
    conflict_bucket = f"passdetection-ci-conflict-{identifier}"
    source.create_bucket(Bucket=conflict_bucket)
    target.create_bucket(Bucket=conflict_bucket)
    target.put_object(Bucket=conflict_bucket, Key="preserve-existing", Body=b"existing destination")
    try:
        copy_snapshot(source, target, conflict_bucket, Path("/evidence") / f"conflict-{identifier}.sqlite")
    except RuntimeError as error:
        assert "unjournaled" in str(error)
    else:
        raise AssertionError("Unrelated destination data was accepted")
    assert target.get_object(Bucket=conflict_bucket, Key="preserve-existing")["Body"].read() == b"existing destination"
    source_provider = os.environ.get("QUALIFICATION_SOURCE_PROVIDER", "MinIO legacy fixture")
    if source_provider not in {"MinIO legacy fixture", "SeaweedFS 4.47"}:
        raise RuntimeError("Unknown synthetic source provider")
    report.update(synthetic=True, source_provider=source_provider, repeat_idempotent=True, source_change_rejected=True,
                  unexpected_destination_rejected=True, current_delete_state_preserved=True)
    report["qualification_complete"] = False
    report["qualification_cases"] = {}
    evidence_path = EVIDENCE / "migration-evidence.json"
    try:
        for name, check in (
            ("metadata_and_tags", metadata_and_tag_changes),
            ("during_copy_integrity", changes_during_copy),
            ("overlapping_processes", overlapping_processes),
            ("successful_put_lost_response", successful_put_lost_response),
            ("insufficient_capacity", insufficient_capacity),
            ("paginated_history", paginated_history),
        ):
            print(f"Starting isolated storage check: {name}", flush=True)
            report["qualification_cases"][name] = check(source, target, identifier)
            evidence_path.write_text(json.dumps(report, indent=2) + "\n")
    except Exception as error:
        report["qualification_error"] = f"{type(error).__name__}: {error}"
        evidence_path.write_text(json.dumps(report, indent=2) + "\n")
        raise
    report["qualification_complete"] = True
    evidence_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
