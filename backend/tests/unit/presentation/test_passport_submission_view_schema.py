from __future__ import annotations

import uuid

from app.presentation.api.v1.schemas.passport_schemas import (
    PassportSubmissionsViewResponse,
)


def test_submission_view_contract_includes_complete_ordered_ids() -> None:
    ordered_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

    response = PassportSubmissionsViewResponse(
        items=[],
        ordered_submission_ids=ordered_ids,
        ordered_selection_snapshot=[
            {
                "submission_id": submission_id,
                "extraction_revision": index,
            }
            for index, submission_id in enumerate(ordered_ids)
        ],
        group_total=10,
        total=3,
        page=2,
        page_size=1,
        total_pages=3,
        returned_count=0,
        expiry_alerts=[],
    )

    payload = response.model_dump(mode="json")
    assert payload["ordered_submission_ids"] == [
        str(submission_id) for submission_id in ordered_ids
    ]
    assert payload["total"] == len(ordered_ids)
    assert payload["ordered_selection_snapshot"] == [
        {
            "submission_id": str(submission_id),
            "extraction_revision": index,
        }
        for index, submission_id in enumerate(ordered_ids)
    ]
