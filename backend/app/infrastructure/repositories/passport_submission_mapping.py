"""Explicit domain/model mappings and the extraction-only write projection."""

from __future__ import annotations

from app.domain.entities.entities import (
    PassportExtractionStatus,
    PassportProcessingStatus,
    PassportSubmission,
)
from app.infrastructure.database.models import PassportSubmissionModel


def _to_entity(model: PassportSubmissionModel) -> PassportSubmission:
    return PassportSubmission(
        id=model.id,
        group_id=model.group_id,
        agency_id=model.agency_id,
        client_name=model.client_name,
        display_name=model.display_name,
        client_email=model.client_email,
        client_phone=model.client_phone,
        departure_city=model.departure_city,
        nearest_domestic_airport=model.nearest_domestic_airport,
        submission_mode=model.submission_mode,
        family_group_id=model.family_group_id,
        family_member_index=model.family_member_index,
        family_relation=model.family_relation,
        family_gender=model.family_gender,
        family_head_name=model.family_head_name,
        family_head_email=model.family_head_email,
        family_head_phone=model.family_head_phone,
        family_broadcast_to_member=model.family_broadcast_to_member,
        image_s3_key=model.image_s3_key,
        thumbnail_s3_key=model.thumbnail_s3_key,
        passport_photo_s3_key=model.passport_photo_s3_key,
        passport_cover_s3_key=model.passport_cover_s3_key,
        passport_back_cover_s3_key=model.passport_back_cover_s3_key,
        passport_back_s3_key=model.passport_back_s3_key,
        acquisition_mode=model.acquisition_mode,
        upload_idempotency_key=model.upload_idempotency_key,
        qualifier_enabled_snapshot=model.qualifier_enabled_snapshot,
        qualifier_selection_id=model.qualifier_selection_id,
        qualifier_is_self=model.qualifier_is_self,
        qualifier_relation_code=model.qualifier_relation_code,
        qualifier_relation_label=model.qualifier_relation_label,
        qualifier_selected_at=model.qualifier_selected_at,
        extraction_status=PassportExtractionStatus(model.extraction_status),
        extraction_revision=model.extraction_revision,
        staff_metadata=model.staff_metadata,
        document_follow_up=bool(model.document_follow_up),
        custom_answers=list(model.custom_answers or []),
        custom_detail_answers=list(model.custom_detail_answers or []),
        status=PassportProcessingStatus(model.status),
        extracted_fields=model.extracted_fields,
        confirmed_fields=model.confirmed_fields,
        extraction_conflicts=list(model.extraction_conflicts or []),
        overall_confidence=model.overall_confidence,
        confidence_score=model.confidence_score,
        mrz_raw=model.mrz_raw,
        error_message=model.error_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
        client_reviewed_at=model.client_reviewed_at,
        confirmed_at=model.confirmed_at,
        post_submission_verification=model.post_submission_verification,
        post_submission_verification_revision=(model.post_submission_verification_revision),
        post_submission_verified_at=model.post_submission_verified_at,
        verification_reviewed_by_user_id=model.verification_reviewed_by_user_id,
        verification_reviewer_name=model.verification_reviewer_name,
        verification_reviewed_at=model.verification_reviewed_at,
    )


def _to_model(entity: PassportSubmission) -> PassportSubmissionModel:
    return PassportSubmissionModel(
        id=entity.id,
        group_id=entity.group_id,
        agency_id=entity.agency_id,
        client_name=entity.client_name,
        display_name=entity.display_name,
        client_email=entity.client_email,
        client_phone=entity.client_phone,
        departure_city=entity.departure_city,
        nearest_domestic_airport=entity.nearest_domestic_airport,
        submission_mode=entity.submission_mode,
        family_group_id=entity.family_group_id,
        family_member_index=entity.family_member_index,
        family_relation=entity.family_relation,
        family_gender=entity.family_gender,
        family_head_name=entity.family_head_name,
        family_head_email=entity.family_head_email,
        family_head_phone=entity.family_head_phone,
        family_broadcast_to_member=entity.family_broadcast_to_member,
        image_s3_key=entity.image_s3_key,
        thumbnail_s3_key=entity.thumbnail_s3_key,
        passport_photo_s3_key=entity.passport_photo_s3_key,
        passport_cover_s3_key=entity.passport_cover_s3_key,
        passport_back_cover_s3_key=entity.passport_back_cover_s3_key,
        passport_back_s3_key=entity.passport_back_s3_key,
        acquisition_mode=entity.acquisition_mode,
        upload_idempotency_key=entity.upload_idempotency_key,
        qualifier_enabled_snapshot=entity.qualifier_enabled_snapshot,
        qualifier_selection_id=entity.qualifier_selection_id,
        qualifier_is_self=entity.qualifier_is_self,
        qualifier_relation_code=entity.qualifier_relation_code,
        qualifier_relation_label=entity.qualifier_relation_label,
        qualifier_selected_at=entity.qualifier_selected_at,
        extraction_status=entity.extraction_status.value,
        extraction_revision=entity.extraction_revision,
        staff_metadata=entity.staff_metadata,
        document_follow_up=entity.document_follow_up,
        custom_answers=entity.custom_answers,
        custom_detail_answers=entity.custom_detail_answers,
        status=entity.status.value,
        extracted_fields=entity.extracted_fields,
        confirmed_fields=entity.confirmed_fields,
        extraction_conflicts=entity.extraction_conflicts,
        overall_confidence=entity.overall_confidence,
        confidence_score=entity.confidence_score,
        mrz_raw=entity.mrz_raw,
        error_message=entity.error_message,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        client_reviewed_at=entity.client_reviewed_at,
        confirmed_at=entity.confirmed_at,
        post_submission_verification=entity.post_submission_verification,
        post_submission_verification_revision=(entity.post_submission_verification_revision),
        post_submission_verified_at=entity.post_submission_verified_at,
        verification_reviewed_by_user_id=entity.verification_reviewed_by_user_id,
        verification_reviewer_name=entity.verification_reviewer_name,
        verification_reviewed_at=entity.verification_reviewed_at,
    )


def _apply_extraction_fields(
    model: PassportSubmissionModel, submission: PassportSubmission
) -> None:
    model.status = submission.status.value
    model.extraction_status = submission.extraction_status.value
    model.extracted_fields = submission.extracted_fields
    model.confirmed_fields = submission.confirmed_fields
    model.extraction_conflicts = submission.extraction_conflicts
    model.overall_confidence = submission.overall_confidence
    model.confidence_score = submission.confidence_score
    model.mrz_raw = submission.mrz_raw
    model.error_message = submission.error_message
    model.updated_at = submission.updated_at
