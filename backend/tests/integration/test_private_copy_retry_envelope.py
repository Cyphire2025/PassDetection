"""An admitted private copy lease includes the supported SDK retry backoff."""

from datetime import UTC, datetime
from types import SimpleNamespace

from botocore.retries.standard import ExponentialBackoff

from app.application.travellers.enrollment import enroll_submission
from app.infrastructure.travellers import asset_copy
from tests.unit.application.test_traveller_enrollment import _fixture


async def test_copy_lease_includes_all_supported_standard_backoff(
    db_session, test_settings, monkeypatch
):
    context = await _fixture(db_session)
    await enroll_submission(db_session, context.request, context.crypto)
    provider = test_settings.s3.model_copy(update={"max_attempts": 10})
    monkeypatch.setattr(asset_copy, "get_settings", lambda: SimpleNamespace(s3=provider))
    now = datetime.now(UTC)
    claim = await asset_copy._reserve(db_session, now)
    assert claim is not None
    backoff = ExponentialBackoff(random=lambda: 1.0)
    retry_seconds = sum(
        backoff.delay_amount(SimpleNamespace(attempt_number=attempt))
        for attempt in range(1, provider.max_attempts)
    )
    required = (
        (provider.connect_timeout_seconds + provider.read_timeout_seconds) * provider.max_attempts
        + retry_seconds
        + 30
    )
    assert (claim.lease_expires_at - now).total_seconds() >= required
