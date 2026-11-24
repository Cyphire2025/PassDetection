"""Local fallback releases old quota state without evicting active guards."""

from types import SimpleNamespace

from app.presentation.middleware import rate_limit


def _middleware(settings):
    async def app(_scope, _receive, _send):
        pass

    return rate_limit.RateLimitMiddleware(app, settings=settings, initialize_redis=False)


async def test_expired_time_buckets_do_not_accumulate_across_redis_outage(test_settings, monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(rate_limit, "time", SimpleNamespace(time=lambda: clock.now))
    middleware = _middleware(test_settings)
    for minute in range(500):
        clock.now = minute * 60.0
        key = middleware._counter_key(scope="api", identifier="203.0.113.8", bucket=minute)
        assert await middleware._increment(key, require_distributed=False) == 1
        assert await middleware._increment(key, require_distributed=False) == 2
    assert len(middleware._local_counts) == 1


async def test_idle_burst_buckets_expire_using_their_own_refill_envelope(test_settings, monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(rate_limit, "time", SimpleNamespace(monotonic=lambda: clock.now))
    middleware = _middleware(test_settings)
    slow = {"refill_per_second": 1, "capacity": 100, "require_distributed": False}
    fast = {"refill_per_second": 1, "capacity": 1, "require_distributed": False}
    for _ in range(100):
        assert (await middleware._consume_token_bucket("slow", **slow))[0]
    assert not (await middleware._consume_token_bucket("slow", **slow))[0]
    for index in range(100):
        assert (await middleware._consume_token_bucket(f"idle-{index}", **fast))[0]

    clock.now = 61.0
    assert (await middleware._consume_token_bucket("fresh", **fast))[0]
    assert set(middleware._local_token_buckets) == {"slow", "fresh"}
    # The active 100-token policy must receive only its accumulated 61 tokens;
    # the shorter one-token policy's expiry must not reset the longer guard.
    assert await middleware._consume_token_bucket("slow", **slow) == (True, 60, 0)
