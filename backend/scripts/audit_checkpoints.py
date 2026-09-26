"""Independent operator command; no implicit application settings or credentials.

Run as a separate scheduled identity with read-only database credentials and a
separately administered immutable S3 bucket. Nonzero results require operational
attention. This command neither sends alerts nor creates buckets or keys.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import boto3
from botocore.client import Config
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.infrastructure.audit.checkpoint_codec import AuditIntegrityError  # noqa: E402
from app.infrastructure.audit.checkpoint_service import verify_and_publish  # noqa: E402
from app.infrastructure.audit.s3_checkpoint_sink import S3AuditIntegritySink  # noqa: E402


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


async def run(*, publish: bool) -> dict[str, int]:
    public_keys = []
    for path in required("AUDIT_CHECKPOINT_PUBLIC_KEY_FILES").split(os.pathsep):
        public = load_pem_public_key(Path(path).read_bytes())
        if not isinstance(public, Ed25519PublicKey):
            raise ValueError("Only Ed25519 verification keys are supported")
        public_keys.append(public)
    private = None
    if publish:
        private = load_pem_private_key(Path(required("AUDIT_CHECKPOINT_PRIVATE_KEY_FILE")).read_bytes(), password=None)
        if not isinstance(private, Ed25519PrivateKey):
            raise ValueError("Only Ed25519 signing keys are supported")
    endpoint = os.environ.get("AUDIT_CHECKPOINT_S3_ENDPOINT") or None
    if endpoint and not endpoint.startswith("https://"):
        raise ValueError("The independent checkpoint endpoint must use HTTPS")
    client = boto3.client(
        "s3", endpoint_url=endpoint, region_name=required("AUDIT_CHECKPOINT_S3_REGION"),
        aws_access_key_id=required("AUDIT_CHECKPOINT_S3_ACCESS_KEY_ID"),
        aws_secret_access_key=required("AUDIT_CHECKPOINT_S3_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=15,
                      retries={"total_max_attempts": 2, "mode": "standard"}),
    )
    sink = S3AuditIntegritySink(client, required("AUDIT_CHECKPOINT_BUCKET"), public_keys=public_keys,
                               private_key=private, retention_days=int(os.getenv("AUDIT_CHECKPOINT_RETENTION_DAYS", "365")))
    database = required("AUDIT_CHECKPOINT_DATABASE_URL")
    if not database.startswith("postgresql+asyncpg://"):
        raise ValueError("The checkpoint database requires PostgreSQL/asyncpg")
    engine = create_async_engine(database, isolation_level="REPEATABLE READ", echo=False)
    try:
        async with async_sessionmaker(engine)() as session, session.begin():
            await session.execute(text("SET TRANSACTION READ ONLY"))
            return await verify_and_publish(session, sink, publish=publish)
    finally:
        await engine.dispose()
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("publish", "verify"))
    args = parser.parse_args()
    try:
        result = asyncio.run(run(publish=args.mode == "publish"))
    except Exception as exc:
        # SDK/DSN exceptions may contain private endpoints or credentials.
        # Keep the process event bounded; detailed diagnosis stays local.
        event = {"event": "audit_integrity_check_failed", "error_type": type(exc).__name__}
        if isinstance(exc, AuditIntegrityError):
            event["reason"] = str(exc)  # fixed internal reason codes; never SDK/DSN details
        print(json.dumps(event), file=sys.stderr)
        return 2
    print(json.dumps({"event": "audit_integrity_check_passed", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
