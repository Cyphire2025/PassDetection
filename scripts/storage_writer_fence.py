"""Durable, single-host writer recovery without guessing an authoritative store.

The release CLI's project lock serializes callers. Checkpoints contain inspected
identities, never credentials. A crash can delay availability, but must never
cause an automatic switch back to a source that lacks newer destination writes.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from release_network_identity import shared_service_networks
from release_traveller_whatsapp import PROJECT_LABEL, SERVICE_LABEL, ReleaseError

WORKING_DIRECTORY_LABEL = "com.docker.compose.project.working_dir"


def _volume(container: dict[str, Any]) -> str:
    mounts = [item for item in container.get("Mounts", []) if item.get("Destination") == "/data"]
    if len(mounts) != 1 or mounts[0].get("Type") != "volume" or not mounts[0].get("Name"):
        raise ReleaseError("Cannot recover writers without one verified storage data volume")
    return str(mounts[0]["Name"])


def _identity(container: dict[str, Any], service: str, project: str, root: Path) -> dict[str, str]:
    labels = container.get("Config", {}).get("Labels") or {}
    working_directory = labels.get(WORKING_DIRECTORY_LABEL)
    if (labels.get(PROJECT_LABEL) != project or labels.get(SERVICE_LABEL) != service
            or not working_directory or Path(working_directory).resolve() != root.resolve()
            or not container.get("Id") or not container.get("Image")):
        raise ReleaseError(f"{service}: inspected identity does not match the checkpoint's project/checkout")
    return {"id": container["Id"], "image": container["Image"], "service": service,
            "project": project, "working_directory": str(root.resolve())}


class StorageWriterFence:
    def __init__(self, release: Any) -> None:
        self.release = release
        self.path = release.directory / "storage-writer-fence.json"

    def _save(self, record: dict[str, Any]) -> None:
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.release.write_private(self.path, json.dumps(record, indent=2) + "\n")

    def _load(self) -> dict[str, Any] | None:
        if self.path.is_symlink():
            raise ReleaseError("Refusing a symbolic-link storage recovery checkpoint")
        if not self.path.exists():
            return None
        record = json.loads(self.path.read_text())
        if (not isinstance(record, dict) or record.get("version") != 1
                or record.get("root") != str(self.release.root.resolve())
                or not isinstance(record.get("project"), str) or not record["project"]
                or record.get("phase") not in {"fencing", "target_verified", "handoff", "complete"}
                or (record.get("phase") != "complete" and record.get("revision") != self.release.revision)):
            raise ReleaseError(f"Storage checkpoint belongs to a different or invalid release: {self.path}; use its recorded checkout/revision")
        return record

    def _private_file(self, value: str) -> Path:
        path = Path(value)
        if (path.is_symlink() or not path.is_file()
                or not path.resolve().is_relative_to((self.release.directory / "storage").resolve())):
            raise ReleaseError("Storage recovery evidence must be a protected regular file in the release directory")
        return path

    def _current(self, service: str, record: dict[str, Any], *, optional: bool = False) -> dict[str, Any] | None:
        identifiers = self.release.run(
            "docker", "ps", "--all", "--quiet",
            "--filter", f"label={PROJECT_LABEL}={record['project']}",
            "--filter", f"label={SERVICE_LABEL}={service}",
        ).split()
        if not identifiers and optional:
            return None
        if len(identifiers) != 1:
            raise ReleaseError(f"{service}: recovery requires exactly one existing container; no writers restarted")
        current = self.release.inspect(identifiers[0])
        _identity(current, service, record["project"], self.release.root)
        return current

    def begin(self, source: dict[str, Any], writers: list[dict[str, Any]],
              config: dict[str, Any], target_image: str, copy_image: str) -> str:
        previous = self._load()
        if previous and previous["phase"] != "complete":
            raise ReleaseError("An unfinished storage writer checkpoint must be recovered before another fence")
        release, project = self.release, self.release.compose[3]
        services = (*release.workers, "backend")
        if len(writers) != len(services):
            raise ReleaseError("Storage writer inventory is incomplete")
        identities = []
        outer = getattr(release, "resources", None)
        already_fenced = outer is not None and outer.active()
        if already_fenced:
            outer.assert_stopped()
        for service, container in zip(services, writers, strict=True):
            if not already_fenced and not container.get("State", {}).get("Running"):
                raise ReleaseError(f"{service}: writer was not running before the fence")
            identities.append(_identity(container, service, project, release.root))
            shared_service_networks(container, source, "minio")
        nginx = release.container("nginx")
        if not nginx.get("State", {}).get("Running"):
            raise ReleaseError("Nginx must be running before storage writer fencing")
        values = config["services"]["database-admin"]["environment"]
        identity_path = self._private_file(values["OBJECT_STORAGE_IDENTITY_FILE"])
        proof_path = Path(values["OBJECT_STORAGE_CUTOVER_PROOF"])
        if proof_path.is_symlink() or not proof_path.resolve().is_relative_to(identity_path.parent.resolve()):
            raise ReleaseError("Storage cutover proof must stay with the protected identity evidence")
        source_identity = _identity(source, "minio", project, release.root)
        source_identity["volume"] = _volume(source)
        if source_identity["volume"] == values["OBJECT_STORAGE_DATA_VOLUME"]:
            raise ReleaseError("Storage recovery requires separate source and destination volumes")
        token = uuid.uuid4().hex
        copy_name = f"{project}-storage-copy-{token}"
        copy_environment = config["services"]["storage-copy"]["environment"]
        self._save({
            "version": 1, "phase": "fencing", "revision": release.revision,
            "root": str(release.root.resolve()), "project": project,
            "writers": identities, "nginx": _identity(nginx, "nginx", project, release.root),
            "source": source_identity,
            "copy": {
                "name": copy_name, "image": copy_image, "token": token,
                "evidence_directory": str(identity_path.parent.resolve()),
                "environment": {key: copy_environment[key] for key in (
                    "S3_BUCKET_NAME", "STORAGE_SOURCE_ENDPOINT", "STORAGE_DESTINATION_ENDPOINT",
                )},
            },
            "target": {"image": target_image, "volume": values["OBJECT_STORAGE_DATA_VOLUME"],
                       "bucket": values["S3_BUCKET_NAME"], "proof_path": str(proof_path.resolve()),
                       "identity_path": str(identity_path.resolve()),
                       "identity_sha256": hashlib.sha256(identity_path.read_bytes()).hexdigest()},
        })
        return copy_name

    def copy_labels(self) -> list[str]:
        record = self._load()
        if not record or not record.get("copy"):
            raise ReleaseError("Storage copy has no durable process claim")
        return ["--label", "passdetection.storage-copy-token=" + record["copy"]["token"]]

    def _copy_container(self, record: dict[str, Any]) -> dict[str, Any] | None:
        expected = record.get("copy")
        if not expected or not expected.get("name") or not expected.get("token"):
            raise ReleaseError("Storage copy process claim is missing; inspect before restarting writers")
        # Do not filter by project: a foreign process holding our exact name
        # must be detected, never mistaken for an already removed copy job.
        identifiers = self.release.run("docker", "ps", "--all", "--quiet",
                                       "--filter", f"name=^/{expected['name']}$").split()
        if not identifiers:
            return None  # Never launched, or --rm removed the completed job.
        if len(identifiers) != 1:
            raise ReleaseError("Storage copy name does not identify exactly one process")
        current = self.release.inspect(identifiers[0])
        _identity(current, "storage-copy", record["project"], self.release.root)
        actual_environment = dict(value.split("=", 1) for value in current["Config"].get("Env", []) if "=" in value)
        if (current.get("Name") != "/" + expected["name"] or current["Image"] != expected["image"]
                or current["Config"]["Labels"].get("passdetection.storage-copy-token") != expected["token"]
                or current["Config"].get("Cmd") != ["python", "scripts/copy_storage_snapshot.py"]
                or any(actual_environment.get(key) != value for key, value in expected["environment"].items())
                or not any(mount.get("Type") == "bind" and mount.get("Source") == expected["evidence_directory"]
                           and mount.get("Destination") == "/evidence" for mount in current.get("Mounts", []))):
            raise ReleaseError("Storage copy process identity/configuration changed; no process was stopped")
        return current

    def _stop_copy(self, record: dict[str, Any]) -> None:
        current = self._copy_container(record)
        if current and current.get("State", {}).get("Running"):
            # A killed Docker client leaves its one-off container alive. Stop
            # that exact verified job before writers or staging can be reused.
            self.release.run("docker", "stop", "--time", "30", current["Id"], timeout=90)
        remaining = self._copy_container(record)
        if remaining and remaining.get("State", {}).get("Running"):
            raise ReleaseError("Storage copy process is still running; writers remain fenced")

    def stop_copy(self) -> None:
        record = self._load()
        if not record:
            raise ReleaseError("Storage copy has no durable process claim")
        self._stop_copy(record)

    def _proof(self, record: dict[str, Any]) -> tuple[dict[str, Any], str]:
        target = record["target"]
        identity = self._private_file(target["identity_path"])
        if hashlib.sha256(identity.read_bytes()).hexdigest() != target["identity_sha256"]:
            raise ReleaseError("Storage identity changed while writers were fenced")
        proof_path = self._private_file(target["proof_path"])
        raw = proof_path.read_bytes()
        proof = json.loads(raw)
        if (proof.get("source_volume") != record["source"]["volume"]
                or proof.get("target_volume") != target["volume"]
                or proof.get("bucket") != target["bucket"]
                or proof.get("identity_sha256") != target["identity_sha256"]
                or proof.get("every_copied_body_sha256_verified") is not True
                or proof.get("source_deleted") is not False):
            raise ReleaseError("Storage preservation proof does not match the writer checkpoint")
        return proof, hashlib.sha256(raw).hexdigest()

    def verified_target(self) -> None:
        record = self._load()
        if not record or record["phase"] != "fencing":
            raise ReleaseError("Cannot record a storage target without an active writer checkpoint")
        _, digest = self._proof(record)
        record["target"]["proof_sha256"] = digest
        record["phase"] = "target_verified"
        self._save(record)

    def begin_handoff(self) -> None:
        record = self._load()
        if not record or record["phase"] != "target_verified":
            raise ReleaseError("Provider handoff requires a verified target checkpoint")
        record["phase"] = "handoff"
        self._save(record)

    def _authoritative_provider(self, record: dict[str, Any]) -> str:
        current = self._current("minio", record)
        assert current is not None
        source, target = record["source"], record["target"]
        if not current.get("State", {}).get("Running"):
            raise ReleaseError("Storage provider is stopped; no writers restarted")
        if (record["phase"] in {"fencing", "target_verified"}
                and current["Id"] == source["id"] and current["Image"] == source["image"]
                and _volume(current) == source["volume"]):
            return "original_source"
        if (record["phase"] != "handoff" or current["Image"] != target["image"]
                or _volume(current) != target["volume"]):
            raise ReleaseError("Provider replacement is incomplete or ambiguous; no writers restarted")
        _, digest = self._proof(record)
        if digest != target.get("proof_sha256"):
            raise ReleaseError("Verified target proof changed after the writer checkpoint")
        if not any(mount.get("Source") == target["identity_path"]
                   and mount.get("Destination") == "/run/secrets/s3.json" and mount.get("RW") is False
                   for mount in current.get("Mounts", [])):
            raise ReleaseError("Active target identity mount differs from the verified copy")
        if current.get("State", {}).get("Health", {}).get("Status") != "healthy":
            raise ReleaseError("Verified target has not become healthy; no writers restarted")
        stage = self._current("storage-stage", record, optional=True)
        if stage and stage.get("State", {}).get("Running") and _volume(stage) == target["volume"]:
            raise ReleaseError("Staging still has the active target volume open; no writers restarted")
        return "verified_target"

    def restore(self) -> None:
        record = self._load()
        if not record or record["phase"] == "complete":
            return
        try:
            self._stop_copy(record)
            provider = self._authoritative_provider(record)
            expected_services = {*self.release.workers, "backend"}
            identities = record["writers"]
            if (len(identities) != len(expected_services)
                    or {item["service"] for item in identities} != expected_services):
                raise ReleaseError("Writer checkpoint is incomplete; no writers restarted")
            outer = getattr(self.release, "resources", None)
            if outer is not None and outer.active():
                outer.assert_stopped()
                for expected in [*identities, record["nginx"]]:
                    current = self._current(expected["service"], record)
                    assert current is not None
                    if _identity(current, expected["service"], record["project"], self.release.root) != expected:
                        raise ReleaseError("Storage process identity changed during outer maintenance")
                record["phase"], record["restored_against"] = "complete", provider
                record["writers_left_stopped_for_resource_maintenance"] = True
                self._save(record)
                return
            stopped = []
            provider_container = self._current("minio", record)
            assert provider_container is not None
            # Validate every process before starting any: never revive obsolete
            # containers after somebody separately recreated one application service.
            for expected in [*identities, record["nginx"]]:
                current = self._current(expected["service"], record)
                assert current is not None
                actual = _identity(current, expected["service"], record["project"], self.release.root)
                if actual != expected:
                    raise ReleaseError(f"{expected['service']}: original process was replaced; no writers restarted")
                shared_service_networks(current, provider_container, "minio")
                if not current["State"].get("Running"):
                    stopped.append(expected["id"])
            if stopped:
                self.release.run("docker", "start", *stopped, timeout=180)
            for expected in [*identities, record["nginx"]]:
                if not self.release.inspect(expected["id"])["State"].get("Running"):
                    raise ReleaseError("A recorded process did not restart; recovery checkpoint retained")
            nginx_id = record["nginx"]["id"]
            self.release.run("docker", "exec", nginx_id, "nginx", "-t", timeout=30)
            self.release.run("docker", "exec", nginx_id, "nginx", "-s", "reload", timeout=30)
            record["phase"], record["restored_against"] = "complete", provider
            self._save(record)
        except (ReleaseError, OSError, ValueError, KeyError, TypeError) as error:
            target = record.get("target", {})
            raise ReleaseError(
                f"Storage writer recovery stopped: {error}. Checkpoint: {self.path}. "
                f"Inspect existing project {record['project']} storage with docker ps -a; "
                f"restore availability of the recorded original source or the proved target volume "
                f"{target.get('volume', '(missing)')} using proof {target.get('proof_path', '(missing)')}, "
                "then rerun the same release command. Do not choose an empty volume or roll back target writes."
            ) from error


def recover_pending_storage_writers(release: Any) -> None:
    """Run before preflight, which legitimately requires a running backend."""
    StorageWriterFence(release).restore()
