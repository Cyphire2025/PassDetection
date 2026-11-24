"""Pure bounded My Photos lifecycle response projections."""

from __future__ import annotations

from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoLivenessSessionModel,
    MyPhotoSearchRunModel,
)
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosLivenessCompleteResponse,
    MyPhotosSearchRunResponse,
)


def _search_response(search: MyPhotoSearchRunModel | None) -> MyPhotosSearchRunResponse | None:
    if search is None:
        return None
    progress = (
        100
        if search.status == "complete"
        else int((search.processed_face_count / search.total_face_count) * 100)
        if search.total_face_count > 0
        else 0
    )
    return MyPhotosSearchRunResponse(
        id=search.id,
        status=search.status,  # type: ignore[arg-type]
        processed_face_count=search.processed_face_count,
        total_face_count=search.total_face_count,
        progress_percent=progress,
        matched_photo_count=search.matched_asset_count,
        best_match_count=search.best_match_count,
        possible_match_count=search.possible_match_count,
        started_at=search.started_at,
        completed_at=search.completed_at,
        error_code=search.stable_error_code,
    )


def _completion_response(
    session: MyPhotoLivenessSessionModel,
    enrollment: MyPhotoEnrollmentModel,
    search: MyPhotoSearchRunModel | None,
) -> MyPhotosLivenessCompleteResponse:
    return MyPhotosLivenessCompleteResponse(
        session_id=session.id,
        session_status=session.status,  # type: ignore[arg-type]
        enrollment_status=enrollment.status,  # type: ignore[arg-type]
        search_run_id=search.id if search is not None else None,
        search_status="queued" if search is not None else "not_started",
        retryable=bool(session.result_retryable),
        error_code=session.stable_error_code,
        cooldown_until=enrollment.cooldown_until,
    )
