"""Exercise real application S3 operations and isolation on synthetic buckets only."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
from urllib.error import HTTPError
from urllib.request import urlopen

import boto3
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from botocore.client import Config
from botocore.exceptions import ClientError


def denied(operation) -> None:
    try:
        operation()
    except ClientError as error:
        assert error.response["ResponseMetadata"]["HTTPStatusCode"] == 403
    else:
        raise AssertionError("The synthetic unauthorized operation was accepted")


def download(url: str) -> bytes:
    with urlopen(url, timeout=10) as response:
        return response.read()


async def main() -> None:
    if os.environ.get("S3_BUCKET_NAME") != "passdetection-ci-storage":
        raise RuntimeError("This qualification only operates on its synthetic bucket")
    endpoint = os.environ["S3_ENDPOINT_URL"]
    if endpoint not in {"http://object-storage:8333", "http://storage-loopback:9000", "http://storage-stage:9000"}:
        raise RuntimeError("This qualification requires the isolated provider network")
    config = Config(signature_version="s3v4", retries={"max_attempts": 2}, connect_timeout=5, read_timeout=10)
    admin = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id="synthetic-admin",
                         aws_secret_access_key="synthetic-admin-secret", config=config)
    bucket = os.environ["S3_BUCKET_NAME"]
    for name in (bucket, "passdetection-ci-forbidden"):
        try:
            admin.create_bucket(Bucket=name)
        except ClientError as error:
            if error.response["Error"]["Code"] not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise
    admin.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    repo = MinioStorageRepository()
    repo.check_bucket_access()
    key = "synthetic/passport.txt"
    payload = b"Synthetic passport document bytes\n" * 5000
    await repo.upload_file(payload, key, "text/plain")
    assert await repo.get_file(key) == payload
    metadata = await repo.stat_file(key)
    assert metadata.size_bytes == len(payload)
    assert metadata.checksum_sha256 == hashlib.sha256(payload).hexdigest()
    assert metadata.content_type == "text/plain"
    assert await repo.get_file_range(key, start=7, end=511) == payload[7:512]
    assert b"".join([part async for part in repo.stream_file(key, start=4, expected_bytes=len(payload)-4)]) == payload[4:]
    assert await repo.calculate_file_sha256(key, expected_bytes=len(payload)) == hashlib.sha256(payload).hexdigest()
    await repo.copy_file(key, "synthetic/copy.txt")
    assert await repo.get_file("synthetic/copy.txt") == payload
    assert len(await repo.list_files(prefix="synthetic/", limit=1)) == 1
    assert await asyncio.to_thread(download, await repo.get_presigned_url(key)) == payload
    try:
        await asyncio.to_thread(download, f"{endpoint}/{bucket}/{key}")
    except HTTPError as error:
        assert error.code == 403
    else:
        raise AssertionError("Anonymous object read was accepted")
    denied(lambda: repo._client.list_objects_v2(Bucket="passdetection-ci-forbidden"))
    denied(lambda: repo._client.put_object(Bucket="passdetection-ci-forbidden", Key=key, Body=b"denied"))
    denied(lambda: repo._client.create_bucket(Bucket="passdetection-ci-unauthorized"))
    denied(lambda: repo._client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Suspended"}))
    previous = admin.head_object(Bucket=bucket, Key=key)["VersionId"]
    denied(lambda: repo._client.delete_object(Bucket=bucket, Key=key, VersionId=previous))
    await repo.upload_file(b"synthetic replacement", key, "text/plain")
    old = admin.get_object(Bucket=bucket, Key=key, VersionId=previous)
    try:
        assert old["Body"].read() == payload
    finally:
        old["Body"].close()
    assert await repo.delete_files(["synthetic/copy.txt"]) == 1
    try:
        socket.getaddrinfo("object-storage-data", 8888)
    except socket.gaierror:
        pass
    else:
        raise AssertionError("The unauthenticated filer is on the application network")
    if endpoint in {"http://storage-loopback:9000", "http://storage-stage:9000"}:
        hostname = endpoint.split("//", 1)[1].split(":", 1)[0]
        for port in (8888, 18888, 9333, 19333, 8080, 18080):
            try:
                socket.create_connection((hostname, port), timeout=2).close()
            except OSError:
                continue
            raise AssertionError("An internal storage port is reachable from the application network")
    print(json.dumps({"synthetic": True, "provider": "SeaweedFS 4.47",
                      "application_adapter_operations": True, "private_bucket_isolation": True,
                      "historical_version_read": True, "filer_network_isolation": True}))


if __name__ == "__main__":
    asyncio.run(main())
