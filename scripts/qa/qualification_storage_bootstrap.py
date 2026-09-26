"""Initialize only the disposable qualification bucket with administrator scope."""

from __future__ import annotations

import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


def main() -> None:
    if os.environ.get("POSTGRES_DB") != "passdetection_ci_browser" or os.environ.get("S3_ENDPOINT_URL") != "http://minio:9000":
        raise RuntimeError("Only the isolated qualification stack is accepted")
    client = boto3.client(
        "s3", endpoint_url="http://minio:9000",
        aws_access_key_id="qualification-storage-admin",
        aws_secret_access_key="qualification-storage-admin-secret-937",
        config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1}),
    )
    for attempt in range(45):
        try:
            client.create_bucket(Bucket="passdetection-passports")
            break
        except ClientError as error:
            if error.response["Error"]["Code"] in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                break
            if attempt == 44:
                raise
        except BotoCoreError:
            if attempt == 44:
                raise
        time.sleep(2)
    client.put_bucket_versioning(Bucket="passdetection-passports", VersioningConfiguration={"Status": "Enabled"})
    print("Synthetic private bucket initialized with versioning enabled")


if __name__ == "__main__":
    main()
