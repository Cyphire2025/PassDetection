"""Validate selected and explicitly resent documents against one preview."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status

from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentDeliveryPreviewRecipient,
    DocumentDeliveryPreviewResponse,
    SendDocumentBroadcastRequest,
)


def _require_selected_documents_ready(
    requested_ids: set[uuid.UUID], eligible_rows: list[DocumentDeliveryPreviewRecipient],
) -> None:
    if requested_ids - {row.document_id for row in eligible_rows}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("A selected document is blocked or no longer assigned. Review its saved "
                    "assignment and WhatsApp number, then refresh the preview before sending."),
        )


def select_document_delivery_rows(
    payload: SendDocumentBroadcastRequest, preview: DocumentDeliveryPreviewResponse,
) -> tuple[set[uuid.UUID], set[uuid.UUID], list[DocumentDeliveryPreviewRecipient]]:
    requested_ids = (
        set(payload.document_ids)
        if payload.document_ids is not None
        else {row.document_id for row in preview.recipients if row.document_id and row.eligible}
    )
    resend_ids = set(payload.resend_document_ids)
    if not resend_ids.issubset(requested_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Every resend document must also be selected for sending",
        )
    resendable_ids = {
        row.document_id for row in preview.recipients if row.document_id and row.resend_allowed
    }
    invalid_resend_ids = resend_ids - resendable_ids
    if invalid_resend_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("A selected resend is not eligible. Refresh the preview before trying again."),
        )
    eligible_rows = [
        row
        for row in preview.recipients
        if row.document_id in requested_ids and (row.eligible or row.document_id in resend_ids)
    ]
    _require_selected_documents_ready(requested_ids, eligible_rows)
    if not eligible_rows:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Select at least one new or safely retryable document",
        )

    return requested_ids, resend_ids, eligible_rows
