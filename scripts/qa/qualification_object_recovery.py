"""Synthetic S3 version recovery; invoked only inside the qualification stack."""

from __future__ import annotations

import hashlib
import json
import os

import boto3
from botocore.exceptions import ClientError


def main() -> None:
    if os.environ.get("POSTGRES_DB") != "passdetection_ci_browser" or os.environ.get("S3_ENDPOINT_URL") != "http://minio:9000":
        raise RuntimeError("Synthetic object recovery requires the isolated qualification stack")
    client = boto3.client(
        "s3", endpoint_url=os.environ["S3_ENDPOINT_URL"],
        aws_access_key_id="qualification-storage-admin",
        aws_secret_access_key="qualification-storage-admin-secret-937", region_name="us-east-1",
    )
    bucket = "passdetection-qualification-recovery"
    try:
        client.create_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            raise
    client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    key = "synthetic/recovery-proof.txt"
    original = b"Synthetic recovery content. No customer documents."
    version = client.put_object(Bucket=bucket, Key=key, Body=original)["VersionId"]
    client.put_object(Bucket=bucket, Key=key, Body=b"Synthetic accidental overwrite")
    restored = client.get_object(Bucket=bucket, Key=key, VersionId=version)["Body"].read()
    assert restored == original
    client.copy_object(Bucket=bucket, Key=key, CopySource={"Bucket": bucket, "Key": key, "VersionId": version})
    current = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    assert current == original
    print(json.dumps({
        "synthetic": True, "provider": "SeaweedFS 4.47 isolated fixture",
        "version_restore": True, "checksum_verified": hashlib.sha256(current).hexdigest(),
        "off_host_backup_proof": False,
    }))


if __name__ == "__main__":
    main()
