"""Fixed source contracts for the deployment runtime qualifier."""

from pathlib import Path

from release_manifest import load_release_manifest

ROOT = Path(__file__).resolve().parents[1]

BASE_COMPOSE = ROOT / "docker-compose.yml"

DEV_COMPOSE = ROOT / "docker-compose.dev.yml"

PROD_COMPOSE = ROOT / "docker-compose.prod.yml"

STORAGE_COMPOSE = ROOT / "docker-compose.storage-production.yml"

BACKEND_DOCKERFILE = ROOT / "backend" / "Dockerfile"

GUNICORN_CONFIG = ROOT / "backend" / "gunicorn.conf.py"

BACKEND_DOCKERIGNORE = ROOT / "backend" / ".dockerignore"

FRONTEND_DOCKERIGNORE = ROOT / "frontend" / ".dockerignore"

BACKEND_SERVICES = (
    "backend",
    "worker",
    "my-photos-worker",
    "email-worker",
    "email-ai-worker",
    "email-beat",
    "extraction-worker",
    "verification-worker",
    "visa-ai-worker",
    "ecr-worker",
)

REDIS_SERVICES = ("redis", "redis-broker", "redis-realtime", "redis-cache")

INTERNAL_SERVICES = (
    "db",
    *REDIS_SERVICES,
    "clamav",
    "minio",
    "metrics-exporter",
    "backend",
)

DEVELOPMENT_PUBLISHED_TARGETS = {
    "db": {5432},
    "redis": {6379},
    "redis-broker": {6379},
    "redis-realtime": {6379},
    "redis-cache": {6379},
    "minio": {9000, 9001},
    "metrics-exporter": {9102},
    "backend": {8000},
}

NGINX_PUBLISHED_TARGETS = {80, 443}

PINNED_NGINX_IMAGE = (
    "nginx:1.30.4-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46"
)

PINNED_CLAMAV_IMAGE = (
    "clamav/clamav:1.5_base@sha256:2a682381f314a3ac6ec13eea55b69bd2594887598e5358d938e711a30df850f2"
)

PINNED_STATSD_EXPORTER_IMAGE = (
    "prom/statsd-exporter:v0.29.0"
    "@sha256:632f705804922d50c1c95ba8ff9c8c0cc18d4bbb0cc265dc4f9ae708271c95b3"
)

EXPECTED_DATABASE_SCHEMA_REVISION = load_release_manifest()["schema_revision"]

FRONTEND_ALLOWED_ENVIRONMENT_KEYS = {
    "NEXT_PUBLIC_API_BASE_URL",
    "NEXT_PUBLIC_APP_URL",
    "NEXT_PUBLIC_DEV_APP_URL",
    "NEXT_PUBLIC_APP_REVISION",
}

FRONTEND_ALLOWED_BUILD_KEYS = FRONTEND_ALLOWED_ENVIRONMENT_KEYS | {"APP_REVISION"}

FRONTEND_FORBIDDEN_ENVIRONMENT_KEYS = {
    "APP_SECRET_KEY",
    "GOOGLE_API_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "REDIS_BROKER_PASSWORD",
    "REDIS_SECURITY_PASSWORD",
    "REDIS_REALTIME_PASSWORD",
    "REDIS_CACHE_PASSWORD",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_WEBHOOK_VERIFY_TOKEN",
}

WORKER_QUEUE_CONTRACTS = {
    "ecr-worker": ("ecr@", "ecr_checks"),
    "worker": ("general@", "passport_ocr", "whatsapp"),
    "my-photos-worker": (
        "my-photos@",
        "my_photos_control",
        "my_photos_index",
        "my_photos_media",
        "my_photos_search",
    ),
    "extraction-worker": (
        "extraction@",
        "interactive-passport-extraction",
    ),
    "verification-worker": (
        "verification@",
        "post-submission-ai-verification",
    ),
    "visa-ai-worker": (
        "visa-ai@",
        "visa-ai-image-edit",
    ),
    "email-worker": (
        "email@",
        "email_integrations",
    ),
    "email-ai-worker": (
        "email-ai@",
        "email_ai",
    ),
}
