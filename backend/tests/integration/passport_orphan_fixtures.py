"""Synthetic durable owners for the private-image orphan reconciliation tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
    PassportImageCropModel,
    PassportSubmissionModel,
    PassportVisaAiImageJobModel,
    PassportVisaAiImageModel,
)
from app.infrastructure.database.passport_ecr_models import PassportEcrCheckModel
from app.infrastructure.database.passport_image_library_model import PassportImageLibraryItemModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel,
    TravellerReturningDraftModel,
)
from tests.integration.traveller_reuse_fixtures import reuse_context, seed_person
from tests.unit.application.test_traveller_reconciliation import _seed_scope

IMAGE_PREFIXES = (
    "passport-image-library/",
    "passport-crops/",
    "passport-edits/",
    "passport-ai-library/",
)
SUBMISSION_FIELDS = (
    "image_s3_key",
    "thumbnail_s3_key",
    "passport_photo_s3_key",
    "passport_cover_s3_key",
    "passport_back_cover_s3_key",
    "passport_back_s3_key",
)


async def retained_image_keys(session, settings, *, prefixes=IMAGE_PREFIXES) -> set[str]:
    """Use actual FK-enforced tables, without depending on library mirrors."""
    service, _, group = await reuse_context(session, settings)
    person = await seed_person(service, group)
    keys: set[str] = set()

    def key(label: str) -> str:
        value = prefixes[len(keys) % len(prefixes)] + label + ".jpg"
        keys.add(value)
        return value

    def submission(**overrides):
        row = PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=group.agency_id,
            group_id=group.id,
            client_name="Synthetic orphan fixture",
            image_s3_key="test-only/front.jpg",
            status="staff_approved",
        )
        for name, value in overrides.items():
            setattr(row, name, value)
        session.add(row)
        return row

    owner = submission(**{name: key(name) for name in SUBMISSION_FIELDS})
    await session.flush()
    session.add(
        PassportImageCropModel(
            submission_id=owner.id,
            image_type="visa_photo",
            active=False,
            source_storage_key=key("crop-source"),
            edit_source_storage_key=key("crop-edit"),
            derived_storage_key=key("inactive-crop"),
            crop_x=0,
            crop_y=0,
            crop_width=1,
            crop_height=1,
            source_width=100,
            source_height=100,
        )
    )
    session.add(
        PassportEcrCheckModel(
            submission_id=owner.id,
            source_storage_key=key("retained-ecr-source"),
            status="processing",
        )
    )
    session.add(
        PassportImageLibraryItemModel(
            submission_id=owner.id,
            image_type="visa_photo",
            source="manual",
            storage_key=key("manual-library"),
            original_source_storage_key=key("library-source"),
        )
    )
    # Historical rows need protection even when no common-library mirror exists.
    session.add(
        PassportVisaAiImageModel(
            submission_id=owner.id,
            original_source_storage_key=key("legacy-source"),
            input_storage_key=key("legacy-input"),
            generated_storage_key=key("legacy-output"),
            prompt="synthetic",
            prompt_sha256="a" * 64,
            content_sha256="b" * 64,
            model="synthetic-model",
        )
    )
    for status in ("queued", "running", "succeeded", "failed"):
        job_owner = submission()
        await session.flush()
        session.add(
            PassportVisaAiImageJobModel(
                submission_id=job_owner.id,
                status=status,
                original_source_storage_key=key(f"{status}-source"),
                input_storage_key=key(f"{status}-input"),
                prompt="synthetic",
                prompt_sha256="a" * 64,
            )
        )
    person.asset.object_key = key("retained-traveller")
    person.asset.source_object_key = key("pending-copy-source")
    person.asset.availability = "pending"
    now = datetime.now(UTC)
    draft = TravellerReturningDraftModel(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        company_id=group.company_id,
        group_id=group.id,
        mode="fresh",
        upload_session_hash="c" * 64,
        secret_hash="d" * 64,
        payload_ciphertext="synthetic-encrypted-payload",
        review_version="e" * 64,
        contact_revision=1,
        profile_revision=1,
        authorization_version=1,
        created_at=now,
        expires_at=now + timedelta(days=1),
    )
    session.add(draft)
    await session.flush()
    session.add(
        TravellerDraftAssetModel(
            agency_id=group.agency_id,
            company_id=group.company_id,
            draft_id=draft.id,
            side="front",
            object_key=key("retained-draft"),
            checksum="f" * 64,
            byte_size=4,
            content_type="image/jpeg",
            idempotency_key="synthetic-draft",
            state="adopted",
            expected_revision=1,
            fields_revision=1,
            available_at=now,
        )
    )
    await session.commit()
    return keys


async def retained_document_keys(session) -> set[str]:
    agency, _, group = await _seed_scope(session)
    rename = DocumentRenameBatchModel(agency_id=agency.id)
    distribution = DocumentDistributionBatchModel(
        agency_id=agency.id,
        group_id=group.id,
        document_type="visa",
    )
    session.add_all([rename, distribution])
    await session.flush()
    rename_key, distribution_key = (
        "document-rename/retained.pdf",
        "document-distribution/retained.pdf",
    )
    session.add_all(
        [
            DocumentRenameItemModel(
                agency_id=agency.id,
                batch_id=rename.id,
                original_filename="original.pdf",
                renamed_filename="renamed.pdf",
                storage_key=rename_key,
            ),
            DistributedDocumentModel(
                agency_id=agency.id,
                group_id=group.id,
                batch_id=distribution.id,
                document_type="visa",
                original_filename="original.pdf",
                storage_key=distribution_key,
            ),
        ]
    )
    await session.commit()
    return {rename_key, distribution_key}
