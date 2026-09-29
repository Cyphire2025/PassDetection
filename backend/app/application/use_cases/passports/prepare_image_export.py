"""Shared database-only passport image ZIP preparation for web and MCP."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.passports.prepare_group_excel import _canonical
from app.domain.entities.entities import ClientGroup, PassportSubmission, User
from app.domain.repositories.interfaces import IObjectStorageRepository
from app.infrastructure.export.passport_image_zip_exporter import PassportImageZipExporter
from app.infrastructure.repositories.passport_export_history_repository import PassportExportMode


class ImagePreparationError(ValueError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


@dataclass(frozen=True)
class ImagePreparationSupport:
    current_submissions: Callable[..., Any]
    resolve_payload: Callable[..., Any]
    owner_scope: Callable[..., Any]
    crop_repository: Callable[..., Any]
    zone_names: Callable[..., Any]
    people_snapshot: Callable[..., Any]


@dataclass(frozen=True)
class PreparedImageExport:
    submissions: list[PassportSubmission]
    render_arguments: dict[str, Any]
    history_fields: dict[str, Any]
    revision: str

    async def render(
        self,
        *,
        storage: IObjectStorageRepository,
        exporter: PassportImageZipExporter | None = None,
        maximum_bytes: int | None = None,
    ) -> tuple[BinaryIO, int, int]:
        arguments = dict(self.render_arguments)
        if maximum_bytes is not None:
            arguments["max_uncompressed_bytes"] = min(
                maximum_bytes, arguments.get("max_uncompressed_bytes", maximum_bytes)
            )
        return await (exporter or PassportImageZipExporter()).export_group(
            self.submissions, storage=storage, **arguments
        )


async def prepare_image_export(
    session: AsyncSession,
    *,
    support: ImagePreparationSupport,
    current_user: User,
    agency_id: uuid.UUID,
    group: ClientGroup,
    export_mode: PassportExportMode = "all",
    baseline_export_id: uuid.UUID | None = None,
    selected_submission_ids: list[uuid.UUID] | None = None,
    selected_maximum_bytes: int = 512 * 1024 * 1024,
) -> PreparedImageExport:
    current = await support.current_submissions(
        session, group_id=group.id, agency_id=agency_id, current_user=current_user
    )
    if selected_submission_ids is not None:
        if export_mode != "all" or baseline_export_id is not None:
            raise ImagePreparationError(
                422, "Selected image exports do not support incremental mode"
            )
        requested = list(dict.fromkeys(selected_submission_ids))
        by_id = {row.id: row for row in current}
        if not requested or any(identifier not in by_id for identifier in requested):
            raise ImagePreparationError(
                404, "One or more selected passport submissions were not found in this group."
            )
        submissions, baseline = [by_id[identifier] for identifier in requested], None
    else:
        submissions, baseline = await support.resolve_payload(
            session,
            group_id=group.id,
            agency_id=agency_id,
            export_kind="passport_images",
            export_mode=export_mode,
            baseline_export_id=baseline_export_id,
            submissions=current,
            created_by_user_id=support.owner_scope(current_user),
        )
    crops = await support.crop_repository(session).list_for_submissions(
        [row.id for row in submissions]
    )
    zones = await support.zone_names(session, current)
    arguments = {
        "group_name": group.name,
        "require_both_pages": getattr(group, "upload_configuration", None) is None,
        "staff_code_enabled": group.staff_code_enabled,
        "agent_employee_code_enabled": group.agent_employee_code_enabled,
        "crop_metadata": crops,
        "zone_names": zones,
        "namespace_submissions": current,
    }
    history: dict[str, Any] = {}
    if selected_submission_ids is None:
        history = {
            "group_id": group.id,
            "agency_id": agency_id,
            "export_kind": "passport_images",
            "export_mode": export_mode,
            "baseline_export_id": baseline.id if baseline else None,
            "snapshot_submission_ids": [row.id for row in current],
            "exported_submission_ids": [row.id for row in submissions],
            "exported_people_snapshot": support.people_snapshot(submissions),
            "created_by_user_id": current_user.id,
            "actor_email": current_user.email,
        }
    else:
        arguments["max_uncompressed_bytes"] = selected_maximum_bytes
    fields = (
        "id",
        "client_name",
        "staff_metadata",
        "confirmed_fields",
        "extracted_fields",
        "image_s3_key",
        "passport_back_s3_key",
        "passport_photo_s3_key",
        "passport_cover_s3_key",
        "passport_back_cover_s3_key",
        "updated_at",
    )
    snapshot = {
        "arguments": {
            key: value for key, value in arguments.items() if key != "namespace_submissions"
        },
        "namespace": [{key: getattr(row, key, None) for key in fields} for row in current],
        "payload": [row.id for row in submissions],
        "history": history,
    }
    revision = hashlib.sha256(
        json.dumps(_canonical(snapshot), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return PreparedImageExport(submissions, arguments, history, revision)
