"""Immutable private assistant records with explicit, owner-scoped chat deletion."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError

from app.application.assistant.contracts import AssistantError, public_asset
from app.domain.entities.entities import User, UserRole
from app.infrastructure.assistant.conversation_records import (
    delete_conversation,
    deletion_record,
    ensure_active,
)
from app.infrastructure.assistant.conversation_records import (
    index_key as _index_key,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository

MAX_RECORD_BYTES = 192 * 1024
MAX_ASSET_BYTES = 8 * 1024 * 1024


def account_scope(user: User) -> str:
    return "super_admin" if user.role == UserRole.SUPER_ADMIN else f"{user.role.value}:{user.agency_id}"


def assistant_store(user: User) -> "AssistantStore":
    return AssistantStore(user.id, scope=None if user.role == UserRole.SUPER_ADMIN else account_scope(user))


class AssistantStore:
    def __init__(self, user_id: UUID, storage: MinioStorageRepository | None = None, *, scope: str | None = None):
        self.storage = storage or MinioStorageRepository()
        self.prefix = f"assistant/v1/accounts/{user_id}/"
        if scope:
            self.prefix += "scopes/" + hashlib.sha256(scope.encode()).hexdigest()[:24] + "/"

    async def _put(self, suffix: str, content: bytes, mime: str) -> None:
        # IfNoneMatch makes published records immutable, including duplicate submissions.
        try:
            await asyncio.to_thread(
                self.storage._client.put_object,
                Bucket=self.storage.settings.bucket_name,
                Key=self.prefix + suffix,
                Body=content,
                ContentType=mime,
                IfNoneMatch="*",
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"PreconditionFailed", "412", "ConditionalRequestConflict"}:
                raise AssistantError(
                    "already_exists", "This request already exists. Refresh the conversation.", 409
                ) from None
            raise AssistantError(
                "storage_unavailable",
                "Your assistant workspace could not be saved. Please try again.",
            ) from None
        except BotoCoreError:
            raise AssistantError(
                "storage_unavailable",
                "Your assistant workspace could not be saved. Please try again.",
            ) from None

    async def _json(self, suffix: str, record: dict[str, Any]) -> None:
        body = json.dumps(record, ensure_ascii=False, allow_nan=False).encode()
        if len(body) > MAX_RECORD_BYTES:
            raise AssistantError(
                "record_limit", "This conversation entry is too large to save.", 413
            )
        await self._put(suffix, body, "application/json")

    async def _get(self, suffix: str, maximum: int = MAX_RECORD_BYTES) -> bytes:
        try:
            response = await asyncio.to_thread(
                self.storage._client.get_object,
                Bucket=self.storage.settings.bucket_name,
                Key=self.prefix + suffix,
            )
            body = response["Body"]
            try:
                if response.get("ContentLength", maximum + 1) > maximum:
                    raise AssistantError(
                        "record_limit", "The saved item exceeds its allowed size.", 413
                    )
                content = await asyncio.to_thread(body.read, maximum + 1)
                if not isinstance(content, bytes):
                    raise AssistantError("invalid_record", "The saved item could not be read.")
                if len(content) > maximum:
                    raise AssistantError(
                        "record_limit", "The saved item exceeds its allowed size.", 413
                    )
                return content
            finally:
                await asyncio.to_thread(body.close)
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code", "")) in {
                "NoSuchKey",
                "404",
                "NotFound",
            }:
                raise AssistantError(
                    "not_found", "This item is not in your workspace.", 404
                ) from None
            raise AssistantError(
                "storage_unavailable", "Your assistant workspace is temporarily unavailable."
            ) from None
        except BotoCoreError:
            raise AssistantError(
                "storage_unavailable", "Your assistant workspace is temporarily unavailable."
            ) from None

    async def _read(self, suffix: str) -> dict[str, Any]:
        try:
            value = json.loads(await self._get(suffix))
        except (ValueError, UnicodeError):
            raise AssistantError("invalid_record", "The saved item could not be read.") from None
        if not isinstance(value, dict):
            raise AssistantError("invalid_record", "The saved item could not be read.")
        return value

    async def _list(
        self, suffix: str, *, cursor: str | None = None, limit: int = 25
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "Bucket": self.storage.settings.bucket_name,
            "Prefix": self.prefix + suffix,
            "MaxKeys": limit,
        }
        if cursor:
            args["ContinuationToken"] = cursor
        try:
            listing = await asyncio.to_thread(self.storage._client.list_objects_v2, **args)
            keys = [
                row["Key"]
                for row in listing.get("Contents", [])
                if row["Key"].startswith(self.prefix + suffix) and row["Key"].endswith(".json")
            ]
            # At most four outstanding object reads per list request.
            records: list[dict[str, Any]] = []
            for start in range(0, len(keys), 4):
                batch = await asyncio.gather(
                    *(self._listed_record(key[len(self.prefix) :]) for key in keys[start : start + 4])
                )
                records.extend(record for record in batch if record is not None)
            return {"items": records, "next_cursor": listing.get("NextContinuationToken")}
        except AssistantError:
            raise
        except Exception:
            raise AssistantError(
                "storage_unavailable", "Your assistant workspace is temporarily unavailable."
            ) from None

    async def _listed_record(self, suffix: str) -> dict[str, Any] | None:
        try:
            return await self._read(suffix)
        except AssistantError as exc:
            # Deletion in another tab may remove an index after it was listed.
            if exc.status != 404:
                raise
            return None

    async def create_conversation(self, conversation_id: UUID, title: str) -> None:
        await ensure_active(self, conversation_id)
        try:
            record = await self._read(f"threads/{conversation_id}.json")
        except AssistantError as exc:
            if exc.status != 404:
                raise
            record = {
                "id": str(conversation_id),
                "title": title[:90],
                "created_at": datetime.now(UTC).isoformat(),
            }
            await self._json(f"threads/{conversation_id}.json", record)
        await self._index("conversations/", record)
        await ensure_active(self, conversation_id, cleanup=True)

    async def _index(self, prefix: str, record: dict[str, Any]) -> None:
        try:
            await self._json(prefix + _index_key(record["created_at"], record["id"]), record)
        except AssistantError as exc:
            if exc.code != "already_exists":
                raise

    async def claim_request(
        self, conversation_id: UUID, request_id: UUID, fingerprint: str
    ) -> None:
        # Claim before a billable call. Interrupted submissions are never silently repeated.
        await ensure_active(self, conversation_id)
        try:
            await self._json(
                f"requests/{conversation_id}/{request_id}.json",
                {
                    "id": str(request_id),
                    "fingerprint": fingerprint,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
        except AssistantError as exc:
            if exc.code == "already_exists":
                raise AssistantError(
                    "request_interrupted",
                    "This request was already submitted. Open the conversation to check its result. Start a new request if you want to try again.",
                    409,
                ) from None
            raise
        await ensure_active(self, conversation_id, cleanup=True)

    async def conversations(self, cursor: str | None = None) -> dict[str, Any]:
        page = await self._list("conversations/", cursor=cursor)
        visible = []
        for record in page["items"]:
            if await deletion_record(self, UUID(record["id"])) is None:
                visible.append(record)
        return {**page, "items": visible}

    async def delete_conversation(self, conversation_id: UUID) -> None:
        await delete_conversation(self, conversation_id)

    async def turns(self, conversation_id: UUID, cursor: str | None = None) -> dict[str, Any]:
        await ensure_active(self, conversation_id)
        page = await self._list(f"timeline/{conversation_id}/", cursor=cursor, limit=50)
        await ensure_active(self, conversation_id)
        return page

    async def turn(self, conversation_id: UUID, request_id: UUID) -> dict[str, Any]:
        await ensure_active(self, conversation_id)
        record = await self._read(f"turns/{conversation_id}/{request_id}.json")
        await self._index(f"timeline/{conversation_id}/", record)
        await ensure_active(self, conversation_id, cleanup=True)
        return record

    async def save_turn(
        self, conversation_id: UUID, request_id: UUID, record: dict[str, Any]
    ) -> None:
        await ensure_active(self, conversation_id)
        await self._json(f"turns/{conversation_id}/{request_id}.json", record)
        await self._index(f"timeline/{conversation_id}/", record)
        await ensure_active(self, conversation_id, cleanup=True)

    async def save_asset(
        self,
        content: bytes,
        *,
        name: str,
        mime: str,
        kind: str,
        text: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        if not content or len(content) > MAX_ASSET_BYTES:
            raise AssistantError("file_limit", "Files must be 8 MB or smaller.", 413)
        identifier = uuid4()
        await self._put(f"content/{identifier}", content, mime)
        record = {
            "id": str(identifier),
            "name": name[:140],
            "mime": mime,
            "size": len(content),
            "kind": kind,
            "created_at": datetime.now(UTC).isoformat(),
            "text": text,
            "prompt": prompt,
        }
        await self._json(f"assets/{identifier}.json", record)
        await self._index("library/", record)
        return public_asset(record)

    async def asset(self, asset_id: UUID) -> dict[str, Any]:
        return await self._read(f"assets/{asset_id}.json")

    async def content(self, asset_id: UUID) -> bytes:
        return await self._get(f"content/{asset_id}", MAX_ASSET_BYTES)

    async def assets(self, cursor: str | None = None) -> dict[str, Any]:
        result = await self._list("library/", cursor=cursor)
        return {**result, "items": [public_asset(record) for record in result["items"]]}
