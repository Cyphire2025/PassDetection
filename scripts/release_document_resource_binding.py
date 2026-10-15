"""Bind an orphaned, stopped Redis create to its exact retained create intent."""
from __future__ import annotations

from mcp_direct_release import _bound_host_config
from release_retained_update import require


def verify_payload(row: dict, payload: dict) -> None:
    config = {key: value for key, value in payload.items() if key not in {"HostConfig", "NetworkingConfig"}}
    require(all(row["Config"].get(key) == value for key, value in config.items()),
            "orphaned_redis_configuration_changed")
    # Docker omits an empty API Mounts array from the inspect representation.
    actual_host = {**row["HostConfig"], "Mounts": row["HostConfig"].get("Mounts") or []}
    require(all(_bound_host_config(actual_host).get(key) == value
                for key, value in _bound_host_config(payload["HostConfig"]).items()),
            "orphaned_redis_host_configuration_changed")
    networks = payload["NetworkingConfig"]["EndpointsConfig"]
    actual = row["NetworkSettings"]["Networks"]
    require(set(actual) == set(networks) and all(actual[key]["NetworkID"] == value["NetworkID"]
            and set(actual[key].get("Aliases") or []) == set(value["Aliases"]) for key, value in networks.items()),
            "orphaned_redis_network_configuration_changed")
