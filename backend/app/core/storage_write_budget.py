"""Lease envelope for the configured standard-mode, total-attempt S3 client."""

from app.core.config.settings import S3Settings


def s3_write_envelope_seconds(settings: S3Settings) -> float:
    """Include configured I/O attempts, SDK maximum retry delays and margin.

    Standard retries cap each exponential delay at 20 seconds. Settings bound
    total attempts to ten; the loop has at most nine terms. The additional
    thirty seconds retains the existing scheduling/cleanup safety margin.
    """
    attempts = settings.max_attempts
    backoff = sum(min(1 << index, 20) for index in range(attempts - 1))
    return (
        (settings.connect_timeout_seconds + settings.read_timeout_seconds) * attempts + backoff + 30
    )
