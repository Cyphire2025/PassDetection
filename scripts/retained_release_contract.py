"""Retained release selection, readiness and immutable source contracts."""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

import release_pdf_checking_profile as pdf_profile
from mcp_direct_build import BuildError
from mcp_direct_state import APPLICATION, INFRASTRUCTURE
from release_code_update import environment, validate_readiness
from release_traveller_whatsapp import ReleaseError

ROOT = Path("/opt/GlobalConnectsDashboard")
SCHEMA = "0129_travel_tracker"
REVISION = re.compile(r"[a-f0-9]{40}")
ACTIVE = APPLICATION | {"nginx"}
SERVICES = ACTIVE | INFRASTRUCTURE
ORIGIN = "https://tech.gctravels.com"
# Full CI may qualify build changes; persistent/task/state contracts remain frozen.
FULL_BUILD_PATHS = (
    "backend/Dockerfile",
    "frontend/Dockerfile",
    "backend/requirements",
    "frontend/package",
    "frontend/tooling/",
    "frontend/scripts/",
    "backend/docker/",
    "frontend/next.config.",
    "backend/.dockerignore",
    "frontend/.dockerignore",
    ".dockerignore",
)
ADDITIONAL_CONTRACT_PATHS = (
    "frontend/tooling",
    "frontend/scripts",
    "backend/docker",
    "frontend/next.config.*",
    "backend/gunicorn.conf.py",
    ".dockerignore",
    "backend/.dockerignore",
    "frontend/.dockerignore",
)
ROUTE_ALLOWLIST = "backend/app/core/config/frontend_route_templates.json"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def wait_full_readiness(probe: Callable[[], dict[str, Any]], revision: str) -> None:
    """Allow bounded worker warmup; every accepted sample uses all release gates."""
    consecutive = 0
    for attempt in range(12):
        try:
            payload = probe()
            # A reachable wrong release is a binding failure, not warmup.
            require(payload.get("revision") == revision, "readiness_revision_mismatch")
            validate_readiness(payload, revision, full=True)
            consecutive += 1
            if consecutive == 2:
                return
        except (
            BuildError,
            ReleaseError,
            OSError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
        ):
            consecutive = 0
        if attempt < 11:
            time.sleep(5)
    raise ValueError("full_readiness_did_not_stabilize")


def select_live(
    rows: list[dict[str, Any]],
    root: Path = ROOT,
    *,
    schema: str = SCHEMA,
    paused_services: frozenset[str] = frozenset(),
) -> dict[str, dict[str, Any]]:
    require(paused_services <= pdf_profile.PAUSED, "unreviewed_paused_services")
    resolved_root = PurePosixPath(root.as_posix())
    selected = {}
    for row in rows:
        labels = row.get("Config", {}).get("Labels") or {}
        name = labels.get("com.docker.compose.service")
        if not isinstance(name, str):
            raise ValueError("ambiguous_running_service_inventory")
        require(name in SERVICES and name not in selected, "ambiguous_running_service_inventory")
        require(
            row.get("State", {}).get("Running") is True
            or name in paused_services
            and labels.get(pdf_profile.LABEL) == pdf_profile.PROFILE
            and row.get("HostConfig", {}).get("RestartPolicy", {}).get("Name") == "no",
            "live_service_not_running",
        )
        work = PurePosixPath(labels.get("com.docker.compose.project.working_dir", ""))
        require(
            work.is_absolute()
            and ".." not in work.parts
            and (work == resolved_root or work.is_relative_to(resolved_root / "tmp")),
            "live_working_directory_outside_root",
        )
        require(labels.get("com.docker.compose.oneoff") == "False", "unexpected_oneoff_service")
        selected[name] = row
    require(set(selected) == SERVICES, "exact_live_service_inventory_required")
    app_projects = {
        selected[name]["Config"]["Labels"].get("com.docker.compose.project") for name in ACTIVE
    }
    require(len(app_projects) == 1 and None not in app_projects, "mixed_live_application_projects")
    revisions = {
        environment(selected[name]).get("APP_REVISION") for name in APPLICATION - {"frontend"}
    }
    require(
        len(revisions) == 1 and REVISION.fullmatch(next(iter(revisions)) or "") is not None,
        "mixed_live_application_revisions",
    )
    require(
        environment(selected["frontend"]).get("NEXT_PUBLIC_APP_REVISION") == next(iter(revisions)),
        "mixed_live_frontend_revision",
    )
    require(
        all(
            environment(selected[name]).get("EXPECTED_DATABASE_SCHEMA_REVISION") == schema
            for name in APPLICATION - {"frontend"}
        ),
        "live_schema_environment_changed",
    )
    return selected


def forbidden_changes(
    paths: list[str], mode: str, *, route_allowlist_validated: bool = False
) -> list[str]:
    require(mode in {"full", "fast"}, "explicit_release_mode_required")
    return [
        path
        for path in paths
        if not (
            path == ROUTE_ALLOWLIST
            and route_allowlist_validated
            or mode == "full"
            and path.startswith(FULL_BUILD_PATHS)
        )
    ]


def validate_route_allowlist(source: Path) -> None:
    backend = json.loads((source / ROUTE_ALLOWLIST).read_text())
    frontend = json.loads((source / "frontend/lib/observability/route-templates.json").read_text())
    require(
        isinstance(backend, list)
        and backend == frontend
        and all(isinstance(item, str) for item in backend),
        "route_allowlists_differ",
    )
    require(
        len(backend) == len(set(backend)) and len(backend) <= 1000,
        "route_allowlist_budget_or_duplicates",
    )
    # Derive the contract from actual App Router pages. Dynamic values must be
    # bracketed placeholders; no URL/query/body values can enter this allowlist.
    expected = {"unknown"}
    app = source / "frontend/app"
    for page in app.rglob("page.tsx"):
        segments = [
            part
            for part in page.relative_to(app).parts[:-1]
            if not (part.startswith("(") and part.endswith(")"))
        ]
        require(
            all(
                re.fullmatch(r"(?:[a-z][a-z0-9-]*|\[[A-Za-z][A-Za-z0-9]*\])", part)
                for part in segments
            ),
            "unreviewed_route_template_grammar",
        )
        expected.add("/" + "/".join(segments))
    require(set(backend) == expected, "route_allowlist_must_match_actual_pages")


def runtime_environment(
    original: dict[str, Any], revision: str, *, schema: str = SCHEMA
) -> dict[str, str]:
    result = environment(original)
    service = original["Config"]["Labels"]["com.docker.compose.service"]
    if service == "frontend":
        result["NEXT_PUBLIC_APP_REVISION"] = revision
    elif service != "nginx":
        result.update(APP_REVISION=revision, EXPECTED_DATABASE_SCHEMA_REVISION=schema)
    return result


def proxy_configuration(config: str, active: dict[str, Any], project: str) -> str:
    for service, port in (("backend", 8000), ("frontend", 3000)):
        aliases = {
            alias
            for network in active[service]["NetworkSettings"]["Networks"].values()
            for alias in network.get("Aliases") or []
        }
        pattern = rf"(upstream\s+{service}\s*\{{\s*server\s+)([a-z0-9_-]+)(:{port};)"
        matches = list(re.finditer(pattern, config))
        require(
            len(matches) == 1 and matches[0].group(2) in aliases, "proxy_upstream_binding_changed"
        )
        config = re.sub(pattern, lambda m: m[1] + project + "-" + service + m[3], config)
    return config


for _name in (
    "require",
    "wait_full_readiness",
    "select_live",
    "forbidden_changes",
    "validate_route_allowlist",
    "runtime_environment",
    "proxy_configuration",
):
    globals()[_name].__module__ = "release_retained_update"
del _name
