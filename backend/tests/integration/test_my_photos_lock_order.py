"""Executed ORM locks follow one order; this is not live PG deadlock qualification."""

from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import LivenessResult, LivenessSessionHandle
from app.infrastructure.database.gc_mobile_models import MobilePassengerIdentityModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoLivenessSessionModel,
)
from app.infrastructure.my_photos.service import MyPhotosService
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosLivenessCompleteRequest,
    MyPhotosLivenessStartRequest,
)
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)


@pytest.mark.parametrize(
    "phase", ["creation_success", "creation_failure", "completion_initial", "completion_final"]
)
async def test_liveness_uses_canonical_executed_lock_order(photo_database, phase):
    env = photo_database
    locks, initial = [], []
    labels = {
        MobilePassengerIdentityModel: "identity",
        MyPhotoEnrollmentModel: "enrollment",
        MyPhotoLivenessSessionModel: "liveness",
    }

    class Provider:
        ready = True
        client_flow = "development_simulator"

        async def create_session(self, request):
            if phase.startswith("creation"):
                locks.clear()  # The durable reservation transaction ended before provider I/O.
            if phase == "creation_failure":
                raise MyPhotosUnavailable("PROVIDER_UNAVAILABLE", "Synthetic provider outage")
            return LivenessSessionHandle("synthetic-provider-session", request.expires_at)

        async def get_result(self, _reference):
            initial[:] = locks
            locks.clear()  # Observe only the transaction reacquired after provider I/O.
            return LivenessResult("passed", reference_face_handle="synthetic-reference")

    providers = SimpleNamespace(
        provider_name="development", liveness=Provider(), face_search=SimpleNamespace(ready=True)
    )
    async with env.sessions() as session:

        @event.listens_for(session.sync_session, "do_orm_execute")
        def observe(execution):
            if not execution.is_select:
                return
            statement = execution.statement
            if "FOR UPDATE" not in str(statement.compile(dialect=postgresql.dialect())):
                return
            entity = statement.column_descriptions[0].get("entity")
            if entity in labels:
                locks.append(labels[entity])

        service = MyPhotosService(session, settings=env.settings, providers=providers)
        start = MyPhotosLivenessStartRequest(
            challenge_mode="movement_only", idempotency_key="synthetic-lock-start"
        )
        if phase == "creation_failure":
            with pytest.raises(MyPhotosUnavailable):
                await service.start_liveness(
                    claims=env.passenger.claims, trip=env.passenger.trip, request=start
                )
            assert locks == ["enrollment", "liveness"]
            return
        created = await service.start_liveness(
            claims=env.passenger.claims, trip=env.passenger.trip, request=start
        )
        await session.commit()
        if phase == "creation_success":
            assert locks == ["identity", "enrollment", "liveness"]
            return
        locks.clear()
        await service.complete_liveness(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            session_id=created.session_id,
            request=MyPhotosLivenessCompleteRequest(
                outcome="completed", idempotency_key="synthetic-lock-completion"
            ),
        )
        assert (initial if phase == "completion_initial" else locks) == [
            "identity",
            "enrollment",
            "liveness",
        ]
