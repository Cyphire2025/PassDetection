"""Exact container operations, candidate staging and readiness proofs."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import release_pdf_checking_profile as pdf_profile
from mcp_direct_activate import clean_stop
from mcp_direct_build import command
from mcp_direct_containers import clone_payload
from mcp_direct_release import bound_original
from release_code_update import environment
from retained_release_contract import (
    ACTIVE,
    ORIGIN,
    ROOT,
    proxy_configuration,
    require,
    runtime_environment,
    wait_full_readiness,
)
from retained_release_host import _RetainedHost


class _RetainedRuntime(_RetainedHost):
    def stop(self, row: dict[str, Any]) -> None:
        clean_stop(self.client.graceful_stop(row["Id"], timeout=120), row)

    def fence_candidate(self, row: dict[str, Any]) -> None:
        # A failed replacement can already have exited with an error or OOM.
        # Recovery requires absence of writers, not a successful candidate exit.
        current = bound_original(row)
        if current["State"]["Running"]:
            current = self.client.graceful_stop(row["Id"], timeout=120)
        require(not current["State"]["Running"], "candidate_still_running_blocks_recovery")
        states = self.record.setdefault("recovery_candidate_states", {})
        states[row["Id"]] = current["State"]
        self.event("candidate-fenced")

    def start(self, row: dict[str, Any]) -> None:
        # Every operation uses a retained exact ID; no name-based removal/recreate.
        current = bound_original(row)
        if not current["State"]["Running"]:
            self.client.start(row["Id"])

    def wait_health(self, rows: dict[str, Any]) -> None:
        rows = {name: row for name, row in rows.items() if name not in self.paused_services()}
        for _ in range(120):
            current = {name: bound_original(row) for name, row in rows.items()}
            if all(
                row["State"].get("Running")
                and (
                    row["State"].get("Health", {}).get("Status") == "healthy"
                    or name in {"frontend", "nginx"}
                    and not row["Config"].get("Healthcheck")
                )
                for name, row in current.items()
            ):
                return
            require(
                not any(row["State"].get("OOMKilled") for row in current.values()), "candidate_oom"
            )
            time.sleep(2)
        raise ValueError("health_checks_did_not_pass")

    def proof(self, rows: dict[str, Any], revision: str, *, public: bool) -> None:
        self.wait_health(rows)
        backend = rows["backend"]["Id"]
        code = "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready',timeout=20))))"
        wait_full_readiness(
            lambda: json.loads(command("docker", "exec", backend, "python", "-c", code)), revision
        )
        frontend = "Promise.all(['/login','/pwa-icon-192.png'].map(async p=>{let r=await fetch('http://127.0.0.1:3000'+p);if(r.status!==200)throw Error('probe')})).catch(()=>process.exit(1))"
        command("docker", "exec", rows["frontend"]["Id"], "node", "-e", frontend)
        require(
            environment(bound_original(rows["frontend"])).get("NEXT_PUBLIC_APP_REVISION")
            == revision,
            "frontend_runtime_revision_changed",
        )
        if public:
            wait_full_readiness(
                lambda: json.loads(
                    command(
                        "curl",
                        "--fail",
                        "--silent",
                        "--show-error",
                        "--max-time",
                        "30",
                        ORIGIN + "/api/v1/health/ready",
                    )
                ),
                revision,
            )
            # Bind served browser bytes, not just the container environment.
            script = """
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const revision=process.argv[1],root='/app/.next/static';let found;
function walk(dir){for(const item of fs.readdirSync(dir,{withFileTypes:true})){const file=path.join(dir,item.name);
 if(item.isDirectory())walk(file);else if(!found&&file.endsWith('.js')){const raw=fs.readFileSync(file);
 if(raw.includes(Buffer.from(revision)))found={path:'/_next/static/'+path.relative(root,file),sha256:crypto.createHash('sha256').update(raw).digest('hex')};}}}
walk(root);if(!found)throw Error('revision asset absent');console.log(JSON.stringify(found));
"""
            asset = json.loads(
                command("docker", "exec", rows["frontend"]["Id"], "node", "-e", script, revision)
            )
            if not isinstance(asset, dict):
                raise ValueError("invalid_frontend_revision_asset")
            require(
                isinstance(asset.get("path"), str)
                and re.fullmatch(r"/_next/static/[A-Za-z0-9_./%@()!~-]+\.js", asset["path"])
                is not None
                and ".." not in asset["path"],
                "invalid_frontend_revision_asset",
            )
            raw = subprocess.check_output(
                [
                    "curl",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--max-time",
                    "30",
                    ORIGIN + asset["path"],
                ],
                timeout=40,
            )
            require(
                hashlib.sha256(raw).hexdigest() == asset["sha256"],
                "public_frontend_revision_asset_mismatch",
            )
        self.retention()

    def candidate_environment(self, original: dict[str, Any]) -> dict[str, str]:
        result = runtime_environment(original, self.revision, schema=self.candidate_schema)
        name = original["Config"]["Labels"]["com.docker.compose.service"]
        if self.paused_services() and name not in {"frontend", "nginx"}:
            result.update(pdf_profile.DISABLED)
        return result

    def create_candidate(self, original: dict[str, Any], options: dict[str, Any]) -> str:
        if self.paused_services():
            return pdf_profile.create_candidate(self.client, original, options)
        return self.client.create_clone(original, **options)

    def stage(self, images: dict[str, Any]) -> dict[str, Any]:
        live = self.record["live"]
        proxy = self.directory / "runtime-nginx" / self.project
        proxy.mkdir(mode=0o700, parents=True)
        mounts = {entry["Destination"]: entry for entry in live["nginx"]["Mounts"]}
        for destination, filename in (
            ("/etc/nginx/nginx.conf", "nginx.conf"),
            ("/etc/nginx/conf.d", "conf.d"),
        ):
            mount = mounts[destination]
            origin = Path(mount["Source"])
            require(
                mount["Type"] == "bind"
                and mount.get("RW") is False
                and origin.resolve() == origin
                and origin.is_relative_to(ROOT),
                "proxy_mount_contract_changed",
            )
            if origin.is_dir():
                require(
                    not any(item.is_symlink() for item in origin.rglob("*")),
                    "proxy_symlink_forbidden",
                )
                shutil.copytree(origin, proxy / filename)
            else:
                (proxy / filename).write_text(
                    proxy_configuration(origin.read_text(), live, self.project)
                )
        candidates = {}
        for name in sorted(ACTIVE):
            old = live[name]
            image = (
                old["Image"]
                if name == "nginx"
                else images["frontend" if name == "frontend" else "backend"]
            )
            options = dict(
                name=self.project + "-" + name,
                image_id=image,
                environment=self.candidate_environment(old),
                new_project=self.project,
                source_root=str(self.source),
                aliases={
                    network: self.project + "-" + name
                    for network in old["NetworkSettings"]["Networks"]
                },
            )
            if name == "nginx":
                options["nginx_mount_overrides"] = {
                    "/etc/nginx/nginx.conf": str(proxy / "nginx.conf"),
                    "/etc/nginx/conf.d": str(proxy / "conf.d"),
                }
            clone_payload(
                old, **options
            )  # Reject unsafe inherited launch policy before any create.
            identifier = self.create_candidate(old, options)
            candidates[name] = self.client.inspect(identifier)
            self.event("candidate-created", candidates=candidates)
        return candidates


# Preserve public method aliases and pickle identities through the compatibility facade.
for _name in (
    "stop",
    "fence_candidate",
    "start",
    "wait_health",
    "proof",
    "candidate_environment",
    "create_candidate",
    "stage",
):
    _function = vars(_RetainedRuntime)[_name]
    _function.__module__ = "release_retained_update"
    _function.__qualname__ = "RetainedUpdate." + _name
del _name, _function
