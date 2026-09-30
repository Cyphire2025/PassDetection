"""Public contracts for streaming MCP transports; these models never buffer uploads."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.contact_workbook import ContactWorkbookErrorCode
from app.presentation.middleware.error_response import HTTP_ERROR_CODES, ApiErrorResponse

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class TransferModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MCPTransferFailure(TransferModel):
    detail: str


class MCPContactWorkbookFailure(MCPTransferFailure):
    code: ContactWorkbookErrorCode


class MCPFileAuthority(TransferModel):
    authorized: Literal[True]
    capabilities: list[Literal["mcp:upload", "mcp:export"]]


class MCPHeaderAuthority(TransferModel):
    authorized: Literal[True]
    capabilities: list[Literal["mcp:upload", "mcp:communicate"]]
    agency_id: UUID
    broadcast_id: UUID


class MCPArtifactGroup(TransferModel):
    agency_id: UUID
    group_id: UUID


class MCPArtifactMetadata(TransferModel):
    artifact_id: str = Field(pattern=r"^gcmcp_artifact_[A-Za-z0-9_-]{64}$")
    direction: Literal["upload", "export"]
    purpose: str = Field(max_length=64)
    agency_id: UUID
    group_id: UUID
    association_groups: list[MCPArtifactGroup]
    filename: str
    media_type: str
    byte_size: int = Field(gt=0)
    sha256: Digest
    expires_at: datetime
    content_path: str
    delivery_ack_required: bool
    delivered_at: datetime | None
    business_ingestion: (
        Literal[
            "not_started",
            "claimed",
            "unavailable",
            "queued",
            "running",
            "failed",
            "unknown",
            "ingested",
        ]
        | None
    )
    ingestion_operation_id: UUID | None


class MCPContactWorksheet(TransferModel):
    name: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)


class MCPContactUpload(TransferModel):
    upload_id: str = Field(pattern=r"^gcmcp_contacts_[A-Za-z0-9_-]{64}$")
    agency_id: UUID
    filename: str
    media_type: Literal["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]
    byte_size: int = Field(gt=0, le=5 * 1024 * 1024)
    sha256: Digest
    expires_at: datetime
    business_import: Literal["not_started"]
    worksheets: list[MCPContactWorksheet]


class MCPHeaderMedia(TransferModel):
    media_artifact_id: UUID
    media_handle: str = Field(pattern=r"^gcmcp_wa_media_[A-Za-z0-9_-]{64}$")
    agency_id: UUID
    broadcast_id: UUID
    filename: str
    media_type: Literal["image/jpeg", "image/png"]
    byte_size: int = Field(gt=0, le=5 * 1024 * 1024)
    sha256: Digest
    provider_content_sha256: Digest
    status: Literal["staged", "uploading", "ready", "failed", "unknown"]
    expires_at: datetime
    attempt_deadline: datetime | None
    failure_code: str | None
    revision: int = Field(ge=1)
    messages_queued: Literal[0]


class DeliveryAcknowledgement(TransferModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    byte_size: int = Field(gt=0, le=512 * 1024 * 1024)
    sha256: Digest


TRANSFER_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"description": description, "model": MCPTransferFailure | ApiErrorResponse}
    for code, description in {**HTTP_ERROR_CODES, 416: "Partial downloads are unsupported"}.items()
}

CONTACT_UPLOAD_ERRORS: dict[int | str, dict[str, Any]] = {
    **TRANSFER_ERRORS,
    422: {
        "description": "Invalid upload or rejected workbook; workbook codes provide fixed corrective guidance.",
        "model": MCPContactWorkbookFailure | MCPTransferFailure | ApiErrorResponse,
    },
}


def upload_contract(
    *media_types: str, maximum: int | None = None, idempotency: bool = False
) -> dict[str, Any]:
    """Documentation only: raw header validation and bounded streaming stay in routes."""
    size = {"type": "integer", "minimum": 1, **({"maximum": maximum} if maximum else {})}
    headers: list[dict[str, Any]] = [
        {
            "in": "header",
            "name": "X-Artifact-Size",
            "required": True,
            "schema": size,
            "description": "Declared original byte count as ASCII decimal; must match the bounded stream. PDF maximum follows the deployment upload limit.",
        },
        {
            "in": "header",
            "name": "X-Artifact-SHA256",
            "required": True,
            "schema": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "description": "Lowercase SHA-256 of the exact original bytes.",
        },
    ]
    if idempotency:
        headers.append(
            {
                "in": "header",
                "name": "Idempotency-Key",
                "required": True,
                "schema": {
                    "type": "string",
                    "minLength": 16,
                    "maxLength": 256,
                    "pattern": "^[ -~]+$",
                },
                "description": "Exactly one stable key for this actor and exact image/scope. Reuse after ambiguous failure; changed content with the same key conflicts. Exactly one size/checksum header is also required.",
            }
        )
    return {
        "parameters": headers,
        "requestBody": {
            "required": True,
            "description": "Raw file bytes, not multipart or JSON. Dedicated MCP bearer token required; dashboard cookies/JWTs do not authorize this lane.",
            "content": {
                media: {"schema": {"type": "string", "format": "binary"}} for media in media_types
            },
        },
    }


DELIVERY_CONTRACT = {
    "requestBody": {
        "required": True,
        "description": "Only after full checksum-verified delivery; maximum1024 bytes. Does not acknowledge a partial or failed download.",
        "content": {"application/json": {"schema": DeliveryAcknowledgement.model_json_schema()}},
    }
}
CONTENT_RESPONSES: dict[int | str, dict[str, Any]] = {
    **TRANSFER_ERRORS,
    200: {
        "description": "Complete authenticated artifact bytes; interrupted streams must not be acknowledged.",
        "content": {
            media: {"schema": {"type": "string", "format": "binary"}}
            for media in ("application/pdf", XLSX_MEDIA, "application/zip")
        },
        "headers": {
            "X-Artifact-SHA256": {"schema": {"type": "string", "pattern": "^[a-f0-9]{64}$"}},
            "X-Artifact-Size": {"schema": {"type": "integer", "minimum": 1}},
            "Content-Length": {"schema": {"type": "integer", "minimum": 1}},
            "Content-Disposition": {"schema": {"type": "string"}},
        },
    },
}
