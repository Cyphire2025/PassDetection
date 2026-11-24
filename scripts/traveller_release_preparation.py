"""Build and bind prepared images before any activation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from traveller_release_contract import (
    ReleaseError,
    image_reference,
)
from traveller_release_readiness import _ReleaseReadiness


class _ReleasePreparation(_ReleaseReadiness):
    if TYPE_CHECKING:
        manifest_path: Path

        def prepare_recovery(self, config: dict[str, Any]) -> None: ...

    def prepare(self) -> None:
        self.say("Checking the exact checkout and existing Compose project")
        config = self.preflight()
        fingerprint = self.config_fingerprint(config)
        references = set(self.dc("config", "--images").splitlines())
        refs = {
            service: image_reference(config, references, service)
            for service in self.activated_services
        }
        if any(refs[service] != refs["worker"] for service in self.workers):
            raise ReleaseError(
                f"All {len(self.node_prefixes)} workers and beat must share the configured worker image"
            )
        self.prepare_recovery(config)
        images = self.prepare_images(config, refs)
        # Recheck Git/environment after a potentially long build before recording it.
        after = self.preflight()
        if self.config_fingerprint(after) != fingerprint:
            raise ReleaseError("Compose settings changed during the build; prepare again")
        manifest = {
            "version": 1,
            "revision": self.revision,
            "schema": self.expected_schema,
            "project": config["name"],
            "config_fingerprint": fingerprint,
            "images": images,
            "references": refs,
        }
        self.write_private(self.manifest_path, json.dumps(manifest, indent=2) + "\n")
        self.say("PREPARED: images verified. Pause new uploads and message sends before activate.")

    def prepare_images(self, config: dict[str, Any], refs: dict[str, str]) -> dict[str, str]:
        """Historical releases build locally; the current release can consume promoted images."""
        build_services = tuple(
            service
            for service in ("backend", "worker", "frontend")
            if service in self.activated_services
        )
        self.say(f"Building {', '.join(build_services)}; current containers stay running")
        self.dc(
            "build",
            "--build-arg",
            f"APP_REVISION={self.revision}",
            *build_services,
            timeout=7200,
            stream=True,
        )
        return {
            service: self.verify_image(refs[service], backend=service != "frontend")
            for service in self.activated_services
        }


# Keep original public method/pickle names through the stable facade.
for _name in ("prepare", "prepare_images"):
    _member = vars(_ReleasePreparation)[_name]
    _function = _member.__func__ if isinstance(_member, staticmethod) else _member
    _function.__module__ = "release_traveller_whatsapp"
    _function.__qualname__ = "Release." + _name
del _name, _member, _function
