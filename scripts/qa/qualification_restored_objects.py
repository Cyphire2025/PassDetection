"""Read restored synthetic rows through application models and reconcile real objects."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re

from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.session import AsyncSessionFactory, engine
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from sqlalchemy import select


async def main() -> None:
    if (not re.fullmatch(r"passdetection_ci_recovery_[0-9a-f]{12}", os.environ.get("POSTGRES_DB", ""))
            or os.environ.get("S3_ENDPOINT_URL") != "http://minio:9000"):
        raise RuntimeError("Only the restored qualification database is accepted")
    storage = MinioStorageRepository()
    checked, placeholders = 0, 0
    hashes: dict[str, str] = {}
    async with AsyncSessionFactory() as db:
        rows = (await db.scalars(select(PassportSubmissionModel).limit(101))).all()
        if len(rows) > 100:
            raise RuntimeError("The recovery fixture unexpectedly exceeds its synthetic bound")
        for row in rows:
            for field in ("image_s3_key", "passport_back_s3_key", "passport_photo_s3_key",
                          "passport_cover_s3_key", "passport_back_cover_s3_key"):
                key = getattr(row, field)
                if not key:
                    continue
                if key.startswith("enterprise-browser-qa/"):
                    # The original rendering fixture declares these placeholder
                    # references without uploading images. Count the exclusion.
                    placeholders += 1
                    continue
                content = await storage.get_file(key)
                metadata = await storage.stat_file(key)
                digest = hashlib.sha256(content).hexdigest()
                assert len(content) == metadata.size_bytes and digest == metadata.checksum_sha256
                hashes[hashlib.sha256(key.encode()).hexdigest()] = digest
                checked += 1
    assert checked >= 2, "A completed real cover-upload journey is required before the restore"
    print(json.dumps({"restored_database_application_read": True, "object_references_checked": checked,
                      "known_rendering_placeholders_excluded": placeholders, "key_hash_to_content_hash": hashes,
                      "production_data_reconciliation": False}))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
