"""Fresh test applications must not spend each other's fallback rate quota."""

from types import SimpleNamespace

import pytest

from app.presentation.middleware import rate_limit


@pytest.mark.asyncio
@pytest.mark.parametrize("application", ["first", "second"])
async def test_http_test_boundary_resets_quota_without_disabling_enforcement(
    client, test_settings, monkeypatch, application,
):
    # Both cases use the same IP, secret and time bucket. The second case must
    # start fresh even though the first deliberately exhausted both counters.
    monkeypatch.setattr(rate_limit, "time", SimpleNamespace(time=lambda: 1_800_000_000, monotonic=lambda: 50.0))
    assert not rate_limit.RateLimitMiddleware._local_counts, application
    assert not rate_limit.RateLimitMiddleware._local_token_buckets, application
    limit = test_settings.rate_limit_per_minute
    assert limit == 60
    for _ in range(limit):
        assert (await client.get("/api/v1/test-only-missing-route")).status_code == 404
    assert (await client.get("/api/v1/test-only-missing-route")).status_code == 429
    middleware = rate_limit.RateLimitMiddleware(
        client._transport.app, settings=test_settings, initialize_redis=False,
    )
    arguments = {"refill_per_second": 1, "capacity": 1, "require_distributed": False}
    assert (await middleware._consume_token_bucket("fixture-burst", **arguments))[0] is True
    assert (await middleware._consume_token_bucket("fixture-burst", **arguments))[0] is False
