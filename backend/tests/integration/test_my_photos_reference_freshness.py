"""Late cleanup and failed creation must preserve newer durable lifecycle state."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.application.my_photos.errors import MyPhotosConflict, MyPhotosUnavailable
from app.application.my_photos.providers import ReferenceDeletionResult
from app.infrastructure.database.my_photos_models import MyPhotoEnrollmentModel
from app.infrastructure.my_photos.context import MyPhotosContext
from app.infrastructure.my_photos.reference_lifecycle import MyPhotosReferenceLifecycle
from app.infrastructure.my_photos.service import MyPhotosService
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosDeleteEnrollmentRequest,
    MyPhotosLivenessStartRequest,
)
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)


@pytest.mark.parametrize("kind", ["current", "current_error", "superseded"])
async def test_late_cleanup_cannot_clear_a_newer_pending_reference(photo_database, kind):
    env = photo_database
    is_current = kind.startswith("current")
    now = datetime.now(UTC)
    async with env.sessions() as session, session.begin():
        enrollment = await session.scalar(select(MyPhotoEnrollmentModel))
        enrollment_id = enrollment.id
        enrollment.provider_name = "development"
        enrollment.provider_reference_handle = "synthetic-current-reference"
        enrollment.reference_version = 2
        enrollment.enrolled_at = now
        if is_current:
            enrollment.status = "deleted"
            enrollment.deleted_at = now
            enrollment.deletion_idempotency_key = "synthetic-delete"
            enrollment.deletion_scope = "enrollment_only"
            enrollment.provider_deletion_status = "pending"
            enrollment.provider_deletion_requested_at = now
        else:
            enrollment.status = "enrolled"
            enrollment.superseded_provider_reference_handle = "synthetic-old-reference"
            enrollment.superseded_reference_deletion_status = "pending"
            enrollment.superseded_reference_deletion_requested_at = now

    class Provider:
        async def delete_reference(self, _request):
            async with env.sessions() as session, session.begin():
                field = (
                    "provider_reference_handle"
                    if is_current
                    else "superseded_provider_reference_handle"
                )
                await session.execute(
                    update(MyPhotoEnrollmentModel)
                    .where(
                        MyPhotoEnrollmentModel.id == enrollment_id,
                    )
                    .values(**{field: "synthetic-new-reference"})
                )
            if kind == "current_error":
                raise MyPhotosUnavailable("PROVIDER_UNAVAILABLE", "Synthetic old-provider failure")
            return ReferenceDeletionResult("deleted")

    providers = SimpleNamespace(provider_name="development", liveness=Provider())
    async with env.sessions() as session:
        try:
            if kind == "current_error":
                service = MyPhotosService(session, settings=env.settings, providers=providers)
                result = await service.delete_enrollment(
                    claims=env.passenger.claims,
                    trip=env.passenger.trip,
                    request=MyPhotosDeleteEnrollmentRequest(
                        scope="enrollment_only", idempotency_key="synthetic-delete"
                    ),
                )
                await session.commit()
                assert result.provider_deletion_status == "pending"
            elif is_current:
                service = MyPhotosService(session, settings=env.settings, providers=providers)
                with pytest.raises(MyPhotosConflict):
                    await service.delete_enrollment(
                        claims=env.passenger.claims,
                        trip=env.passenger.trip,
                        request=MyPhotosDeleteEnrollmentRequest(
                            scope="enrollment_only", idempotency_key="synthetic-delete"
                        ),
                    )
                    await session.commit()
            else:
                enrollment = await session.get(MyPhotoEnrollmentModel, enrollment_id)
                references = MyPhotosReferenceLifecycle(
                    MyPhotosContext(session, env.settings, providers)
                )
                result = await references._delete_superseded_reference(
                    enrollment=enrollment, passenger_identity_id=env.passenger.identity.id
                )
                await session.commit()
                assert result.superseded_provider_reference_handle == "synthetic-new-reference"
                assert result.superseded_reference_deletion_status == "pending"
        finally:
            await session.rollback()
    async with env.sessions() as session:
        saved = await session.get(MyPhotoEnrollmentModel, enrollment_id)
        if is_current:
            assert saved.provider_reference_handle == "synthetic-new-reference"
            assert saved.provider_deletion_status == "pending"
            if kind == "current_error":
                assert saved.provider_deletion_attempt_count == 0
                assert saved.provider_deletion_error_code is None
        else:
            assert saved.superseded_provider_reference_handle == "synthetic-new-reference"
            assert saved.superseded_reference_deletion_status == "pending"


@pytest.mark.parametrize("revoke", [True, False])
async def test_provider_creation_failure_preserves_concurrent_consent_revocation(
    photo_database, revoke
):
    env = photo_database

    class Provider:
        ready = True
        client_flow = "development_simulator"

        async def create_session(self, _request):
            if revoke:
                async with env.sessions() as session, session.begin():
                    await session.execute(
                        update(MyPhotoEnrollmentModel).values(
                            status="revoked", revoked_at=datetime.now(UTC)
                        )
                    )
            raise MyPhotosUnavailable("PROVIDER_UNAVAILABLE", "Synthetic provider outage")

    providers = SimpleNamespace(
        provider_name="development", liveness=Provider(), face_search=SimpleNamespace(ready=True)
    )
    async with env.sessions() as session:
        service = MyPhotosService(session, settings=env.settings, providers=providers)
        with pytest.raises(MyPhotosUnavailable):
            await service.start_liveness(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                request=MyPhotosLivenessStartRequest(
                    challenge_mode="movement_only", idempotency_key="synthetic-failed-start"
                ),
            )
        await session.rollback()
    async with env.sessions() as session:
        saved = await session.scalar(select(MyPhotoEnrollmentModel))
        assert saved.status == ("revoked" if revoke else "ready")
        assert (saved.revoked_at is not None) is revoke
        if not revoke:
            assert saved.attempt_count == 0
