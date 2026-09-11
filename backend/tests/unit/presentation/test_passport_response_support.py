"""Keep domain enum values explicit at the passport response boundary."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import PassportExtractionStatus, PassportSubmission
from app.presentation.api.v1.routes.passport_routes import response_support
from app.presentation.api.v1.schemas.passport_schemas import PassportSubmissionResponse


@pytest.mark.parametrize("extraction_status", list(PassportExtractionStatus))
async def test_submission_response_serializes_domain_extraction_status(
    extraction_status: PassportExtractionStatus,
) -> None:
    submission = PassportSubmission.create(
        group_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        client_name="Test traveller",
        client_email="traveller@example.test",
        image_s3_key="synthetic/passport.jpg",
    )
    submission.extraction_status = extraction_status
    session = AsyncMock(spec=AsyncSession)

    with (
        patch.object(
            response_support.PassportImageCropRepository,
            "list_for_submissions",
            new=AsyncMock(return_value={}),
        ),
        patch.object(
            response_support,
            "_passport_qr_status",
            new=AsyncMock(return_value={"status": "not_generated"}),
        ),
        patch.object(
            response_support.PassportProcessingJobRepository,
            "latest_for_submission",
            new=AsyncMock(return_value=None),
        ),
        patch.object(
            PassportSubmissionResponse,
            "model_validate",
            wraps=PassportSubmissionResponse.model_validate,
        ) as validate,
    ):
        response = await response_support._response_from_submission(submission, session=session)

    validate.assert_called_once()
    payload = validate.call_args.args[0]
    # Newer Pydantic versions accept str-backed enums in Literal fields. Keep
    # the boundary contract explicit so that they cannot mask a 2.7.4 failure.
    assert type(payload["extraction_status"]) is str
    assert payload["extraction_status"] == extraction_status.value
    assert type(payload["status"]) is str
    serialized = response.model_dump(mode="json")
    assert serialized["id"] == str(submission.id)
    assert serialized["extraction_status"] == extraction_status.value
    assert serialized["status"] == submission.status.value
    assert submission.extraction_status is extraction_status
