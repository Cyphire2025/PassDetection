"""Exercise recoverable liveness outcomes with real durable rows and fake providers."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.application.my_photos.errors import (
    MyPhotosConflict,
    MyPhotosRateLimited,
    MyPhotosUnavailable,
)
from app.application.my_photos.providers import LivenessResult, LivenessSessionHandle
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


class SyntheticLiveness:
    ready = True
    client_flow = "development_simulator"

    def __init__(self, outcome="passed"):
        self.outcome = outcome
        self.created = 0
        self.verified = 0

    async def create_session(self, request):
        self.created += 1
        return LivenessSessionHandle(f"synthetic-provider-{self.created}", request.expires_at)

    async def get_result(self, _reference):
        self.verified += 1
        return LivenessResult(
            self.outcome,
            reference_face_handle="synthetic-reference" if self.outcome == "passed" else None,
            retryable=self.outcome != "passed",
        )


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


async def start_session(service, env):
    return await service.start_liveness(
        claims=env.passenger.claims,
        trip=env.passenger.trip,
        request=MyPhotosLivenessStartRequest(
            challenge_mode="movement_only", idempotency_key="synthetic-transition-start"
        ),
    )


@pytest.mark.parametrize("outcome", ["cancelled", "expired", "failed"])
async def test_client_terminal_outcomes_do_not_call_provider_or_schedule_search(
    photo_database, outcome
):
    env = photo_database
    provider = SyntheticLiveness()
    async with env.sessions() as session:
        service = service_for(session, env, provider)
        created = await start_session(service, env)
        await session.commit()
        request = MyPhotosLivenessCompleteRequest(
            outcome=outcome, idempotency_key="synthetic-terminal-completion"
        )
        result = await service.complete_liveness(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            session_id=created.session_id,
            request=request,
        )
        await session.commit()
        replay = await service.complete_liveness(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            session_id=created.session_id,
            request=request,
        )
        assert result.session_status == replay.session_status == outcome
        assert result.search_run_id is None and replay.search_run_id is None
        assert provider.verified == 0 and provider.created == 1
        saved = await session.get(MyPhotoLivenessSessionModel, created.session_id)
        assert saved.consumed_at is not None and saved.provider_claim_token is None


@pytest.mark.parametrize("outcome", ["rejected", "unavailable", "throttled"])
async def test_provider_outcomes_preserve_retryable_claims_or_terminal_results(
    photo_database, outcome
):
    env = photo_database
    provider = SyntheticLiveness(outcome)
    async with env.sessions() as session:
        service = service_for(session, env, provider)
        created = await start_session(service, env)
        await session.commit()
        request = MyPhotosLivenessCompleteRequest(
            outcome="completed", idempotency_key="synthetic-provider-completion"
        )
        if outcome == "rejected":
            result = await service.complete_liveness(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                session_id=created.session_id,
                request=request,
            )
            await session.commit()
            assert result.session_status == "rejected" and result.enrollment_status == "rejected"
            assert result.search_run_id is None
        else:
            expected = MyPhotosRateLimited if outcome == "throttled" else MyPhotosUnavailable
            with pytest.raises(expected):
                await service.complete_liveness(
                    claims=env.passenger.claims,
                    trip=env.passenger.trip,
                    session_id=created.session_id,
                    request=request,
                )
            saved = await session.get(MyPhotoLivenessSessionModel, created.session_id)
            assert saved.status == "running" and saved.provider_claim_token is None
            provider.outcome = "passed"
            result = await service.complete_liveness(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                session_id=created.session_id,
                request=request,
            )
            await session.commit()
            assert result.session_status == "completed" and result.search_run_id is not None
            assert provider.verified == 2


async def test_start_admission_rejects_conflicts_and_replaces_expired_session(photo_database):
    env = photo_database
    provider = SyntheticLiveness()
    async with env.sessions() as session:
        service = service_for(session, env, provider)
        created = await start_session(service, env)
        await session.commit()
        with pytest.raises(MyPhotosRateLimited):
            await service.start_liveness(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                request=MyPhotosLivenessStartRequest(
                    challenge_mode="movement_only", idempotency_key="synthetic-competing-start"
                ),
            )
        with pytest.raises(MyPhotosConflict):
            await service.start_liveness(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                request=MyPhotosLivenessStartRequest(
                    challenge_mode="movement_and_light",
                    idempotency_key="synthetic-transition-start",
                ),
            )
        expired = await session.get(MyPhotoLivenessSessionModel, created.session_id)
        expired.created_at = datetime.now(UTC) - timedelta(minutes=10)
        expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        restarted = await service.start_liveness(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            request=MyPhotosLivenessStartRequest(
                challenge_mode="movement_only", idempotency_key="synthetic-restarted-start"
            ),
        )
        await session.commit()
        assert restarted.session_id != created.session_id and provider.created == 2
        assert (
            await session.get(MyPhotoLivenessSessionModel, created.session_id)
        ).status == "expired"
        assert (await session.scalar(select(MyPhotoEnrollmentModel))).attempt_count == 2


@pytest.mark.parametrize("failure", ["throttled", "invalid_handle"])
async def test_creation_failure_is_private_durable_and_refunds_unusable_attempt(
    photo_database, failure
):
    env = photo_database

    class Provider(SyntheticLiveness):
        async def create_session(self, request):
            if failure == "throttled":
                raise MyPhotosUnavailable("MY_PHOTOS_PROVIDER_THROTTLED", "Synthetic provider busy")
            return LivenessSessionHandle(
                "https://synthetic.invalid/private-handle", request.expires_at
            )

    async with env.sessions() as session:
        service = service_for(session, env, Provider())
        expected = MyPhotosRateLimited if failure == "throttled" else MyPhotosUnavailable
        with pytest.raises(expected):
            await start_session(service, env)
        await session.rollback()
    async with env.sessions() as session:
        enrollment = await session.scalar(select(MyPhotoEnrollmentModel))
        liveness = await session.scalar(select(MyPhotoLivenessSessionModel))
        assert enrollment.status == "ready" and enrollment.attempt_count == 0
        assert liveness.status == "failed" and liveness.consumed_at is not None
        assert liveness.provider_session_reference is None and liveness.native_launch_handle is None
        assert liveness.provider_claim_token is None and "https" not in liveness.stable_error_code
