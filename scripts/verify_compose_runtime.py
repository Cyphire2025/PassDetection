"""Verify that development and production Compose runtimes stay separated.

This check renders Compose configuration only; it does not require a running
Docker daemon or start any container.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from compose_runtime_capacity import validate_production_capacity
from compose_runtime_clients import (
    validate_development,
    validate_frontend,
    validate_runtime_source_files,
)
from compose_runtime_contract import (
    BACKEND_DOCKERFILE as BACKEND_DOCKERFILE,
)
from compose_runtime_contract import (
    BACKEND_DOCKERIGNORE as BACKEND_DOCKERIGNORE,
)
from compose_runtime_contract import (
    BACKEND_SERVICES as BACKEND_SERVICES,
)
from compose_runtime_contract import (
    BASE_COMPOSE as BASE_COMPOSE,
)
from compose_runtime_contract import (
    DEV_COMPOSE as DEV_COMPOSE,
)
from compose_runtime_contract import (
    DEVELOPMENT_PUBLISHED_TARGETS as DEVELOPMENT_PUBLISHED_TARGETS,
)
from compose_runtime_contract import (
    EXPECTED_DATABASE_SCHEMA_REVISION as EXPECTED_DATABASE_SCHEMA_REVISION,
)
from compose_runtime_contract import (
    FRONTEND_ALLOWED_BUILD_KEYS as FRONTEND_ALLOWED_BUILD_KEYS,
)
from compose_runtime_contract import (
    FRONTEND_ALLOWED_ENVIRONMENT_KEYS as FRONTEND_ALLOWED_ENVIRONMENT_KEYS,
)
from compose_runtime_contract import (
    FRONTEND_DOCKERIGNORE as FRONTEND_DOCKERIGNORE,
)
from compose_runtime_contract import (
    FRONTEND_FORBIDDEN_ENVIRONMENT_KEYS as FRONTEND_FORBIDDEN_ENVIRONMENT_KEYS,
)
from compose_runtime_contract import (
    GUNICORN_CONFIG as GUNICORN_CONFIG,
)
from compose_runtime_contract import (
    INTERNAL_SERVICES as INTERNAL_SERVICES,
)
from compose_runtime_contract import (
    NGINX_PUBLISHED_TARGETS as NGINX_PUBLISHED_TARGETS,
)
from compose_runtime_contract import (
    PINNED_CLAMAV_IMAGE as PINNED_CLAMAV_IMAGE,
)
from compose_runtime_contract import (
    PINNED_NGINX_IMAGE as PINNED_NGINX_IMAGE,
)
from compose_runtime_contract import (
    PINNED_STATSD_EXPORTER_IMAGE as PINNED_STATSD_EXPORTER_IMAGE,
)
from compose_runtime_contract import (
    PROD_COMPOSE as PROD_COMPOSE,
)
from compose_runtime_contract import (
    REDIS_SERVICES as REDIS_SERVICES,
)
from compose_runtime_contract import (
    ROOT as ROOT,
)
from compose_runtime_contract import (
    STORAGE_COMPOSE as STORAGE_COMPOSE,
)
from compose_runtime_contract import (
    WORKER_QUEUE_CONTRACTS as WORKER_QUEUE_CONTRACTS,
)
from compose_runtime_services import validate_production_topology
from compose_runtime_values import (
    _command_text as _command_text,
)
from compose_runtime_values import (
    _healthcheck_text as _healthcheck_text,
)
from compose_runtime_values import (
    _published_port_targets as _published_port_targets,
)
from compose_runtime_values import (
    _require as _require,
)
from compose_runtime_values import (
    _volume_targets as _volume_targets,
)
from compose_runtime_workers import validate_backend_consistency, validate_workers
from image_runtime_policy import validate_process_isolation
from release_manifest import verify_source_defaults
from verify_database_deployment_budget import calculate as database_budget
from verify_database_deployment_budget import capacity_markdown


def _render_compose(*files: Path) -> dict[str, Any]:
    # Compose still checks required service env_file paths when rendering with
    # --no-env-resolution. Use an isolated project directory so a clean checkout
    # works and an operator's real .env is never loaded by this source check.
    with tempfile.TemporaryDirectory(prefix="passdetection-compose-contract-") as directory:
        fixture = Path(directory) / ".env"
        fixture.write_bytes((ROOT / ".env.example").read_bytes())
        return _render_compose_fixture(files, fixture)


def _render_compose_fixture(files: tuple[Path, ...], fixture: Path) -> dict[str, Any]:
    command = [
        "docker",
        "compose",
        "--profile",
        "maintenance",
        "--project-name",
        "passdetection-compose-contract",
        "--project-directory",
        str(fixture.parent),
        "--env-file",
        str(fixture),
    ]
    for file in files:
        command.extend(("-f", str(file)))
    command.extend(("config", "--format", "json", "--no-env-resolution"))
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                # Render-only fixtures. Never start services using these values.
                "MINIO_ROOT_USER": "compose-contract-storage-admin",
                "MINIO_ROOT_PASSWORD": "compose-contract-storage-admin-secret",
                "POSTGRES_RUNTIME_USER": "compose-contract-runtime",
                "POSTGRES_RUNTIME_PASSWORD": "compose-contract-runtime-secret",
                "POSTGRES_MIGRATION_USER": "compose-contract-migrator",
                "POSTGRES_MIGRATION_PASSWORD": "compose-contract-migrator-secret",
                "EXPECTED_DATABASE_SCHEMA_REVISION": EXPECTED_DATABASE_SCHEMA_REVISION,
                "S3_BUCKET_NAME": "compose-contract-passports",
                "OBJECT_STORAGE_ADMIN_ACCESS_KEY": "compose-contract-object-admin",
                "OBJECT_STORAGE_ADMIN_SECRET_KEY": "compose-contract-object-admin-secret",
                "OBJECT_STORAGE_IDENTITY_FILE": str(ROOT / "tmp/compose-contract/identities.json"),
                "OBJECT_STORAGE_CUTOVER_PROOF": str(ROOT / "tmp/compose-contract/cutover.json"),
                "OBJECT_STORAGE_MIGRATION_DIRECTORY": str(ROOT / "tmp/compose-contract"),
                "OBJECT_STORAGE_DATA_VOLUME": "compose-contract-new-object-data",
            },
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Docker Compose CLI is required for this check.") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "Compose configuration failed."
        raise RuntimeError(detail)
    decoded = json.loads(completed.stdout)
    if not isinstance(decoded, dict):
        raise RuntimeError("Rendered Compose configuration must be an object")
    return decoded


def main() -> int:
    verify_source_defaults()
    production = _render_compose(BASE_COMPOSE, PROD_COMPOSE, STORAGE_COMPOSE)
    budget = database_budget(
        production,
        json.loads((ROOT / "tooling/database-deployment-budget.json").read_text()),
    )
    _require(
        not budget["errors"],
        "Rendered production database pool budget exceeds capacity",
    )
    _require(
        (ROOT / "docs/DATABASE_CONNECTION_CAPACITY.generated.md").read_text(encoding="utf-8")
        == capacity_markdown(budget),
        "Generated database capacity table is stale; review the rendered deployment and regenerate it",
    )
    development = _render_compose(BASE_COMPOSE, DEV_COMPOSE)
    production_services = production["services"]
    validate_process_isolation(
        production_services, storage_directory=str(ROOT / "tmp/compose-contract")
    )
    development_services = development["services"]
    production_backend = production_services["backend"]
    validate_production_topology(production_services, production_backend)
    validate_backend_consistency(production_services, production_backend)
    validate_production_capacity(production_services, production_backend)
    validate_frontend(production_services)
    validate_workers(production_services)
    validate_runtime_source_files(
        BACKEND_DOCKERFILE, GUNICORN_CONFIG, FRONTEND_DOCKERIGNORE, BACKEND_DOCKERIGNORE
    )
    validate_development(development_services)
    print(
        "Compose runtime contracts verified: production uses the immutable Gunicorn image with internal services private behind Nginx; development retains hot reload and local service ports."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Compose runtime verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
