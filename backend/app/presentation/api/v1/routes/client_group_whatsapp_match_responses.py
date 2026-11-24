"""Project current roster and persisted resolutions into dashboard response schemas."""


from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from math import ceil
from typing import Literal, cast

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
    SubmissionMatchSummary,
)
from app.infrastructure.database.models import (
    PassportRosterResolutionModel,
    PassportSubmissionModel,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_resolutions import stored_uuid_list
from app.presentation.api.v1.schemas.client_group_schemas import (
    ClientGroupWhatsAppMatchesResponse,
    PassportRosterResolutionResponse,
    WhatsAppRecipientImportedFieldsResponse,
    WhatsAppSubmissionDetailResponse,
    WhatsAppSubmissionMatchCountsResponse,
    WhatsAppSubmissionMatchEvidenceResponse,
    WhatsAppSubmissionMatchRowResponse,
)

_RosterResolutionType = Literal["replacement", "rejected"]
_RosterResolutionStatus = Literal["active", "restored"]
_MatchStatus = Literal[
    "submitted",
    "not_submitted",
    "multiple_submissions",
    "needs_review",
    "unmatched_submission",
    "replacement",
    "rejected_upload",
]
_MatchConfidence = Literal["high", "medium", "none"]
_MatchEvidenceKind = str


def _validated_roster_resolution_type(value: str) -> _RosterResolutionType:
    if value not in {"replacement", "rejected"}:
        raise RuntimeError("Invalid persisted passport roster resolution type.")
    return cast(_RosterResolutionType, value)


def _validated_roster_resolution_status(value: str) -> _RosterResolutionStatus:
    if value not in {"active", "restored"}:
        raise RuntimeError("Invalid persisted passport roster resolution status.")
    return cast(_RosterResolutionStatus, value)


def _validated_match_status(value: str) -> _MatchStatus:
    allowed = {
        "submitted",
        "not_submitted",
        "multiple_submissions",
        "needs_review",
        "unmatched_submission",
        "replacement",
        "rejected_upload",
    }
    if value not in allowed:
        raise RuntimeError("Invalid WhatsApp submission match status.")
    return cast(_MatchStatus, value)


def _validated_match_confidence(value: str) -> _MatchConfidence:
    if value not in {"high", "medium", "none"}:
        raise RuntimeError("Invalid WhatsApp submission match confidence.")
    return cast(_MatchConfidence, value)


def _validated_match_evidence_kind(value: str) -> _MatchEvidenceKind:
    if re.fullmatch(r"[a-z0-9_]{1,64}", value) is None:
        raise RuntimeError("Invalid WhatsApp submission evidence kind.")
    return value


def submission_detail_response(
    submission: PassportSubmissionModel,
) -> WhatsAppSubmissionDetailResponse:
    fields: dict[str, object] = dict(
        submission.confirmed_fields or submission.extracted_fields or {}
    )
    for key, value in dict(submission.staff_metadata or {}).items():
        fields.setdefault(key, value)
    supplemental = {
        "nearest_international_airport": submission.departure_city,
        "nearest_domestic_airport": submission.nearest_domestic_airport,
        "family_relation": submission.family_relation,
        "family_head_name": submission.family_head_name,
    }
    for key, supplemental_value in supplemental.items():
        if supplemental_value not in (None, ""):
            fields.setdefault(key, supplemental_value)
    return WhatsAppSubmissionDetailResponse(
        submission_id=submission.id,
        name=submission.client_name,
        phone=submission.client_phone,
        email=submission.client_email,
        fields=fields,
    )


def roster_resolution_response(
    resolution: PassportRosterResolutionModel,
) -> PassportRosterResolutionResponse:
    return PassportRosterResolutionResponse(
        id=resolution.id,
        client_group_id=resolution.client_group_id,
        submission_id=resolution.submission_id,
        resolution_type=_validated_roster_resolution_type(resolution.resolution_type),
        status=_validated_roster_resolution_status(resolution.status),
        broadcast_recipient_id=resolution.broadcast_recipient_id,
        suppressed_recipient_ids=stored_uuid_list(resolution.suppressed_recipient_ids),
        excluded_submission_ids=stored_uuid_list(resolution.excluded_submission_ids),
        created_at=resolution.created_at,
        restored_at=resolution.restored_at,
    )


def build_whatsapp_matches_response(
    *,
    client_group_id: uuid.UUID,
    selected_broadcast_id: uuid.UUID | None,
    linked_broadcast_count: int,
    counts: SubmissionMatchSummary,
    page_rows: Sequence[SubmissionMatchRow],
    submissions_by_id: Mapping[uuid.UUID, PassportSubmissionModel],
    total: int,
    page: int,
    page_size: int,
) -> ClientGroupWhatsAppMatchesResponse:
    """Serialize a bounded page without leaking submissions outside the loaded group."""

    return ClientGroupWhatsAppMatchesResponse(
        client_group_id=client_group_id,
        selected_broadcast_id=selected_broadcast_id,
        linked_broadcast_count=linked_broadcast_count,
        counts=WhatsAppSubmissionMatchCountsResponse(
            total_recipients=counts.total_recipients,
            submitted_count=counts.submitted_count,
            not_submitted_count=counts.not_submitted_count,
            multiple_submission_count=counts.multiple_submission_count,
            matched_submission_count=counts.matched_submission_count,
            needs_review_count=counts.needs_review_count,
            needs_review_submission_count=counts.needs_review_submission_count,
            unmatched_submission_count=counts.unmatched_submission_count,
            replacement_count=counts.replacement_count,
            rejected_upload_count=counts.rejected_upload_count,
        ),
        matches=[
            WhatsAppSubmissionMatchRowResponse(
                status=_validated_match_status(row.status),
                match_basis=row.match_basis,
                normalized_phone=row.normalized_phone,
                recipient_ids=list(row.recipient_ids),
                submission_ids=list(row.submission_ids),
                broadcast_ids=list(row.broadcast_ids),
                broadcast_names=list(row.broadcast_names),
                recipient_names=list(row.recipient_names),
                submission_names=list(row.submission_names),
                confidence=_validated_match_confidence(row.confidence),
                match_evidence=[
                    WhatsAppSubmissionMatchEvidenceResponse(
                        submission_id=evidence.submission_id,
                        kind=_validated_match_evidence_kind(evidence.kind),
                        recipient_value=evidence.recipient_value,
                        submission_value=evidence.submission_value,
                        weight=evidence.weight,
                    )
                    for evidence in row.match_evidence
                ],
                candidate_submission_ids=list(row.candidate_submission_ids),
                duplicate_submission_ids=list(row.duplicate_submission_ids),
                recipient_fields=[
                    WhatsAppRecipientImportedFieldsResponse(
                        recipient_id=field_set.recipient_id,
                        fields=field_set.fields,
                    )
                    for field_set in row.recipient_fields
                ],
                submission_details=[
                    submission_detail_response(submissions_by_id[submission_id])
                    for submission_id in row.submission_ids
                    if submission_id in submissions_by_id
                ],
                resolution_id=row.resolution_id,
                updated_at=row.updated_at,
            )
            for row in page_rows
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total else 0,
    )


# Preserve the established public import and pickle namespace.
_validated_roster_resolution_type.__module__ = 'app.presentation.api.v1.routes.client_group_whatsapp_match_support'
_validated_roster_resolution_status.__module__ = 'app.presentation.api.v1.routes.client_group_whatsapp_match_support'
_validated_match_status.__module__ = 'app.presentation.api.v1.routes.client_group_whatsapp_match_support'
_validated_match_confidence.__module__ = 'app.presentation.api.v1.routes.client_group_whatsapp_match_support'
_validated_match_evidence_kind.__module__ = 'app.presentation.api.v1.routes.client_group_whatsapp_match_support'
submission_detail_response.__module__ = 'app.presentation.api.v1.routes.client_group_whatsapp_match_support'
roster_resolution_response.__module__ = 'app.presentation.api.v1.routes.client_group_whatsapp_match_support'
build_whatsapp_matches_response.__module__ = 'app.presentation.api.v1.routes.client_group_whatsapp_match_support'
