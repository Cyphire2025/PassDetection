"""Owner-scoped conversation deletion; library and business objects are never targets."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError

from app.application.assistant.contracts import AssistantError

if TYPE_CHECKING:
    from app.infrastructure.assistant.store import AssistantStore


def index_key(created_at: str, identifier: str) -> str:
    # S3 lists lexically. Inverted microseconds keep bounded pages newest first.
    stamp = int(datetime.fromisoformat(created_at).timestamp() * 1_000_000)
    return f"{9_999_999_999_999_999_999 - stamp:019d}-{UUID(identifier)}.json"


async def deletion_record(store: AssistantStore, identifier: UUID) -> dict[str, Any] | None:
    try:
        return await store._read(f"deleted/{identifier}.json")
    except AssistantError as exc:
        if exc.status != 404:
            raise
        return None


async def _purge(store: AssistantStore, identifier: UUID, marker: dict[str, Any]) -> None:
    client = store.storage._client
    bucket = store.storage.settings.bucket_name
    try:
        # Every target is a fixed suffix of this authenticated owner's namespace.
        # Read the first bounded batch again after deletion; don't reuse cursors
        # whose offsets may change while removing objects from a listing.
        for kind in ("turns", "timeline", "requests"):
            prefix = f"{store.prefix}{kind}/{identifier}/"
            for _ in range(64):
                page = await asyncio.to_thread(
                    client.list_objects_v2, Bucket=bucket, Prefix=prefix, MaxKeys=1000
                )
                keys = [row["Key"] for row in page.get("Contents", []) if row["Key"].startswith(prefix)]
                if not keys:
                    break
                result = await asyncio.to_thread(
                    client.delete_objects,
                    Bucket=bucket,
                    Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
                )
                if result.get("Errors"):
                    raise AssistantError("deletion_incomplete", "Deletion could not finish. Please try again.")
            else:
                raise AssistantError("deletion_incomplete", "Deletion could not finish. Please try again.")
        suffixes = (
            f"conversations/{index_key(marker['created_at'], str(identifier))}",
            f"threads/{identifier}.json",
        )
        for suffix in suffixes:
            await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=store.prefix + suffix)
    except (BotoCoreError, ClientError, ValueError, KeyError):
        raise AssistantError("deletion_incomplete", "Deletion could not finish. Please try again.") from None


async def ensure_active(store: AssistantStore, identifier: UUID, *, cleanup: bool = False) -> None:
    marker = await deletion_record(store, identifier)
    if marker is None:
        return
    if cleanup:
        # A write that raced the tombstone must not leave a new history copy.
        await _purge(store, identifier, marker)
    raise AssistantError("conversation_deleted", "This conversation was deleted. Start a new conversation.", 410)


async def delete_conversation(store: AssistantStore, identifier: UUID) -> None:
    marker = await deletion_record(store, identifier)
    if marker is None:
        thread = await store._read(f"threads/{identifier}.json")
        marker = {"id": str(identifier), "created_at": thread["created_at"], "deleted_at": datetime.now(UTC).isoformat()}
        try:
            # Publish the durable barrier before removing any message objects.
            # It also prevents stale clients from recreating this conversation ID.
            await store._json(f"deleted/{identifier}.json", marker)
        except AssistantError as exc:
            if exc.code != "already_exists":
                raise
            marker = await store._read(f"deleted/{identifier}.json")
    await _purge(store, identifier, marker)
