"""Preserve the private Redis backend binding across worker app reconstruction."""

from celery.loaders.app import AppLoader


class PrivateTaskLoader(AppLoader):  # type: ignore[misc]  # Celery's extension base is untyped.
    override_backends = {
        **AppLoader.override_backends,
        "redis": "app.infrastructure.processing.private_result_backend:PrivateRedisBackend",
        "rediss": "app.infrastructure.processing.private_result_backend:PrivateRedisBackend",
    }
