"""Direct release staging responsibilities."""

from __future__ import annotations

import json
import re

from mcp_activation_contract import WRITERS, environment, render_proxy, runtime_environment
from mcp_activation_identity import _ActivationIdentity
from mcp_direct_build import BuildError, command
from mcp_direct_release import bound_original, inspect
from mcp_direct_state import ROOT, private_json


class _ActivationStaging(_ActivationIdentity):
    def stage(self, *, candidate_receipt: str = "candidates.private.json") -> None:
        if not re.fullmatch(r"candidates(?:-[a-z0-9-]{1,40})?\.private\.json", candidate_receipt):
            raise BuildError("invalid_retained_candidate_receipt")
        if (self.state.directory / candidate_receipt).exists():
            raise BuildError("candidate_stage_already_retained")
        for original in self.originals.values():
            if not bound_original(original)["State"]["Running"]:
                raise BuildError("stage_requires_original_services_running")
        self.memory_checkpoint(
            "stage", self.originals, first=not hasattr(self, "_retry_baseline_path")
        )
        # Resolve existing maintenance credentials without changing roles or .env.
        resolved = json.loads(
            command(
                "docker",
                "compose",
                "--project-directory",
                str(ROOT),
                "--env-file",
                str(ROOT / ".env"),
                "-f",
                str(ROOT / "docker-compose.yml"),
                "-f",
                str(ROOT / "docker-compose.prod.yml"),
                "--profile",
                "maintenance",
                "config",
                "--format",
                "json",
            )
        )
        maintenance = resolved["services"]["database-migrate"]["environment"]
        credentials = {key: maintenance[key] for key in ("POSTGRES_USER", "POSTGRES_PASSWORD")}
        if any(not isinstance(value, str) or not value for value in credentials.values()):
            raise BuildError("existing_migration_credentials_unavailable")
        credential_path = self.state.directory / "migration-credentials.private.json"
        if credential_path.exists():
            if (
                credential_path.is_symlink()
                or json.loads(credential_path.read_text()) != credentials
            ):
                raise BuildError("retained_migration_credentials_changed")
        else:
            private_json(credential_path, credentials)
        proxy = self.state.directory / "runtime-nginx" / self.project
        proxy.mkdir(mode=0o700, parents=True)
        for relative in ("nginx.conf", "conf.d"):
            source = self.state.source / "nginx" / relative
            paths = [source] if source.is_file() else sorted(source.rglob("*"))
            for path in paths:
                if not path.is_file():
                    continue
                target = proxy / path.relative_to(self.state.source / "nginx")
                target.parent.mkdir(parents=True, exist_ok=True)
                raw = path.read_bytes()
                if relative == "nginx.conf":
                    raw = render_proxy(
                        raw.decode(),
                        next(iter(self.aliases("backend").values())),
                        next(iter(self.aliases("frontend").values())),
                    ).encode()
                with target.open("xb") as stream:
                    stream.write(raw)
        candidates = {}
        for service in sorted(WRITERS):
            original = self.originals[service]
            image_id = (
                original["Image"]
                if service == "nginx"
                else self.images["frontend" if service == "frontend" else "backend"]["image_id"]
            )
            overrides = (
                {
                    "/etc/nginx/nginx.conf": str(proxy / "nginx.conf"),
                    "/etc/nginx/conf.d": str(proxy / "conf.d"),
                }
                if service == "nginx"
                else None
            )
            identifier = self.client.create_clone(
                original,
                name=f"{self.project}-{service}",
                image_id=image_id,
                environment=environment(original)
                if service == "nginx"
                else runtime_environment(original, self.state.revision),
                new_project=self.project,
                source_root=str(self.state.source),
                aliases=self.aliases(service),
                nginx_mount_overrides=overrides,
            )
            candidates[service] = inspect(identifier)
            self.state.event(
                "candidate-container-retained", service=service, container_id=identifier
            )
        private_json(self.state.directory / candidate_receipt, candidates)
        self.candidate_receipt = candidate_receipt
        self.state.verify_retention(self.baseline)
        self.state.event("candidate-stage-complete")


# Keep canonical public method and pickle aliases in the stable facade.
for _name in ("stage",):
    _function = vars(_ActivationStaging)[_name]
    _function.__module__ = "mcp_direct_activate"
    _function.__qualname__ = "DirectActivation." + _name
del _name, _function
