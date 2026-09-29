"""Durable header-upload claims; provider outcomes are never made transactional."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import re
import tempfile
import uuid
from collections.abc import AsyncIterable
from datetime import UTC, datetime, timedelta
from typing import Any, BinaryIO, cast

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError, _filename, _spool, transfer_slot
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import credential_hash, utc
from app.application.mcp.whatsapp_media_access import MCPWhatsAppMediaAccess
from app.core.config.settings import Settings
from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.database.mcp_whatsapp_media_models import (
    MCPWhatsAppHeaderAccessModel,
    MCPWhatsAppHeaderMediaModel,
)
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.security.upload_security import UploadSecurityContext, UploadSecurityService
from app.infrastructure.storage.mcp_artifact_storage import MCPArtifactStorage
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    upload_whatsapp_image,
)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MEDIA_LIFETIME = timedelta(hours=1)
ATTEMPT_LIFETIME = timedelta(minutes=2)


class MCPWhatsAppMediaUploads(MCPWhatsAppMediaAccess):
    """HTTP-only service owning durable claim commits before provider side effects."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        storage: MCPArtifactStorage | None = None,
        security: UploadSecurityService | None = None,
    ):
        super().__init__(session, settings)
        self._storage, self.security = storage, security

    @property
    def storage(self) -> MCPArtifactStorage:
        if self._storage is None:
            self._storage = MCPArtifactStorage()
        return self._storage

    async def existing(
        self, principal: MCPPrincipal, key_hash: str, request_hash: str, *, lock: bool = False
    ) -> MCPWhatsAppHeaderMediaModel | None:
        statement = select(MCPWhatsAppHeaderMediaModel).where(
            MCPWhatsAppHeaderMediaModel.user_id == principal.user_id,
            MCPWhatsAppHeaderMediaModel.idempotency_hash == key_hash,
        )
        if lock:
            statement = statement.with_for_update()
        row = await self.session.scalar(statement.execution_options(populate_existing=True))
        if row is not None:
            if row.request_hash != request_hash:
                raise ArtifactError(
                    "This idempotency key already identifies different image details", 409
                )
            if row.original_grant_id != principal.grant_id:
                raise ArtifactError("Recover a ready image explicitly in the new connection", 409)
            if utc(row.expires_at) <= datetime.now(UTC):
                raise ArtifactError("The image upload receipt has expired", 409)
        return row

    async def upload(
        self,
        principal: MCPPrincipal,
        *,
        agency_id: uuid.UUID,
        broadcast_id: uuid.UUID,
        filename: str,
        media_type: str,
        expected_size: int,
        expected_sha256: str,
        idempotency_key: str,
        body: AsyncIterable[bytes],
    ) -> dict[str, Any]:
        if (
            media_type not in {"image/jpeg", "image/png"}
            or not 1 <= expected_size <= MAX_IMAGE_BYTES
            or re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is None
            or not 16 <= len(idempotency_key) <= 256
            or not idempotency_key.isascii()
            or any(ord(c) < 32 or ord(c) == 127 for c in idempotency_key)
        ):
            raise ArtifactError(
                "Provide a JPEG/PNG image, bounded size, SHA-256 and stable idempotency key", 422
            )
        if not self.settings.whatsapp_access_token or not self.settings.whatsapp_phone_number_id:
            raise ArtifactError("WhatsApp media upload is not configured", 503)
        safe_name = _filename(filename, ".png" if media_type == "image/png" else ".jpg")
        key_hash = hashlib.sha256(("mcp-wa-header-v1\0" + idempotency_key).encode()).hexdigest()
        request_hash = hashlib.sha256(
            json.dumps(
                {
                    "agency_id": str(agency_id),
                    "broadcast_id": str(broadcast_id),
                    "filename": safe_name,
                    "media_type": media_type,
                    "byte_size": expected_size,
                    "sha256": expected_sha256,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        await self.authority(principal)
        await self.scope(agency_id, broadcast_id)
        existing = await self.existing(principal, key_hash, request_hash)
        if existing is not None:
            identifier = existing.id
            await self.session.rollback()
            async with transfer_slot(), asyncio.timeout(120):
                return await self._start_or_observe(principal, identifier)
        await self.session.rollback()
        async with transfer_slot(), asyncio.timeout(120):
            with tempfile.TemporaryFile(mode="w+b") as temporary:
                original = cast(BinaryIO, temporary)
                size, checksum = await _spool(body, original, maximum=MAX_IMAGE_BYTES)
                if size != expected_size or not hmac.compare_digest(checksum, expected_sha256):
                    raise ArtifactError("Image size or SHA-256 does not match", 422)
                original.seek(0)
                content = original.read(MAX_IMAGE_BYTES + 1)
                security = self.security or UploadSecurityService(settings=self.settings)
                validated = (
                    await run_bounded_storage_operations(
                        [
                            lambda: security.validate_image(
                                content=content,
                                filename=safe_name,
                                declared_content_type=media_type,
                                context=UploadSecurityContext(
                                    ingestion_flow="mcp_whatsapp_header",
                                    agency_id=agency_id,
                                    user_id=principal.user_id,
                                ),
                                max_bytes=MAX_IMAGE_BYTES,
                                allowed_source_formats=frozenset({"JPEG", "PNG"}),
                            )
                        ],
                        concurrency=1,
                    )
                )[0]
                if not 1 <= len(validated.content) <= MAX_IMAGE_BYTES:
                    raise ArtifactError("Normalized image exceeds the header upload limit", 422)
                await self.authority(principal, lock=True)
                await self.scope(agency_id, broadcast_id, lock=True)
                row = await self.existing(principal, key_hash, request_hash, lock=True)
                if row is None:
                    row = await self._save_source(
                        principal,
                        agency_id=agency_id,
                        broadcast_id=broadcast_id,
                        filename=safe_name,
                        media_type=media_type,
                        size=size,
                        checksum=checksum,
                        key_hash=key_hash,
                        request_hash=request_hash,
                        original=original,
                        normalized=validated.content,
                        normalized_media_type=validated.content_type,
                    )
                identifier = row.id
                await self.session.commit()
            return await self._start_or_observe(principal, identifier)

    async def _save_source(
        self,
        principal: MCPPrincipal,
        *,
        agency_id: uuid.UUID,
        broadcast_id: uuid.UUID,
        filename: str,
        media_type: str,
        size: int,
        checksum: str,
        key_hash: str,
        request_hash: str,
        original: BinaryIO,
        normalized: bytes,
        normalized_media_type: str,
    ) -> MCPWhatsAppHeaderMediaModel:
        identifier, now = uuid.uuid4(), datetime.now(UTC)
        row = MCPWhatsAppHeaderMediaModel(
            id=identifier,
            user_id=principal.user_id,
            original_grant_id=principal.grant_id,
            agency_id=agency_id,
            broadcast_id=broadcast_id,
            idempotency_hash=key_hash,
            request_hash=request_hash,
            original_storage_key=f"mcp-transfers/v1/{uuid.uuid4()}",
            normalized_storage_key=f"mcp-transfers/v1/{uuid.uuid4()}",
            original_sha256=checksum,
            normalized_sha256=hashlib.sha256(normalized).hexdigest(),
            original_byte_size=size,
            normalized_byte_size=len(normalized),
            filename=filename,
            original_media_type=media_type,
            normalized_media_type=normalized_media_type,
            provider_phone_number_id=self.settings.whatsapp_phone_number_id,
            status="staged",
            revision=1,
            created_at=now,
            updated_at=now,
            expires_at=now + MEDIA_LIFETIME,
        )
        handle = self.handle(row, principal.grant_id)
        row.handle_hash = credential_hash(handle, self.settings.app_secret_key)
        await self.storage.put_transfer(
            original,
            key=row.original_storage_key,
            size=size,
            sha256=checksum,
            media_type=media_type,
        )
        await self.storage.put_transfer(
            io.BytesIO(normalized),
            key=row.normalized_storage_key,
            size=len(normalized),
            sha256=row.normalized_sha256,
            media_type=normalized_media_type,
        )
        dialect = self.session.get_bind().dialect.name
        insert = (
            pg_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
        )
        if insert is None:
            raise ArtifactError("Image staging database is unavailable", 503)
        await self.session.execute(
            insert(MCPWhatsAppHeaderMediaModel)
            .values({column.name: getattr(row, column.name) for column in row.__table__.columns})
            .on_conflict_do_nothing(index_elements=["user_id", "idempotency_hash"])
        )
        winner = await self.existing(principal, key_hash, request_hash, lock=True)
        if winner is None:
            raise ArtifactError("Image staging claim is unavailable", 503)
        if winner.id == identifier:
            self.session.add(
                MCPWhatsAppHeaderAccessModel(
                    media_id=winner.id, grant_id=principal.grant_id, handle_hash=row.handle_hash
                )
            )
            await self.audit(principal, winner, "staged")
            await self.session.flush()
        return winner

    async def _owned_locked(
        self, principal: MCPPrincipal, identifier: uuid.UUID
    ) -> MCPWhatsAppHeaderMediaModel:
        await self.authority(principal, lock=True)
        row: MCPWhatsAppHeaderMediaModel | None = await self.session.scalar(
            select(MCPWhatsAppHeaderMediaModel).where(
                MCPWhatsAppHeaderMediaModel.id == identifier,
                MCPWhatsAppHeaderMediaModel.user_id == principal.user_id,
                MCPWhatsAppHeaderMediaModel.original_grant_id == principal.grant_id,
            )
        )
        if row is None:
            raise ArtifactError("Header image was not found", 404)
        await self.scope(row.agency_id, row.broadcast_id, lock=True)
        row = await self.session.scalar(
            select(MCPWhatsAppHeaderMediaModel)
            .where(
                MCPWhatsAppHeaderMediaModel.id == identifier,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or utc(row.expires_at) <= datetime.now(UTC):
            raise ArtifactError("Header image was not found", 404)
        if row.provider_phone_number_id != self.settings.whatsapp_phone_number_id:
            raise ArtifactError("Header image sender configuration changed", 409)
        return row

    async def _start_or_observe(
        self, principal: MCPPrincipal, identifier: uuid.UUID
    ) -> dict[str, Any]:
        row = await self._owned_locked(principal, identifier)
        if row.status != "staged":
            result = await self.observe(principal, self.handle(row, principal.grant_id))
            await self.session.commit()
            return result
        now, attempt = datetime.now(UTC), uuid.uuid4()
        row.status, row.attempt_id, row.attempted_at = "uploading", attempt, now
        row.attempt_expires_at, row.updated_at = now + ATTEMPT_LIFETIME, now
        row.revision += 1
        await self.audit(principal, row, "claimed")
        await self.session.commit()
        # A crash after this durable claim is uncertain. No later caller can
        # repeat the provider call merely because it did not receive a response.
        row = await self._owned_locked(principal, identifier)
        if row.status != "uploading" or row.attempt_id != attempt:
            return self.metadata(row, self.handle(row, principal.grant_id))
        try:
            content = await self._provider_content(row)
        except StorageError:
            row.status, row.failure_code = "failed", "source_integrity_unavailable"
        else:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                    provider_id = await upload_whatsapp_image(
                        client=client,
                        settings=self.settings,
                        file_name=_filename(row.filename, ".jpg"),
                        file_content=content,
                        content_type=row.normalized_media_type,
                    )
                if not provider_id or len(provider_id) > 255:
                    raise ValueError("Unusable provider receipt")
                row.provider_media_id = provider_id
                row.status, row.failure_code = "ready", None
            except WhatsAppCloudApiError as exc:
                row.status = (
                    "failed"
                    if exc.code
                    in {"WHATSAPP_MEDIA_UPLOAD_UNREACHABLE", "WHATSAPP_PROVIDER_NOT_CONFIGURED"}
                    else "unknown"
                )
                row.failure_code = (
                    "provider_upload_unreachable"
                    if row.status == "failed"
                    else "provider_upload_unconfirmed"
                )
            except Exception:
                row.status, row.failure_code = "unknown", "provider_upload_unconfirmed"
        # Retain the provider receipt under the authority+row barrier already
        # held through I/O, even if wall-clock token expiry passed during upload.
        row.completed_at = row.updated_at = datetime.now(UTC)
        row.revision += 1
        await self.audit(principal, row, row.status)
        result = self.metadata(row, self.handle(row, principal.grant_id))
        await self.session.commit()
        return result

    async def _provider_content(self, row: MCPWhatsAppHeaderMediaModel) -> bytes:
        checksum, data = hashlib.sha256(), bytearray()
        async for part in self.storage.stream_file(
            row.normalized_storage_key,
            start=0,
            expected_bytes=row.normalized_byte_size,
            chunk_size=65536,
        ):
            data.extend(part)
            if len(data) > row.normalized_byte_size:
                raise StorageError("Header image size changed")
            checksum.update(part)
        if len(data) != row.normalized_byte_size or not hmac.compare_digest(
            checksum.hexdigest(), row.normalized_sha256
        ):
            raise StorageError("Header image checksum changed")
        return bytes(data)
