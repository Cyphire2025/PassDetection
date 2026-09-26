"""Single-host, version-preserving storage cutover for the current release.

The old MinIO volume is retained. A new prepare against legacy storage allocates
a fresh target name, so an interrupted/uncertain copy never requires deleting
either the source or a partially copied destination to retry safely.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import uuid
from pathlib import Path
from typing import Any

from database_identity_environment import prepare_environment_defaults
from release_network_identity import shared_service_networks
from release_traveller_whatsapp import ReleaseError
from storage_identity import storage_identity
from storage_writer_fence import StorageWriterFence

STORAGE_IMAGE = "chrislusf/seaweedfs:4.47@sha256:ce9e796f1fe6f06968f4c04bdaf8f678dad9c8acdfef3d244133d71bfa6bf882"


def environment(container: dict[str, Any]) -> dict[str, str]:
    return dict(value.split("=", 1) for value in container["Config"].get("Env", []) if "=" in value)


def data_volume(container: dict[str, Any]) -> str:
    mounts = [value for value in container.get("Mounts", []) if value.get("Destination") == "/data"]
    if len(mounts) != 1 or mounts[0].get("Type") != "volume" or not mounts[0].get("Name"):
        raise ReleaseError("Storage requires one inspected named /data volume; no data directory was changed")
    return str(mounts[0]["Name"])


def set_values(text: str, values: dict[str, str]) -> str:
    lines, seen = [], set()
    for line in text.splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Z_]+)\s*=", line)
        key = match.group(1) if match else ""
        if key in values:
            if key in seen:
                raise ReleaseError("Duplicate storage release configuration key")
            seen.add(key)
            line = f"{key}='{values[key]}'"
        lines.append(line)
    for key, value in values.items():
        if "'" in value or "\n" in value or "\r" in value:
            raise ReleaseError("Storage release path cannot contain quotes or newlines")
        if key not in seen:
            lines.append(f"{key}='{value}'")
    return "\n".join(lines) + "\n"


class StorageRelease:
    def __init__(self, release: Any) -> None:
        self.release = release

    def maintained(self, container: dict[str, Any]) -> bool:
        return container["Image"] == self.release.inspect(STORAGE_IMAGE, image=True)["Id"]

    def prepare_environment(self, text: str) -> str:
        release = self.release
        # Pulling an immutable image does not recreate any current service.
        release.run("docker", "pull", STORAGE_IMAGE, timeout=600)
        current = release.container("minio")
        if self.maintained(current):
            return text
        if not str(current["Config"].get("Image", "")).startswith("minio/minio"):
            raise ReleaseError("Existing storage provider is not the reviewed MinIO source")
        data_volume(current)
        attempt = uuid.uuid4().hex
        directory = release.directory / "storage" / attempt
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        text = prepare_environment_defaults(text, {
            "OBJECT_STORAGE_ADMIN_ACCESS_KEY": "gc_storage_admin_" + secrets.token_hex(8),
            "OBJECT_STORAGE_ADMIN_SECRET_KEY": secrets.token_urlsafe(48),
        })
        return set_values(text, {
            "OBJECT_STORAGE_IDENTITY_FILE": str(directory / "identities.json"),
            "OBJECT_STORAGE_CUTOVER_PROOF": str(directory / "cutover.json"),
            "OBJECT_STORAGE_MIGRATION_DIRECTORY": str(directory),
            "OBJECT_STORAGE_DATA_VOLUME": f"{release.compose[3]}_objects_{attempt}",
        })

    def prepare_identity(self, config: dict[str, Any]) -> None:
        release = self.release
        values = config["services"]["database-admin"]["environment"]
        path = Path(values["OBJECT_STORAGE_IDENTITY_FILE"])
        if not path.resolve().is_relative_to((release.directory / "storage").resolve()) or path.is_symlink():
            raise ReleaseError("Storage identity must stay within the protected release evidence directory")
        document = storage_identity(values)
        if path.exists():
            if path.read_text() != document:
                raise ReleaseError("Existing storage identity differs; secret rotation requires a separate reviewed operation")
            return
        release.write_private(path, document, exclusive=True)
        if os.name == "posix":
            # Parent evidence directory stays 0700. Docker binds this one file
            # directly into the unprivileged provider; no other service sees it.
            if os.geteuid() == 0:
                os.chown(path, 1000, 1000)
            elif os.geteuid() != 1000:
                raise ReleaseError("Storage identity provisioning requires root or the provider UID 1000")
            path.chmod(0o400)

    def validate(self, config: dict[str, Any]) -> None:
        release = self.release
        current = release.container("minio")
        values = config["services"]["database-admin"]["environment"]
        backend = release.container("backend")
        live_app = environment(backend)
        shared = shared_service_networks(backend, current, "minio")
        candidate = config["services"]["backend"]["environment"]
        for name in ("backend", "minio", "storage-stage", "storage-copy"):
            networks = config["services"][name].get("networks", {})
            if not any(config.get("networks", {}).get(network, {}).get("name") in shared for network in networks):
                raise ReleaseError("Prepared storage services do not use the verified application network")
        path = Path(values["OBJECT_STORAGE_IDENTITY_FILE"])
        if path.is_symlink() or not path.is_file() or path.read_text() != storage_identity(values):
            raise ReleaseError("Storage identity drifted from the prepared credentials/policy")
        expected_volume = values["OBJECT_STORAGE_DATA_VOLUME"]
        if config.get("volumes", {}).get("object_storage_data", {}).get("name") != expected_volume:
            raise ReleaseError("Rendered storage volume differs from the prepared destination")
        for name in ("minio", "storage-stage"):
            mounts = config["services"][name].get("volumes", [])
            if not any(mount.get("source") == "object_storage_data" and mount.get("target") == "/data" for mount in mounts):
                raise ReleaseError("Prepared provider does not mount the distinct target volume")
            if not any(mount.get("source") == str(path) and mount.get("target") == "/run/secrets/s3.json" and mount.get("read_only") is True for mount in mounts):
                raise ReleaseError("Prepared provider does not mount the verified identity read-only")
        for name in ("S3_ENDPOINT_URL", "S3_BUCKET_NAME", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_PUBLIC_ENDPOINT_URL"):
            if live_app.get(name, "") != candidate.get(name, ""):
                raise ReleaseError("Storage release cannot change the live bucket, endpoints or application credentials")
        if candidate.get("S3_ENDPOINT_URL") != "http://minio:9000":
            raise ReleaseError("This cutover only supports the existing local minio:9000 endpoint")
        if self.maintained(current):
            proof = Path(values["OBJECT_STORAGE_CUTOVER_PROOF"])
            if not proof.is_file() or proof.is_symlink():
                raise ReleaseError("The maintained provider has no verified cutover evidence")
            document = json.loads(proof.read_text())
            identity_digest = hashlib.sha256(Path(values["OBJECT_STORAGE_IDENTITY_FILE"]).read_bytes()).hexdigest()
            if (document.get("target_volume") != data_volume(current)
                    or expected_volume != data_volume(current)
                    or document.get("bucket") != candidate["S3_BUCKET_NAME"]
                    or document.get("identity_sha256") != identity_digest):
                raise ReleaseError("Storage cutover evidence does not match the current data volume/bucket")
            if not any(mount.get("Source") == str(path) and mount.get("Destination") == "/run/secrets/s3.json" and mount.get("RW") is False for mount in current.get("Mounts", [])):
                raise ReleaseError("The active provider identity mount differs from the verified configuration")
        else:
            live = environment(current)
            if any(live.get(key) != values.get(key) or not live.get(key) for key in ("MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD")):
                raise ReleaseError("Storage source administrator differs from the running provider")
            if data_volume(current) == values["OBJECT_STORAGE_DATA_VOLUME"]:
                raise ReleaseError("Source and target storage volumes must be distinct")

    def activate(self, config: dict[str, Any]) -> None:
        release = self.release
        self.validate(config)
        original = release.container("minio")
        if self.maintained(original):
            return
        values = config["services"]["database-admin"]["environment"]
        writers = [release.container(name) for name in (*release.workers, "backend")]
        fence = StorageWriterFence(release)
        copy_image = json.loads(release.pin_path.read_text())["services"]["storage-copy"]["image"]
        copy_name = fence.begin(original, writers, config, release.inspect(STORAGE_IMAGE, image=True)["Id"], copy_image)
        release.say("Fencing existing application writers for a verified version-preserving storage copy")
        try:
            release.dc("stop", "--timeout", "180", *release.workers, "backend", timeout=900)
            for container in writers:
                stopped = release.inspect(container["Id"])
                if stopped["State"].get("Running") or stopped["State"].get("ExitCode") != 0:
                    raise ReleaseError("An application writer did not stop cleanly; storage copy was not attempted")
            release.dc("up", "-d", "--no-deps", "--wait", "--wait-timeout", "180", "storage-stage", timeout=240)
            stage = release.container("storage-stage")
            if data_volume(stage) != values["OBJECT_STORAGE_DATA_VOLUME"] or data_volume(stage) == data_volume(original):
                raise ReleaseError("Inspected staging volume is not the separate prepared destination")
            space = release.dc("exec", "-T", "storage-stage", "df", "-Pk", "/data").splitlines()
            columns = space[-1].split() if space else []
            if len(columns) < 6 or not columns[3].isdigit():
                raise ReleaseError("Could not measure the destination volume's free disk space")
            available = int(columns[3]) * 1024
            report = json.loads(release.dc("run", "--rm", "--no-deps", "--name", copy_name, *fence.copy_labels(),
                                          "-e", f"STORAGE_AVAILABLE_BYTES={available}", "storage-copy", pinned=True, timeout=7200))
            fence.stop_copy()
            if report.get("every_copied_body_sha256_verified") is not True or report.get("source_deleted") is not False:
                raise ReleaseError("Storage copy did not return verified preservation evidence")
            proof = {**report, "source_volume": data_volume(original), "target_volume": data_volume(stage),
                     "identity_sha256": hashlib.sha256(Path(values["OBJECT_STORAGE_IDENTITY_FILE"]).read_bytes()).hexdigest()}
            release.write_private(Path(values["OBJECT_STORAGE_CUTOVER_PROOF"]), json.dumps(proof, indent=2) + "\n")
            fence.verified_target()
            # Both provider processes must never open the same embedded metadata
            # store concurrently. Stop staging before recreating the stable name.
            release.dc("stop", "--timeout", "60", "storage-stage", timeout=90)
            stopped_stage = release.inspect(stage["Id"])
            if stopped_stage["State"].get("Running") or stopped_stage["State"].get("ExitCode") != 0:
                raise ReleaseError("Staging did not stop cleanly; the stable provider was not replaced")
            fence.begin_handoff()
            release.dc("up", "-d", "--no-deps", "--wait", "--wait-timeout", "180", "minio", timeout=240)
            active = release.container("minio")
            if not self.maintained(active) or data_volume(active) != data_volume(stage):
                raise ReleaseError("Storage activation did not use the verified provider and volume")
        finally:
            # Recovery is also called before normal preflight on the next CLI
            # invocation, covering a killed helper that never reaches finally.
            # An ambiguous provider handoff keeps writers fenced for review.
            fence.restore()
