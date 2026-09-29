"""Local retained application-container clones; no removal or force-stop operations."""
from __future__ import annotations

import copy
import http.client
import json
import os
import re
import socket
import sys
import time
from urllib.parse import urlencode

SERVICES = {"backend", "frontend", "worker", "email-worker", "email-ai-worker", "email-beat",
            "extraction-worker", "verification-worker", "visa-ai-worker", "my-photos-worker", "ecr-worker", "nginx"}
ID = re.compile("[a-f0-9]{64}")
NAME = re.compile("[a-z0-9][a-z0-9_-]{0,100}")


class ContainerError(ValueError):
    pass


def service_of(container: dict) -> str:
    service = (container.get("Config", {}).get("Labels") or {}).get("com.docker.compose.service")
    if service not in SERVICES or not ID.fullmatch(container.get("Id", "")):
        raise ContainerError("application_container_required")
    return service


def clone_payload(original: dict, *, name: str, image_id: str, environment: dict[str, str],
                  new_project: str, source_root: str, aliases: dict[str, str],
                  nginx_mount_overrides: dict[str, str] | None = None) -> dict:
    service = service_of(original)
    if (not NAME.fullmatch(name) or name == original.get("Name", "").lstrip("/")
            or not NAME.fullmatch(new_project) or not re.fullmatch("sha256:[a-f0-9]{64}", image_id)
            or not source_root.startswith("/opt/GlobalConnectsDashboard/tmp/mcp-direct-")
            or not source_root.endswith("/source") or "/../" in source_root):
        raise ContainerError("invalid_candidate_binding")
    config, host = copy.deepcopy(original["Config"]), copy.deepcopy(original["HostConfig"])
    if (type(host.get("Memory")) is not int or host["Memory"] <= 0
            or type(host.get("NanoCpus")) is not int or host["NanoCpus"] <= 0
            or host.get("Privileged") is not False or host.get("AutoRemove") is True):
        raise ContainerError("unsafe_original_resource_policy")
    ports = host.get("PortBindings") or {}
    if service != "nginx" and ports:
        raise ContainerError("application_host_ports_forbidden")
    if service == "nginx" and any(
        port not in {"80/tcp", "443/tcp"}
        or any(binding.get("HostPort") != port.split("/")[0] for binding in bindings)
        for port, bindings in ports.items()
    ):
        raise ContainerError("unreviewed_proxy_ports")
    networks = original["NetworkSettings"]["Networks"]
    if not networks or set(aliases) != set(networks) or host.get("NetworkMode") not in networks:
        raise ContainerError("exact_original_network_required")
    endpoints = {}
    for network, entry in networks.items():
        alias = aliases[network]
        if not NAME.fullmatch(alias) or alias in (entry.get("Aliases") or []):
            raise ContainerError("candidate_must_use_unique_alias")
        endpoints[network] = {"NetworkID": entry["NetworkID"], "Aliases": [alias]}
    if any(not isinstance(key, str) or not re.fullmatch("[A-Za-z_][A-Za-z0-9_]*", key)
           or not isinstance(value, str) or "\0" in value for key, value in environment.items()):
        raise ContainerError("invalid_environment")
    config.update(Image=image_id, Env=[f"{key}={value}" for key, value in sorted(environment.items())], Hostname=name)
    # Docker create treats null as "inherit from image". An original without
    # an entrypoint must explicitly clear any candidate image build entrypoint.
    config["Entrypoint"] = config.get("Entrypoint") or []
    config["Labels"] = {**(config.get("Labels") or {}), "com.docker.compose.project": new_project,
                        "com.docker.compose.project.working_dir": source_root,
                        "com.docker.compose.oneoff": "False", "com.docker.compose.service": service,
                        "globalconnects.retained_original": original["Id"]}
    # Old Compose config-file labels cannot authorize management of this clone.
    config["Labels"].pop("com.docker.compose.project.config_files", None)
    if nginx_mount_overrides:
        if service != "nginx" or set(nginx_mount_overrides) != {"/etc/nginx/nginx.conf", "/etc/nginx/conf.d"}:
            raise ContainerError("invalid_proxy_mount_override")
        binds = list(host.get("Binds") or [])
        for destination, replacement in nginx_mount_overrides.items():
            release_root = source_root.removesuffix("/source")
            if not replacement.startswith(release_root + "/runtime-nginx/") or "/../" in replacement:
                raise ContainerError("invalid_proxy_source_path")
            matching = [index for index, binding in enumerate(binds)
                        if binding.split(":")[1:] == [destination, "ro"]]
            if len(matching) != 1:
                raise ContainerError("proxy_readonly_bind_required")
            binds[matching[0]] = f"{replacement}:{destination}:ro"
        host["Binds"] = binds
    return {**config, "HostConfig": host, "NetworkingConfig": {"EndpointsConfig": endpoints}}


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, *, timeout: int = 15):
        super().__init__("localhost", timeout=timeout)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


class LocalDocker:
    def __init__(self):
        if sys.platform != "linux" or os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
            raise ContainerError("local_linux_docker_required")

    def request(self, method: str, path: str, payload: dict | None = None, *, timeout: int = 15):
        if type(timeout) is not int or not 1 <= timeout <= 120:
            raise ContainerError("invalid_docker_request_timeout")
        connection = UnixConnection(timeout=timeout)
        try:
            body = json.dumps(payload).encode() if payload is not None else None
            connection.request(method, "/v1.45" + path, body, {"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024 or not 200 <= response.status < 300:
                raise ContainerError("docker_request_failed")
            return json.loads(raw) if raw else None
        except (OSError, ValueError, http.client.HTTPException):
            raise ContainerError("docker_request_failed") from None
        finally:
            connection.close()

    @staticmethod
    def identifier(value: str) -> str:
        if not ID.fullmatch(value):
            raise ContainerError("exact_container_id_required")
        return value

    def inspect(self, identifier: str) -> dict:
        result = self.request("GET", f"/containers/{self.identifier(identifier)}/json")
        if not isinstance(result, dict) or result.get("Id") != identifier:
            raise ContainerError("container_identity_changed")
        return result

    def list_containers(self, *, all: bool = True) -> list:
        result = self.request("GET", "/containers/json?" + urlencode({"all": int(all)}))
        if not isinstance(result, list):
            raise ContainerError("container_inventory_unavailable")
        return result

    def create_clone(self, original: dict, **options) -> str:
        payload = clone_payload(original, **options)
        result = self.request("POST", "/containers/create?" + urlencode({"name": options["name"]}), payload)
        return self.identifier(result.get("Id", ""))

    def start(self, identifier: str) -> None:
        service_of(self.inspect(identifier))
        self.request("POST", f"/containers/{self.identifier(identifier)}/start")

    def graceful_stop(self, identifier: str, *, timeout: int = 60) -> dict:
        if not 1 <= timeout <= 120:
            raise ContainerError("invalid_drain_timeout")
        current = self.inspect(identifier)
        service = service_of(current)
        if not current["State"]["Running"]:
            return current
        signal = "QUIT" if service == "nginx" else "TERM"
        self.request("POST", f"/containers/{identifier}/kill?signal={signal}")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = self.inspect(identifier)
            if not current["State"]["Running"]:
                return current
            time.sleep(0.25)
        raise ContainerError("container_still_draining_no_force_stop")
