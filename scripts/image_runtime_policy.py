"""Executable deployment preconditions for privileged native-library mitigations."""
from __future__ import annotations

import re

BACKEND_PROCESSES = (
    "backend", "worker", "my-photos-worker", "email-worker", "email-ai-worker",
    "email-beat", "extraction-worker", "verification-worker", "visa-ai-worker",
    "ecr-worker", "database-admin", "database-migrate",
)

WORKER_COMMANDS = {
    "worker": ("general", "passport_ocr,whatsapp"),
    "my-photos-worker": ("my-photos", "my_photos_control,my_photos_index,my_photos_media,my_photos_search"),
    "email-worker": ("email", "email_integrations"),
    "email-ai-worker": ("email-ai", "email_ai"),
    "extraction-worker": ("extraction", "interactive-passport-extraction"),
    "verification-worker": ("verification", "post-submission-ai-verification"),
    "visa-ai-worker": ("visa-ai", "visa-ai-image-edit"),
    "ecr-worker": ("ecr", "ecr_checks"),
}
CELERY_COMMAND = "exec celery -A app.infrastructure.processing.celery_app:celery_app"


def reviewed_process_command(name: str, concurrency: int = 1) -> list[str] | None:
    if name == "backend":
        return None  # The qualified image's Gunicorn command remains authoritative.
    if name == "database-admin":
        return ["python", "scripts/provision_database_roles.py"]
    if name == "database-migrate":
        return ["alembic", "upgrade", "head"]
    if name == "email-beat":
        return ["sh", "-c", CELERY_COMMAND + " beat --loglevel=INFO --schedule=/tmp/passdetection-email-beat"]
    prefix, queues = WORKER_COMMANDS[name]
    return ["sh", "-c", f"{CELERY_COMMAND} worker --hostname={prefix}@%h --loglevel=INFO --concurrency={concurrency} -Q {queues}"]


def validate_process_command(name: str, service: dict) -> None:
    if service.get("entrypoint") is not None or service.get("working_dir") not in (None, "/app"):
        raise ValueError(f"{name}: startup overrides invalidate the reviewed native call paths")
    command = service.get("command")
    expected = reviewed_process_command(name)
    if name in WORKER_COMMANDS:
        if not isinstance(command, list) or len(command) != 3 or command[:2] != ["sh", "-c"]:
            raise ValueError(f"{name}: unreviewed worker command")
        pattern = re.escape(expected[2]).replace(re.escape("--concurrency=1"), r"--concurrency=[1-9][0-9]{0,2}")
        if re.fullmatch(pattern, " ".join(command[2].split())) is None:
            raise ValueError(f"{name}: worker command differs from the reviewed executable and queues")
    elif command != expected:
        raise ValueError(f"{name}: startup command differs from the reviewed image contract")


def validate_code_boundary(name: str, service: dict) -> None:
    if any(service.get(key) for key in ("volumes_from", "tmpfs", "configs", "secrets")):
        raise ValueError(f"{name}: filesystem overlays invalidate the qualified image bytes")
    environment = service.get("environment", {})
    for key, value in environment.items():
        if value is None or value == "":
            continue
        if key.startswith(("LD_", "PYTHON")) or key in {"PATH", "BASH_ENV", "ENV", "GLIBC_TUNABLES"}:
            raise ValueError(f"{name}: interpreter/loader overrides invalidate native-call review")


def validate_process_isolation(services: dict, *, storage_directory: str | None = None) -> None:
    for name in BACKEND_PROCESSES:
        service = services[name]
        validate_code_boundary(name, service)
        validate_process_command(name, service)
        if service.get("user") != "1001:1001":
            raise ValueError(f"{name}: reviewed native-library mitigation requires UID/GID 1001")
        if set(service.get("cap_drop", [])) != {"ALL"} or service.get("cap_add"):
            raise ValueError(f"{name}: all capabilities must be dropped without additions")
        options = set(service.get("security_opt", []))
        if options != {"no-new-privileges:true"}:
            raise ValueError(f"{name}: no-new-privileges and the default confinement are required")
        if service.get("privileged") or service.get("pid") == "host" or service.get("ipc") == "host":
            raise ValueError(f"{name}: host privilege or namespace sharing invalidates the mitigation")
        if service.get("devices") or service.get("device_cgroup_rules"):
            raise ValueError(f"{name}: device access invalidates the reviewed boundary")
        for volume in service.get("volumes", []):
            if volume.get("type") != "bind":
                raise ValueError(f"{name}: runtime volumes must not overlay qualified image bytes")
            # Only the specific, read-only push credential directory is allowed.
            secret = {"/run/gc-fcm": "/opt/global-connect-secrets/fcm",
                      "/run/gc-apns": "/opt/global-connect-secrets/apns"}.get(volume.get("target"))
            if not (name == "worker" and secret and volume.get("source") == secret
                    and volume.get("read_only") is True):
                raise ValueError(f"{name}: unexpected host bind mount invalidates the mitigation")
    if "storage-copy" in services:
        copy = services["storage-copy"]
        validate_code_boundary("storage-copy", copy)
        if (copy.get("user") != "0:0" or set(copy.get("cap_drop", [])) != {"ALL"}
                or copy.get("cap_add") or copy.get("privileged") or copy.get("devices") or copy.get("device_cgroup_rules")
                or copy.get("pid") == "host" or copy.get("ipc") == "host"
                or set(copy.get("security_opt", [])) != {"no-new-privileges:true"}
                or copy.get("command") != ["python", "scripts/copy_storage_snapshot.py"]
                or copy.get("entrypoint") or copy.get("restart") != "no"):
            raise ValueError("storage-copy must retain the exact confined one-off maintenance contract")
        mounts = copy.get("volumes", [])
        # Compose v2 omits false JSON fields, rendering an explicit
        # create_host_path:false as bind:{}. Require that bind object; short
        # syntax renders create_host_path:true and must still be rejected.
        if (len(mounts) != 1 or mounts[0].get("type") != "bind"
                or mounts[0].get("target") != "/evidence"
                or not isinstance(mounts[0].get("bind"), dict)
                or mounts[0]["bind"].get("create_host_path", False) is not False):
            raise ValueError("storage-copy may only mount the existing protected evidence directory")
        expected = storage_directory or services["database-admin"].get("environment", {}).get("OBJECT_STORAGE_MIGRATION_DIRECTORY")
        if not expected:
            raise ValueError("Prepared storage evidence directory is required")
        if mounts[0].get("source") != expected:
            raise ValueError("storage-copy evidence mount differs from the prepared directory")
