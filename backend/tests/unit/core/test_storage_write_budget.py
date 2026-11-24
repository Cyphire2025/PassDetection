"""The private-write envelope remains conservative for the pinned SDK policy."""

from types import SimpleNamespace

import pytest
from botocore.retries.standard import ExponentialBackoff

from app.core.config.settings import S3Settings
from app.core.storage_write_budget import s3_write_envelope_seconds


@pytest.mark.parametrize("attempts", range(1, 11))
def test_all_supported_attempts_cover_the_actual_sdk_maximum_backoff(attempts):
    settings = S3Settings(max_attempts=attempts, _env_file=None)
    sdk = ExponentialBackoff(random=lambda: 1.0)
    total = settings.connect_timeout_seconds + settings.read_timeout_seconds
    for attempt in range(1, attempts):
        total += sdk.delay_amount(SimpleNamespace(attempt_number=attempt))
        total += settings.connect_timeout_seconds + settings.read_timeout_seconds
    assert s3_write_envelope_seconds(settings) >= total + 30
