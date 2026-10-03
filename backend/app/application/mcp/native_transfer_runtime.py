"""Bounded streaming with committed upload leases and verified delivery receipts."""

import hmac
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from datetime import UTC, datetime, timedelta

import anyio
from sqlalchemy import select

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.credentials import credential_hash, utc
from app.application.mcp.native_transfers import MCPNativeTransferService
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_contact_import_models import MCPContactImportUploadModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_native_transfer_models import MCPNativeTransferModel


async def upload_content(
    service: MCPNativeTransferService,
    identifier: uuid.UUID,
    secret: str,
    body: AsyncIterable[bytes],
) -> dict[str, object]:
    row, principal = await service.limited(
        identifier, secret, name="create_native_upload", lock=True
    )
    if row.kind not in {"upload_workbook", "upload_pdf"}:
        raise ArtifactError("This ticket does not allow uploads", 405)
    if row.status == "completed":
        return await service.metadata(row)
    now = datetime.now(UTC)
    if row.status == "failed":
        raise ArtifactError("This upload failed; request a new transfer ticket", 409)
    if row.status == "transferring" and (
        row.claim_expires_at is None or utc(row.claim_expires_at) > now
    ):
        raise ArtifactError("This upload is already in progress", 409)
    claim = uuid.uuid4()
    row.status, row.claim_id, row.claim_expires_at = (
        "transferring",
        claim,
        now + timedelta(minutes=3),
    )
    # Stage scanners intentionally release SQL locks while parsing. Commit a
    # bounded ticket lease first so concurrent requests cannot duplicate sources.
    kind, purpose, agency, group, filename, size, sha = (
        row.kind,
        row.purpose,
        row.agency_id,
        row.group_id,
        row.filename,
        row.byte_size,
        row.sha256,
    )
    await service.audit(row, "upload_started")
    await service.session.commit()
    try:
        if kind == "upload_pdf":
            if group is None:
                raise ArtifactError("The prepared target is unavailable", 404)
            result = await service.artifacts.stage_pdf(
                principal,
                agency_id=agency,
                group_id=group,
                filename=filename,
                expected_size=size,
                expected_sha256=sha,
                body=body,
            )
            source = await service.session.scalar(
                select(MCPArtifactModel).where(
                    MCPArtifactModel.handle_hash
                    == credential_hash(str(result["artifact_id"]), service.settings.app_secret_key)
                )
            )
        else:
            result = await service.contact_service(purpose).stage(
                principal,
                agency_id=agency,
                filename=filename,
                expected_size=size,
                expected_sha256=sha,
                body=body,
            )
            source = await service.session.scalar(
                select(MCPContactImportUploadModel).where(
                    MCPContactImportUploadModel.handle_hash
                    == credential_hash(str(result["upload_id"]), service.settings.app_secret_key)
                )
            )
        row, _ = await service.limited(identifier, secret, name="create_native_upload", lock=True)
        if (
            row.status != "transferring"
            or row.claim_id != claim
            or row.claim_expires_at is None
            or utc(row.claim_expires_at) <= datetime.now(UTC)
            or source is None
        ):
            raise ArtifactError("The upload lease is no longer current", 409)
        if (source.byte_size, source.sha256, source.agency_id) != (size, sha, agency):
            raise ArtifactError("The staged source does not match its prepared ticket", 409)
        if kind == "upload_pdf":
            if (
                source.group_id != group
                or source.grant_id != principal.grant_id
                or source.user_id != principal.user_id
            ):
                raise ArtifactError("The staged source does not match its prepared ticket", 409)
            row.artifact_id = source.id
        else:
            if (
                source.original_grant_id != principal.grant_id
                or source.user_id != principal.user_id
            ):
                raise ArtifactError("The staged source does not match its prepared ticket", 409)
            row.workbook_id = source.id
        row.status, row.completed_at, row.claim_id, row.claim_expires_at = (
            "completed",
            datetime.now(UTC),
            None,
            None,
        )
        await service.audit(row, "upload_completed")
        await service.session.flush()
        return await service.metadata(row)
    except BaseException:
        with anyio.CancelScope(shield=True):
            await service.session.rollback()
            # The transport lease is bookkeeping only. Updating its own claimed
            # failure cannot restore authority or commit staged business rows.
            await service.session.scalar(
                select(MCPControlModel).where(MCPControlModel.id == 1).with_for_update(read=True)
            )
            await service.session.scalar(
                select(MCPGrantModel)
                .where(MCPGrantModel.id == principal.grant_id)
                .with_for_update()
            )
            failed = await service.session.scalar(
                select(MCPNativeTransferModel)
                .where(MCPNativeTransferModel.id == identifier)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if failed is not None and failed.status == "transferring" and failed.claim_id == claim:
                failed.status, failed.claim_id, failed.claim_expires_at = "failed", None, None
                await service.audit(failed, "upload_failed")
                await service.session.commit()
        raise


async def prepare_download(service: MCPNativeTransferService, identifier: uuid.UUID, secret: str):
    row, principal = await service.limited(
        identifier, secret, name="read_native_artifact", lock=True
    )
    if row.kind != "download":
        raise ArtifactError("This ticket does not allow downloads", 405)
    artifact = await service.artifacts.get(principal, service.artifact_handle(row))
    await service.artifacts.validate_storage(artifact)
    await service.audit(row, "download_started")
    await service.session.commit()
    return row, principal, artifact


async def download_content(
    service: MCPNativeTransferService, identifier: uuid.UUID, secret: str, principal, artifact
) -> AsyncIterator[bytes]:
    handle = service.artifacts._handle(artifact.id, principal.user_id, principal.grant_id)
    try:
        async for part in service.artifacts.stream(principal, handle, artifact):
            yield part
        row, _ = await service.limited(identifier, secret, name="read_native_artifact", lock=True)
        row.status, row.download_completed_at = "completed", datetime.now(UTC)
        await service.audit(row, "download_completed")
        await service.session.commit()
    except BaseException:
        with anyio.CancelScope(shield=True):
            await service.session.rollback()
        raise


async def acknowledge_delivery(
    service: MCPNativeTransferService,
    identifier: uuid.UUID,
    secret: str,
    *,
    byte_size: int,
    sha256: str,
) -> dict[str, object]:
    row, principal = await service.limited(
        identifier, secret, name="read_native_artifact", lock=True
    )
    if row.kind != "download" or row.download_completed_at is None:
        raise ArtifactError(
            "Completely download and verify the file before confirming its saved copy", 409
        )
    if byte_size != row.byte_size or not hmac.compare_digest(sha256, row.sha256):
        raise ArtifactError("The saved file size or SHA256 does not match", 422)
    await service.artifacts.acknowledge(
        principal, service.artifact_handle(row), byte_size=byte_size, sha256=sha256
    )
    if row.delivered_at is None:
        row.delivered_at = datetime.now(UTC)
        await service.audit(row, "delivered")
    await service.session.flush()
    return await service.metadata(row)
