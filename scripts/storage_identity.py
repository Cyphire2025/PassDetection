"""Render private SeaweedFS identities; secrets never appear in CLI arguments."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping


def storage_identity(environment: Mapping[str, str]) -> str:
    bucket = environment.get("S3_BUCKET_NAME", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        raise ValueError("A valid explicit S3 bucket is required")
    keys = ("OBJECT_STORAGE_ADMIN_ACCESS_KEY", "OBJECT_STORAGE_ADMIN_SECRET_KEY",
            "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
    values = [environment.get(key, "") for key in keys]
    if any(not value or value.startswith("CHANGE_ME") for value in values):
        raise ValueError("Independent storage administrator and runtime credentials are required")
    if values[0] == values[2] or values[1] == values[3]:
        raise ValueError("Storage administrator and runtime credentials must be distinct")
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
         "Resource": [f"arn:aws:s3:::{bucket}"]},
        {"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject",
                                       "s3:GetObjectTagging", "s3:PutObjectTagging"],
         "Resource": [f"arn:aws:s3:::{bucket}/*"]},
        {"Effect": "Deny", "Action": ["s3:DeleteObjectVersion"],
         "Resource": [f"arn:aws:s3:::{bucket}/*"]},
    ]}
    # The IAM engine requires a signing key even with no external identity
    # providers. Domain separation derives an independent key from the existing
    # high-entropy administrator secret; no public or application key can sign.
    signing_key = base64.b64encode(hashlib.sha256(
        ("passdetection-storage-sts-v1:" + values[1]).encode()
    ).digest()).decode()
    return json.dumps({"policy": {"defaultEffect": "Deny"},
                       "sts": {"signingKey": signing_key},
                       "policies": [{"name": "application-objects", "content": json.dumps(policy), "document": policy}],
                       "identities": [
        {"name": "storage-administrator", "credentials": [
            {"accessKey": values[0], "secretKey": values[1]}],
         "actions": ["Admin", "Read", "Write", "List", "Tagging"]},
        {"name": "application", "credentials": [
            {"accessKey": values[2], "secretKey": values[3]}],
         # Bucket-wide Write also authorizes changes to versioning. Restrict
         # mutation to object paths; readiness/listing retain bucket read scope.
         "policyNames": ["application-objects"]},
    ]}, indent=2) + "\n"
