"""Prepare and activate the GC App/receipt reliability release, 0093 -> 0094.

Prepare preserves the previous running images under durable recovery tags.
Activate requires paused traffic, idle workers, and a private PostgreSQL custom
archive whose complete contents pg_restore can decode. It never restores a
backup, downgrades the database, or rolls back application images automatically:
older app images reintroduce the announcement revocation defect.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from release_traveller_whatsapp import ROOT, Release, ReleaseError
from release_traveller_whatsapp import main as run_release

SCHEMA = "0094_whatsapp_receipt_inbox"
PREVIOUS_SCHEMA = "0093_phone_welcome"
DATABASE_SERVICE = "db"
DUMP_COMMAND = (
    'set -eu; umask 077; export PGPASSWORD="$POSTGRES_PASSWORD"; '
    'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" '
    '--format=custom --file="$1"'
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ReliabilityRelease(Release):
    def __init__(
        self, revision: str, root: Path = ROOT, *,
        expected_schema: str = SCHEMA,
        previous_schema: str = PREVIOUS_SCHEMA,
        directory_name: str = "reliability-release",
        include_frontend: bool = True,
        preserve_release_artifacts: bool = False,
    ) -> None:
        super().__init__(
            revision, root, expected_schema=expected_schema, previous_schema=previous_schema,
            directory_name=directory_name,
            include_frontend=include_frontend,
            preserve_release_artifacts=preserve_release_artifacts,
        )
        self.previous_images_path = self.directory / f"{revision}.previous-images.json"
        self.backups_path = self.directory / f"{revision}.database-backups.json"

    def _load_evidence(self, path: Path) -> dict[str, Any]:
        evidence = json.loads(path.read_text())
        if (
            not isinstance(evidence, dict)
            or evidence.get("version") != 1
            or evidence.get("revision") != self.revision
            or evidence.get("project") != self.compose[3]
        ):
            raise ReleaseError("Recovery evidence does not match this release and Compose project")
        return evidence

    def _verify_previous_images(self) -> dict[str, Any]:
        if not self.previous_images_path.is_file():
            raise ReleaseError("Previous image recovery evidence is missing; run prepare first")
        evidence = self._load_evidence(self.previous_images_path)
        services = evidence.get("services", {})
        if not isinstance(services, dict) or set(services) != set(self.activated_services):
            raise ReleaseError("Previous image recovery evidence is incomplete")
        for service, entry in services.items():
            if (
                not isinstance(entry, dict) or not isinstance(entry.get("image_id"), str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", entry["image_id"])
                or not isinstance(entry.get("tag"), str)
            ):
                raise ReleaseError(f"{service}: previous image ID is invalid")
            if self.inspect(entry.get("tag", ""), image=True).get("Id") != entry["image_id"]:
                raise ReleaseError(f"{service}: previous image recovery tag changed or disappeared")
        return evidence

    def prepare_recovery(self, config: dict[str, Any]) -> None:
        self._database_container(config)
        # Retries retain the first pre-release snapshot, including after partial
        # activation. Never replace it with a mixture of old and new images.
        if self.previous_images_path.exists():
            self._verify_previous_images()
            return
        self.say("Preserving all previous running application image IDs and recovery tags")
        scope = hashlib.sha256(f"{config['name']}:{self.root}".encode()).hexdigest()[:12]
        services: dict[str, dict[str, str]] = {}
        for service in self.activated_services:
            container = self.container(service)
            image_id = container.get("Image", "")
            if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
                raise ReleaseError(f"{service}: previous container image is invalid")
            tag = f"passdetection-recovery-{scope}:{self.revision}-{service}"
            existing = self.run("docker", "image", "ls", "--quiet", "--no-trunc", tag)
            if existing and existing != image_id:
                raise ReleaseError(f"{service}: recovery tag already points to another image")
            self.run("docker", "image", "tag", image_id, tag)
            if self.inspect(tag, image=True).get("Id") != image_id:
                raise ReleaseError(f"{service}: previous image tag could not be verified")
            services[service] = {"image_id": image_id, "tag": tag}
        self.write_private(self.previous_images_path, json.dumps({
            "version": 1, "revision": self.revision, "project": config["name"],
            "captured_at": datetime.now(timezone.utc).isoformat(), "services": services,
            "automatic_rollback_allowed": False,
        }, indent=2) + "\n", exclusive=True)

    def _database_container(self, config: dict[str, Any]) -> dict[str, Any]:
        if DATABASE_SERVICE not in config["services"]:
            raise ReleaseError("The existing db PostgreSQL Compose service is required for backup")
        target = config["services"]["backend"].get("environment", {})
        if (
            target.get("POSTGRES_HOST") != DATABASE_SERVICE
            or str(target.get("POSTGRES_PORT", "5432")) != "5432"
        ):
            raise ReleaseError("The prepared backend must target the existing db PostgreSQL service")
        postgres = self.container(DATABASE_SERVICE)
        current = dict(
            item.split("=", 1) for item in postgres["Config"].get("Env", []) if "=" in item
        )
        if any(
            not target.get(key) or target[key] != current.get(key)
            for key in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
        ):
            raise ReleaseError("The backup database identity/settings do not match the prepared backend")
        return postgres

    def _validate_backup_record(self, record: Any) -> Path:
        if not isinstance(record, dict):
            raise ReleaseError("The database backup evidence is malformed")
        filename = record.get("filename")
        if (
            not isinstance(filename, str)
            or not re.fullmatch(r"[0-9a-f]{40}\.[0-9a-f]{32}\.pgdump", filename)
            or not filename.startswith(self.revision + ".")
        ):
            raise ReleaseError("The database backup filename is invalid")
        path = self.directory / filename
        if (
            not path.is_file() or path.is_symlink()
            or record.get("schema") != self.previous_schema
            or record.get("validation") != "pg_restore_full_archive_decode"
            or path.stat().st_size != record.get("bytes")
            or file_sha256(path) != record.get("sha256")
        ):
            raise ReleaseError("The pre-migration database backup failed integrity validation")
        with path.open("rb") as handle:
            if handle.read(5) != b"PGDMP":
                raise ReleaseError("The database backup is not a PostgreSQL custom archive")
        return path

    def before_migration(self, current_schema: str) -> None:
        self._verify_previous_images()
        evidence = self._load_evidence(self.backups_path) if self.backups_path.exists() else {
            "version": 1, "revision": self.revision, "project": self.compose[3], "backups": [],
        }
        records = evidence.get("backups")
        if not isinstance(records, list):
            raise ReleaseError("The database backup history is malformed")
        if current_schema == self.expected_schema and self.previous_schema != self.expected_schema:
            if not records:
                raise ReleaseError("Migration is already applied but its pre-migration backup evidence is missing")
            self._validate_backup_record(records[-1])
            self.say("Validated the preserved pre-migration database backup for activation retry")
            return
        # A code-only release has no schema transition that identifies a retry.
        # Capture current data before every activation; never reuse an older
        # snapshot as evidence of a fresh backup for that deployment attempt.
        self.say("Saving and validating a private PostgreSQL custom archive before migration")
        postgres = self._database_container(json.loads(self.dc("config", "--format", "json")))
        attempt = uuid.uuid4().hex
        filename = f"{self.revision}.{attempt}.pgdump"
        destination = self.directory / filename
        partial = self.directory / f".{filename}.partial"
        remote = f"/tmp/passdetection-reliability-{attempt}.pgdump"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.dc("exec", "-T", DATABASE_SERVICE, "sh", "-c", DUMP_COMMAND, "release-backup", remote, timeout=3600)
            toc = self.dc("exec", "-T", DATABASE_SERVICE, "pg_restore", "--list", remote, timeout=180)
            if "alembic_version" not in toc or "TABLE DATA" not in toc:
                raise ReleaseError("Backup archive does not contain the application schema/data")
            # Fully decode compressed data as well as the table of contents.
            # This writes no SQL to the application database and is explicitly
            # not reported as a restore rehearsal against a second database.
            self.dc("exec", "-T", DATABASE_SERVICE, "pg_restore", "--file=/dev/null", remote, timeout=3600)
            checksum_output = self.dc("exec", "-T", DATABASE_SERVICE, "sha256sum", remote, timeout=180).split()
            remote_digest = checksum_output[0] if checksum_output else ""
            if not re.fullmatch(r"[0-9a-f]{64}", remote_digest):
                raise ReleaseError("The database backup checksum was not returned")
            self.run("docker", "cp", f"{postgres['Id']}:{remote}", str(partial), timeout=3600)
            if os.name == "posix":
                partial.chmod(0o600)
            if not partial.is_file() or file_sha256(partial) != remote_digest:
                raise ReleaseError("The copied database backup failed checksum verification")
            with partial.open("r+b") as handle:
                os.fsync(handle.fileno())
            os.replace(partial, destination)
            record = {
                "filename": filename, "schema": current_schema,
                "sha256": remote_digest, "bytes": destination.stat().st_size,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "validation": "pg_restore_full_archive_decode", "restore_rehearsed": False,
            }
            self._validate_backup_record(record)
            records.append(record)
            self.write_private(self.backups_path, json.dumps(evidence, indent=2) + "\n")
            self.say(f"BACKUP VERIFIED: {destination}; SHA-256 {remote_digest}")
        finally:
            if self.preserve_release_artifacts:
                self.say(f"Release artifacts retained, including any temporary PostgreSQL archive at {remote}")
            else:
                partial.unlink(missing_ok=True)
                # Remove only this invocation's unpredictable, explicitly named
                # temporary archive. The private host backup is retained.
                try:
                    self.dc("exec", "-T", DATABASE_SERVICE, "rm", "-f", "--", remote)
                except ReleaseError:
                    print("Temporary PostgreSQL archive cleanup was deferred; host backup evidence is preserved.", flush=True)


def main() -> int:
    return run_release(ReliabilityRelease, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
