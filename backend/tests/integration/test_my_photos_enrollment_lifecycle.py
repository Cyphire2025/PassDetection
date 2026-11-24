"""Consent, reference rotation and retryable deletion use durable private state."""

from datetime import UTC
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.application.my_photos.errors import MyPhotosConflict, MyPhotosUnavailable
from app.application.my_photos.providers import (
    LivenessResult,
    LivenessSessionHandle,
    ReferenceDeletionResult,
)
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoJobModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.service import MyPhotosService
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosConsentRequest,
    MyPhotosDeleteEnrollmentRequest,
    MyPhotosLivenessCompleteRequest,
    MyPhotosLivenessStartRequest,
)
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)


class SyntheticProvider:
    ready = True
    client_flow = "development_simulator"

    def __init__(self):
        self.references = 0
        self.deletions = []
        self.fail_delete = False

    async def create_session(self, request):
        return LivenessSessionHandle("synthetic-provider-session", request.expires_at)

    async def get_result(self, _reference):
        self.references += 1
        return LivenessResult(
            "passed", reference_face_handle=f"synthetic-reference-{self.references}"
        )

    async def delete_reference(self, request):
        self.deletions.append(request.provider_reference)
        if self.fail_delete:
            raise MyPhotosUnavailable("PROVIDER_UNAVAILABLE", "Synthetic provider outage")
        return ReferenceDeletionResult("deleted")


def service_for(session, env, provider):
    return MyPhotosService(
        session,
        settings=env.settings,
        providers=SimpleNamespace(
            provider_name="development",
            liveness=provider,
            face_search=SimpleNamespace(ready=True),
        ),
    )


async def test_consent_delete_and_reaccept_preserve_idempotency(photo_database):
    env = photo_database
    provider = SyntheticProvider()
    async with env.sessions() as session:
        service = service_for(session, env, provider)
        consent = MyPhotosConsentRequest(
            consent_version=env.settings.my_photos.consent_version,
            accepted=True,
            idempotency_key="synthetic-consent",
        )
        accepted = await service.accept_consent(
            claims=env.passenger.claims, trip=env.passenger.trip, request=consent
        )
        assert accepted.consent.required is False
        await session.commit()
        request = MyPhotosDeleteEnrollmentRequest(
            scope="enrollment_and_search_data", idempotency_key="synthetic-delete"
        )
        deleted = await service.delete_enrollment(
            claims=env.passenger.claims, trip=env.passenger.trip, request=request
        )
        await session.commit()
        repeated = await service.delete_enrollment(
            claims=env.passenger.claims, trip=env.passenger.trip, request=request
        )
        assert repeated.deleted_at.replace(tzinfo=UTC) == deleted.deleted_at.replace(tzinfo=UTC)
        assert repeated.provider_deletion_status == "not_required" and repeated.removed_search_data
        with pytest.raises(MyPhotosConflict):
            await service.delete_enrollment(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                request=request.model_copy(update={"idempotency_key": "synthetic-other-delete"}),
            )
        restored = await service.accept_consent(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            request=consent.model_copy(update={"idempotency_key": "synthetic-new-consent"}),
        )
        await session.commit()
        assert restored.enrollment.status == "ready"
        saved = await session.scalar(select(MyPhotoEnrollmentModel))
        assert saved.deleted_at is None and saved.deletion_idempotency_key is None
        assert saved.provider_reference_handle is None and saved.reference_version == 0
        assert provider.deletions == []


async def test_reference_rotation_and_pending_deletion_retry_do_not_duplicate_searches(
    photo_database,
):
    env = photo_database
    provider = SyntheticProvider()
    async with env.sessions() as session:
        service = service_for(session, env, provider)
        for version in (1, 2):
            created = await service.start_liveness(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                request=MyPhotosLivenessStartRequest(
                    challenge_mode="movement_only", idempotency_key=f"synthetic-start-{version}"
                ),
            )
            await session.commit()
            completed = await service.complete_liveness(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                session_id=created.session_id,
                request=MyPhotosLivenessCompleteRequest(
                    outcome="completed", idempotency_key=f"synthetic-complete-{version}"
                ),
            )
            await session.commit()
            assert completed.search_run_id is not None
        saved = await session.scalar(select(MyPhotoEnrollmentModel))
        assert (
            saved.reference_version == 2
            and saved.provider_reference_handle == "synthetic-reference-2"
        )
        assert saved.superseded_provider_reference_handle is None
        assert provider.deletions == ["synthetic-reference-1"]
        assert await session.scalar(select(func.count()).select_from(MyPhotoSearchRunModel)) == 2
        provider.fail_delete = True
        request = MyPhotosDeleteEnrollmentRequest(
            scope="enrollment_and_search_data", idempotency_key="synthetic-final-delete"
        )
        pending = await service.delete_enrollment(
            claims=env.passenger.claims, trip=env.passenger.trip, request=request
        )
        await session.commit()
        assert pending.provider_deletion_status == "pending" and pending.provider_deletion_retryable
        assert "synthetic-reference" not in pending.model_dump_json()
        assert await session.scalar(select(func.count()).select_from(MyPhotoSearchRunModel)) == 0
        assert await session.scalar(select(func.count()).select_from(MyPhotoJobModel)) == 0
        provider.fail_delete = False
        deleted = await service.delete_enrollment(
            claims=env.passenger.claims, trip=env.passenger.trip, request=request
        )
        await session.commit()
        replay = await service.delete_enrollment(
            claims=env.passenger.claims, trip=env.passenger.trip, request=request
        )
        assert deleted.provider_deletion_status == replay.provider_deletion_status == "complete"
        assert deleted.local_downloads_affected is False
        assert provider.deletions == [
            "synthetic-reference-1",
            "synthetic-reference-2",
            "synthetic-reference-2",
        ]
        assert (
            await session.scalar(select(MyPhotoEnrollmentModel))
        ).provider_reference_handle is None
