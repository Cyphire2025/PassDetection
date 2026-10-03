"""Durable current-image ZIP generation; originals and saved edits are read-only."""

from __future__ import annotations

import asyncio
import hmac
import io
import uuid
from collections.abc import AsyncIterator
from typing import Any, BinaryIO, Literal

import anyio
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import CHUNK_BYTES, ArtifactError, MCPArtifactService
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.export_capacity import admitted_export
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
    MCPOperationProgress,
    MCPOperationService,
)
from app.application.use_cases.passports.prepare_image_export import (
    ImagePreparationSupport,
    PreparedImageExport,
    prepare_image_export,
)
from app.core.config.settings import Settings
from app.domain.entities.entities import ClientGroup, User
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportImageCropModel,
    PassportSubmissionModel,
)
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.export.passport_image_zip_exporter import (
    PassportImageZipExporter,
    safe_download_filename,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportHistoryRepository,
)
from app.infrastructure.storage.mcp_image_export_storage import (
    MAX_IMAGE_ARCHIVE_BYTES,
    MAX_IMAGE_SOURCE_BYTES,
    MCPImageExportStorage,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository

IMAGE_POLICY = MCPToolPolicy(
    "prepare_image_export", MCPCapability.EXPORT, frozenset({"prepare_export"})
)
_GENERATIONS = anyio.CapacityLimiter(1)


class ImageExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agency_id: uuid.UUID
    group_id: uuid.UUID
    selection: Literal["group", "selected_passports"] = "group"
    submission_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    mode: Literal["all", "incremental"] = "all"
    baseline_export_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def selection_contract(self) -> ImageExportRequest:
        if (self.mode == "incremental") != (self.baseline_export_id is not None):
            raise ValueError("Incremental mode needs a completed image baseline")
        if len(self.submission_ids) != len(set(self.submission_ids)):
            raise ValueError("Duplicate selected passports")
        if self.selection == "selected_passports":
            if not self.submission_ids or self.mode != "all":
                raise ValueError("Selected image exports need exact IDs and all mode")
        elif self.submission_ids:
            raise ValueError("Submission IDs require selected_passports mode")
        return self


class ImageExportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    export: ImageExportRequest
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class MCPImageExportService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        support: ImagePreparationSupport,
        *,
        linked_source: Any,
        artifacts: MCPArtifactService | None = None,
        image_storage: MinioStorageRepository | None = None,
    ):
        self.session, self.settings, self.support = session, settings, support
        self.linked_source = linked_source
        self.artifacts = artifacts or MCPArtifactService(session, settings)
        self.image_storage = image_storage

    async def _scope(
        self, principal: MCPPrincipal, request: ImageExportRequest
    ) -> tuple[User, ClientGroup]:
        actor = await self.artifacts._group(
            principal, request.agency_id, request.group_id, "export"
        )
        model = await self.session.scalar(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == request.group_id,
                ClientGroupModel.agency_id == request.agency_id,
                ClientGroupModel.deleted_at.is_(None),
                ClientGroupModel.status != "deleted",
            )
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        )
        if model is None:
            raise ArtifactError("Group was not found", 404)
        return actor, ClientGroupRepository._to_entity(model)

    @admitted_export
    async def prepare(
        self, principal: MCPPrincipal, request: ImageExportRequest
    ) -> PreparedImageExport:
        await self.artifacts._authority(principal, "mcp:export", lock=True)
        actor, group = await self._scope(principal, request)
        if self.session.get_bind().dialect.name == "postgresql":
            await self.session.execute(text("SET LOCAL lock_timeout = '250ms'"))
        # Preserve canonical order and freeze linked zones before passport/crop locks.
        await self.linked_source(self.session, group=group, lock=True, max_source_rows=5000)
        roster = (
            await self.session.scalars(
                select(PassportSubmissionModel)
                .where(
                    PassportSubmissionModel.agency_id == request.agency_id,
                    PassportSubmissionModel.group_id == request.group_id,
                )
                .order_by(PassportSubmissionModel.id)
                .limit(5001)
                .with_for_update(nowait=True)
                .execution_options(populate_existing=True)
            )
        ).all()
        if len(roster) > 5000:
            raise ArtifactError("Image export naming scope exceeds 5000 passengers", 413)
        # UPDATE passport parent locks prevent new crop rows via their FK. Existing
        # crop-first writers fail NOWAIT here instead of forming a lock-order cycle.
        await self.session.execute(
            select(PassportImageCropModel)
            .where(
                PassportImageCropModel.submission_id.in_([row.id for row in roster]),
            )
            .order_by(PassportImageCropModel.submission_id, PassportImageCropModel.image_type)
            .with_for_update(read=True, nowait=True)
            .execution_options(populate_existing=True)
        )
        return await prepare_image_export(
            self.session,
            support=self.support,
            current_user=actor,
            agency_id=request.agency_id,
            group=group,
            export_mode=request.mode,
            baseline_export_id=request.baseline_export_id,
            selected_submission_ids=request.submission_ids
            if request.selection == "selected_passports"
            else None,
        )

    @admitted_export
    async def inspect(self, principal: MCPPrincipal, request: ImageExportRequest) -> dict[str, Any]:
        prepared = await self.prepare(principal, request)
        return {
            "export": request.model_dump(mode="json"),
            "expected_revision": prepared.revision,
            "passenger_count": len(prepared.submissions),
            "history_checkpoint": bool(prepared.history_fields),
            "maximum_source_bytes": min(
                MAX_IMAGE_SOURCE_BYTES, self.settings.upload_max_file_size_bytes
            ),
            "maximum_archive_uncompressed_bytes": MAX_IMAGE_ARCHIVE_BYTES,
        }

    @staticmethod
    def _revision(prepared: PreparedImageExport, expected: str) -> None:
        if not hmac.compare_digest(prepared.revision, expected):
            raise MCPOperationError("export_revision_changed")

    @staticmethod
    def _source_keys(prepared: PreparedImageExport) -> set[str]:
        keys = set()
        for member in prepared.submissions:
            for name in (
                "image_s3_key",
                "passport_back_s3_key",
                "passport_photo_s3_key",
                "passport_cover_s3_key",
                "passport_back_cover_s3_key",
            ):
                value = getattr(member, name, None)
                if value and not value.startswith("excel-imports/"):
                    keys.add(value)
        for crops in prepared.render_arguments["crop_metadata"].values():
            for crop in crops.values():
                for value in (
                    crop.source_storage_key,
                    crop.derived_storage_key,
                    crop.edit_source_storage_key,
                ):
                    if value:
                        keys.add(value)
        return keys

    @admitted_export
    async def generate(self, *, access_token: str, operation_id: uuid.UUID) -> dict[str, Any]:
        borrower = object()
        try:
            _GENERATIONS.acquire_on_behalf_of_nowait(borrower)
        except anyio.WouldBlock as exc:
            raise ArtifactError("Image generation capacity is busy; resume later", 503) from exc
        try:
            return await self._generate(access_token=access_token, operation_id=operation_id)
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "55P03":
                raise ArtifactError("Image export sources are busy; resume later", 503) from exc
            raise
        finally:
            _GENERATIONS.release_on_behalf_of(borrower)

    async def _generate(self, *, access_token: str, operation_id: uuid.UUID) -> dict[str, Any]:
        operations = MCPOperationService(self.session, self.settings)
        principal = await operations._authorize(access_token, "mcp:export", tool_name="generate_image_export")
        operation = await self.session.scalar(
            select(MCPOperationModel)
            .where(
                MCPOperationModel.id == operation_id,
                MCPOperationModel.user_id == principal.user_id,
                MCPOperationModel.operation_name == IMAGE_POLICY.name,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if operation is None or operation.initial_result is None:
            raise MCPOperationError("operation_not_found")
        command = ImageExportCommand.model_validate(operation.initial_result["data"])
        await self._scope(principal, command.export)
        if operation.status == "succeeded":
            identifiers = [
                item["entity_id"]
                for item in operation.created_entities
                if item["entity_type"] == "mcp_artifact"
            ]
            if len(identifiers) != 1:
                raise MCPOperationError("operation_receipt_unavailable")
            metadata = await self.artifacts.recover_export(principal, uuid.UUID(identifiers[0]))
            return {"operation_id": str(operation.id), "status": "succeeded", "artifact": metadata}
        if operation.status != "queued":
            raise MCPOperationError("export_not_resumable")
        prepared = await self.prepare(principal, command.export)
        self._revision(prepared, command.expected_revision)
        storage = MCPImageExportStorage(
            self.image_storage or MinioStorageRepository(),
            self._source_keys(prepared),
            maximum_source_bytes=self.settings.upload_max_file_size_bytes,
        )
        exporter = PassportImageZipExporter()
        exporter.STORAGE_FETCH_BATCH_SIZE = 2
        rendered: tuple[BinaryIO, int, int] | None = None

        async def render() -> None:
            nonlocal rendered
            async with asyncio.timeout(300):
                rendered = await prepared.render(
                    storage=storage, exporter=exporter, maximum_bytes=MAX_IMAGE_ARCHIVE_BYTES
                )

        try:
            # Drain render/native workers before closing their spool or returning capacity.
            await run_bounded_storage_operations([render], concurrency=1)
            assert rendered is not None
            spool, image_count, source_bytes = rendered
            spool.seek(0, io.SEEK_END)
            archive_size = spool.tell()
            spool.seek(0)
            self._revision(await self.prepare(principal, command.export), command.expected_revision)
            history = None
            if prepared.history_fields:
                history = await PassportExportHistoryRepository(self.session).record(
                    **prepared.history_fields,
                    request_id=operation.id,
                    artifact_metadata={
                        "image_count": image_count,
                        "uncompressed_bytes": source_bytes,
                        "archive_bytes": archive_size,
                    },
                )

            async def body() -> AsyncIterator[bytes]:
                while part := (
                    await run_bounded_storage_operations(
                        [
                            lambda: asyncio.to_thread(spool.read, CHUNK_BYTES),
                        ],
                        concurrency=1,
                    )
                )[0]:
                    yield part

            metadata = await self.artifacts.prepare_export(
                principal,
                agency_id=command.export.agency_id,
                group_id=command.export.group_id,
                purpose="passport_images",
                filename=safe_download_filename(prepared.render_arguments["group_name"]),
                body=body(),
                export_history_id=history.id if history else None,
            )
            self._revision(await self.prepare(principal, command.export), command.expected_revision)
            artifact = await self.artifacts.get(principal, str(metadata["artifact_id"]), lock=True)
            await operations.record_progress(
                operation_id=operation.id,
                expected_revision=operation.revision,
                update=MCPOperationProgress(
                    status="succeeded",
                    progress=1,
                    stage="prepared_for_delivery",
                    created_entities=(
                        MCPCreatedEntity("mcp_artifact", str(artifact.id), "/admin/mcp"),
                    ),
                ),
            )
            return {"operation_id": str(operation.id), "status": "succeeded", "artifact": metadata}
        finally:
            if rendered is not None:
                rendered[0].close()


def image_export_operation(
    settings: Settings, support: ImagePreparationSupport, *, linked_source: Any
) -> MCPDatabaseOperation:
    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = ImageExportCommand.model_validate(payload)
        service = MCPImageExportService(
            context.session, settings, support, linked_source=linked_source
        )
        prepared = await service.prepare(context.principal, command.export)
        service._revision(prepared, command.expected_revision)
        return MCPDatabaseResult(command.model_dump(mode="json"), status="queued")

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        command = ImageExportCommand.model_validate(receipt["data"])
        await MCPImageExportService(
            context.session, settings, support, linked_source=linked_source
        )._scope(context.principal, command.export)

    return MCPDatabaseOperation(IMAGE_POLICY, mutate, authorize)
