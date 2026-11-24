"""Voice allowance commits only after setup and counts are private to an owner/day."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.application.assistant.contracts import AssistantError
from app.core.assistant_usage import AssistantUsageLimits
from app.infrastructure.assistant import limits, usage


@pytest.mark.parametrize(
    "admitted,commit,expected",
    [
        (1, True, ["ADMIT", "RELEASE"]),
        (1, False, ["ADMIT", "CANCEL_VOICE", "RELEASE"]),
        (0, False, ["ADMIT", "RELEASE"]),
    ],
)
async def test_native_setup_commit_or_refund(monkeypatch, admitted, commit, expected):
    redis = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(limits, "_redis", lambda: redis)
    evaluate = AsyncMock(side_effect=[admitted, 1, 1])
    monkeypatch.setattr(limits, "_eval", evaluate)
    async with limits.assistant_admission(
        uuid4(), operation="voice_chats", limit=30, distinct_id=uuid4()
    ) as receipt:
        if commit:
            receipt.commit()
    assert [call.args[1] for call in evaluate.await_args_list] == [
        getattr(limits, name) for name in expected
    ]
    redis.aclose.assert_awaited_once()


async def test_daily_denial_is_specific_and_does_not_reserve_work(monkeypatch):
    redis = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(limits, "_redis", lambda: redis)
    evaluate = AsyncMock(return_value=-2)
    monkeypatch.setattr(limits, "_eval", evaluate)
    with pytest.raises(AssistantError) as denied:
        async with limits.assistant_admission(
            uuid4(), operation="voice_chats", limit=0, distinct_id=uuid4()
        ):
            pytest.fail("Disabled voice must not call a provider")
    assert denied.value.code == "daily_limit" and "voice chat" in denied.value.message
    assert evaluate.await_count == 1


async def test_a_failed_refund_still_releases_the_active_lease(monkeypatch):
    redis = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(limits, "_redis", lambda: redis)
    evaluate = AsyncMock(side_effect=[1, ConnectionError(), 1])
    monkeypatch.setattr(limits, "_eval", evaluate)
    async with limits.assistant_admission(
        uuid4(), operation="voice_chats", limit=30, distinct_id=uuid4()
    ):
        pass
    assert evaluate.await_args_list[-1].args[1] == limits.RELEASE
    redis.aclose.assert_awaited_once()


async def test_usage_reads_exact_owner_keys_and_resets_at_utc_midnight(monkeypatch):
    owner = uuid4()
    redis = SimpleNamespace(mget=AsyncMock(return_value=[2, 7, 1, 3, 4]), aclose=AsyncMock())
    monkeypatch.setattr(usage, "_redis", lambda: redis)
    policy = AssistantUsageLimits()
    result = await usage.usage_snapshot(owner, policy)
    assert result.used == {
        "voice_chats": 2,
        "typed_requests": 7,
        "images": 1,
        "uploads": 3,
        "speech_requests": 4,
    }
    assert result.resets_at.hour == result.resets_at.minute == result.resets_at.second == 0
    assert result.resets_at.tzinfo == UTC and result.resets_at > result.observed_at
    keys = redis.mget.await_args.args[0]
    assert all(str(owner) in key for key in keys)
    assert all(key.endswith(result.observed_at.strftime("%Y%m%d")) for key in keys)
    assert limits._daily_key(owner, "chat", datetime(2026, 12, 31, 23, 59, tzinfo=UTC)).endswith(
        "20261231"
    )
    assert limits._daily_key(owner, "chat", datetime(2027, 1, 1, tzinfo=UTC)).endswith("20270101")


async def test_unavailable_usage_is_an_error_not_a_false_zero(monkeypatch):
    redis = SimpleNamespace(mget=AsyncMock(side_effect=ConnectionError()), aclose=AsyncMock())
    monkeypatch.setattr(usage, "_redis", lambda: redis)
    with pytest.raises(AssistantError) as error:
        await usage.usage_snapshot(uuid4(), AssistantUsageLimits())
    assert error.value.code == "usage_unavailable"
    redis.aclose.assert_awaited_once()
