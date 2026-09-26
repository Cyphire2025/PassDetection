"""Bind a live application's Docker hostname to one inspected service."""

import re
from typing import Any

from release_traveller_whatsapp import ReleaseError


def shared_service_networks(
    application: dict[str, Any], service: dict[str, Any], hostname: str,
) -> set[str]:
    extra_hosts = application.get("HostConfig", {}).get("ExtraHosts") or []
    if any(re.split(r"[:=]", str(host), maxsplit=1)[0] == hostname for host in extra_hosts):
        raise ReleaseError(f"Live application overrides the {hostname} hostname; verify its actual target")
    application_networks = application.get("NetworkSettings", {}).get("Networks", {})
    service_networks = service.get("NetworkSettings", {}).get("Networks", {})
    if not isinstance(application_networks, dict) or not isinstance(service_networks, dict):
        raise ReleaseError("Cannot verify live service network identity")
    shared = {
        name for name, endpoint in application_networks.items()
        if isinstance(endpoint, dict) and endpoint.get("NetworkID")
        and isinstance(service_networks.get(name), dict)
        and endpoint["NetworkID"] == service_networks[name].get("NetworkID")
        and hostname in (service_networks[name].get("Aliases") or [])
    }
    if not shared:
        raise ReleaseError(f"Live application and {hostname} do not share a verified network and DNS alias")
    return shared
