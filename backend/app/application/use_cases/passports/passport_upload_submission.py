"""Construct a passport draft from the already stored, ordered upload plan."""

from __future__ import annotations

from app.domain.entities.entities import ClientGroup, PassportSubmission, QualifierSelection

from .passport_upload_plan import UploadSpec


def prepare_passport_submission(
    *,
    group: ClientGroup,
    client_name: str,
    front_key: str,
    acquisition_mode: str,
    normalized_key: str | None,
    qualifier_selection: QualifierSelection | None,
    upload_specs: list[UploadSpec],
) -> PassportSubmission:
    submission = PassportSubmission.create(
        group_id=group.id,
        agency_id=group.agency_id,
        client_name=client_name,
        client_email=None,
        image_s3_key=front_key,
        acquisition_mode=acquisition_mode,
        upload_idempotency_key=normalized_key,
    )
    if qualifier_selection is not None:
        submission.attach_qualifier_selection(qualifier_selection)
    for stored_document_type, _content, _content_type, upload_key in upload_specs:
        if stored_document_type is None:
            continue
        if stored_document_type == "photo":
            submission.promote_passport_photo(upload_key)
        elif stored_document_type == "back":
            # Back pages are persisted and displayed only. They are not
            # passed to any field extraction service.
            submission.promote_passport_back(upload_key)
        elif stored_document_type == "cover":
            submission.promote_passport_cover(upload_key)
        else:
            submission.promote_passport_back_cover(upload_key)

    if not front_key:
        submission.prepare_without_passport_front()
    return submission
