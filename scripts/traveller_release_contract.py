"""Fixed historical release contracts and exact worker/image admission helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

SCHEMA = "0093_phone_welcome"

PREVIOUS_SCHEMA = "0092_whatsapp_matching_fields"

NODE_PREFIXES = {
    "worker": "general",
    "email-worker": "email",
    "email-ai-worker": "email-ai",
    "extraction-worker": "extraction",
    "verification-worker": "verification",
    "visa-ai-worker": "visa-ai",
    "my-photos-worker": "my-photos",
}

WORKERS = (*NODE_PREFIXES, "email-beat")

ACTIVATED = (*WORKERS, "backend", "frontend")

PROJECT_LABEL = "com.docker.compose.project"

SERVICE_LABEL = "com.docker.compose.service"

PUBLIC_URL = "https://tech.gctravels.com"

PROBE_MARKER = "TRAVELLER_RELEASE_PROBE="

CONTROL_PROBE = """
import json, sys
from app.infrastructure.processing.celery_app import celery_app
nodes = json.loads(sys.argv[1])
inspector = celery_app.control.inspect(destination=nodes, timeout=10)
methods = ('ping',) if sys.argv[2] == 'ping' else ('active', 'reserved', 'scheduled')
print('TRAVELLER_RELEASE_PROBE=' + json.dumps({key: getattr(inspector, key)() for key in methods}))
"""

READY_PROBE = """
import urllib.request
with urllib.request.urlopen('http://localhost:8000/api/v1/health/ready', timeout=10) as r:
    assert r.status == 200, r.status
print('Backend readiness: 200')
"""


class ReleaseError(RuntimeError):
    pass


ReleaseError.__module__ = "release_traveller_whatsapp"


def updated_environment(text: str, revision: str, expected_schema: str = SCHEMA) -> str:
    values = {"APP_REVISION": revision, "EXPECTED_DATABASE_SCHEMA_REVISION": expected_schema}
    seen: set[str] = set()
    lines = []
    for line in text.splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Z_]+)\s*=", line)
        key = match.group(1) if match else None
        if key in values:
            if key not in seen:
                lines.append(f"{key}={values[key]}")
                seen.add(key)
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in values.items() if key not in seen)
    return "\n".join(lines) + "\n"


def validate_worker_probe(
    payload: Any, nodes: set[str], *, idle: bool, expected_count: int = 7
) -> None:
    methods = ("active", "reserved", "scheduled") if idle else ("ping",)
    if not isinstance(payload, dict) or set(payload) != set(methods):
        raise ReleaseError("Worker inspection is incomplete; no activation is allowed")
    for method in methods:
        replies = payload[method]
        if not isinstance(replies, dict) or set(replies) != nodes or len(nodes) != expected_count:
            raise ReleaseError(f"{method}: all {expected_count} exact worker nodes must reply")
        for node, tasks in replies.items():
            if idle and (not isinstance(tasks, list) or tasks):
                raise ReleaseError(
                    f"{method}: {node} is busy or returned invalid task data; wait and retry"
                )
            if not idle and (not isinstance(tasks, dict) or tasks.get("ok") != "pong"):
                raise ReleaseError(f"{node} has not become ready")


def image_reference(config: dict[str, Any], images: set[str], service: str) -> str:
    explicit = config["services"][service].get("image")
    if explicit:
        if explicit not in images:
            raise ReleaseError(f"{service}: configured image was not resolved by Compose")
        return str(explicit)
    # Ask Compose which spelling it actually generated (compatibility mode uses '_').
    candidates = {f"{config['name']}-{service}", f"{config['name']}_{service}"} & images
    if len(candidates) != 1:
        raise ReleaseError(f"{service}: unable to resolve one exact Compose image")
    return candidates.pop()


for _export in (updated_environment, validate_worker_probe, image_reference):
    _export.__module__ = "release_traveller_whatsapp"
del _export
