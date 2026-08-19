"""Validated production Gunicorn process configuration."""

from app.core.config.settings import get_settings

_settings = get_settings()

bind = "0.0.0.0:8000"
workers = _settings.web_concurrency
worker_class = "app.infrastructure.bounded_uvicorn_worker.BoundedUvicornWorker"
timeout = 120
graceful_timeout = 30
keepalive = 5
errorlog = "-"
accesslog = None
preload_app = False
