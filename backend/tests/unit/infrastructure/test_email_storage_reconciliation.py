from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.infrastructure.storage.minio_repository import MinioStorageRepository


async def test_email_storage_listing_is_bounded_and_paginated() -> None:
    first_modified = datetime(2026, 7, 26, tzinfo=UTC)
    second_modified = datetime(2026, 7, 27, tzinfo=UTC)
    client = Mock()
    client.list_objects_v2.side_effect = [
        {
            "Contents": [
                {
                    "Key": "email-integrations/agency/message/one.pdf",
                    "LastModified": first_modified,
                }
            ],
            "IsTruncated": True,
            "NextContinuationToken": "next-page",
        },
        {
            "Contents": [
                {
                    "Key": "email-integrations/agency/message/two.pdf",
                    "LastModified": second_modified,
                }
            ],
            "IsTruncated": False,
        },
    ]
    repository = object.__new__(MinioStorageRepository)
    repository.settings = SimpleNamespace(bucket_name="test-bucket")
    repository._client = client

    objects = await repository.list_files(
        prefix="email-integrations/",
        limit=2,
    )

    assert objects == [
        ("email-integrations/agency/message/one.pdf", first_modified),
        ("email-integrations/agency/message/two.pdf", second_modified),
    ]
    assert client.list_objects_v2.call_count == 2
    assert client.list_objects_v2.call_args_list[1].kwargs["ContinuationToken"] == "next-page"


async def test_storage_listing_rejects_unbounded_empty_prefix() -> None:
    repository = object.__new__(MinioStorageRepository)

    with pytest.raises(ValueError):
        await repository.list_files(prefix="", limit=10)
