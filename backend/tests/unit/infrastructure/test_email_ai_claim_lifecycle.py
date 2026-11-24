"""Claim recovery rejects stale work and preserves bounded durable retry state."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.domain.value_objects.email_ai_analysis import (
    EmailAnalysisProviderStatus,
    EmailAnalysisResult,
)
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.email import ai_runtime


def _claim():
    return ai_runtime.EmailAiClaim(
        analysis_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        owner_user_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        provider_account_id="synthetic-provider",
        sync_generation=1,
        lease_token="synthetic-lease",
    )


def _settings(**overrides):
    return SimpleNamespace(
        **{
            "email_ai_max_attempts": 10,
            "email_ai_notifications_ready": True,
            **overrides,
        }
    )


def _retry_result():
    return EmailAnalysisResult.review_fallback(
        provider_status=EmailAnalysisProviderStatus.TIMEOUT,
        reason_code="provider_timeout",
        model="synthetic-model",
    )


def _wire(monkeypatch, row):
    session = AsyncMock()

    class Context:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(ai_runtime, "AsyncSessionFactory", Context)
    loader = AsyncMock(return_value=row)
    monkeypatch.setattr(ai_runtime, "_load_valid_claim", loader)
    notifications = Mock(side_effect=AssertionError("recovery must not disclose or send"))
    monkeypatch.setattr(ai_runtime, "NotificationRepository", notifications)
    return session, loader, notifications


async def _invoke(action, claim):
    if action == "defer":
        return await ai_runtime._defer_for_ai_priority(claim, retry_after_ms=2500)
    if action == "runtime_error":
        return await ai_runtime.release_email_ai_claim_after_error(claim, settings=_settings())
    if action == "publish_error":
        return await ai_runtime.release_email_ai_claim_after_publish_failure(claim)
    if action == "retry":
        return await ai_runtime._retry_transient_failure(
            claim, result=_retry_result(), settings=_settings()
        )
    if action == "finish":
        return await ai_runtime._finish_without_analysis(
            claim, status="failed", error_code="owner_context_unavailable"
        )
    return await ai_runtime._pause_claim_for_policy(claim, error_code="rollout_policy_disabled")


@pytest.mark.parametrize(
    "action", ["defer", "runtime_error", "publish_error", "retry", "finish", "pause"]
)
async def test_stale_recovery_never_commits_or_creates_attention(monkeypatch, action):
    claim = _claim()
    session, loader, notifications = _wire(monkeypatch, None)
    result = await _invoke(action, claim)
    loader.assert_awaited_once_with(session, claim, for_update=True)
    session.commit.assert_not_awaited()
    session.add.assert_not_called()
    notifications.assert_not_called()
    assert result is (True if action == "retry" else None)


@pytest.mark.parametrize("action", ["defer", "publish_error", "runtime_error", "finish", "pause"])
async def test_current_recovery_applies_only_owned_transition_and_commits_once(monkeypatch, action):
    claim = _claim()
    old = datetime.now(UTC) - timedelta(minutes=1)
    analysis = EmailAiAnalysisModel(
        id=claim.analysis_id,
        agency_id=claim.agency_id,
        owner_user_id=claim.owner_user_id,
        connection_id=claim.connection_id,
        message_id=claim.message_id,
        status="processing",
        attempt_count=2,
        lease_token=claim.lease_token,
        lease_expires_at=old + timedelta(minutes=5),
        started_at=old,
        completed_at=old,
        needs_attention=True,
    )
    session, loader, notifications = _wire(monkeypatch, (analysis, object(), object()))
    before = datetime.now(UTC)
    await _invoke(action, claim)
    after = datetime.now(UTC)
    loader.assert_awaited_once_with(session, claim, for_update=True)
    session.commit.assert_awaited_once()
    notifications.assert_not_called()
    assert analysis.lease_token is None and analysis.lease_expires_at is None
    assert analysis.status == ("failed" if action == "finish" else "pending")
    refund = action in {"defer", "publish_error", "pause"}
    assert analysis.attempt_count == (1 if refund else 2)
    if action in {"defer", "publish_error", "pause"}:
        assert analysis.started_at is None and analysis.completed_at is None
    if action == "finish":
        assert before <= analysis.completed_at <= after and analysis.needs_attention
    if action == "pause":
        assert analysis.next_attempt_at is None and not analysis.needs_attention
    elif action != "finish":
        delay = {"defer": 3, "publish_error": 5, "runtime_error": 30}[action]
        assert (
            before + timedelta(seconds=delay)
            <= analysis.next_attempt_at
            <= after + timedelta(seconds=delay)
        )


@pytest.mark.parametrize("attempt,expected_delay", [(1, 10), (8, 300)])
async def test_transient_retry_is_bounded_and_does_not_refund_provider_attempt(
    monkeypatch, attempt, expected_delay
):
    claim = _claim()
    analysis = EmailAiAnalysisModel(
        attempt_count=attempt, status="processing", lease_token=claim.lease_token
    )
    session, _, notifications = _wire(monkeypatch, (analysis, object(), object()))
    before = datetime.now(UTC)
    assert await ai_runtime._retry_transient_failure(
        claim, result=_retry_result(), settings=_settings()
    )
    after = datetime.now(UTC)
    assert analysis.status == "pending" and analysis.attempt_count == attempt
    assert analysis.last_error_code == "provider_timeout"
    assert analysis.lease_token is None and analysis.lease_expires_at is None
    assert (
        before + timedelta(seconds=expected_delay)
        <= analysis.next_attempt_at
        <= after + timedelta(seconds=expected_delay)
    )
    session.commit.assert_awaited_once()
    notifications.assert_not_called()


async def test_exhausted_transient_budget_preserves_claim_for_final_failure_persistence(
    monkeypatch,
):
    claim = _claim()
    analysis = EmailAiAnalysisModel(
        attempt_count=10, status="processing", lease_token=claim.lease_token
    )
    session, _, notifications = _wire(monkeypatch, (analysis, object(), object()))
    assert not await ai_runtime._retry_transient_failure(
        claim, result=_retry_result(), settings=_settings()
    )
    assert analysis.status == "processing" and analysis.lease_token == claim.lease_token
    assert analysis.attempt_count == 10
    session.commit.assert_not_awaited()
    notifications.assert_not_called()
