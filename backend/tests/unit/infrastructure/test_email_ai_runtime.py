from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.config.settings import Settings
from app.domain.value_objects.email_ai_analysis import (
    ActionDisposition,
    ActionPolicyDecision,
    CandidateLink,
    DeadlineResolutionStatus,
    EmailActionProposal,
    EmailActionType,
    EmailAnalysisProviderStatus,
    EmailAnalysisRequest,
    EmailAnalysisResult,
    EmailIntent,
    EmailPriority,
    EmailRelevance,
    ReplySendState,
    ReplyTone,
    ResolvedDeadline,
    RiskLevel,
    UnsentReplyDraft,
    VisibleEmailCandidate,
)
from app.infrastructure.ai_priority.state import (
    AdmissionDecision,
    AdmissionStatus,
    AiWorkload,
    PriorityLease,
    QueueCounts,
)
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailAiRolloutPolicyModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import (
    EmailConnectionModel,
    EmailMessageModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    NotificationModel,
    UserModel,
)
from app.infrastructure.email import ai_runtime, ai_tasks
from app.infrastructure.email.ai_runtime import EmailAiClaim
from app.infrastructure.email.ai_tasks import _parse_claim


def _settings(**overrides) -> Settings:
    values = {
        "app_secret_key": "test-secret",
        "email_integrations_enabled": True,
        "email_sync_enabled": True,
        "email_ai_enabled": True,
        "email_ai_notifications_enabled": True,
        "google_api_key": "test-provider-key",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


class _PriorityCoordinator:
    def __init__(
        self,
        *,
        status: AdmissionStatus = AdmissionStatus.ADMITTED,
        reason: str = "admitted",
        retry_after_ms: int = 0,
    ) -> None:
        self.status = status
        self.reason = reason
        self.retry_after_ms = retry_after_ms
        self.started: list[str] = []
        self.released: list[PriorityLease] = []

    def try_start_verification(self, job_reference: str) -> AdmissionDecision:
        self.started.append(job_reference)
        return AdmissionDecision(
            status=self.status,
            reason=self.reason,
            lease=PriorityLease(
                workload=AiWorkload.VERIFICATION,
                job_key="fixture-priority-job",
                generation=1,
                lease_ms=30_000,
                redis_available=False,
            ),
            counts=QueueCounts(),
            retry_after_ms=self.retry_after_ms,
        )

    def release(self, lease: PriorityLease) -> bool:
        self.released.append(lease)
        return True


def test_ai_task_envelope_is_strict_and_contains_no_mail_content() -> None:
    identifiers = [uuid.uuid4() for _ in range(5)]
    claim = _parse_claim(
        analysis_id=str(identifiers[0]),
        agency_id=str(identifiers[1]),
        owner_user_id=str(identifiers[2]),
        connection_id=str(identifiers[3]),
        message_id=str(identifiers[4]),
        provider_account_id="provider-account",
        sync_generation=4,
        lease_token="a" * 32,
    )
    assert claim is not None
    assert claim.task_kwargs() == {
        "analysis_id": str(identifiers[0]),
        "agency_id": str(identifiers[1]),
        "owner_user_id": str(identifiers[2]),
        "connection_id": str(identifiers[3]),
        "message_id": str(identifiers[4]),
        "provider_account_id": "provider-account",
        "sync_generation": 4,
        "lease_token": "a" * 32,
    }
    assert _parse_claim(
        analysis_id=str(identifiers[0]),
        agency_id=str(identifiers[1]),
        owner_user_id=str(identifiers[2]),
        connection_id=str(identifiers[3]),
        message_id=str(identifiers[4]),
        provider_account_id="provider-account",
        sync_generation=4,
        lease_token="forged",
    ) is None


def test_canonical_links_fail_closed_for_multiple_groups_or_duplicate_names() -> None:
    first_group = uuid.uuid4()
    second_group = uuid.uuid4()
    first_passenger = uuid.uuid4()
    second_passenger = uuid.uuid4()
    request = EmailAnalysisRequest(
        subject="Ambiguous matches",
        body_text="Alex Kim is listed for two possible groups.",
        received_at=datetime.now(tz=UTC),
        timezone="UTC",
        visible_candidates=[
            VisibleEmailCandidate(
                alias="group_1",
                entity_type="group",
                safe_facts=["name: Group One"],
            ),
            VisibleEmailCandidate(
                alias="group_2",
                entity_type="group",
                safe_facts=["name: Group Two"],
            ),
            VisibleEmailCandidate(
                alias="passenger_1",
                entity_type="passenger",
                safe_facts=["name: Alex Kim"],
            ),
            VisibleEmailCandidate(
                alias="passenger_2",
                entity_type="passenger",
                safe_facts=["name: Alex Kim"],
            ),
        ],
    )
    context = SimpleNamespace(
        aliases={
            "group_1": ("group", first_group),
            "group_2": ("group", second_group),
            "passenger_1": ("passenger", first_passenger),
            "passenger_2": ("passenger", second_passenger),
        },
        request=request,
    )
    result = EmailAnalysisResult(
        provider_status=EmailAnalysisProviderStatus.ANALYZED,
        model="configured-test-model",
        relevance=EmailRelevance.RELEVANT,
        intent=EmailIntent.ITINERARY_UPDATE,
        priority=EmailPriority.NORMAL,
        confidence=0.96,
        summary="Multiple candidates require review.",
        candidate_links=[
            CandidateLink(
                alias="group_1",
                confidence=0.96,
                rationale="The first group might match.",
            ),
            CandidateLink(
                alias="group_2",
                confidence=0.96,
                rationale="The second group might match.",
            ),
            CandidateLink(
                alias="passenger_1",
                confidence=0.96,
                rationale="The first same-name passenger might match.",
            ),
            CandidateLink(
                alias="passenger_2",
                confidence=0.96,
                rationale="The second same-name passenger might match.",
            ),
        ],
        needs_review=True,
    )

    assert ai_runtime._canonical_link_ids(
        context=context,  # type: ignore[arg-type]
        result=result,
        confidence_threshold=0.9,
    ) == (None, [])


def test_canonical_links_require_confidence_and_matching_passenger_parent() -> None:
    first_group = uuid.uuid4()
    second_group = uuid.uuid4()
    passenger_id = uuid.uuid4()
    request = EmailAnalysisRequest(
        subject="Candidate integrity",
        body_text="One passenger belongs to the first group.",
        received_at=datetime.now(tz=UTC),
        timezone="UTC",
        visible_candidates=[
            VisibleEmailCandidate(
                alias="group_1",
                entity_type="group",
                safe_facts=["name: Group One"],
            ),
            VisibleEmailCandidate(
                alias="group_2",
                entity_type="group",
                safe_facts=["name: Group Two"],
            ),
            VisibleEmailCandidate(
                alias="passenger_1",
                entity_type="passenger",
                safe_facts=[
                    "name: Taylor Lee",
                    "group alias: group_1",
                ],
            ),
        ],
    )
    context = SimpleNamespace(
        aliases={
            "group_1": ("group", first_group),
            "group_2": ("group", second_group),
            "passenger_1": ("passenger", passenger_id),
        },
        request=request,
    )

    mismatched = EmailAnalysisResult(
        provider_status=EmailAnalysisProviderStatus.ANALYZED,
        model="configured-test-model",
        relevance=EmailRelevance.RELEVANT,
        intent=EmailIntent.ITINERARY_UPDATE,
        priority=EmailPriority.NORMAL,
        confidence=0.95,
        summary="A mismatched parent requires review.",
        candidate_links=[
            CandidateLink(
                alias="group_2",
                confidence=0.95,
                rationale="The second group name appears.",
            ),
            CandidateLink(
                alias="passenger_1",
                confidence=0.95,
                rationale="The passenger name appears.",
            ),
        ],
        needs_review=True,
    )
    assert ai_runtime._canonical_link_ids(
        context=context,  # type: ignore[arg-type]
        result=mismatched,
        confidence_threshold=0.9,
    ) == (second_group, [])
    assert ai_runtime._candidate_links_are_ambiguous(
        context=context,  # type: ignore[arg-type]
        result=mismatched,
    )

    low_confidence = mismatched.model_copy(
        update={
            "candidate_links": [
                CandidateLink(
                    alias="group_1",
                    confidence=0.01,
                    rationale="The match is speculative.",
                ),
                CandidateLink(
                    alias="passenger_1",
                    confidence=0.01,
                    rationale="The passenger match is speculative.",
                ),
            ],
        }
    )
    assert ai_runtime._canonical_link_ids(
        context=context,  # type: ignore[arg-type]
        result=low_confidence,
        confidence_threshold=0.9,
    ) == (None, [])

    passenger_only = mismatched.model_copy(
        update={
            "candidate_links": [
                CandidateLink(
                    alias="passenger_1",
                    confidence=0.95,
                    rationale="The passenger match is deterministic.",
                )
            ],
        }
    )
    assert ai_runtime._canonical_link_ids(
        context=context,  # type: ignore[arg-type]
        result=passenger_only,
        confidence_threshold=0.9,
    ) == (first_group, [str(passenger_id)])


def test_dispatch_publish_failure_releases_the_exact_claim(monkeypatch) -> None:
    claim = EmailAiClaim(
        analysis_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        provider_account_id="provider-account",
        sync_generation=4,
        lease_token="e" * 32,
    )
    released: list[EmailAiClaim] = []

    async def seed() -> list[EmailAiClaim]:
        return [claim]

    async def release(item: EmailAiClaim) -> None:
        released.append(item)

    def fail_publish(**_kwargs) -> None:
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(ai_tasks, "seed_and_claim_email_ai_work", seed)
    monkeypatch.setattr(
        ai_tasks,
        "release_email_ai_claim_after_publish_failure",
        release,
    )
    monkeypatch.setattr(ai_tasks.celery_async_runtime, "run", asyncio.run)
    monkeypatch.setattr(ai_tasks.analyze_travel_email, "apply_async", fail_publish)

    assert ai_tasks.dispatch_email_ai_analyses.run() == 0
    assert released == [claim]


@pytest.mark.asyncio
async def test_broker_publish_failure_never_consumes_provider_attempts(
    monkeypatch,
) -> None:
    claim = EmailAiClaim(
        analysis_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        provider_account_id="provider-account",
        sync_generation=4,
        lease_token="f" * 32,
    )
    analysis = SimpleNamespace(
        status="processing",
        attempt_count=3,
        last_error_code=None,
        lease_token=claim.lease_token,
        lease_expires_at=datetime.now(tz=UTC),
        next_attempt_at=None,
        started_at=datetime.now(tz=UTC),
        completed_at=None,
    )
    session = AsyncMock()

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(ai_runtime, "AsyncSessionFactory", lambda: SessionContext())
    monkeypatch.setattr(
        ai_runtime,
        "_load_valid_claim",
        AsyncMock(
            return_value=(
                analysis,
                SimpleNamespace(),
                SimpleNamespace(),
            )
        ),
    )

    await ai_runtime.release_email_ai_claim_after_publish_failure(claim)
    assert analysis.status == "pending"
    assert analysis.attempt_count == 2
    assert analysis.last_error_code == "broker_publish_failed"
    assert analysis.lease_token is None
    assert analysis.next_attempt_at is not None

    analysis.status = "processing"
    analysis.lease_token = claim.lease_token
    analysis.lease_expires_at = datetime.now(tz=UTC)
    await ai_runtime.release_email_ai_claim_after_publish_failure(claim)
    assert analysis.attempt_count == 1
    assert analysis.status == "pending"
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_disabled_global_ai_switch_does_not_open_a_database_session(
    monkeypatch,
) -> None:
    class FailingSessionFactory:
        def __call__(self):
            raise AssertionError("AI disabled must not touch the database")

    monkeypatch.setattr(ai_runtime, "AsyncSessionFactory", FailingSessionFactory())
    assert (
        await ai_runtime.seed_and_claim_email_ai_work(
            _settings(email_ai_enabled=False)
        )
        == []
    )


@pytest.mark.asyncio
async def test_disabled_rollout_rows_cannot_starve_later_enabled_owner(
    db_session,
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    base_time = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)
    disabled_owner_ids: list[uuid.UUID] = []
    for index in range(50):
        owner_id = uuid.uuid4()
        disabled_owner_ids.append(owner_id)
        db_session.add(
            UserModel(
                id=owner_id,
                email=f"disabled-{index}@example.test",
                hashed_password="not-used",
                full_name=f"Disabled Owner {index}",
                role="agency_staff",
                agency_id=agency_id,
                is_active=True,
            )
        )
        connection = EmailConnectionModel(
            agency_id=agency_id,
            owner_user_id=owner_id,
            provider="gmail",
            provider_account_id=f"provider-disabled-{index}",
            email_address=f"disabled-{index}@example.test",
            status="active",
            ai_processing_enabled=True,
            ai_enabled_at=base_time - timedelta(seconds=1),
            created_by_user_id=owner_id,
        )
        db_session.add(connection)
        await db_session.flush()
        db_session.add(
            EmailMessageModel(
                agency_id=agency_id,
                owner_user_id=owner_id,
                connection_id=connection.id,
                provider_message_id=f"disabled-message-{index}",
                sender_address="supplier@example.test",
                subject="Older relevant message",
                body_excerpt="Please confirm.",
                received_at=base_time + timedelta(seconds=index),
                relevance_status="relevant",
                processing_status="completed",
            )
        )
        db_session.add(
            EmailAiRolloutPolicyModel(
                agency_id=agency_id,
                owner_user_id=owner_id,
                scope_type="user",
                enabled=False,
                updated_by_user_id=owner_id,
            )
        )

    enabled_owner_id = uuid.uuid4()
    db_session.add(
        UserModel(
            id=enabled_owner_id,
            email="enabled-owner@example.test",
            hashed_password="not-used",
            full_name="Enabled Owner",
            role="agency_staff",
            agency_id=agency_id,
            is_active=True,
        )
    )
    enabled_connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=enabled_owner_id,
        provider="outlook",
        provider_account_id="provider-enabled",
        email_address="enabled-owner@example.test",
        status="active",
        ai_processing_enabled=True,
        ai_enabled_at=base_time - timedelta(seconds=1),
        created_by_user_id=enabled_owner_id,
    )
    db_session.add(enabled_connection)
    await db_session.flush()
    db_session.add(
        EmailMessageModel(
            agency_id=agency_id,
            owner_user_id=enabled_owner_id,
            connection_id=enabled_connection.id,
            provider_message_id="enabled-message",
            sender_address="supplier@example.test",
            subject="Later relevant message",
            body_excerpt="Please confirm tomorrow.",
            received_at=base_time + timedelta(minutes=2),
            relevance_status="relevant",
            processing_status="completed",
        )
    )
    await db_session.flush()

    class SharedSessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(
        ai_runtime,
        "AsyncSessionFactory",
        lambda: SharedSessionContext(),
    )

    claims = await ai_runtime.seed_and_claim_email_ai_work(_settings())

    assert [claim.owner_user_id for claim in claims] == [enabled_owner_id]
    analyses = (
        await db_session.execute(select(EmailAiAnalysisModel))
    ).scalars().all()
    assert [analysis.owner_user_id for analysis in analyses] == [enabled_owner_id]
    assert not set(disabled_owner_ids).intersection(
        analysis.owner_user_id for analysis in analyses
    )


@pytest.mark.asyncio
async def test_opt_in_watermark_and_per_owner_batching_prioritize_new_mail_fairly(
    db_session,
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    watermark = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)
    owner_ids = [uuid.uuid4(), uuid.uuid4()]
    connections = []
    for index, owner_id in enumerate(owner_ids):
        db_session.add(
            UserModel(
                id=owner_id,
                email=f"fair-owner-{index}@example.test",
                hashed_password="not-used",
                full_name=f"Fair Owner {index}",
                role="agency_staff",
                agency_id=agency_id,
                is_active=True,
            )
        )
        connection = EmailConnectionModel(
            agency_id=agency_id,
            owner_user_id=owner_id,
            provider="gmail",
            provider_account_id=f"fair-provider-{index}",
            email_address=f"fair-owner-{index}@example.test",
            status="active",
            ai_processing_enabled=True,
            ai_enabled_at=watermark,
            created_by_user_id=owner_id,
        )
        db_session.add(connection)
        await db_session.flush()
        connections.append(connection)

    for index in range(5):
        db_session.add(
            EmailMessageModel(
                agency_id=agency_id,
                owner_user_id=owner_ids[0],
                connection_id=connections[0].id,
                provider_message_id=f"busy-owner-message-{index}",
                sender_address="supplier@example.test",
                subject="New operational mail",
                body_excerpt="Please confirm.",
                received_at=watermark + timedelta(minutes=index + 1),
                relevance_status="relevant",
                processing_status="completed",
            )
        )
    db_session.add_all(
        [
            EmailMessageModel(
                agency_id=agency_id,
                owner_user_id=owner_ids[1],
                connection_id=connections[1].id,
                provider_message_id="quiet-owner-new",
                sender_address="supplier@example.test",
                subject="New operational mail",
                body_excerpt="Please confirm.",
                received_at=watermark + timedelta(minutes=1),
                relevance_status="relevant",
                processing_status="completed",
            ),
            EmailMessageModel(
                agency_id=agency_id,
                owner_user_id=owner_ids[1],
                connection_id=connections[1].id,
                provider_message_id="quiet-owner-prefiltered-ignored",
                sender_address="marketing@example.test",
                subject="Possibly irrelevant marketing",
                body_excerpt="The AI must still classify this post-opt-in message.",
                received_at=watermark + timedelta(minutes=2),
                relevance_status="ignored",
                processing_status="ignored",
            ),
            EmailMessageModel(
                agency_id=agency_id,
                owner_user_id=owner_ids[1],
                connection_id=connections[1].id,
                provider_message_id="quiet-owner-history",
                sender_address="supplier@example.test",
                subject="Historical mail",
                body_excerpt="Do not backfill.",
                received_at=watermark - timedelta(seconds=1),
                relevance_status="relevant",
                processing_status="completed",
            ),
        ]
    )
    await db_session.flush()

    class SharedSessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(
        ai_runtime,
        "AsyncSessionFactory",
        lambda: SharedSessionContext(),
    )

    claims = await ai_runtime.seed_and_claim_email_ai_work(
        _settings(email_ai_max_inflight=4)
    )
    claim_owner_ids = [claim.owner_user_id for claim in claims]
    assert claim_owner_ids.count(owner_ids[0]) == 2
    assert claim_owner_ids.count(owner_ids[1]) == 2
    analyzed_message_ids = set(
        (
            await db_session.execute(
                select(EmailMessageModel.provider_message_id)
                .join(
                    EmailAiAnalysisModel,
                    EmailAiAnalysisModel.message_id == EmailMessageModel.id,
                )
            )
        ).scalars()
    )
    assert "quiet-owner-new" in analyzed_message_ids
    assert "quiet-owner-prefiltered-ignored" in analyzed_message_ids
    assert "quiet-owner-history" not in analyzed_message_ids


@pytest.mark.asyncio
async def test_seeding_pairs_newest_mail_with_starved_oldest_backlog(
    db_session,
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    db_session.add(
        UserModel(
            id=owner_id,
            email="backlog-owner@example.test",
            hashed_password="not-used",
            full_name="Backlog Owner",
            role="agency_staff",
            agency_id=agency_id,
            is_active=True,
        )
    )
    connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="gmail",
        provider_account_id="backlog-provider",
        email_address="backlog-owner@example.test",
        status="active",
        ai_processing_enabled=True,
        ai_enabled_at=now - timedelta(hours=2),
        created_by_user_id=owner_id,
    )
    db_session.add(connection)
    await db_session.flush()
    for provider_id, received_at in (
        ("starved-oldest", now - timedelta(hours=1)),
        ("starved-middle", now - timedelta(minutes=40)),
        ("recent-middle", now - timedelta(minutes=2)),
        ("newest-arrival", now - timedelta(seconds=5)),
    ):
        db_session.add(
            EmailMessageModel(
                agency_id=agency_id,
                owner_user_id=owner_id,
                connection_id=connection.id,
                provider_message_id=provider_id,
                sender_address="supplier@example.test",
                subject="Operational update",
                body_excerpt="Please review.",
                received_at=received_at,
                relevance_status="relevant",
                processing_status="completed",
            )
        )
    await db_session.flush()

    class SharedSessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(
        ai_runtime,
        "AsyncSessionFactory",
        lambda: SharedSessionContext(),
    )
    claims = await ai_runtime.seed_and_claim_email_ai_work(
        _settings(email_ai_max_inflight=2)
    )
    claimed_provider_ids = set(
        (
            await db_session.execute(
                select(EmailMessageModel.provider_message_id).where(
                    EmailMessageModel.id.in_(
                        [claim.message_id for claim in claims]
                    )
                )
            )
        ).scalars()
    )
    assert claimed_provider_ids == {"newest-arrival", "starved-oldest"}


@pytest.mark.asyncio
async def test_starved_work_outranks_fresh_mail_under_global_saturation(
    db_session,
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    for index in range(3):
        owner_id = uuid.uuid4()
        db_session.add(
            UserModel(
                id=owner_id,
                email=f"saturated-owner-{index}@example.test",
                hashed_password="not-used",
                full_name=f"Saturated Owner {index}",
                role="agency_staff",
                agency_id=agency_id,
                is_active=True,
            )
        )
        connection = EmailConnectionModel(
            agency_id=agency_id,
            owner_user_id=owner_id,
            provider="gmail",
            provider_account_id=f"saturated-provider-{index}",
            email_address=f"saturated-owner-{index}@example.test",
            status="active",
            ai_processing_enabled=True,
            ai_enabled_at=now - timedelta(hours=3),
            created_by_user_id=owner_id,
        )
        db_session.add(connection)
        await db_session.flush()
        db_session.add_all(
            [
                EmailMessageModel(
                    agency_id=agency_id,
                    owner_user_id=owner_id,
                    connection_id=connection.id,
                    provider_message_id=f"starved-owner-{index}",
                    sender_address="supplier@example.test",
                    subject="Old pending operation",
                    body_excerpt="This work must not starve.",
                    received_at=now
                    - timedelta(minutes=90 - index * 10),
                    relevance_status="relevant",
                    processing_status="completed",
                ),
                EmailMessageModel(
                    agency_id=agency_id,
                    owner_user_id=owner_id,
                    connection_id=connection.id,
                    provider_message_id=f"fresh-owner-{index}",
                    sender_address="supplier@example.test",
                    subject="Fresh operation",
                    body_excerpt="A newer email arrived.",
                    received_at=now - timedelta(seconds=index + 1),
                    relevance_status="relevant",
                    processing_status="completed",
                ),
            ]
        )
    await db_session.flush()

    class SharedSessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(
        ai_runtime,
        "AsyncSessionFactory",
        lambda: SharedSessionContext(),
    )
    claims = await ai_runtime.seed_and_claim_email_ai_work(
        _settings(email_ai_max_inflight=2)
    )
    claimed_provider_ids = set(
        (
            await db_session.execute(
                select(EmailMessageModel.provider_message_id).where(
                    EmailMessageModel.id.in_(
                        [claim.message_id for claim in claims]
                    )
                )
            )
        ).scalars()
    )
    assert claimed_provider_ids == {"starved-owner-0", "starved-owner-1"}


@pytest.mark.asyncio
async def test_seeding_distinguishes_body_processing_failure_from_ai_exclusions(
    db_session,
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    db_session.add(
        UserModel(
            id=owner_id,
            email="eligibility-owner@example.test",
            hashed_password="not-used",
            full_name="Eligibility Owner",
            role="agency_staff",
            agency_id=agency_id,
            is_active=True,
        )
    )
    connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="outlook",
        provider_account_id="eligibility-provider",
        email_address="eligibility-owner@example.test",
        status="active",
        ai_processing_enabled=True,
        ai_enabled_at=now - timedelta(hours=1),
        created_by_user_id=owner_id,
    )
    db_session.add(connection)
    await db_session.flush()
    messages = [
        EmailMessageModel(
            agency_id=agency_id,
            owner_user_id=owner_id,
            connection_id=connection.id,
            provider_message_id="attachment-processing-inflight",
            sender_address="supplier@example.test",
            subject="Attachment processing is still running",
            body_excerpt="Wait for the existing document pipeline to settle.",
            received_at=now - timedelta(minutes=5),
            relevance_status="relevant",
            processing_status="processing",
        ),
        EmailMessageModel(
            agency_id=agency_id,
            owner_user_id=owner_id,
            connection_id=connection.id,
            provider_message_id="body-processing-failed",
            sender_address="supplier@example.test",
            subject="Readable body remains eligible",
            body_excerpt="The body can still be classified.",
            received_at=now - timedelta(minutes=4),
            relevance_status="relevant",
            processing_status="failed",
        ),
        EmailMessageModel(
            agency_id=agency_id,
            owner_user_id=owner_id,
            connection_id=connection.id,
            provider_message_id="heuristic-ignored",
            sender_address="supplier@example.test",
            subject="Heuristic uncertainty",
            body_excerpt="Gemini must make the final relevance decision.",
            received_at=now - timedelta(minutes=3),
            relevance_status="ignored",
            processing_status="ignored",
        ),
        EmailMessageModel(
            agency_id=agency_id,
            owner_user_id=owner_id,
            connection_id=connection.id,
            provider_message_id="relevance-failed",
            sender_address="supplier@example.test",
            subject="No safe relevance input",
            body_excerpt="Excluded.",
            received_at=now - timedelta(minutes=2),
            relevance_status="failed",
            processing_status="completed",
        ),
        EmailMessageModel(
            agency_id=agency_id,
            owner_user_id=owner_id,
            connection_id=connection.id,
            provider_message_id="human-unrelated",
            sender_address="supplier@example.test",
            subject="Owner marked unrelated",
            body_excerpt="Excluded even if otherwise readable.",
            received_at=now - timedelta(minutes=1),
            relevance_status="ignored",
            processing_status="ignored",
            evidence_json={"human_marked_unrelated": True},
        ),
    ]
    db_session.add_all(messages)
    await db_session.flush()

    class SharedSessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(
        ai_runtime,
        "AsyncSessionFactory",
        lambda: SharedSessionContext(),
    )
    claims = await ai_runtime.seed_and_claim_email_ai_work(
        _settings(email_ai_max_inflight=4)
    )
    claimed_provider_ids = set(
        (
            await db_session.execute(
                select(EmailMessageModel.provider_message_id).where(
                    EmailMessageModel.id.in_(
                        [claim.message_id for claim in claims]
                    )
                )
            )
        ).scalars()
    )
    assert claimed_provider_ids == {
        "body-processing-failed",
        "heuristic-ignored",
    }
    analyses = list(
        (
            await db_session.execute(
                select(EmailAiAnalysisModel)
                .join(
                    EmailMessageModel,
                    EmailMessageModel.id
                    == EmailAiAnalysisModel.message_id,
                )
                .where(
                    EmailMessageModel.provider_message_id
                    == "attachment-processing-inflight"
                )
            )
        ).scalars()
    )
    assert analyses == []


@pytest.mark.asyncio
async def test_claim_persists_auditable_proposal_draft_and_owner_notification(
    db_session,
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    db_session.add(
        AgencyModel(
            id=agency_id,
            name="Owner Runtime Agency",
            email="owner-runtime-agency@example.test",
            is_active=True,
        )
    )
    owner = UserModel(
        id=owner_id,
        email="owner@example.test",
        hashed_password="not-used",
        full_name="Owner",
        role="agency_staff",
        agency_id=agency_id,
        is_active=True,
    )
    db_session.add(owner)
    connection = EmailConnectionModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        provider="gmail",
        provider_account_id="provider-owner",
        email_address="owner@example.test",
        status="active",
        ai_processing_enabled=True,
        ai_enabled_at=datetime.now(tz=UTC) - timedelta(minutes=5),
        created_by_user_id=owner_id,
    )
    db_session.add(connection)
    await db_session.flush()
    linked_group = ClientGroupModel(
        agency_id=agency_id,
        name="Owner Runtime Group",
        token=f"owner-runtime-{uuid.uuid4().hex}",
        status="active",
        created_by_user_id=owner_id,
    )
    db_session.add(linked_group)
    await db_session.flush()
    message = EmailMessageModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        provider_message_id="message-1",
        sender_address="supplier@example.test",
        sender_name="Example Supplier",
        recipients_json=[
            {"address": "owner@example.test", "display_name": "Owner"}
        ],
        subject="Arrival details",
        body_excerpt="Please confirm the arrival details tomorrow.",
        received_at=datetime.now(tz=UTC),
        relevance_status="relevant",
        processing_status="completed",
        group_id=linked_group.id,
    )
    db_session.add(message)
    await db_session.flush()
    lease_token = "b" * 32
    analysis = EmailAiAnalysisModel(
        agency_id=agency_id,
        owner_user_id=owner_id,
        connection_id=connection.id,
        message_id=message.id,
        status="processing",
        input_hash="c" * 64,
        prompt_schema_version=ai_runtime.EMAIL_AI_SCHEMA_VERSION,
        config_version="v1",
        ai_model="configured-test-model",
        attempt_count=1,
        lease_token=lease_token,
        lease_expires_at=datetime.now(tz=UTC) + timedelta(minutes=2),
    )
    db_session.add(analysis)
    await db_session.flush()

    duplicate_proposal = EmailActionProposal(
        action=EmailActionType.PREPARE_REPLY_DRAFT,
        rationale="A concise confirmation is useful.",
        confidence=0.94,
    )
    duplicate_decision = ActionPolicyDecision(
        action=EmailActionType.PREPARE_REPLY_DRAFT.value,
        disposition=ActionDisposition.PROPOSAL_ONLY,
        risk_level=RiskLevel.LOW,
        reason_code="proposal_recording_allowed",
    )
    duplicate_deadline = ResolvedDeadline(
        source_text="Please confirm tomorrow.",
        expression="tomorrow",
        confidence=0.94,
        status=DeadlineResolutionStatus.RESOLVED,
        due_at=datetime.now(tz=UTC) + timedelta(days=1),
        reason_code="relative_day_resolved",
    )
    result = EmailAnalysisResult(
        provider_status=EmailAnalysisProviderStatus.ANALYZED,
        model="configured-test-model",
        relevance=EmailRelevance.RELEVANT,
        intent=EmailIntent.INFORMATION_REQUEST,
        priority=EmailPriority.HIGH,
        confidence=0.96,
        summary="Arrival details need a reply.",
        deadlines=[duplicate_deadline, duplicate_deadline],
        proposals=[duplicate_proposal, duplicate_proposal],
        action_decisions=[duplicate_decision, duplicate_decision],
        reply_draft=UnsentReplyDraft(
            subject="Re: Arrival details",
            body="Thank you. We are confirming the arrival details and will reply shortly.",
            tone=ReplyTone.PROFESSIONAL,
            send_state=ReplySendState.UNSENT,
        ),
        candidate_links=[
            CandidateLink(
                alias="group_001",
                confidence=0.98,
                rationale="The authorized group is explicitly linked.",
            )
        ],
        needs_review=False,
    )

    captured_requests = []

    class FakeAnalysisService:
        def __init__(self, **_kwargs) -> None:
            pass

        async def analyze(self, request):
            captured_requests.append(request)
            return result

    class SharedSessionContext:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(
        ai_runtime,
        "AsyncSessionFactory",
        lambda: SharedSessionContext(),
    )
    monkeypatch.setattr(
        ai_runtime,
        "GeminiEmailAnalysisService",
        FakeAnalysisService,
    )
    priority = _PriorityCoordinator()
    await ai_runtime.run_email_ai_claim(
        EmailAiClaim(
            analysis_id=analysis.id,
            agency_id=agency_id,
            owner_user_id=owner_id,
            connection_id=connection.id,
            message_id=message.id,
            provider_account_id=connection.provider_account_id,
            sync_generation=connection.sync_generation,
            lease_token=lease_token,
        ),
        settings=_settings(
            gemini_model="configured-test-model",
            email_ai_default_timezone="UTC",
        ),
        priority_coordinator=priority,  # type: ignore[arg-type]
    )

    await db_session.refresh(analysis)
    assert analysis.status == "completed"
    assert analysis.ai_model == "configured-test-model"
    assert analysis.confidence == pytest.approx(0.96)
    assert analysis.lease_token is None
    assert captured_requests[0].sender_display_name == "Example Supplier"
    assert captured_requests[0].sender_domain == "example.test"
    assert captured_requests[0].recipient_domains == ["example.test"]
    assert captured_requests[0].connected_account_domain == "example.test"
    assert priority.started == [f"email-ai:{analysis.id}"]
    assert len(priority.released) == 1

    proposal = (
        await db_session.execute(
            select(EmailActionProposalModel).where(
                EmailActionProposalModel.analysis_id == analysis.id
            )
        )
    ).scalar_one()
    assert proposal.status == "approval_required"
    assert proposal.action_type == "prepare_reply_draft"
    deadlines = (
        await db_session.execute(
            select(EmailDetectedDeadlineModel).where(
                EmailDetectedDeadlineModel.analysis_id == analysis.id
            )
        )
    ).scalars().all()
    assert len(deadlines) == 1

    draft = (
        await db_session.execute(
            select(EmailReplyDraftModel).where(
                EmailReplyDraftModel.analysis_id == analysis.id
            )
        )
    ).scalar_one()
    assert draft.status == "prepared"
    assert draft.recipients_json == ["supplier@example.test"]

    notification = (
        await db_session.execute(
            select(NotificationModel).where(
                NotificationModel.user_id == owner_id
            )
        )
    ).scalar_one()
    assert notification.category == "email_operations"
    assert notification.entity_id == str(message.id)
    assert notification.metadata_json["proposal_count"] == 1
    assert notification.metadata_json["deadline_count"] == 1
    assert notification.metadata_json["provider"] == "gmail"
    assert notification.metadata_json["account_email"] == (
        "owner@example.test"
    )
    assert notification.metadata_json["group_name"] == (
        "Owner Runtime Group"
    )


@pytest.mark.asyncio
async def test_priority_deferral_prevents_provider_call_and_releases_claim(
    monkeypatch,
) -> None:
    claim = EmailAiClaim(
        analysis_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        provider_account_id="provider-account",
        sync_generation=1,
        lease_token="e" * 32,
    )
    analysis = SimpleNamespace(input_hash=None, context_manifest={})
    message = SimpleNamespace()
    connection = SimpleNamespace(email_address="owner@example.test")
    session = AsyncMock()

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            return False

    context = SimpleNamespace(
        input_hash="f" * 64,
        manifest={"candidate_count": 0},
        request=object(),
    )
    deferred = AsyncMock()
    monkeypatch.setattr(ai_runtime, "AsyncSessionFactory", lambda: SessionContext())
    monkeypatch.setattr(
        ai_runtime,
        "_load_valid_claim",
        AsyncMock(return_value=(analysis, message, connection)),
    )
    monkeypatch.setattr(
        ai_runtime,
        "email_ai_policy_allows",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        ai_runtime,
        "load_email_ai_context",
        AsyncMock(return_value=context),
    )
    monkeypatch.setattr(ai_runtime, "_defer_for_ai_priority", deferred)
    monkeypatch.setattr(
        ai_runtime,
        "GeminiEmailAnalysisService",
        lambda **_kwargs: pytest.fail("provider must not run before admission"),
    )

    await ai_runtime.run_email_ai_claim(
        claim,
        settings=_settings(),
        priority_coordinator=_PriorityCoordinator(
            status=AdmissionStatus.DEFERRED,
            reason="deferred_extraction_priority",
            retry_after_ms=2_500,
        ),  # type: ignore[arg-type]
    )

    deferred.assert_awaited_once_with(claim, retry_after_ms=2_500)
    assert analysis.input_hash == context.input_hash
    assert analysis.context_manifest == context.manifest
    session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_rollout_pause_before_provider_restores_attempt_without_provider_call(
    monkeypatch,
) -> None:
    claim = EmailAiClaim(
        analysis_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        provider_account_id="provider-account",
        sync_generation=1,
        lease_token="f" * 32,
    )
    analysis = SimpleNamespace(
        status="processing",
        attempt_count=2,
        last_error_code=None,
        needs_attention=True,
        lease_token=claim.lease_token,
        lease_expires_at=datetime.now(tz=UTC) + timedelta(minutes=2),
        next_attempt_at=datetime.now(tz=UTC),
        started_at=datetime.now(tz=UTC),
        completed_at=datetime.now(tz=UTC),
    )
    row = (analysis, SimpleNamespace(), SimpleNamespace())
    session = AsyncMock()

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(ai_runtime, "AsyncSessionFactory", lambda: SessionContext())
    monkeypatch.setattr(
        ai_runtime,
        "_load_valid_claim",
        AsyncMock(return_value=row),
    )
    monkeypatch.setattr(
        ai_runtime,
        "email_ai_policy_allows",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        ai_runtime,
        "GeminiEmailAnalysisService",
        lambda **_kwargs: pytest.fail("provider must not run while rollout is paused"),
    )

    await ai_runtime.run_email_ai_claim(
        claim,
        settings=_settings(),
        priority_coordinator=_PriorityCoordinator(),  # type: ignore[arg-type]
    )

    assert analysis.status == "pending"
    assert analysis.attempt_count == 1
    assert analysis.last_error_code == "rollout_policy_disabled"
    assert analysis.needs_attention is False
    assert analysis.lease_token is None
    assert analysis.lease_expires_at is None
    assert analysis.next_attempt_at is None
    assert analysis.started_at is None
    assert analysis.completed_at is None
    session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_rollout_pause_during_provider_discards_result_and_restores_attempt(
    monkeypatch,
) -> None:
    claim = EmailAiClaim(
        analysis_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        provider_account_id="provider-account",
        sync_generation=1,
        lease_token="9" * 32,
    )
    analysis = SimpleNamespace(
        input_hash="0" * 64,
        context_manifest={},
        status="processing",
        attempt_count=2,
        last_error_code=None,
        needs_attention=True,
        lease_token=claim.lease_token,
        lease_expires_at=datetime.now(tz=UTC) + timedelta(minutes=2),
        next_attempt_at=datetime.now(tz=UTC),
        started_at=datetime.now(tz=UTC),
        completed_at=datetime.now(tz=UTC),
    )
    message = SimpleNamespace()
    connection = SimpleNamespace(email_address="owner@example.test")
    session = AsyncMock()

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            return False

    context = SimpleNamespace(
        input_hash="1" * 64,
        manifest={"candidate_count": 0},
        request=object(),
    )
    result = EmailAnalysisResult(
        provider_status=EmailAnalysisProviderStatus.ANALYZED,
        model="configured-test-model",
        relevance=EmailRelevance.RELEVANT,
        intent=EmailIntent.INFORMATION_REQUEST,
        priority=EmailPriority.NORMAL,
        confidence=0.95,
        summary="This result must be discarded after the rollout pause.",
        needs_review=False,
    )
    provider_calls = 0

    class FakeAnalysisService:
        def __init__(self, **_kwargs) -> None:
            pass

        async def analyze(self, request):
            nonlocal provider_calls
            assert request is context.request
            provider_calls += 1
            return result

    policy_check = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(ai_runtime, "AsyncSessionFactory", lambda: SessionContext())
    monkeypatch.setattr(
        ai_runtime,
        "_load_valid_claim",
        AsyncMock(return_value=(analysis, message, connection)),
    )
    monkeypatch.setattr(ai_runtime, "email_ai_policy_allows", policy_check)
    monkeypatch.setattr(
        ai_runtime,
        "load_email_ai_context",
        AsyncMock(return_value=context),
    )
    monkeypatch.setattr(
        ai_runtime,
        "GeminiEmailAnalysisService",
        FakeAnalysisService,
    )

    await ai_runtime.run_email_ai_claim(
        claim,
        settings=_settings(gemini_model="configured-test-model"),
        priority_coordinator=_PriorityCoordinator(),  # type: ignore[arg-type]
    )

    assert provider_calls == 1
    assert policy_check.await_count == 2
    assert analysis.status == "pending"
    assert analysis.attempt_count == 1
    assert analysis.last_error_code == "rollout_policy_disabled_during_analysis"
    assert analysis.needs_attention is False
    assert analysis.lease_token is None
    assert analysis.lease_expires_at is None
    assert analysis.next_attempt_at is None
    assert analysis.started_at is None
    assert analysis.completed_at is None
    session.add.assert_not_called()
    assert session.commit.await_count == 2


@pytest.mark.asyncio
async def test_priority_deferral_does_not_consume_analysis_attempt(
    monkeypatch,
) -> None:
    claim = EmailAiClaim(
        analysis_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        provider_account_id="provider-account",
        sync_generation=1,
        lease_token="a" * 32,
    )
    analysis = SimpleNamespace(
        status="processing",
        attempt_count=2,
        last_error_code=None,
        lease_token=claim.lease_token,
        lease_expires_at=datetime.now(tz=UTC),
        next_attempt_at=None,
        started_at=datetime.now(tz=UTC),
        completed_at=datetime.now(tz=UTC),
    )
    session = AsyncMock()

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(ai_runtime, "AsyncSessionFactory", lambda: SessionContext())
    monkeypatch.setattr(
        ai_runtime,
        "_load_valid_claim",
        AsyncMock(return_value=(analysis, SimpleNamespace(), SimpleNamespace())),
    )

    before = datetime.now(tz=UTC)
    await ai_runtime._defer_for_ai_priority(claim, retry_after_ms=2_500)

    assert analysis.status == "pending"
    assert analysis.attempt_count == 1
    assert analysis.last_error_code == "ai_priority_admission_deferred"
    assert analysis.lease_token is None
    assert analysis.lease_expires_at is None
    assert analysis.started_at is None
    assert analysis.completed_at is None
    assert analysis.next_attempt_at is not None
    assert analysis.next_attempt_at >= before + timedelta(seconds=3)
    session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_persistent_unexpected_failure_notifies_only_the_claim_owner(
    monkeypatch,
) -> None:
    claim = EmailAiClaim(
        analysis_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        provider_account_id="provider-account",
        sync_generation=2,
        lease_token="d" * 32,
    )
    analysis = SimpleNamespace(
        id=claim.analysis_id,
        agency_id=claim.agency_id,
        owner_user_id=claim.owner_user_id,
        attempt_count=3,
        status="processing",
        needs_attention=False,
        completed_at=None,
        next_attempt_at=None,
        last_error_code=None,
        lease_token=claim.lease_token,
        lease_expires_at=datetime.now(tz=UTC) + timedelta(minutes=2),
    )
    message = SimpleNamespace(id=claim.message_id)
    connection = SimpleNamespace(
        provider="outlook",
        email_address="owner@example.test",
    )
    session = AsyncMock()

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            return False

    create_notification = AsyncMock()
    monkeypatch.setattr(ai_runtime, "AsyncSessionFactory", lambda: SessionContext())
    monkeypatch.setattr(
        ai_runtime,
        "_load_valid_claim",
        AsyncMock(return_value=(analysis, message, connection)),
    )
    monkeypatch.setattr(
        ai_runtime,
        "NotificationRepository",
        lambda _session: SimpleNamespace(create=create_notification),
    )

    await ai_runtime.release_email_ai_claim_after_error(
        claim,
        settings=_settings(email_ai_max_attempts=3),
    )

    assert analysis.status == "failed"
    assert analysis.needs_attention is True
    assert analysis.lease_token is None
    create_notification.assert_awaited_once()
    notification_args = create_notification.await_args.kwargs
    assert notification_args["user_id"] == claim.owner_user_id
    assert notification_args["agency_id"] == claim.agency_id
    assert notification_args["entity_id"] == str(claim.message_id)
    session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_irrelevant_email_persists_no_operational_notification(
    db_session,
) -> None:
    agency_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    db_session.add(
        AgencyModel(
            id=agency_id,
            name="Irrelevant Runtime Agency",
            email="irrelevant-runtime-agency@example.test",
            is_active=True,
        )
    )
    db_session.add(
        UserModel(
            id=owner_id,
            email="irrelevant-owner@example.test",
            hashed_password="not-used",
            full_name="Irrelevant Owner",
            role="agency_staff",
            agency_id=agency_id,
            is_active=True,
        )
    )
    await db_session.flush()
    analysis = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        owner_user_id=owner_id,
        status="ignored",
        result_json={},
    )
    message = SimpleNamespace(id=uuid.uuid4())
    connection = SimpleNamespace(
        provider="gmail",
        email_address="irrelevant-owner@example.test",
    )
    result = EmailAnalysisResult(
        provider_status=EmailAnalysisProviderStatus.ANALYZED,
        model="configured-test-model",
        relevance=EmailRelevance.UNRELATED,
        intent=EmailIntent.OTHER,
        priority=EmailPriority.NORMAL,
        confidence=0.99,
        summary="This message is not related to travel operations.",
        needs_review=True,
    )

    await ai_runtime._create_attention_notification(
        db_session,
        analysis=analysis,
        message=message,
        connection=connection,
        result=result,
        deadlines=[],
        draft=None,
        proposal_count=0,
        notification_window_days=14,
    )
    await db_session.flush()

    notifications = list(
        (
            await db_session.execute(
                select(NotificationModel).where(
                    NotificationModel.user_id == owner_id,
                    NotificationModel.category == "email_operations",
                )
            )
        )
        .scalars()
        .all()
    )
    assert notifications == []


@pytest.mark.asyncio
async def test_far_future_deadline_does_not_create_an_early_notification(
    monkeypatch,
) -> None:
    analysis = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        status="completed",
    )
    message = SimpleNamespace(id=uuid.uuid4())
    connection = SimpleNamespace(
        provider="gmail",
        email_address="owner@example.test",
    )
    result = EmailAnalysisResult(
        provider_status=EmailAnalysisProviderStatus.ANALYZED,
        model="configured-test-model",
        relevance=EmailRelevance.RELEVANT,
        intent=EmailIntent.INFORMATION_REQUEST,
        priority=EmailPriority.NORMAL,
        confidence=0.96,
        summary="A future deadline was recorded.",
        needs_review=False,
    )
    deadline = SimpleNamespace(
        status="detected",
        due_at=datetime.now(tz=UTC) + timedelta(days=30),
    )
    create_notification = AsyncMock()
    monkeypatch.setattr(
        ai_runtime,
        "NotificationRepository",
        lambda _session: SimpleNamespace(create=create_notification),
    )

    await ai_runtime._create_attention_notification(
        AsyncMock(),
        analysis=analysis,
        message=message,
        connection=connection,
        result=result,
        deadlines=[deadline],
        draft=None,
        proposal_count=0,
        notification_window_days=14,
    )

    create_notification.assert_not_awaited()

    deadline.status = "review_required"
    await ai_runtime._create_attention_notification(
        AsyncMock(),
        analysis=analysis,
        message=message,
        connection=connection,
        result=result,
        deadlines=[deadline],
        draft=None,
        proposal_count=0,
        notification_window_days=14,
    )
    create_notification.assert_awaited_once()
